# Observability Guide

## Overview

APEX S01 implements three-pillar observability following
Beyer et al. (2016) SRE Book Ch. 6 (four golden signals)
and Majors & Fong-Jones (2022) Observability Engineering.

- **Metrics**: Prometheus counters/histograms/gauges via `prometheus_client`
- **Tracing**: OpenTelemetry with OTLP/gRPC export
- **Health checks**: Structured liveness/readiness probes

## Quick Start

### View metrics locally

```bash
# Start the serving layer
uvicorn services.data_ingestion.serving.main:app --port 8001

# Fetch metrics
curl http://localhost:8001/metrics
```

### View health status

```bash
curl http://localhost:8001/health
```

### Start Prometheus + Grafana (optional)

```bash
docker compose -f docker/docker-compose.yml --profile observability up -d
```

- Prometheus: http://localhost:9091
- Grafana: http://localhost:3000 (admin/admin)
- Import `docs/grafana/apex_overview.json` in Grafana

## Adding New Metrics

1. Define the metric in `services/data_ingestion/observability/metrics.py`
2. Add a `record_*` helper function
3. Call the helper from the component — never import `prometheus_client` directly
4. Add a test in `tests/unit/s01/observability/test_metrics.py`

## Adding a New Health Check

1. Create a class implementing `DependencyCheck` in `healthcheck.py`
2. Register it in the `HealthChecker` constructor (see `serving/app.py` lifespan)
3. Add tests in `tests/unit/s01/observability/test_healthcheck.py`

## Adding Tracing to a Function

```python
from services.data_ingestion.observability.tracing import trace_async

@trace_async("my_service.my_operation")
async def my_operation(self, ...) -> ...:
    ...
```

## Grafana Dashboard

Pre-built dashboard at `docs/grafana/apex_overview.json` with 7 panels:
- Connector fetch rate and error rate
- DB insert rate and query duration P95
- Quality issues by check type
- Serving request rate and duration P95
