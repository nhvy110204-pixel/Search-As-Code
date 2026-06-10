import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app_environment import AppEnvironment
from app.api.routes import routers
from app.config.settings import settings
from app.observability.metrics import init_metrics
from app.observability.tracing import init_tracing

logger = logging.getLogger(__name__)

app = FastAPI(debug=settings.APP_DEBUG)


class ASGIRequestLoggingMiddleware:
    """Pure ASGI Logging Middleware: Thay thế BaseHTTPMiddleware,

    đo lường chính xác tốc độ phản hồi mà không block stream.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_perf = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            process_time = (time.perf_counter() - start_perf) * 1000
            client = scope.get("client")
            client_host = client[0] if client else "unknown"
            
            logger.info(
                "[REQUEST] %s - %s %s - Status: %s - Time: %.2fms",
                client_host,
                scope.get("method"),
                scope.get("path"),
                status_code,
                process_time,
            )


# --- Khởi chạy cấu trúc Middleware thứ tự chuẩn Production ---
app.add_middleware(ASGIRequestLoggingMiddleware)

# Khởi tạo sớm tầng Metrics (Bao gồm việc mount endpoint /metrics)
try:
    init_metrics(app)
except Exception:
    logger.exception("Failed to initialize metrics; continuing without metrics")


@app.on_event("startup")
async def _init_tracing_on_startup():
    try:
        # Khởi chạy Tracing độc lập ở vòng đời startup giúp tránh nghẽn I/O
        init_tracing()
    except Exception:
        logger.exception("Failed to initialize tracing; continuing without tracing")


# --- CORS Configurations ---
if AppEnvironment.is_local_env(settings.APP_ENV):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
elif AppEnvironment.is_remote_env(settings.APP_ENV):
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.ALLOWED_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(routers.api_router)


@app.get("/")
def read_root():
    return {"message": "BASE APP API", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}