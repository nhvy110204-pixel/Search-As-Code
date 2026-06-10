Observability quick reference

Environment variables (recommended):

- METRICS_ENABLED=true
- METRICS_PATH=/metrics
- PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc (set when running multiple workers)

- TRACING_ENABLED=true
- OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
- OTEL_SERVICE_NAME=ragflash-backend
- TRACING_BATCH_MAX_QUEUE_SIZE=2048
- TRACING_BATCH_SCHEDULE_DELAY_MS=5000
- TRACING_BATCH_MAX_EXPORT_BATCH_SIZE=512
- TRACING_HEAVY_SANITIZE=false  # if true, full sanitization runs via background worker

Notes:
- Prometheus: do NOT attach high-cardinality labels (task_id, user_id). Keep labels coarse.
- If using multiple workers (gunicorn/uvicorn --workers), enable Prometheus multiprocess mode and set `PROMETHEUS_MULTIPROC_DIR`.
- Tracing: BatchSpanProcessor is configured by default; exporters are non-blocking. Ensure `TRACING_HEAVY_SANITIZE` is false on hot paths.

Quick local run (dev):

If you use Poetry (recommended):

```bash
poetry install
poetry run uvicorn main:app --reload
# visit http://localhost:8000/metrics
```

If you prefer pip:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# visit http://localhost:8000/metrics
```
