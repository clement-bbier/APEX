"""Tests for /v1/bars and /v1/trades endpoints."""

from __future__ import annotations


def test_get_bars_success(client, mock_repo, sample_asset, sample_bar):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_bars.return_value = [sample_bar]
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["bar_size"] == "1m"
    assert data[0]["close"] == "50050"


def test_get_bars_asset_not_found(client, mock_repo):
    mock_repo.get_asset.return_value = None
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "NOPE",
            "exchange": "X",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_bars_empty(client, mock_repo, sample_asset):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_bars.return_value = []
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_bars_with_bar_type(client, mock_repo, sample_asset, sample_bar):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_bars.return_value = [sample_bar]
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "bar_size": "1h",
            "bar_type": "volume",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    mock_repo.get_bars.assert_called_once()


def test_get_bars_limit_applied(client, mock_repo, sample_asset, sample_bar):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_bars.return_value = [sample_bar] * 2
    resp = client.get(
        "/v1/bars",
        params={
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "bar_size": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
            "limit": 2,
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_bars.call_args
    assert kwargs["limit"] == 2


def test_get_bars_missing_required_param(client):
    resp = client.get("/v1/bars", params={"symbol": "X"})
    assert resp.status_code == 422


def test_get_trades_success(client, mock_repo, sample_asset, sample_tick):
    mock_repo.get_asset.return_value = sample_asset
    mock_repo.get_ticks.return_value = [sample_tick]
    resp = client.get(
        "/v1/trades",
        params={
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["side"] == "buy"
    assert data[0]["price"] == "50000"


def test_get_trades_asset_not_found(client, mock_repo):
    mock_repo.get_asset.return_value = None
    resp = client.get(
        "/v1/trades",
        params={
            "symbol": "NOPE",
            "exchange": "X",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []
