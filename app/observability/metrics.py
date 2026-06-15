from __future__ import annotations

import re
import time
from prometheus_client import Counter, Gauge, Histogram, Summary, make_asgi_app
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import settings

AI_LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0, float("inf")
)

HTTP_REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["method", "status", "path_category"],
)

HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds with custom AI buckets",
    ["method", "path_category"],
    buckets=AI_LATENCY_BUCKETS,
)

HTTP_EXCEPTIONS_TOTAL = Counter(
    "http_exceptions_total",
    "Total unhandled exceptions caught on the HTTP path",
    ["exception_type", "path_category"],
)

HTTP_REQUEST_SIZE_BYTES = Summary(
    "http_request_size_bytes",
    "Dung lượng request nhận vào từ client (Ingress Payload Size)",
    ["method", "path_category"],
)

HTTP_RESPONSE_SIZE_BYTES = Summary(
    "http_response_size_bytes",
    "Dung lượng response trả về cho client (Egress Payload Size)",
    ["method", "path_category"],
)

SAC_TASKS_TOTAL = Counter(
    "sac_tasks_total",
    "Total SAC tasks processed by end-status",
    ["status"],
)

SAC_SDK_CALLS_TOTAL = Counter(
    "sac_sdk_calls_total",
    "Total atomized SDK primitives executed inside sandboxes",
    ["operation"],
)

CHAT_STREAMS_TOTAL = Counter(
    "chat_streams_total",
    "Total chat streams by end-status",
    ["status"],
)

CHAT_STREAM_DURATION_SECONDS = Histogram(
    "chat_stream_duration_seconds",
    "Chat stream duration in seconds",
    ["status"],
    buckets=AI_LATENCY_BUCKETS,
)

CHAT_STREAM_TIME_TO_FIRST_DELTA_SECONDS = Histogram(
    "chat_stream_time_to_first_delta_seconds",
    "Seconds until the first chat stream delta is emitted",
    buckets=AI_LATENCY_BUCKETS,
)

# Ingestion pipeline metrics
UPLOAD_REQUESTS_TOTAL = Counter(
    'upload_requests_total',
    'Total upload requests',
    ['status']  # success, failed, quota_exceeded, rate_limited
)

UPLOAD_FILE_SIZE_BYTES = Histogram(
    'upload_file_size_bytes',
    'File size distribution for uploads',
    buckets=[1e6, 10e6, 50e6, 100e6]  # 1MB, 10MB, 50MB, 100MB
)

QUOTA_EXCEEDED_TOTAL = Counter(
    'quota_exceeded_total',
    'Total quota exceeded errors',
    ['user_id', 'project_id']
)

RATE_LIMIT_EXCEEDED_TOTAL = Counter(
    'rate_limit_exceeded_total',
    'Total rate limit exceeded errors',
    ['key_type']  # user, project
)

INGESTION_TASKS_TOTAL = Counter(
    'ingestion_tasks_total',
    'Total ingestion tasks',
    ['status']  # pending, processing, completed, failed
)

INGESTION_STEP_DURATION_SECONDS = Histogram(
    'ingestion_step_duration_seconds',
    'Duration of ingestion pipeline steps',
    ['step'],  # parse, summary, chunk, dedup, enrich, embed, link, finalize
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300]
)

INGESTION_STEP_RETRIES_TOTAL = Counter(
    'ingestion_step_retries_total',
    'Total retries for ingestion steps',
    ['step']
)

INGESTION_FAILED_CHUNKS_TOTAL = Counter(
    'ingestion_failed_chunks_total',
    'Total failed chunks during embedding',
    ['document_id']
)

INGESTION_EMBEDDING_BATCH_SIZE = Histogram(
    'ingestion_embedding_batch_size',
    'Batch size for embedding operations',
    buckets=[1, 5, 10, 20, 50, 100]
)

INGESTION_COST_USD_TOTAL = Counter(
    'ingestion_cost_usd_total',
    'Total cost in USD for ingestion operations',
    ['operation']  # embedding, summarization
)

INGESTION_DOCUMENT_SIZE_BYTES = Histogram(
    'ingestion_document_size_bytes',
    'Document size distribution for ingestion',
    buckets=[1e4, 1e5, 1e6, 10e6, 100e6]  # 10KB, 100KB, 1MB, 10MB, 100MB
)

INGESTION_QDRANT_UPSERTS_TOTAL = Counter(
    'ingestion_qdrant_upserts_total',
    'Total Qdrant upsert operations',
    ['status']  # success, failed
)

INGESTION_ACTIVE_TASKS = Gauge(
    'ingestion_active_tasks',
    'Number of currently active ingestion tasks'
)

INGESTION_CHUNK_DEDUP_RATIO = Gauge(
    'ingestion_chunk_dedup_ratio',
    'Ratio of deduplicated chunks (existing / total)',
    ['document_id']
)

class ASGIMetricsMiddleware:
    """Pure ASGI Middleware: Đảm bảo luồng Stream Token,

    không bị cache toàn bộ dữ liệu vào RAM gây tăng Latency/OOM.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == settings.METRICS_PATH:
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        method = scope.get("method", "UNKNOWN")
        status_code = "500"
        response_size = 0

        headers = dict(scope.get("headers", []))
        request_size = int(headers.get(b"content-length", b"0").decode("utf-8", errors="ignore"))

        async def send_wrapper(message):
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = str(message["status"])
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_size += len(body)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            route = scope.get("route")
            path_cat = route.path if route and hasattr(route, "path") else path
            HTTP_EXCEPTIONS_TOTAL.labels(exception_type=e.__class__.__name__, path_category=path_cat).inc()
            raise
        finally:
            latency = time.perf_counter() - start_time
            
            route = scope.get("route")
            path_cat = route.path if route and hasattr(route, "path") else path

            HTTP_REQUEST_COUNT.labels(method=method, status=status_code, path_category=path_cat).inc()
            HTTP_REQUEST_LATENCY_SECONDS.labels(method=method, path_category=path_cat).observe(latency)
            HTTP_REQUEST_SIZE_BYTES.labels(method=method, path_category=path_cat).observe(request_size)
            HTTP_RESPONSE_SIZE_BYTES.labels(method=method, path_category=path_cat).observe(response_size)


def init_metrics(app: ASGIApp):
    """Gắn ASGI app của Prometheus và kích hoạt lớp bọc Middleware điều phối."""
    if not settings.METRICS_ENABLED:
        return

    metrics_app = make_asgi_app()
    mount_path = settings.METRICS_PATH or "/metrics"
    app.mount(mount_path, metrics_app)
    app.add_middleware(ASGIMetricsMiddleware)


def _sanitize_coarse_path(path: str) -> str:

    if not path or path == "/":
        return "root"

    path = re.sub(r"[0-9a-fA-F]{8,}", ":id", path)
    path = re.sub(r"\b\d+\b", ":id", path)

    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else "root"


def record_sac_task_status(status: str):
    SAC_TASKS_TOTAL.labels(status=status).inc()


def record_sac_sdk_call(operation: str):
    SAC_SDK_CALLS_TOTAL.labels(operation=operation).inc()


def record_chat_stream_started():
    CHAT_STREAMS_TOTAL.labels(status="started").inc()


def record_chat_stream_completed(duration_seconds: float, time_to_first_delta_seconds: float | None):
    CHAT_STREAMS_TOTAL.labels(status="completed").inc()
    CHAT_STREAM_DURATION_SECONDS.labels(status="completed").observe(duration_seconds)
    if time_to_first_delta_seconds is not None:
        CHAT_STREAM_TIME_TO_FIRST_DELTA_SECONDS.observe(time_to_first_delta_seconds)


def record_chat_stream_failed(duration_seconds: float):
    CHAT_STREAMS_TOTAL.labels(status="failed").inc()
    CHAT_STREAM_DURATION_SECONDS.labels(status="failed").observe(duration_seconds)


def record_chat_stream_disconnected(duration_seconds: float):
    CHAT_STREAMS_TOTAL.labels(status="disconnected").inc()
    CHAT_STREAM_DURATION_SECONDS.labels(status="disconnected").observe(duration_seconds)

# Ingestion metric helper functions
def track_upload_status(status: str):
    """Track upload request status."""
    UPLOAD_REQUESTS_TOTAL.labels(status=status).inc()


def track_file_size(file_size: int):
    """Track uploaded file size."""
    UPLOAD_FILE_SIZE_BYTES.observe(file_size)


def track_quota_exceeded(user_id: str, project_id: str):
    """Track quota exceeded event."""
    QUOTA_EXCEEDED_TOTAL.labels(user_id=user_id, project_id=project_id).inc()


def track_rate_limit_exceeded(key_type: str):
    """Track rate limit exceeded event."""
    RATE_LIMIT_EXCEEDED_TOTAL.labels(key_type=key_type).inc()


def track_ingestion_task_status(status: str):
    """Track ingestion task status change."""
    INGESTION_TASKS_TOTAL.labels(status=status).inc()


def track_step_duration(step_name: str):
    """Decorator to track step duration in Prometheus."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                INGESTION_STEP_DURATION_SECONDS.labels(step=step_name).observe(duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                INGESTION_STEP_DURATION_SECONDS.labels(step=step_name).observe(duration)
                INGESTION_STEP_RETRIES_TOTAL.labels(step=step_name).inc()
                raise
        return wrapper
    return decorator


def track_failed_chunks(document_id: str, count: int):
    """Track failed chunks for a document."""
    INGESTION_FAILED_CHUNKS_TOTAL.labels(document_id=document_id).inc(count)


def track_embedding_batch_size(batch_size: int):
    """Track embedding batch size."""
    INGESTION_EMBEDDING_BATCH_SIZE.observe(batch_size)


def track_cost(operation: str, cost_usd: float):
    """Track operation cost in USD."""
    INGESTION_COST_USD_TOTAL.labels(operation=operation).inc(cost_usd)


def track_document_size(document_size: int):
    """Track document size for ingestion."""
    INGESTION_DOCUMENT_SIZE_BYTES.observe(document_size)


def track_qdrant_upsert(status: str):
    """Track Qdrant upsert operation."""
    INGESTION_QDRANT_UPSERTS_TOTAL.labels(status=status).inc()


def set_active_tasks(count: int):
    """Set the number of active ingestion tasks."""
    INGESTION_ACTIVE_TASKS.set(count)


def set_chunk_dedup_ratio(document_id: str, ratio: float):
    """Set the chunk deduplication ratio for a document."""
    INGESTION_CHUNK_DEDUP_RATIO.labels(document_id=document_id).set(ratio)
