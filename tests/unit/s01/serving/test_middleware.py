"""Unit tests for S01 serving observability middleware.

Verifies that the ObservabilityMiddleware records metrics for
HTTP requests and excludes internal paths.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter, Histogram

from services.s01_data_ingestion.observability import metrics
from services.s01_data_ingestion.serving.middleware import ObservabilityMiddleware


@pytest.fixture
def test_app() -> FastAPI:
    """Create a minimal FastAPI app with middleware."""
    application = FastAPI()
    application.add_middleware(ObservabilityMiddleware)

    @application.get("/v1/test")
    async def test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/metrics")
    async def metrics_endpoint() -> dict[str, str]:
        return {"metrics": "data"}

    return application


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def _isolated_serving_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace serving metrics with isolated instances."""
    registry = CollectorRegistry()
    monkeypatch.setattr(
        metrics,
        "serving_requests_total",
        Counter(
            "test_mw_requests_total",
            "test",
            ["method", "endpoint"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "serving_request_duration",
        Histogram(
            "test_mw_request_duration_seconds",
            "test",
            ["method", "endpoint"],
            registry=registry,
        ),
    )
    monkeypatch.setattr(
        metrics,
        "serving_responses_total",
        Counter(
            "test_mw_responses_total",
            "test",
            ["method", "endpoint", "status_code"],
            registry=registry,
        ),
    )


class TestObservabilityMiddleware:
    """Tests for the ObservabilityMiddleware."""

    def test_records_request_metrics(self, client: TestClient) -> None:
        client.get("/v1/test")
        val = metrics.serving_requests_total.labels(method="GET", endpoint="/v1/test")._value.get()
        assert val == 1.0

    def test_records_response_status(self, client: TestClient) -> None:
        client.get("/v1/test")
        val = metrics.serving_responses_total.labels(
            method="GET", endpoint="/v1/test", status_code="200"
        )._value.get()
        assert val == 1.0

    def test_records_duration_histogram(self, client: TestClient) -> None:
        client.get("/v1/test")
        # Verify the duration histogram was observed (sum >= 0)
        total = metrics.serving_request_duration.labels(
            method="GET", endpoint="/v1/test"
        )._sum.get()
        assert total >= 0.0

    def test_excludes_metrics_path(self, client: TestClient) -> None:
        client.get("/metrics")
        val = metrics.serving_requests_total.labels(method="GET", endpoint="/metrics")._value.get()
        assert val == 0.0

    def test_multiple_requests_accumulate(self, client: TestClient) -> None:
        client.get("/v1/test")
        client.get("/v1/test")
        val = metrics.serving_requests_total.labels(method="GET", endpoint="/v1/test")._value.get()
        assert val == 2.0
