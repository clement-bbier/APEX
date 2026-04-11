# S01 Observability Module

Three-pillar observability for the Data Ingestion service (S01).

## Architecture

```
metrics.py        Prometheus counters, histograms, gauges + record_* helpers
tracing.py        OpenTelemetry tracer init + @trace_async decorator
healthcheck.py    HealthChecker with pluggable DependencyCheck strategies
metrics_server.py mount_metrics_endpoint() for FastAPI /metrics
```

## Metrics (Prometheus)

All metrics use the `apex_s01_` prefix. Components call `record_*` helpers
from `metrics.py` — they never import `prometheus_client` directly.

| Metric | Type | Labels |
|---|---|---|
| `apex_s01_connector_fetch_total` | Counter | connector, source, status |
| `apex_s01_connector_fetch_duration_seconds` | Histogram | connector, source |
| `apex_s01_connector_errors_total` | Counter | connector, source |
| `apex_s01_db_inserts_total` | Counter | table |
| `apex_s01_db_insert_duration_seconds` | Histogram | table |
| `apex_s01_db_query_duration_seconds` | Histogram | table, operation |
| `apex_s01_quality_issues_total` | Counter | check_type, severity |
| `apex_s01_quality_records_total` | Counter | status |
| `apex_s01_serving_requests_total` | Counter | method, endpoint |
| `apex_s01_serving_request_duration_seconds` | Histogram | method, endpoint |
| `apex_s01_serving_responses_total` | Counter | method, endpoint, status_code |

## Tracing (OpenTelemetry)

```python
from services.s01_data_ingestion.observability.tracing import trace_async

@trace_async("connector.alpaca.fetch_bars")
async def fetch_bars(self, ...) -> ...:
    ...
```

Exports to OTLP/gRPC when `otel_endpoint` is set, otherwise ConsoleSpanExporter.

## Health Checks

```python
from services.s01_data_ingestion.observability.healthcheck import (
    HealthChecker, DatabaseCheck,
)

checker = HealthChecker(dependency_checks=[DatabaseCheck(repo)])
report = await checker.readiness()  # HealthReport
```

## Endpoints

- `GET /metrics` — Prometheus exposition format
- `GET /health` — JSON readiness report via HealthChecker
