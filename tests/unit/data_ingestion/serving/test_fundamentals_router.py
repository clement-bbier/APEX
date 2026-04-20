"""Tests for /v1/fundamentals endpoint."""

from __future__ import annotations


def test_get_fundamentals_success(client, mock_repo, sample_asset, sample_fundamental):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_fundamentals.return_value = [sample_fundamental]
    resp = client.get(
        "/v1/fundamentals",
        params={
            "symbol": "AAPL",
            "exchange": "NYSE",
            "start": "2024-01-01",
            "end": "2024-12-31",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["metric_name"] == "revenue"
    assert data[0]["period_type"] == "quarterly"


def test_get_fundamentals_asset_not_found(client, mock_repo):
    mock_repo.get_asset.return_value = None
    resp = client.get(
        "/v1/fundamentals",
        params={
            "symbol": "NOPE",
            "exchange": "X",
            "start": "2024-01-01",
            "end": "2024-12-31",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_fundamentals_with_period_type(client, mock_repo, sample_asset, sample_fundamental):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_fundamentals.return_value = [sample_fundamental]
    resp = client.get(
        "/v1/fundamentals",
        params={
            "symbol": "AAPL",
            "exchange": "NYSE",
            "start": "2024-01-01",
            "end": "2024-12-31",
            "period_type": "quarterly",
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_fundamentals.call_args
    assert kwargs["period_type"] == "quarterly"


def test_get_fundamentals_empty(client, mock_repo, sample_asset):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_fundamentals.return_value = []
    resp = client.get(
        "/v1/fundamentals",
        params={
            "symbol": "AAPL",
            "exchange": "NYSE",
            "start": "2024-01-01",
            "end": "2024-12-31",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []
