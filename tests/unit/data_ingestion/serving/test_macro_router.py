"""Tests for /v1/macro_series and /v1/macro_series/metadata endpoints."""

from __future__ import annotations


def test_get_macro_series_success(client, mock_repo, sample_macro_point):
    mock_repo.get_macro_series.return_value = [sample_macro_point]
    resp = client.get(
        "/v1/macro_series",
        params={
            "series_id": "VIXCLS",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-07-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["series_id"] == "VIXCLS"
    assert data[0]["value"] == 15.5


def test_get_macro_series_empty(client, mock_repo):
    mock_repo.get_macro_series.return_value = []
    resp = client.get(
        "/v1/macro_series",
        params={
            "series_id": "UNKNOWN",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-07-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_macro_series_limit(client, mock_repo, sample_macro_point):
    mock_repo.get_macro_series.return_value = [sample_macro_point] * 3
    resp = client.get(
        "/v1/macro_series",
        params={
            "series_id": "VIXCLS",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-07-01T00:00:00Z",
            "limit": 3,
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_macro_series.call_args
    assert kwargs["limit"] == 3


def test_get_macro_metadata_success(client, mock_repo, sample_macro_meta):
    mock_repo.get_macro_metadata.return_value = sample_macro_meta
    resp = client.get(
        "/v1/macro_series/metadata",
        params={"series_id": "VIXCLS"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["series_id"] == "VIXCLS"
    assert body["source"] == "FRED"
    assert body["frequency"] == "daily"


def test_get_macro_metadata_not_found(client, mock_repo):
    mock_repo.get_macro_metadata.return_value = None
    resp = client.get(
        "/v1/macro_series/metadata",
        params={"series_id": "NONEXISTENT"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_get_macro_series_missing_param(client):
    resp = client.get("/v1/macro_series", params={"series_id": "VIXCLS"})
    assert resp.status_code == 422
