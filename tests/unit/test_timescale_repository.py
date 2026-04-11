"""Unit tests for core/data/timescale_repository.py.

Uses mocked asyncpg pool/connection to verify SQL queries and COPY protocol usage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import after models so we can mock asyncpg
from core.data.timescale_repository import TimescaleRepository
from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    DataQualityEntry,
    DbTick,
    IngestionStatus,
    MacroPoint,
    MacroSeriesMeta,
    Severity,
)

NOW = datetime.now(UTC)
ASSET_ID = uuid.uuid4()


@pytest.fixture
def repo():
    """Create a repository with a mocked pool."""
    r = TimescaleRepository(dsn="postgresql://test:test@localhost:5432/test")
    mock_pool = AsyncMock()
    r._pool = mock_pool
    return r


# ── Connection tests ──────────────────────────────────────────────────────────


class TestConnection:
    def test_get_pool_raises_when_not_connected(self):
        repo = TimescaleRepository(dsn="postgresql://x:x@localhost/x")
        with pytest.raises(RuntimeError, match="not connected"):
            repo._get_pool()

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        repo = TimescaleRepository(dsn="postgresql://x:x@localhost/x")
        with patch(
            "core.data.timescale_repository.asyncpg.create_pool", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = AsyncMock()
            await repo.connect()
            mock_create.assert_called_once_with(
                "postgresql://x:x@localhost/x",
                min_size=2,
                max_size=10,
                init=TimescaleRepository._init_connection,
            )
            assert repo._pool is not None

    @pytest.mark.asyncio
    async def test_close_closes_pool(self):
        repo = TimescaleRepository(dsn="postgresql://x:x@localhost/x")
        mock_pool = AsyncMock()
        repo._pool = mock_pool
        await repo.close()
        mock_pool.close.assert_called_once()
        assert repo._pool is None


# ── Asset tests ───────────────────────────────────────────────────────────────


class TestUpsertAsset:
    @pytest.mark.asyncio
    async def test_upsert_asset_uses_on_conflict(self, repo):
        asset = Asset(
            symbol="BTCUSDT",
            exchange="BINANCE",
            asset_class=AssetClass.CRYPTO,
            currency="USD",
        )
        mock_row = {"asset_id": asset.asset_id}
        repo._pool.fetchrow = AsyncMock(return_value=mock_row)

        result = await repo.upsert_asset(asset)

        assert result == asset.asset_id
        call_args = repo._pool.fetchrow.call_args
        sql = call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "symbol, exchange" in sql

    @pytest.mark.asyncio
    async def test_get_asset_returns_none_when_missing(self, repo):
        repo._pool.fetchrow = AsyncMock(return_value=None)
        result = await repo.get_asset("MISSING", "NOWHERE")
        assert result is None


# ── Bar tests ─────────────────────────────────────────────────────────────────


class TestInsertBars:
    @pytest.mark.asyncio
    async def test_insert_bars_uses_copy(self, repo):
        bars = [
            Bar(
                asset_id=ASSET_ID,
                bar_type=BarType.TIME,
                bar_size=BarSize.M1,
                timestamp=NOW,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            ),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_bars(bars)

        assert count == 1
        call_args = repo._pool.copy_records_to_table.call_args
        assert call_args[1]["columns"] == [
            "asset_id",
            "bar_type",
            "bar_size",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_count",
            "vwap",
            "adj_close",
        ]

    @pytest.mark.asyncio
    async def test_insert_bars_empty_list(self, repo):
        count = await repo.insert_bars([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_bars_query(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "asset_id": ASSET_ID,
            "bar_type": "time",
            "bar_size": "1m",
            "timestamp": NOW,
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100.5"),
            "volume": Decimal("1000"),
            "trade_count": None,
            "vwap": None,
            "adj_close": None,
        }[key]

        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        bars = await repo.get_bars(
            ASSET_ID,
            "time",
            "1m",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(bars) == 1
        assert bars[0].bar_type == BarType.TIME

        call_args = repo._pool.fetch.call_args
        sql = call_args[0][0]
        assert "bar_type" in sql
        assert "bar_size" in sql


# ── Tick tests ────────────────────────────────────────────────────────────────


class TestInsertTicks:
    @pytest.mark.asyncio
    async def test_insert_ticks_uses_copy(self, repo):
        ticks = [
            DbTick(
                asset_id=ASSET_ID,
                timestamp=NOW,
                price=Decimal("50000"),
                quantity=Decimal("0.1"),
                trade_id="t1",
            ),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_ticks(ticks)

        assert count == 1
        call_args = repo._pool.copy_records_to_table.call_args
        assert call_args[1]["columns"] == [
            "asset_id",
            "timestamp",
            "trade_id",
            "price",
            "quantity",
            "side",
        ]

    @pytest.mark.asyncio
    async def test_insert_ticks_empty(self, repo):
        count = await repo.insert_ticks([])
        assert count == 0


# ── Health check tests ────────────────────────────────────────────────────────


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_true(self, repo):
        mock_row = {"ok": 1}
        repo._pool.fetchrow = AsyncMock(return_value=mock_row)
        assert await repo.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_on_error(self, repo):
        repo._pool.fetchrow = AsyncMock(side_effect=Exception("connection lost"))
        assert await repo.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_false_when_not_connected(self):
        repo = TimescaleRepository(dsn="postgresql://x:x@localhost/x")
        assert await repo.health_check() is False


# ── Macro tests ───────────────────────────────────────────────────────────────


class TestMacro:
    @pytest.mark.asyncio
    async def test_insert_macro_points(self, repo):
        points = [
            MacroPoint(series_id="VIXCLS", timestamp=NOW, value=18.5),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_macro_points(points)
        assert count == 1

    @pytest.mark.asyncio
    async def test_upsert_macro_metadata(self, repo):
        meta = MacroSeriesMeta(series_id="VIXCLS", source="FRED", name="VIX Close")
        repo._pool.execute = AsyncMock()
        await repo.upsert_macro_metadata(meta)

        call_args = repo._pool.execute.call_args
        sql = call_args[0][0]
        assert "ON CONFLICT" in sql


# ── Ingestion tracking tests ─────────────────────────────────────────────────


class TestIngestionTracking:
    @pytest.mark.asyncio
    async def test_start_ingestion_run(self, repo):
        repo._pool.execute = AsyncMock()
        run_id = await repo.start_ingestion_run("binance", ASSET_ID)
        assert isinstance(run_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_finish_ingestion_run(self, repo):
        repo._pool.execute = AsyncMock()
        run_id = uuid.uuid4()
        await repo.finish_ingestion_run(run_id, IngestionStatus.SUCCESS, 1000)
        repo._pool.execute.assert_called_once()


# ── Data quality tests ────────────────────────────────────────────────────────


class TestDataQuality:
    @pytest.mark.asyncio
    async def test_log_quality_check(self, repo):
        entry = DataQualityEntry(
            check_type="gap",
            severity=Severity.WARNING,
            asset_id=ASSET_ID,
        )
        repo._pool.execute = AsyncMock()
        await repo.log_quality_check(entry)
        repo._pool.execute.assert_called_once()


# ── New query method tests (Phase 2.10) ─────────────────────────────────────


class TestListAssets:
    @pytest.mark.asyncio
    async def test_list_assets_all(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "asset_id": ASSET_ID,
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "asset_class": "crypto",
            "currency": "USD",
            "timezone": "UTC",
            "tick_size": None,
            "lot_size": None,
            "is_active": True,
            "listing_date": None,
            "delisting_date": None,
            "metadata_json": {},
            "created_at": NOW,
            "updated_at": NOW,
        }[key]
        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        assets = await repo.list_assets()
        assert len(assets) == 1
        assert assets[0].symbol == "BTCUSDT"

        sql = repo._pool.fetch.call_args[0][0]
        assert "ORDER BY symbol" in sql

    @pytest.mark.asyncio
    async def test_list_assets_filtered(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.list_assets(asset_class=AssetClass.CRYPTO)
        sql = repo._pool.fetch.call_args[0][0]
        assert "asset_class" in sql


class TestGetMacroMetadata:
    @pytest.mark.asyncio
    async def test_get_macro_metadata_found(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "series_id": "VIXCLS",
            "source": "FRED",
            "name": "VIX Close",
            "frequency": "daily",
            "unit": "index",
            "description": "Volatility index",
        }[key]
        repo._pool.fetchrow = AsyncMock(return_value=mock_row)

        meta = await repo.get_macro_metadata("VIXCLS")
        assert meta is not None
        assert meta.series_id == "VIXCLS"
        assert meta.source == "FRED"

    @pytest.mark.asyncio
    async def test_get_macro_metadata_not_found(self, repo):
        repo._pool.fetchrow = AsyncMock(return_value=None)
        meta = await repo.get_macro_metadata("NONEXISTENT")
        assert meta is None


class TestGetFundamentals:
    @pytest.mark.asyncio
    async def test_get_fundamentals_query(self, repo):
        from datetime import date

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "asset_id": ASSET_ID,
            "report_date": date(2024, 3, 31),
            "period_type": "quarterly",
            "metric_name": "revenue",
            "value": 94836000000.0,
            "currency": "USD",
        }[key]
        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        results = await repo.get_fundamentals(
            ASSET_ID,
            date(2024, 1, 1),
            date(2024, 12, 31),
        )
        assert len(results) == 1
        assert results[0].metric_name == "revenue"

    @pytest.mark.asyncio
    async def test_get_fundamentals_with_period_type(self, repo):
        from datetime import date

        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_fundamentals(
            ASSET_ID,
            date(2024, 1, 1),
            date(2024, 12, 31),
            period_type="quarterly",
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "period_type" in sql


class TestGetEconomicEvents:
    @pytest.mark.asyncio
    async def test_get_economic_events_basic(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "event_id": uuid.uuid4(),
            "event_type": "FOMC",
            "scheduled_time": NOW,
            "actual": None,
            "consensus": None,
            "prior": None,
            "impact_score": 3,
            "related_asset_id": None,
            "source": "fed",
        }[key]
        mock_row.get = lambda key, default=None: {
            "source": "fed",
        }.get(key, default)
        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        events = await repo.get_economic_events(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(events) == 1
        assert events[0].event_type == "FOMC"

    @pytest.mark.asyncio
    async def test_get_economic_events_with_type(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_economic_events(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            event_type="FOMC",
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "event_type" in sql

    @pytest.mark.asyncio
    async def test_get_economic_events_with_limit(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_economic_events(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            limit=10,
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "LIMIT 10" in sql


# ── On-insert callback tests ────────────────────────────────────────────────


class TestOnInsertCallback:
    @pytest.mark.asyncio
    async def test_callback_invoked_after_insert_bars(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value="COPY 5")
        repo._pool = mock_pool

        bars = [
            Bar(
                asset_id=ASSET_ID,
                bar_type=BarType.TIME,
                bar_size=BarSize.D1,
                timestamp=NOW,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            )
        ]
        await repo.insert_bars(bars)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "bars"
        assert args[1] == 5  # rows from "COPY 5"
        assert isinstance(args[2], float)  # duration

    @pytest.mark.asyncio
    async def test_no_callback_when_none(self):
        repo = TimescaleRepository(dsn="postgresql://x:x@localhost/x")
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value="COPY 1")
        repo._pool = mock_pool

        ticks = [
            DbTick(
                asset_id=ASSET_ID,
                timestamp=NOW,
                trade_id="t1",
                price=Decimal("100"),
                quantity=Decimal("1"),
                side="buy",
            )
        ]
        # Should not raise even without callback
        await repo.insert_ticks(ticks)
