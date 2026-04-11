"""End-to-end integration test for the APEX Serving Layer.

Requires a running TimescaleDB instance. Skipped unless
APEX_NETWORK_TESTS=1 is set in the environment.

Tests insert data via TimescaleRepository, then query via
httpx.AsyncClient to verify full round-trip.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    EconomicEvent,
    MacroPoint,
    MacroSeriesMeta,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("APEX_NETWORK_TESTS") != "1",
        reason="APEX_NETWORK_TESTS not set",
    ),
]

_ASSET_ID = uuid.uuid4()
_TS = datetime(2024, 6, 15, 14, 30, 0, tzinfo=UTC)


@pytest.fixture
async def repo():
    """Create a real TimescaleRepository connected to the test DB."""
    from core.config import get_settings
    from core.data.timescale_repository import TimescaleRepository

    settings = get_settings()
    r = TimescaleRepository(dsn=settings.timescale_dsn)
    await r.connect()
    yield r
    await r.close()


@pytest.fixture
async def e2e_client(repo):
    """Async httpx client wired to the FastAPI app with a real repo."""
    from services.s01_data_ingestion.serving.app import app
    from services.s01_data_ingestion.serving.deps import get_repo

    app.dependency_overrides[get_repo] = lambda: repo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def test_bars_round_trip(repo, e2e_client):
    """Insert a bar via repo, query via API."""
    asset = Asset(
        asset_id=_ASSET_ID,
        symbol="TESTBTC",
        exchange="TESTEX",
        asset_class=AssetClass.CRYPTO,
        currency="USD",
    )
    await repo.upsert_asset(asset)
    bar = Bar(
        asset_id=_ASSET_ID,
        bar_type=BarType.TIME,
        bar_size=BarSize.M1,
        timestamp=_TS,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1000"),
    )
    await repo.insert_bars([bar])
    resp = await e2e_client.get(
        "/v1/bars",
        params={
            "symbol": "TESTBTC",
            "exchange": "TESTEX",
            "bar_size": "1m",
            "start": "2024-06-15T00:00:00Z",
            "end": "2024-06-16T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


async def test_macro_round_trip(repo, e2e_client):
    """Insert a macro point via repo, query via API."""
    meta = MacroSeriesMeta(
        series_id="TEST_VIX",
        source="TEST",
        name="Test VIX",
    )
    await repo.upsert_macro_metadata(meta)
    point = MacroPoint(series_id="TEST_VIX", timestamp=_TS, value=20.0)
    await repo.insert_macro_points([point])
    resp = await e2e_client.get(
        "/v1/macro_series",
        params={
            "series_id": "TEST_VIX",
            "start": "2024-06-01T00:00:00Z",
            "end": "2024-07-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


async def test_upcoming_events_round_trip(repo, e2e_client):
    """Insert a future event via repo, query via /upcoming."""
    future_time = datetime.now(UTC) + timedelta(minutes=30)
    event = EconomicEvent(
        event_type="FOMC_TEST",
        scheduled_time=future_time,
        impact_score=3,
        source="test",
    )
    await repo.insert_economic_events([event])
    resp = await e2e_client.get(
        "/v1/economic_events/upcoming",
        params={"within_minutes": 60},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["event_type"] == "FOMC_TEST" for e in data)


async def test_health_with_real_db(e2e_client):
    """Verify /health returns ok with a real DB."""
    resp = await e2e_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
