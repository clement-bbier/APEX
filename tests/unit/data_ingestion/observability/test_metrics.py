"""Unit tests for S01 observability metrics.

Verifies that each recording helper correctly increments the
corresponding Prometheus counter/histogram.
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Histogram

from services.s01_data_ingestion.observability import metrics


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace all module-level metrics with fresh instances per test.

    This prevents state leakage between tests since Prometheus metrics
    are global singletons.
    """
    registry = CollectorRegistry()

    # Rebuild all counters/histograms in the isolated registry
    monkeypatch.setattr(
        metrics,
        "connector_fetch_total",
        Counter(
            "test_connector_fetch_total",
            "test",
            ["connector", "source", "status"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "connector_fetch_duration",
        Histogram(
            "test_connector_fetch_duration_seconds",
            "test",
            ["connector", "source"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "connector_errors_total",
        Counter(
            "test_connector_errors_total",
            "test",
            ["connector", "source"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "db_inserts_total",
        Counter("test_db_inserts_total", "test", ["table"], registry=registry),
    )
    monkeypatch.setattr(
        metrics,
        "db_insert_duration",
        Histogram(
            "test_db_insert_duration_seconds",
            "test",
            ["table"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "db_query_duration",
        Histogram(
            "test_db_query_duration_seconds",
            "test",
            ["table", "operation"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "quality_issues_total",
        Counter(
            "test_quality_issues_total",
            "test",
            ["check_type", "severity"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "quality_records_total",
        Counter(
            "test_quality_records_total",
            "test",
            ["status"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "serving_requests_total",
        Counter(
            "test_serving_requests_total",
            "test",
            ["method", "endpoint"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "serving_request_duration",
        Histogram(
            "test_serving_request_duration_seconds",
            "test",
            ["method", "endpoint"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "serving_responses_total",
        Counter(
            "test_serving_responses_total",
            "test",
            ["method", "endpoint", "status_code"],
            registry=registry,
        ),
    )


class TestRecordConnectorFetch:
    """Tests for record_connector_fetch helper."""

    def test_success_increments_counter(self) -> None:
        metrics.record_connector_fetch("alpaca", "bars", "success", 1.5)
        val = metrics.connector_fetch_total.labels(
            connector="alpaca", source="bars", status="success"
        )._value.get()
        assert val == 1.0

    def test_error_increments_error_counter(self) -> None:
        metrics.record_connector_fetch("fred", "series", "error", 5.0)
        val = metrics.connector_errors_total.labels(connector="fred", source="series")._value.get()
        assert val == 1.0

    def test_duration_observed(self) -> None:
        metrics.record_connector_fetch("binance", "ticks", "success", 0.42)
        count = metrics.connector_fetch_duration.labels(
            connector="binance", source="ticks"
        )._sum.get()
        assert count == pytest.approx(0.42)

    def test_multiple_calls_accumulate(self) -> None:
        metrics.record_connector_fetch("ecb", "series", "success", 1.0)
        metrics.record_connector_fetch("ecb", "series", "success", 2.0)
        val = metrics.connector_fetch_total.labels(
            connector="ecb", source="series", status="success"
        )._value.get()
        assert val == 2.0


class TestRecordDbInsert:
    """Tests for record_db_insert helper."""

    def test_increments_counter_by_rows(self) -> None:
        metrics.record_db_insert("bars", rows=50, duration_s=0.01)
        val = metrics.db_inserts_total.labels(table="bars")._value.get()
        assert val == 50.0

    def test_records_duration(self) -> None:
        metrics.record_db_insert("ticks", rows=10, duration_s=0.123)
        total = metrics.db_insert_duration.labels(table="ticks")._sum.get()
        assert total == pytest.approx(0.123)


class TestRecordDbQuery:
    """Tests for record_db_query helper."""

    def test_records_query_duration(self) -> None:
        metrics.record_db_query("bars", "select", 0.05)
        total = metrics.db_query_duration.labels(table="bars", operation="select")._sum.get()
        assert total == pytest.approx(0.05)


class TestRecordQualityIssue:
    """Tests for record_quality_issue helper."""

    def test_increments_by_type_and_severity(self) -> None:
        metrics.record_quality_issue("gap_check", "warn")
        val = metrics.quality_issues_total.labels(
            check_type="gap_check", severity="warn"
        )._value.get()
        assert val == 1.0


class TestRecordQualityRecords:
    """Tests for record_quality_records helper."""

    def test_records_all_statuses(self) -> None:
        metrics.record_quality_records(passed=10, warnings=2, failures=1)
        assert metrics.quality_records_total.labels(status="passed")._value.get() == 10.0
        assert metrics.quality_records_total.labels(status="warning")._value.get() == 2.0
        assert metrics.quality_records_total.labels(status="failure")._value.get() == 1.0


class TestRecordServingRequest:
    """Tests for record_serving_request helper."""

    def test_increments_request_counter(self) -> None:
        metrics.record_serving_request("GET", "/v1/bars", 200, 0.05)
        val = metrics.serving_requests_total.labels(method="GET", endpoint="/v1/bars")._value.get()
        assert val == 1.0

    def test_records_response_status_code(self) -> None:
        metrics.record_serving_request("GET", "/health", 200, 0.01)
        val = metrics.serving_responses_total.labels(
            method="GET", endpoint="/health", status_code="200"
        )._value.get()
        assert val == 1.0
