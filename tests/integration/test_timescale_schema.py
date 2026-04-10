"""Integration tests for TimescaleDB schema and repository.

Requires a running TimescaleDB instance (docker-compose.test.yml).
Run with: pytest tests/integration/ -m integration

These tests verify the full cycle:
  init_db -> insert assets -> insert bars/ticks -> query -> verify idempotence
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    DbTick,
    MacroPoint,
    MacroSeriesMeta,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(asyncpg is None, reason="asyncpg not installed"),
]

TEST_DSN = "postgresql://apex_test:apex_test@localhost:5433/apex_test"


@pytest.fixture
async def initialized_db():
    """Run migrations on the test database."""
    from scripts.init_db import run_migrations

    await run_migrations(
        host="localhost",
        port=5433,
        db="apex_test",
        user="apex_test",
        password="apex_test",
    )
    return


@pytest.fixture
async def repo(initialized_db):
    """Create a connected TimescaleRepository."""
    from core.data.timescale_repository import TimescaleRepository

    r = TimescaleRepository(dsn=TEST_DSN, pool_min=1, pool_max=3)
    await r.connect()
    yield r
    await r.close()


class TestFullCycle:
    @pytest.mark.asyncio
    async def test_asset_create_and_retrieve(self, repo):
        asset = Asset(
            symbol="BTCUSDT",
            exchange="BINANCE",
            asset_class=AssetClass.CRYPTO,
            currency="USD",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        )
        asset_id = await repo.upsert_asset(asset)
        assert isinstance(asset_id, uuid.UUID)

        fetched = await repo.get_asset("BTCUSDT", "BINANCE")
        assert fetched is not None
        assert fetched.symbol == "BTCUSDT"
        assert fetched.asset_class == AssetClass.CRYPTO

    @pytest.mark.asyncio
    async def test_insert_and_get_bars(self, repo):
        asset = Asset(
            symbol="ETHUSDT",
            exchange="BINANCE",
            asset_class=AssetClass.CRYPTO,
            currency="USD",
        )
        asset_id = await repo.upsert_asset(asset)

        base_time = datetime(2024, 6, 1, tzinfo=UTC)
        bars = [
            Bar(
                asset_id=asset_id,
                bar_type=BarType.TIME,
                bar_size=BarSize.M1,
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal("3500") + Decimal(str(i)),
                high=Decimal("3510") + Decimal(str(i)),
                low=Decimal("3490") + Decimal(str(i)),
                close=Decimal("3505") + Decimal(str(i)),
                volume=Decimal("100") + Decimal(str(i)),
            )
            for i in range(500)
        ]

        count = await repo.insert_bars(bars)
        assert count == 500

        result = await repo.get_bars(
            asset_id,
            "time",
            "1m",
            base_time,
            base_time + timedelta(minutes=500),
        )
        assert len(result) == 500
        assert result[0].open == Decimal("3500")
        assert result[-1].open == Decimal("3999")

    @pytest.mark.asyncio
    async def test_insert_and_get_ticks(self, repo):
        asset = Asset(
            symbol="AAPL",
            exchange="NYSE",
            asset_class=AssetClass.EQUITY,
            currency="USD",
        )
        asset_id = await repo.upsert_asset(asset)

        base_time = datetime(2024, 6, 1, tzinfo=UTC)
        ticks = [
            DbTick(
                asset_id=asset_id,
                timestamp=base_time + timedelta(milliseconds=i),
                trade_id=str(i),
                price=Decimal("175.50") + Decimal(str(i)) / Decimal("100"),
                quantity=Decimal("10"),
                side="buy" if i % 2 == 0 else "sell",
            )
            for i in range(1000)
        ]

        count = await repo.insert_ticks(ticks)
        assert count == 1000

        result = await repo.get_ticks(asset_id, base_time, base_time + timedelta(seconds=2))
        assert len(result) == 1000

    @pytest.mark.asyncio
    async def test_macro_series(self, repo):
        meta = MacroSeriesMeta(
            series_id="VIXCLS",
            source="FRED",
            name="CBOE VIX Close",
            frequency="daily",
            unit="index",
        )
        await repo.upsert_macro_metadata(meta)

        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        points = [
            MacroPoint(
                series_id="VIXCLS",
                timestamp=base_time + timedelta(days=i),
                value=15.0 + i * 0.1,
            )
            for i in range(30)
        ]
        count = await repo.insert_macro_points(points)
        assert count == 30

        result = await repo.get_macro_series("VIXCLS", base_time, base_time + timedelta(days=30))
        assert len(result) == 30

    @pytest.mark.asyncio
    async def test_schema_versions_populated(self, repo):
        pool = repo._get_pool()
        rows = await pool.fetch("SELECT * FROM schema_versions")
        assert len(rows) >= 1
        assert rows[0]["filename"] == "001_universal_schema.sql"

    @pytest.mark.asyncio
    async def test_init_db_idempotent(self, repo):
        """Re-running init_db should not error or duplicate entries."""
        from scripts.init_db import run_migrations

        await run_migrations(
            host="localhost",
            port=5433,
            db="apex_test",
            user="apex_test",
            password="apex_test",
        )

        pool = repo._get_pool()
        rows = await pool.fetch("SELECT * FROM schema_versions")
        filenames = [r["filename"] for r in rows]
        assert filenames.count("001_universal_schema.sql") == 1

    @pytest.mark.asyncio
    async def test_health_check(self, repo):
        assert await repo.health_check() is True
