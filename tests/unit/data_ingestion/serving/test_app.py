"""Tests for the serving layer app (lifespan, health, error handlers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from services.data_ingestion.serving.app import app


def test_health_ok(client, mock_repo):
    mock_repo.health_check.return_value = True
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] is True


def test_health_degraded(client, mock_repo):
    mock_repo.health_check.return_value = False
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["database"] is False


def test_value_error_returns_400(client, mock_repo):
    mock_repo.get_asset.side_effect = ValueError("bad input")
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "X",
            "exchange": "Y",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 400
    assert "bad input" in resp.json()["detail"]


def test_generic_error_returns_500(client, mock_repo):
    mock_repo.get_asset.side_effect = RuntimeError("db exploded")
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "X",
            "exchange": "Y",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error"
    assert "exploded" not in resp.json()["detail"]


def test_lifespan_creates_and_closes_repo():
    """Verify lifespan wires up the repo correctly."""
    mock_repo = AsyncMock()
    mock_repo.connect = AsyncMock()
    mock_repo.close = AsyncMock()
    mock_repo.health_check = AsyncMock(return_value=True)

    with (
        patch(
            "services.data_ingestion.serving.app.TimescaleRepository",
            return_value=mock_repo,
        ),
        patch("services.data_ingestion.serving.app.init_tracing"),
    ):
        with TestClient(app):
            mock_repo.connect.assert_called_once()
        mock_repo.close.assert_called_once()
