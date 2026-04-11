"""Prometheus metrics definitions and recording helpers for S01.

All metrics are defined here as module-level constants. Components
import only the ``record_*`` helpers — never ``prometheus_client``
directly — to maintain loose coupling (DIP).

Naming convention follows Prometheus best practices:
    ``apex_s01_<subsystem>_<metric>_<unit>``

References:
    Beyer et al. (2016) SRE Book Ch. 6 — four golden signals
    Prometheus naming conventions — https://prometheus.io/docs/practices/naming/
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Metric name constants ────────────────────────────────────────────────────

_PREFIX = "apex_s01"

# Connector metrics
_CONNECTOR_FETCH_TOTAL = f"{_PREFIX}_connector_fetch_total"
_CONNECTOR_FETCH_DURATION = f"{_PREFIX}_connector_fetch_duration_seconds"
_CONNECTOR_ERRORS_TOTAL = f"{_PREFIX}_connector_errors_total"

# Database metrics
_DB_INSERTS_TOTAL = f"{_PREFIX}_db_inserts_total"
_DB_INSERT_DURATION = f"{_PREFIX}_db_insert_duration_seconds"
_DB_QUERY_DURATION = f"{_PREFIX}_db_query_duration_seconds"

# Quality metrics
_QUALITY_ISSUES_TOTAL = f"{_PREFIX}_quality_issues_total"
_QUALITY_RECORDS_TOTAL = f"{_PREFIX}_quality_records_total"

# Orchestrator metrics
_ORCHESTRATOR_JOBS_TOTAL = f"{_PREFIX}_orchestrator_jobs_total"
_ORCHESTRATOR_JOB_DURATION = f"{_PREFIX}_orchestrator_job_duration_seconds"
_ORCHESTRATOR_JOBS_RUNNING = f"{_PREFIX}_orchestrator_jobs_running"

# Serving metrics
_SERVING_REQUESTS_TOTAL = f"{_PREFIX}_serving_requests_total"
_SERVING_REQUEST_DURATION = f"{_PREFIX}_serving_request_duration_seconds"
_SERVING_RESPONSES_TOTAL = f"{_PREFIX}_serving_responses_total"

# ── Label name constants ─────────────────────────────────────────────────────

_LABEL_CONNECTOR = "connector"
_LABEL_SOURCE = "source"
_LABEL_STATUS = "status"
_LABEL_TABLE = "table"
_LABEL_OPERATION = "operation"
_LABEL_CHECK_TYPE = "check_type"
_LABEL_SEVERITY = "severity"
_LABEL_METHOD = "method"
_LABEL_ENDPOINT = "endpoint"
_LABEL_STATUS_CODE = "status_code"
_LABEL_JOB = "job"

# ── Histogram bucket definitions ─────────────────────────────────────────────

# Connector fetch: typically 100ms to 30s
_CONNECTOR_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# DB operations: typically 1ms to 5s
_DB_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0)

# Orchestrator jobs: typically 1s to 5min
_ORCHESTRATOR_BUCKETS = (0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)

# HTTP serving: typically 5ms to 10s
_SERVING_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 10.0)

# ── Metric definitions ───────────────────────────────────────────────────────

# Connectors
connector_fetch_total = Counter(
    _CONNECTOR_FETCH_TOTAL,
    "Total number of connector fetch operations",
    [_LABEL_CONNECTOR, _LABEL_SOURCE, _LABEL_STATUS],
)

connector_fetch_duration = Histogram(
    _CONNECTOR_FETCH_DURATION,
    "Duration of connector fetch operations in seconds",
    [_LABEL_CONNECTOR, _LABEL_SOURCE],
    buckets=_CONNECTOR_BUCKETS,
)

connector_errors_total = Counter(
    _CONNECTOR_ERRORS_TOTAL,
    "Total number of connector errors",
    [_LABEL_CONNECTOR, _LABEL_SOURCE],
)

# Database
db_inserts_total = Counter(
    _DB_INSERTS_TOTAL,
    "Total number of database insert operations",
    [_LABEL_TABLE],
)

db_insert_duration = Histogram(
    _DB_INSERT_DURATION,
    "Duration of database insert operations in seconds",
    [_LABEL_TABLE],
    buckets=_DB_BUCKETS,
)

db_query_duration = Histogram(
    _DB_QUERY_DURATION,
    "Duration of database query operations in seconds",
    [_LABEL_TABLE, _LABEL_OPERATION],
    buckets=_DB_BUCKETS,
)

# Quality
quality_issues_total = Counter(
    _QUALITY_ISSUES_TOTAL,
    "Total number of data quality issues detected",
    [_LABEL_CHECK_TYPE, _LABEL_SEVERITY],
)

quality_records_total = Counter(
    _QUALITY_RECORDS_TOTAL,
    "Total number of records processed by quality checks",
    [_LABEL_STATUS],
)

# Orchestrator
orchestrator_jobs_total = Counter(
    _ORCHESTRATOR_JOBS_TOTAL,
    "Total number of orchestrator job runs",
    [_LABEL_JOB, _LABEL_STATUS],
)

orchestrator_job_duration = Histogram(
    _ORCHESTRATOR_JOB_DURATION,
    "Duration of orchestrator job runs in seconds",
    [_LABEL_JOB],
    buckets=_ORCHESTRATOR_BUCKETS,
)

orchestrator_jobs_running = Gauge(
    _ORCHESTRATOR_JOBS_RUNNING,
    "Number of orchestrator jobs currently running",
    [_LABEL_JOB],
)

# Serving
serving_requests_total = Counter(
    _SERVING_REQUESTS_TOTAL,
    "Total number of HTTP requests to the serving layer",
    [_LABEL_METHOD, _LABEL_ENDPOINT],
)

serving_request_duration = Histogram(
    _SERVING_REQUEST_DURATION,
    "Duration of HTTP requests in seconds",
    [_LABEL_METHOD, _LABEL_ENDPOINT],
    buckets=_SERVING_BUCKETS,
)

serving_responses_total = Counter(
    _SERVING_RESPONSES_TOTAL,
    "Total number of HTTP responses by status code",
    [_LABEL_METHOD, _LABEL_ENDPOINT, _LABEL_STATUS_CODE],
)


# ── Recording helpers ────────────────────────────────────────────────────────


def record_connector_fetch(
    connector: str,
    source: str,
    status: str,
    duration_s: float,
) -> None:
    """Record a connector fetch operation.

    Args:
        connector: Connector name (e.g. ``alpaca_historical``).
        source: Data source identifier (e.g. ``bars``, ``ticks``).
        status: Outcome (``success`` or ``error``).
        duration_s: Fetch duration in seconds.
    """
    connector_fetch_total.labels(connector=connector, source=source, status=status).inc()
    connector_fetch_duration.labels(connector=connector, source=source).observe(duration_s)
    if status == "error":
        connector_errors_total.labels(connector=connector, source=source).inc()


def record_db_insert(table: str, duration_s: float) -> None:
    """Record a database insert operation.

    Args:
        table: Target table name (e.g. ``bars``, ``ticks``).
        duration_s: Insert duration in seconds.
    """
    db_inserts_total.labels(table=table).inc()
    db_insert_duration.labels(table=table).observe(duration_s)


def record_db_query(table: str, operation: str, duration_s: float) -> None:
    """Record a database query operation.

    Args:
        table: Target table name.
        operation: Query type (e.g. ``select``, ``upsert``).
        duration_s: Query duration in seconds.
    """
    db_query_duration.labels(table=table, operation=operation).observe(duration_s)


def record_quality_issue(check_type: str, severity: str) -> None:
    """Record a data quality issue.

    Args:
        check_type: Type of check that detected the issue.
        severity: Issue severity (``WARN`` or ``FAIL``).
    """
    quality_issues_total.labels(check_type=check_type, severity=severity).inc()


def record_quality_records(passed: int, warnings: int, failures: int) -> None:
    """Record quality check outcomes for a batch of records.

    Args:
        passed: Number of records that passed.
        warnings: Number of records with warnings.
        failures: Number of records that failed.
    """
    quality_records_total.labels(status="passed").inc(passed)
    quality_records_total.labels(status="warning").inc(warnings)
    quality_records_total.labels(status="failure").inc(failures)


def record_orchestrator_job(job_name: str, status: str, duration_s: float) -> None:
    """Record an orchestrator job run.

    Args:
        job_name: Job configuration name.
        status: Outcome (e.g. ``success``, ``failed``, ``timeout``).
        duration_s: Job duration in seconds.
    """
    orchestrator_jobs_total.labels(job=job_name, status=status).inc()
    orchestrator_job_duration.labels(job=job_name).observe(duration_s)


def record_serving_request(
    method: str,
    endpoint: str,
    status_code: int,
    duration_s: float,
) -> None:
    """Record an HTTP request to the serving layer.

    Args:
        method: HTTP method (e.g. ``GET``).
        endpoint: Request path (e.g. ``/v1/bars``).
        status_code: HTTP response status code.
        duration_s: Request duration in seconds.
    """
    serving_requests_total.labels(method=method, endpoint=endpoint).inc()
    serving_request_duration.labels(method=method, endpoint=endpoint).observe(duration_s)
    serving_responses_total.labels(
        method=method, endpoint=endpoint, status_code=str(status_code)
    ).inc()
