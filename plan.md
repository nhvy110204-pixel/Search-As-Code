Observability integration plan — Prometheus / Grafana / Langfuse

Goal
- Add production-grade observability: metrics (Prometheus), dashboards (Grafana), and LLM tracing (Langfuse or OTLP) for Search-as-Code (SaC).

Phases

Phase 1 — Scaffolding (short)
- Create `app/observability/metrics.py` with Prometheus counters/histograms helpers
- Create `app/observability/tracing.py` with tracing init (OTLP + Langfuse adapter)
- Add settings keys in `app/config/settings.py` for metrics/tracing endpoints and secrets
- Wire middleware in `main.py` to expose `/metrics` and to register request metrics

Checklist:
- [ ] `metrics.py` file with `init_metrics()` and helpers
- [ ] `tracing.py` file with `init_tracing()` and span helpers
- [ ] `main.py` updated to call init functions
- [ ] Settings environment variables documented

Phase 2 — Prometheus instrumentation (COARSE-GRAINED only)
- Use `prometheus_client` for counters/histograms
- Instrument HTTP requests (status, path category, method, latency)
- Expose `/metrics` endpoint
- Record only low-cardinality, aggregate metrics. Examples:
  - `sac_tasks_total{status="failed"}`
  - `sac_sdk_calls_total{operation="web_search"}`
  - `sac_task_duration_seconds_bucket` (aggregated histogram by operation type)

Notes (MANDATORY):
- Never attach `task_id`, `user_id`, or other high-cardinality identifiers as Prometheus labels. Doing so will create unbounded series and OOM the Prometheus server.
- Send high-cardinality, per-task traces and identifiers to the tracing system (Langfuse/OTLP), which is designed for that workload.

Checklist:
- [ ] Add request counter and latency histogram (coarse labels only)
- [ ] Add aggregate task-related metric helpers (no task_id labels)
- [ ] Hook aggregated metrics into SaC worker / finalizer
- [ ] Unit tests for metric helpers (smoke)

Phase 3 — Langfuse / OpenTelemetry tracing
- Implement tracing wrapper that can use Langfuse SDK (if available) or OTLP exporter
- Trace key events: `planner`, `reasoner` (LLM call), `executor` (sandbox exec), `observer`, `finalizer`
- Record metadata: `task_id`, `turn`, `model`, `tokens`, `prompt_hash`, `stop_reason` and sanitized prompts

Checklist:
- [ ] `init_tracing()` supports env: LANGFUSE_API_KEY or OTEL_EXPORTER_OTLP_ENDPOINT
- [ ] Helper decorator/context manager `trace_task_span(task_id, name, attrs)`
- [ ] Integrate trace calls in `app/graph/nodes/*` (reasoner/executor) as spans
- [ ] Ensure secrets masking before sending traces

Phase 4 — Instrument SaC internals
- Add hooks to record metrics and traces in nodes:
  - In `reasoner`: trace prompt & response, record tokens
  - In `executor`: trace validation result, exec duration, sdk_calls
  - In `observer/finalizer`: record coverage_score/confidence and final metrics

Checklist:
- [ ] Update `app/graph/nodes/reasoner.py` to use trace and metrics helpers
- [ ] Update `app/graph/nodes/executor.py` similarly
- [ ] Update `finalizer` to emit task-level metrics
- [ ] Add tests for instrumentation (integration smoke)

Phase 5 — Observability stack deployment
- Add `docker/docker-compose.observability.yml` including Prometheus + Grafana (+ optional Langfuse OSS or instructions for Langfuse cloud)
- Add Prometheus scrape job for the backend `/metrics`
- Add sample Grafana dashboards (JSON) for quick import

Checklist:
- [x] `docker/docker-compose.observability.yml`
- [x] `docker/prometheus/prometheus.yml` with scrape configs
- [ ] Grafana dashboard JSON files in `docker/grafana/dashboards/`

Phase 6 — Dashboards & Alerts (alerting policy rules)
- Build dashboards: API, Task metrics, LLM cost/time, Sandbox failures (rate charts)

Alerting policy (MANDATORY):
- Distinguish between Infrastructure Errors (page Ops) and AI Turn Failures (do not page):
  - Infrastructure Alerts (send PagerDuty/SMS): service down, Prometheus scrape failure, exporter OOM, Docker sandbox crash, host OOM, connectivity to critical external services.
  - AI Turn Failures (do NOT page Ops): AST validation failures, model-generated syntax/runtime errors, or single-turn execution exceptions. These should increment counters/ratios and appear on dashboards but should not create immediate on-call pages.

Best practices:
- Alert on aggregated error rates over a time window (e.g., `rate(sac_turn_failure_total[5m]) > X`), not single events.
- Use deduplication and inhibition rules so repeated AI-turn failures don't flood the on-call channel.

Checklist:
- [ ] Dashboard for API /tasks overview
- [ ] Alerts: 5xx spike, infra-level failures, long task duration > threshold
- [ ] Counters and dashboards for sandbox/validation failures (no paging)

Phase 7 — Docs & Run instructions
- Add `README.md` section with env vars, run commands, quick test sample
- Provide commands to run stack locally with docker compose

Checklist:
- [ ] `plan.md` (this file)
- [ ] `README.md` observability section
- [ ] Quick test instructions

Next step (I'll start now)
- Implement Phase 1: create `metrics.py` and `tracing.py` skeletons, add settings, wire `main.py` to initialize them.


Environment notes & security
- Do not log raw prompts or secret values. Always mask/strip before sending to Langfuse or traces.
- Prometheus metrics must avoid including unbounded label values (e.g., do not label by full prompt or URL; use hashed or coarse labels).

Performance & tracing safety (MANDATORY):
- Tracing/Masking must never block the API/worker main path. Use asynchronous background exporters or batching exporters to perform masking and network export off the request path.
- Prefer the OpenTelemetry BatchSpanProcessor, an async background worker, or a dedicated tracing ingestion worker/process that receives spans via a local queue. Do not `await` remote exporter calls on the request thread.
- For prompt masking or PII scrubbing that is CPU-heavy, perform masking in a background task or use a lightweight streaming sanitizer on the hot path and full sanitization in the background before export.
- Configure exporters to batch and compress payloads; set reasonable time and size limits for batches to avoid memory leaks.

Run locally (example)

1. Start backend (dev):

```bash
# from backend/
uvicorn main:app --reload
```

2. Start observability (once docker compose added):

```bash
docker compose -f docker/docker-compose.observability.yml up --build
```
