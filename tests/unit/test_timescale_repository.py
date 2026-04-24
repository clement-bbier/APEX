"""Unit tests for core/data/timescale_repository.py.

Uses mocked asyncpg pool/connection to verify SQL queries and COPY protocol usage.

Coverage mission: 65% → ≥85% (Sprint 4 Vague 2 Wave B, Agent F).
Closes the 1pp gap to main-wide 85% threshold, unblocking #203.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
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
    CorporateEvent,
    DataQualityEntry,
    DbTick,
    EconomicEvent,
    FundamentalPoint,
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


# ── Connection init codec tests ──────────────────────────────────────────────


class TestInitConnection:
    @pytest.mark.asyncio
    async def test_init_connection_registers_json_codecs(self):
        """_init_connection registers both json and jsonb codecs."""
        conn = AsyncMock()
        await TimescaleRepository._init_connection(conn)

        # Two set_type_codec calls: one for jsonb, one for json
        assert conn.set_type_codec.await_count == 2
        calls = [call.args for call in conn.set_type_codec.await_args_list]
        codec_names = [args[0] for args in calls]
        assert "jsonb" in codec_names
        assert "json" in codec_names


# ── Asset lookup tests (covering get_asset/get_asset_by_id/search_assets) ────


def _mock_asset_row():
    """Build a mock asyncpg row for an Asset."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "asset_id": ASSET_ID,
        "symbol": "AAPL",
        "exchange": "NYSE",
        "asset_class": "equity",
        "currency": "USD",
        "timezone": "America/New_York",
        "tick_size": None,
        "lot_size": None,
        "is_active": True,
        "listing_date": None,
        "delisting_date": None,
        "metadata_json": {"sector": "tech"},
        "created_at": NOW,
        "updated_at": NOW,
    }[key]
    return row


class TestGetAsset:
    @pytest.mark.asyncio
    async def test_get_asset_found_returns_asset(self, repo):
        repo._pool.fetchrow = AsyncMock(return_value=_mock_asset_row())
        result = await repo.get_asset("aapl", "nyse")
        assert result is not None
        assert result.symbol == "AAPL"
        # symbol/exchange uppercased in query
        call_args = repo._pool.fetchrow.call_args
        assert call_args[0][1] == "AAPL"
        assert call_args[0][2] == "NYSE"

    @pytest.mark.asyncio
    async def test_get_asset_metadata_empty_when_falsy(self, repo):
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "asset_id": ASSET_ID,
            "symbol": "AAPL",
            "exchange": "NYSE",
            "asset_class": "equity",
            "currency": "USD",
            "timezone": "UTC",
            "tick_size": None,
            "lot_size": None,
            "is_active": True,
            "listing_date": None,
            "delisting_date": None,
            "metadata_json": None,
            "created_at": NOW,
            "updated_at": NOW,
        }[key]
        repo._pool.fetchrow = AsyncMock(return_value=row)
        result = await repo.get_asset("AAPL", "NYSE")
        assert result is not None
        assert result.metadata_json == {}


class TestGetAssetById:
    @pytest.mark.asyncio
    async def test_get_asset_by_id_found(self, repo):
        repo._pool.fetchrow = AsyncMock(return_value=_mock_asset_row())
        result = await repo.get_asset_by_id(ASSET_ID)
        assert result is not None
        assert result.symbol == "AAPL"
        sql = repo._pool.fetchrow.call_args[0][0]
        assert "asset_id" in sql

    @pytest.mark.asyncio
    async def test_get_asset_by_id_not_found(self, repo):
        repo._pool.fetchrow = AsyncMock(return_value=None)
        result = await repo.get_asset_by_id(ASSET_ID)
        assert result is None


class TestSearchAssets:
    @pytest.mark.asyncio
    async def test_search_assets_without_class_filter(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[_mock_asset_row()])
        result = await repo.search_assets("AAP")
        assert len(result) == 1
        sql = repo._pool.fetch.call_args[0][0]
        assert "ILIKE" in sql
        assert "asset_class" not in sql
        # LIKE pattern with % suffix
        assert repo._pool.fetch.call_args[0][1] == "AAP%"

    @pytest.mark.asyncio
    async def test_search_assets_with_class_filter(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.search_assets("BTC", asset_class=AssetClass.CRYPTO)
        sql = repo._pool.fetch.call_args[0][0]
        assert "asset_class" in sql
        # Both query pattern and asset_class value passed
        assert repo._pool.fetch.call_args[0][1] == "BTC%"
        assert repo._pool.fetch.call_args[0][2] == AssetClass.CRYPTO.value


# ── Bar tests (covering get_bars with limit) ─────────────────────────────────


class TestGetBarsWithLimit:
    @pytest.mark.asyncio
    async def test_get_bars_with_limit_appends_sql(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_bars(
            ASSET_ID,
            "time",
            "1m",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
            limit=100,
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "LIMIT 100" in sql

    @pytest.mark.asyncio
    async def test_insert_bars_result_not_string_uses_len(self, repo):
        """If copy_records_to_table returns non-str (e.g. None in older asyncpg), fall back to len."""
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
        repo._pool.copy_records_to_table = AsyncMock(return_value=None)
        count = await repo.insert_bars(bars)
        assert count == 2  # falls back to len(records)


# ── Tick tests (covering get_ticks + on_insert callback branch) ──────────────


class TestGetTicks:
    @pytest.mark.asyncio
    async def test_get_ticks_basic(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "asset_id": ASSET_ID,
            "timestamp": NOW,
            "trade_id": "t1",
            "price": Decimal("100"),
            "quantity": Decimal("1"),
            "side": "buy",
        }[key]
        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        ticks = await repo.get_ticks(
            ASSET_ID,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(ticks) == 1
        assert ticks[0].trade_id == "t1"

    @pytest.mark.asyncio
    async def test_get_ticks_with_limit(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_ticks(
            ASSET_ID,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
            limit=50,
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "LIMIT 50" in sql


class TestInsertTicksCallback:
    @pytest.mark.asyncio
    async def test_insert_ticks_invokes_callback(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value="COPY 3")
        repo._pool = mock_pool

        ticks = [
            DbTick(
                asset_id=ASSET_ID,
                timestamp=NOW,
                trade_id=f"t{i}",
                price=Decimal("100"),
                quantity=Decimal("1"),
                side="buy",
            )
            for i in range(3)
        ]
        await repo.insert_ticks(ticks)

        callback.assert_called_once()
        assert callback.call_args[0][0] == "ticks"
        assert callback.call_args[0][1] == 3


# ── Macro series tests (get_macro_series, callback, fallback on len) ─────────


class TestGetMacroSeries:
    @pytest.mark.asyncio
    async def test_get_macro_series_basic(self, repo):
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "series_id": "VIXCLS",
            "timestamp": NOW,
            "value": 18.5,
        }[key]
        repo._pool.fetch = AsyncMock(return_value=[mock_row])

        results = await repo.get_macro_series(
            "VIXCLS",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].series_id == "VIXCLS"
        assert results[0].value == 18.5

    @pytest.mark.asyncio
    async def test_get_macro_series_with_limit(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_macro_series(
            "VIXCLS",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
            limit=25,
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "LIMIT 25" in sql


class TestInsertMacroCallback:
    @pytest.mark.asyncio
    async def test_insert_macro_points_empty(self, repo):
        count = await repo.insert_macro_points([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_macro_points_callback_and_non_str_result(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        # Non-string return triggers len(records) fallback
        mock_pool.copy_records_to_table = AsyncMock(return_value=None)
        repo._pool = mock_pool

        points = [
            MacroPoint(series_id="VIXCLS", timestamp=NOW, value=18.5),
            MacroPoint(series_id="VIXCLS", timestamp=NOW, value=19.0),
        ]
        count = await repo.insert_macro_points(points)
        assert count == 2
        callback.assert_called_once()
        assert callback.call_args[0][0] == "macro_series"
        assert callback.call_args[0][1] == 2


# ── Fundamentals tests (insert_fundamentals + get_fundamentals with limit) ───


class TestInsertFundamentals:
    @pytest.mark.asyncio
    async def test_insert_fundamentals_empty(self, repo):
        count = await repo.insert_fundamentals([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_fundamentals_uses_copy(self, repo):
        points = [
            FundamentalPoint(
                asset_id=ASSET_ID,
                report_date=date(2024, 3, 31),
                period_type="quarterly",
                metric_name="revenue",
                value=94.8e9,
                currency="USD",
            ),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_fundamentals(points)
        assert count == 1
        call_args = repo._pool.copy_records_to_table.call_args
        assert call_args[1]["columns"] == [
            "asset_id",
            "report_date",
            "period_type",
            "metric_name",
            "value",
            "currency",
        ]

    @pytest.mark.asyncio
    async def test_insert_fundamentals_invokes_callback(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value="COPY 4")
        repo._pool = mock_pool

        points = [
            FundamentalPoint(
                asset_id=ASSET_ID,
                report_date=date(2024, 3, 31),
                period_type="quarterly",
                metric_name="revenue",
                value=1.0,
            )
            for _ in range(4)
        ]
        await repo.insert_fundamentals(points)
        callback.assert_called_once()
        assert callback.call_args[0][0] == "fundamentals"
        assert callback.call_args[0][1] == 4


class TestGetFundamentalsLimit:
    @pytest.mark.asyncio
    async def test_get_fundamentals_with_limit(self, repo):
        repo._pool.fetch = AsyncMock(return_value=[])
        await repo.get_fundamentals(
            ASSET_ID,
            date(2024, 1, 1),
            date(2024, 12, 31),
            limit=15,
        )
        sql = repo._pool.fetch.call_args[0][0]
        assert "LIMIT 15" in sql


# ── Economic events tests (insert_economic_events full path) ─────────────────


class TestInsertEconomicEvents:
    @pytest.mark.asyncio
    async def test_insert_economic_events_empty(self, repo):
        count = await repo.insert_economic_events([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_economic_events_uses_copy(self, repo):
        events = [
            EconomicEvent(
                event_type="FOMC",
                scheduled_time=NOW,
                impact_score=3,
                source="fed",
            ),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_economic_events(events)
        assert count == 1
        call_args = repo._pool.copy_records_to_table.call_args
        assert call_args[1]["columns"] == [
            "event_id",
            "event_type",
            "scheduled_time",
            "actual",
            "consensus",
            "prior",
            "impact_score",
            "related_asset_id",
            "source",
        ]

    @pytest.mark.asyncio
    async def test_insert_economic_events_callback_and_len_fallback(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value=None)  # non-str
        repo._pool = mock_pool

        events = [
            EconomicEvent(event_type="FOMC", scheduled_time=NOW, impact_score=2) for _ in range(2)
        ]
        count = await repo.insert_economic_events(events)
        assert count == 2
        callback.assert_called_once()
        assert callback.call_args[0][0] == "economic_events"


# ── Corporate events tests (insert_corporate_events full path) ───────────────


class TestInsertCorporateEvents:
    @pytest.mark.asyncio
    async def test_insert_corporate_events_empty(self, repo):
        count = await repo.insert_corporate_events([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_corporate_events_uses_copy(self, repo):
        events = [
            CorporateEvent(
                asset_id=ASSET_ID,
                event_date=date(2024, 6, 1),
                event_type="split",
                details_json={"ratio": "4:1"},
            ),
        ]
        repo._pool.copy_records_to_table = AsyncMock(return_value="COPY 1")

        count = await repo.insert_corporate_events(events)
        assert count == 1
        call_args = repo._pool.copy_records_to_table.call_args
        assert call_args[1]["columns"] == [
            "event_id",
            "asset_id",
            "event_date",
            "event_type",
            "details_json",
        ]

    @pytest.mark.asyncio
    async def test_insert_corporate_events_invokes_callback(self):
        callback = MagicMock()
        repo = TimescaleRepository(
            dsn="postgresql://x:x@localhost/x",
            on_insert=callback,
        )
        mock_pool = AsyncMock()
        mock_pool.copy_records_to_table = AsyncMock(return_value="COPY 2")
        repo._pool = mock_pool

        events = [
            CorporateEvent(
                asset_id=ASSET_ID,
                event_date=date(2024, 6, 1),
                event_type="dividend",
            )
            for _ in range(2)
        ]
        await repo.insert_corporate_events(events)
        callback.assert_called_once()
        assert callback.call_args[0][0] == "corporate_events"
        assert callback.call_args[0][1] == 2
