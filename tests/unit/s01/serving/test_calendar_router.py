"""Tests for /v1/economic_events and /v1/economic_events/upcoming endpoints."""

from __future__ import annotations


def test_get_economic_events_success(client, mock_repo, sample_event):
    mock_repo.get_economic_events.return_value = [sample_event]
    resp = client.get(
        "/v1/economic_events",
        params={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-12-31T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "FOMC"
    assert data[0]["impact_score"] == 3


def test_get_economic_events_with_type_filter(client, mock_repo, sample_event):
    mock_repo.get_economic_events.return_value = [sample_event]
    resp = client.get(
        "/v1/economic_events",
        params={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-12-31T00:00:00Z",
            "event_type": "FOMC",
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_economic_events.call_args
    assert kwargs["event_type"] == "FOMC"


def test_get_economic_events_with_min_impact(client, mock_repo):
    mock_repo.get_economic_events.return_value = []
    resp = client.get(
        "/v1/economic_events",
        params={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-12-31T00:00:00Z",
            "min_impact": 3,
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_economic_events.call_args
    assert kwargs["min_impact"] == 3


def test_get_economic_events_empty(client, mock_repo):
    mock_repo.get_economic_events.return_value = []
    resp = client.get(
        "/v1/economic_events",
        params={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_economic_events_limit(client, mock_repo, sample_event):
    mock_repo.get_economic_events.return_value = [sample_event] * 2
    resp = client.get(
        "/v1/economic_events",
        params={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-12-31T00:00:00Z",
            "limit": 2,
        },
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_economic_events.call_args
    assert kwargs["limit"] == 2


def test_get_upcoming_events_success(client, mock_repo, sample_event):
    mock_repo.get_economic_events.return_value = [sample_event]
    resp = client.get(
        "/v1/economic_events/upcoming",
        params={"within_minutes": 60},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "FOMC"


def test_get_upcoming_events_empty(client, mock_repo):
    mock_repo.get_economic_events.return_value = []
    resp = client.get(
        "/v1/economic_events/upcoming",
        params={"within_minutes": 30},
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_upcoming_events_with_min_impact(client, mock_repo):
    mock_repo.get_economic_events.return_value = []
    resp = client.get(
        "/v1/economic_events/upcoming",
        params={"within_minutes": 45, "min_impact": 2},
    )
    assert resp.status_code == 200
    _, kwargs = mock_repo.get_economic_events.call_args
    assert kwargs["min_impact"] == 2


def test_get_upcoming_events_invalid_window(client):
    resp = client.get(
        "/v1/economic_events/upcoming",
        params={"within_minutes": 0},
    )
    assert resp.status_code == 422


def test_get_upcoming_events_missing_param(client):
    resp = client.get("/v1/economic_events/upcoming")
    assert resp.status_code == 422
