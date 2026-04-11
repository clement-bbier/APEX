"""Shared fixtures for serving layer tests."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    DbTick,
    EconomicEvent,
    FundamentalPoint,
    MacroPoint,
    MacroSeriesMeta,
)
from services.s01_data_ingestion.serving.app import app
from services.s01_data_ingestion.serving.deps import get_repo

_ASSET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_EVENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_repo():
    """Return an AsyncMock mimicking TimescaleRepository."""
    repo = AsyncMock()
    repo.health_check.return_value = True
    return repo


@pytest.fixture
def client(mock_repo):
    """Return a FastAPI TestClient with mocked repository."""
    app.dependency_overrides[get_repo] = lambda: mock_repo
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_asset():
    return Asset(
        asset_id=_ASSET_ID,
        symbol="BTCUSDT",
        exchange="BINANCE",
        asset_class=AssetClass.CRYPTO,
        currency="USD",
    )


@pytest.fixture
def sample_bar():
    return Bar(
        asset_id=_ASSET_ID,
        bar_type=BarType.TIME,
        bar_size=BarSize.M1,
        timestamp=_TS,
        open=Decimal("50000"),
        high=Decimal("50100"),
        low=Decimal("49900"),
        close=Decimal("50050"),
        volume=Decimal("123.45"),
    )


@pytest.fixture
def sample_tick():
    return DbTick(
        asset_id=_ASSET_ID,
        timestamp=_TS,
        trade_id="t1",
        price=Decimal("50000"),
        quantity=Decimal("0.5"),
        side="buy",
    )


@pytest.fixture
def sample_macro_point():
    return MacroPoint(
        series_id="VIXCLS",
        timestamp=_TS,
        value=15.5,
    )


@pytest.fixture
def sample_macro_meta():
    return MacroSeriesMeta(
        series_id="VIXCLS",
        source="FRED",
        name="CBOE Volatility Index: VIX",
        frequency="daily",
        unit="index",
        description="Market volatility index",
    )


@pytest.fixture
def sample_event():
    return EconomicEvent(
        event_id=_EVENT_ID,
        event_type="FOMC",
        scheduled_time=_TS,
        impact_score=3,
        source="fed",
    )


@pytest.fixture
def sample_fundamental():
    return FundamentalPoint(
        asset_id=_ASSET_ID,
        report_date=date(2024, 3, 31),
        period_type="quarterly",
        metric_name="revenue",
        value=94836000000.0,
        currency="USD",
    )
