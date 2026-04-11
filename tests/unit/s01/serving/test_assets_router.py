"""Tests for /v1/assets endpoint."""

from __future__ import annotations


def test_get_assets_all(client, mock_repo, sample_asset):
    mock_repo.list_assets.return_value = [sample_asset]
    resp = client.get("/v1/assets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "BTCUSDT"
    assert data[0]["asset_class"] == "crypto"


def test_get_assets_by_class(client, mock_repo, sample_asset):
    mock_repo.list_assets.return_value = [sample_asset]
    resp = client.get("/v1/assets", params={"asset_class": "crypto"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_assets_by_query(client, mock_repo, sample_asset):
    mock_repo.search_assets.return_value = [sample_asset]
    resp = client.get("/v1/assets", params={"query": "BTC"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "BTCUSDT"


def test_get_assets_empty(client, mock_repo):
    mock_repo.list_assets.return_value = []
    resp = client.get("/v1/assets")
    assert resp.status_code == 200
    assert resp.json() == []
