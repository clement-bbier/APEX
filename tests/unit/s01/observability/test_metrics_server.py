"""Unit tests for S01 observability metrics server.

Verifies that the /metrics endpoint returns Prometheus exposition format.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter

from services.s01_data_ingestion.observability.metrics_server import (
    mount_metrics_endpoint,
)


@pytest.fixture
def test_app() -> FastAPI:
    """Create a minimal FastAPI app with metrics endpoint."""
    application = FastAPI()
    registry = CollectorRegistry()
    # Add a test metric to the registry
    test_counter = Counter(
        "test_requests_total",
        "A test counter",
        registry=registry,
    )
    test_counter.inc()
    mount_metrics_endpoint(application, registry=registry)
    return application


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(test_app)


class TestMetricsEndpoint:
    """Tests for the /metrics endpoint."""

    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_content_type_is_prometheus(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_contains_metric_data(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert b"test_requests_total" in resp.content

    def test_custom_path(self) -> None:
        application = FastAPI()
        registry = CollectorRegistry()
        mount_metrics_endpoint(application, path="/custom_metrics", registry=registry)
        client = TestClient(application)
        resp = client.get("/custom_metrics")
        assert resp.status_code == 200

    def test_not_in_openapi_schema(self, test_app: FastAPI) -> None:
        schema = test_app.openapi()
        assert "/metrics" not in schema.get("paths", {})
