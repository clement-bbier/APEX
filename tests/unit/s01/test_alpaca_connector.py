"""Unit tests for Alpaca connectors and normalizers (Phase 2.5).

Tests: AlpacaHistoricalConnector, AlpacaBarNormalizer, AlpacaTradeNormalizer.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType, DbTick
from services.s01_data_ingestion.connectors.alpaca_historical import (
    AlpacaFetchError,
    AlpacaHistoricalConnector,
    _bar_size_to_timeframe,
    _placeholder_asset,
)
from services.s01_data_ingestion.normalizers.alpaca_bar import AlpacaBarNormalizer
from services.s01_data_ingestion.normalizers.alpaca_trade import AlpacaTradeNormalizer

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "alpaca_aapl_1m_2024-01-02.json"

_DUMMY_ASSET = Asset(
    asset_id=uuid.UUID(int=1),
    symbol="AAPL",
    exchange="ALPACA",
    asset_class=AssetClass.EQUITY,
    currency="USD",
)


def _make_alpaca_bar(
    ts: datetime | None = None,
    open_: float = 185.50,
    high: float = 185.75,
    low: float = 185.35,
    close: float = 185.55,
    volume: float = 10000,
    vwap: float | None = 185.53,
    trade_count: int | None = 100,
) -> SimpleNamespace:
    """Create a mock alpaca-py Bar object."""
    return SimpleNamespace(
        timestamp=ts or datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=vwap,
        trade_count=trade_count,
    )


def _make_alpaca_trade(
    ts: datetime | None = None,
    price: float = 185.50,
    size: float = 100,
    trade_id: int = 12345,
) -> SimpleNamespace:
    """Create a mock alpaca-py Trade object."""
    return SimpleNamespace(
        timestamp=ts or datetime(2024, 1, 2, 14, 30, 0, tzinfo=UTC),
        price=price,
        size=size,
        id=trade_id,
        exchange="V",
        conditions=["@"],
    )


class TestAlpacaBarNormalizer:
    """Tests for AlpacaBarNormalizer."""

    def test_normalize_basic(self) -> None:
        normalizer = AlpacaBarNormalizer(BarSize.M1)
        raw = _make_alpaca_bar()
        bar = normalizer.normalize(raw, _DUMMY_ASSET)
        assert isinstance(bar, Bar)
        assert bar.bar_type == BarType.TIME
        assert bar.bar_size == BarSize.M1
        assert bar.open == Decimal("185.5")
        assert bar.high == Decimal("185.75")
        assert bar.low == Decimal("185.35")
        assert bar.close == Decimal("185.55")
        assert bar.volume == Decimal("10000")
        assert bar.vwap == Decimal("185.53")
        assert bar.trade_count == 100
        assert bar.asset_id == _DUMMY_ASSET.asset_id

    def test_normalize_no_vwap(self) -> None:
        normalizer = AlpacaBarNormalizer()
        raw = _make_alpaca_bar(vwap=None)
        bar = normalizer.normalize(raw, _DUMMY_ASSET)
        assert bar.vwap is None

    def test_normalize_no_trade_count(self) -> None:
        normalizer = AlpacaBarNormalizer()
        raw = _make_alpaca_bar(trade_count=None)
        bar = normalizer.normalize(raw, _DUMMY_ASSET)
        assert bar.trade_count is None

    def test_normalize_naive_timestamp(self) -> None:
        normalizer = AlpacaBarNormalizer()
        raw = _make_alpaca_bar(ts=datetime(2024, 1, 2, 14, 30))
        bar = normalizer.normalize(raw, _DUMMY_ASSET)
        assert bar.timestamp.tzinfo is not None

    def test_normalize_batch(self) -> None:
        normalizer = AlpacaBarNormalizer()
        raws = [_make_alpaca_bar() for _ in range(5)]
        bars = normalizer.normalize_batch(raws, _DUMMY_ASSET)
        assert len(bars) == 5
        assert all(isinstance(b, Bar) for b in bars)

    @pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="fixture not available")
    def test_fixture_parsing(self) -> None:
        with open(FIXTURE_PATH) as f:
            data = json.load(f)
        normalizer = AlpacaBarNormalizer(BarSize.M1)
        bars = []
        for item in data:
            raw = SimpleNamespace(
                timestamp=datetime.fromisoformat(item["timestamp"]),
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
                volume=item["volume"],
                vwap=item.get("vwap"),
                trade_count=item.get("trade_count"),
            )
            bars.append(normalizer.normalize(raw, _DUMMY_ASSET))
        assert len(bars) == 10
        assert bars[0].timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


class TestAlpacaTradeNormalizer:
    """Tests for AlpacaTradeNormalizer."""

    def test_normalize_basic(self) -> None:
        normalizer = AlpacaTradeNormalizer()
        raw = _make_alpaca_trade()
        tick = normalizer.normalize(raw, _DUMMY_ASSET)
        assert isinstance(tick, DbTick)
        assert tick.price == Decimal("185.5")
        assert tick.quantity == Decimal("100")
        assert tick.trade_id == "12345"
        assert tick.side == "unknown"
        assert tick.asset_id == _DUMMY_ASSET.asset_id

    def test_normalize_naive_timestamp(self) -> None:
        normalizer = AlpacaTradeNormalizer()
        raw = _make_alpaca_trade(ts=datetime(2024, 1, 2, 14, 30))
        tick = normalizer.normalize(raw, _DUMMY_ASSET)
        assert tick.timestamp.tzinfo is not None


class TestAlpacaHistoricalConnector:
    """Tests for AlpacaHistoricalConnector."""

    def test_connector_name(self) -> None:
        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient"
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)
            assert connector.connector_name == "alpaca_historical"

    def test_placeholder_asset(self) -> None:
        asset = _placeholder_asset("AAPL")
        assert asset.symbol == "AAPL"
        assert asset.exchange == "ALPACA"
        assert asset.asset_class == AssetClass.EQUITY
        assert asset.asset_id == uuid.UUID(int=0)

    def test_bar_size_to_timeframe_m1(self) -> None:
        from alpaca.data.timeframe import TimeFrameUnit

        tf = _bar_size_to_timeframe(BarSize.M1)
        assert tf.unit == TimeFrameUnit.Minute
        assert tf.amount == 1

    def test_bar_size_to_timeframe_d1(self) -> None:
        from alpaca.data.timeframe import TimeFrameUnit

        tf = _bar_size_to_timeframe(BarSize.D1)
        assert tf.unit == TimeFrameUnit.Day
        assert tf.amount == 1

    @pytest.mark.asyncio
    async def test_fetch_bars_yields_batches(self) -> None:
        mock_bar = _make_alpaca_bar()
        mock_response = MagicMock()
        mock_response.data = {"AAPL": [mock_bar]}
        mock_response.next_page_token = None

        mock_client = MagicMock()
        mock_client.get_stock_bars = MagicMock(return_value=mock_response)

        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient",
            return_value=mock_client,
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        batches = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            batches.append(batch)

        assert len(batches) == 1
        assert isinstance(batches[0][0], Bar)

    @pytest.mark.asyncio
    async def test_fetch_bars_empty_response(self) -> None:
        mock_response = MagicMock()
        mock_response.data = {"AAPL": []}
        mock_response.next_page_token = None

        mock_client = MagicMock()
        mock_client.get_stock_bars = MagicMock(return_value=mock_response)

        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient",
            return_value=mock_client,
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        batches = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            batches.append(batch)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_fetch_bars_api_error_raises(self) -> None:
        mock_client = MagicMock()
        mock_client.get_stock_bars = MagicMock(side_effect=RuntimeError("API down"))

        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient",
            return_value=mock_client,
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        with pytest.raises(AlpacaFetchError, match="API down"):
            async for _ in connector.fetch_bars("AAPL", BarSize.M1, start, end):
                pass

    @pytest.mark.asyncio
    async def test_fetch_ticks_yields_ticks(self) -> None:
        mock_trade = _make_alpaca_trade()
        mock_response = MagicMock()
        mock_response.data = {"AAPL": [mock_trade]}
        mock_response.next_page_token = None

        mock_client = MagicMock()
        mock_client.get_stock_trades = MagicMock(return_value=mock_response)

        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient",
            return_value=mock_client,
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        batches = []
        async for batch in connector.fetch_ticks("AAPL", start, end):
            batches.append(batch)

        assert len(batches) == 1
        assert isinstance(batches[0][0], DbTick)

    @pytest.mark.asyncio
    async def test_fetch_bars_pagination(self) -> None:
        mock_bar1 = _make_alpaca_bar(ts=datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
        mock_bar2 = _make_alpaca_bar(ts=datetime(2024, 1, 2, 14, 31, tzinfo=UTC))

        resp_page1 = MagicMock()
        resp_page1.data = {"AAPL": [mock_bar1]}
        resp_page1.next_page_token = "page2token"

        resp_page2 = MagicMock()
        resp_page2.data = {"AAPL": [mock_bar2]}
        resp_page2.next_page_token = None

        mock_client = MagicMock()
        mock_client.get_stock_bars = MagicMock(side_effect=[resp_page1, resp_page2])

        with patch(
            "services.s01_data_ingestion.connectors.alpaca_historical.StockHistoricalDataClient",
            return_value=mock_client,
        ):
            from core.config import Settings

            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            connector = AlpacaHistoricalConnector(settings)

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        all_bars = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            all_bars.extend(batch)

        assert len(all_bars) == 2
