from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from app.config.settings import settings

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    # Thành phần cốt lõi xử lý truyền và nhận ngữ cảnh Trace ID phân tán
    from opentelemetry.trace.propagation.trace_context import TraceContextTextMapPropagator
    OTEL_AVAILABLE = True
except Exception:
    OTEL_AVAILABLE = False


def _sanitize_prompt_light(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    # Xóa bỏ các chuỗi ký tự nhạy cảm dạng PII/Tokens ngay trên Hot-path
    text = re.sub(r"[\w\.-]+@[\w\.-]+", "[EMAIL]", text)
    text = re.sub(r"\b\d{5,}\b", "[NUM]", text)
    text = re.sub(r"[A-Za-z0-9_-]{40,}", "[TOKEN]", text)
    return text


def init_tracing() -> None:
    """Khởi tạo OpenTelemetry Tracer Provider tích hợp BatchSpanProcessor nhằm đẩy

    toàn bộ tác vụ Network I/O xuất Trace dữ liệu chạy ẩn dưới nền.
    """
    if not settings.TRACING_ENABLED or not OTEL_AVAILABLE:
        return

    resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        span_processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(span_processor)

    trace.set_tracer_provider(provider)


@asynccontextmanager
async def trace_task_span(task_id: Optional[str], name: str, attrs: Optional[Dict[str, Any]] = None):
    """Async context manager bọc các Node trong LangGraph.

    Tự động liên đới (Correlate) và duy trì cây phân cấp Span Cha-Con của OpenTelemetry.
    """
    if OTEL_AVAILABLE and settings.TRACING_ENABLED:
        tracer = trace.get_tracer("sac.core_engine")
        with tracer.start_as_current_span(name) as span:
            if attrs:
                sanitized = {k: (_sanitize_prompt_light(v) if isinstance(v, str) else v) for k, v in attrs.items()}
                for k, v in sanitized.items():
                    span.set_attribute(k, str(v))
            if task_id:
                span.set_attribute("task.id", task_id)
            yield span
    else:
        class _Noop:
            def set_attribute(self, *_): pass
        yield _Noop()


def inject_trace_context() -> Dict[str, str]:
    """Gọi hàm này ở tầng API trước khi ném Task vào Message Queue.

    Nó sẽ trả về một bộ dictionary chứa W3C 'traceparent' token.
    """
    carrier = {}
    if OTEL_AVAILABLE and settings.TRACING_ENABLED:
        TraceContextTextMapPropagator().inject(carrier)
    return carrier


def extract_trace_context(carrier: Dict[str, str]) -> Optional[Any]:
    """Gọi hàm này ở tầng Worker (Celery/ARQ) ngay khi vừa lôi Task ra khỏi Queue.

    Nó giúp Worker bắt được Trace ID gốc ban đầu của API và nối tiếp dòng chảy log.
    """
    if OTEL_AVAILABLE and settings.TRACING_ENABLED:
        return TraceContextTextMapPropagator().extract(carrier)
    return None