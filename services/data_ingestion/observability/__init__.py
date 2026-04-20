"""Observability module for S01 Data Ingestion.

Provides three pillars of observability:
- **Metrics**: Prometheus counters, histograms, and gauges (metrics.py)
- **Tracing**: OpenTelemetry distributed tracing with @trace_async (tracing.py)
- **Health checks**: Structured liveness/readiness checks (healthcheck.py)

References:
    Beyer et al. (2016) — "Site Reliability Engineering" Ch. 6
    Majors & Fong-Jones (2022) — "Observability Engineering"
"""
