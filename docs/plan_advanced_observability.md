# Advanced Observability Plan - OpenTelemetry Integration

## Overview

This plan describes the refactoring of the observability stack to follow OpenTelemetry (OTEL) standards. The goal is to create a unified observability architecture with metrics, logs, and traces flowing through OTEL Collector to Prometheus, Loki, and Tempo.

## Architecture

```
FastAPI
    │
OpenTelemetry SDK
    │
    ▼
OTEL Collector
    │
 ┌──┼─────────┐
 │  │         │
 ▼  ▼         ▼
Prometheus  Loki  Tempo
    │         │     │
    └─────────┴─────┘
              │
         Grafana
```

**Note:** Langfuse will be retained for LLM-specific tracing (Agent, Planner, Reasoner, Executor) as OTEL does not have semantic attributes for LLM operations.

---

## Phase 1: OpenTelemetry SDK for FastAPI

### Objectives
- Install OpenTelemetry SDK dependencies
- Configure OTEL instrumentation (auto + manual)
- Integrate with existing FastAPI application

### Changes

#### 1. Install Dependencies
```bash
poetry add opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi
poetry add opentelemetry-instrumentation-sqlalchemy opentelemetry-instrumentation-httpx
poetry add opentelemetry-exporter-otlp
```

#### 2. Create `app/core/otel.py`
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.config.settings import settings

def init_otel():
    """Initialize OpenTelemetry SDK for tracing and metrics."""
    
    # Initialize tracing
    trace.set_tracer_provider(TracerProvider())
    otlp_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)
    
    # Initialize metrics
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    )
    metrics.set_meter_provider(MeterProvider(metric_reader=metric_reader))
    
    # Auto-instrumentation
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
    HTTPXClientInstrumentor().instrument()
```

#### 3. Update `main.py`
```python
from app.core.otel import init_otel

if settings.TRACING_ENABLED:
    init_otel()
```

#### 4. Update `app/config/settings.py`
```python
# Add/update existing OTEL settings
OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"  # OTEL Collector
```

---

## Phase 2: OTEL Collector

### Objectives
- Add OTEL Collector to docker-compose
- Configure Collector exporters (Prometheus, Loki, Tempo)
- Centralize telemetry data processing

### Changes

#### 1. Create `docker/otel-collector-config.yaml`
```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
    tls:
      insecure: true
  
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    tls:
      insecure: true
    
  otlp:
    endpoint: http://tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp]
    
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheusremotewrite]
    
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [loki]
```

#### 2. Update `docker/docker-compose.observability.yml`
```yaml
otel-collector:
  image: otel/opentelemetry-collector:latest
  container_name: ragflash-otel-collector
  restart: unless-stopped
  command: ["--config=/etc/otel-collector-config.yaml"]
  volumes:
    - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
  ports:
    - "4317:4317"  # OTLP gRPC
    - "4318:4318"  # OTLP HTTP
  depends_on:
    - prometheus
    - loki
    - tempo
  networks:
    - ragflash-network
```

---

## Phase 3: Loki - Log Aggregation

### Objectives
- Add Loki container for log aggregation
- Configure structured logging with OTEL
- Centralize log storage and querying

### Changes

#### 1. Update `docker/docker-compose.observability.yml`
```yaml
loki:
  image: grafana/loki:latest
  container_name: ragflash-loki
  restart: unless-stopped
  ports:
    - "3100:3100"
  command: -config.file=/etc/loki/local-config.yaml
  volumes:
    - ./loki-config.yaml:/etc/loki/local-config.yaml
    - loki_data:/loki
  networks:
    - ragflash-network
```

#### 2. Create `docker/loki-config.yaml`
```yaml
server:
  http_listen_port: 3100

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: loki_index_
        period: 24h

storage_config:
  filesystem:
    directory: /loki/chunks

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
```

#### 3. Update `app/core/logger.py`
```python
from opentelemetry import logs
from opentelemetry.sdk.logs import LoggerProvider
from opentelemetry.sdk.logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc.log_exporter import OTLPLogExporter

def init_otel_logging():
    """Initialize OpenTelemetry logging."""
    logger_provider = LoggerProvider()
    log_exporter = OTLPLogExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    logs.set_logger_provider(logger_provider)
```

#### 4. Update volumes in `docker/docker-compose.observability.yml`
```yaml
volumes:
  prometheus_data:
  grafana_data:
  langfuse_db_data:
  clickhouse_data:
  minio_data:
  loki_data:
```

---

## Phase 4: Tempo - Distributed Tracing

### Objectives
- Add Tempo container for distributed tracing
- Migrate Langfuse traces to OTEL format where applicable
- Enable end-to-end distributed tracing

### Changes

#### 1. Update `docker/docker-compose.observability.yml`
```yaml
tempo:
  image: grafana/tempo:latest
  container_name: ragflash-tempo
  restart: unless-stopped
  command: -config.file=/etc/tempo-config.yaml
  ports:
    - "3200:3200"  # Tempo UI
    - "4317:4317"  # OTLP gRPC (for direct export if needed)
    - "4318:4318"  # OTLP HTTP
  volumes:
    - ./tempo-config.yaml:/etc/tempo-config.yaml
    - tempo_data:/tmp/tempo
  networks:
    - ragflash-network
```

#### 2. Create `docker/tempo-config.yaml`
```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
        http:

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo
```

#### 3. Update `app/core/langfuse_tracing.py`
```python
# Add OTEL tracing for system-wide operations
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def create_otel_span(name: str, **kwargs):
    """Create an OTEL span for system operations."""
    with tracer.start_as_current_span(name, **kwargs) as span:
        span.set_attribute("service.name", settings.OTEL_SERVICE_NAME)
        return span

# Keep Langfuse for LLM-specific tracing (Agent, Planner, Reasoner, Executor)
# Langfuse provides semantic attributes for LLM operations that OTEL lacks
```

#### 4. Update volumes in `docker/docker-compose.observability.yml`
```yaml
volumes:
  prometheus_data:
  grafana_data:
  langfuse_db_data:
  clickhouse_data:
  minio_data:
  loki_data:
  tempo_data:
```

---

## Phase 5: Grafana Integration

### Objectives
- Update Grafana datasources (Loki, Tempo)
- Create unified dashboard (Metrics + Logs + Traces)
- Enable correlation between metrics, logs, and traces

### Changes

#### 1. Update `docker/grafana/provisioning/datasources/prometheus.yml`
```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: true

  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    editable: true
```

#### 2. Create unified dashboard `docker/grafana/dashboards/unified_observability.json`
Include panels for:
- **Metrics:** Request rate, latency, error rate (from Prometheus)
- **Logs:** Log stream with filters (from Loki)
- **Traces:** Trace timeline with span details (from Tempo)
- **Correlation:** Click on metric → see related logs → see related traces

---

## Phase 6: Testing & Cleanup

### Objectives
- Test end-to-end observability flow
- Remove deprecated Prometheus direct export
- Verify all components working together

### Testing Steps

#### 1. Start Observability Stack
```bash
cd docker
docker-compose -f docker-compose.observability.yml up -d
```

#### 2. Start FastAPI with OTEL
```bash
cd ..
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export TRACING_ENABLED=true
poetry run uvicorn main:app --reload
```

#### 3. Make Test API Calls
```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/documents
```

#### 4. Verify in Grafana
- **Metrics:** http://localhost:3010 → Prometheus datasource
- **Logs:** http://localhost:3010 → Loki datasource → Explore
- **Traces:** http://localhost:3010 → Tempo datasource → Search

#### 5. Cleanup Deprecated Code
- Remove direct Prometheus export from `app/observability/metrics.py` (keep metrics definitions, remove ASGIMiddleware if using OTEL)
- Keep Langfuse for LLM-specific tracing (complementary to OTEL)
- Remove deprecated tracing code if any

---

## Timeline Estimate

- **Phase 1:** 2-3 hours (SDK installation and configuration)
- **Phase 2:** 1-2 hours (OTEL Collector setup)
- **Phase 3:** 2-3 hours (Loki integration)
- **Phase 4:** 3-4 hours (Tempo integration + Langfuse migration)
- **Phase 5:** 1-2 hours (Grafana datasources and dashboards)
- **Phase 6:** 2-3 hours (Testing and cleanup)

**Total:** ~11-17 hours

---

## Rollback Plan

If any phase fails:
1. Stop the affected containers
2. Revert the specific changes
3. Restart with previous configuration
4. Document the issue for future reference

---

## Notes

- **Langfuse Retention:** Langfuse will be retained for LLM-specific tracing as it provides semantic attributes for LLM operations that OTEL does not have.
- **Incremental Implementation:** Implement each phase incrementally and test thoroughly before proceeding to the next phase.
- **Performance:** Monitor performance impact of OTEL instrumentation, especially on hot paths.
- **Resource Requirements:** Additional containers (Loki, Tempo, OTEL Collector) will increase resource usage. Ensure sufficient system resources.

---

## References

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Grafana Tempo Documentation](https://grafana.com/docs/tempo/latest/)
- [Langfuse Documentation](https://langfuse.com/docs)
