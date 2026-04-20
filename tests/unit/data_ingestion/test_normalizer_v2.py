"""Unit tests for Normalizer v2 — Strategy pattern normalizers.

Tests: NormalizerRouter, BinanceTickNormalizer, AlpacaTickNormalizer,
BinanceBarNormalizer, stub normalizers, and backward compatibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType
from core.models.tick import Market, NormalizedTick, Session, TradeSide
from services.s01_data_ingestion.normalizers.alpaca_tick import AlpacaTickNormalizer
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy
from services.s01_data_ingestion.normalizers.binance_bar import BinanceBarNormalizer
from services.s01_data_ingestion.normalizers.binance_tick import BinanceTickNormalizer
from services.s01_data_ingestion.normalizers.calendar_event import (
    CalendarEventNormalizer,
)
from services.s01_data_ingestion.normalizers.fred_macro import FREDMacroNormalizer
from services.s01_data_ingestion.normalizers.ibkr_bar import IBKRBarNormalizer
from services.s01_data_ingestion.normalizers.polygon_bar import PolygonBarNormalizer
from services.s01_data_ingestion.normalizers.router import NormalizerRouter


def _make_asset(
    symbol: str = "BTCUSDT",
    exchange: str = "BINANCE",
    asset_class: AssetClass = AssetClass.CRYPTO,
) -> Asset:
    """Create a test Asset instance."""
    return Asset(
        asset_id=uuid.uuid4(),
        symbol=symbol,
        exchange=exchange,
        asset_class=asset_class,
        currency="USD",
    )


# ── NormalizerRouter ─────────────────────────────────────────────────────────


class TestNormalizerRouter:
    """Tests for NormalizerRouter."""

    def test_register_and_get(self) -> None:
        router = NormalizerRouter()
        normalizer = BinanceTickNormalizer()
        router.register("binance", "tick", normalizer)
        assert router.get("binance", "tick") is normalizer

    def test_get_unregistered_raises(self) -> None:
        router = NormalizerRouter()
        with pytest.raises(KeyError, match="No normalizer registered"):
            router.get("unknown", "tick")

    def test_normalize_dispatches(self) -> None:
        router = NormalizerRouter()
        mock_normalizer = MagicMock(spec=NormalizerStrategy)
        mock_normalizer.normalize.return_value = "result"
        router.register("test", "data", mock_normalizer)
        asset = _make_asset()
        result = router.normalize("test", "data", {"key": "val"}, asset)
        assert result == "result"
        mock_normalizer.normalize.assert_called_once_with({"key": "val"}, asset)

    def test_normalize_batch_dispatches(self) -> None:
        router = NormalizerRouter()
        mock_normalizer = MagicMock(spec=NormalizerStrategy)
        mock_normalizer.normalize_batch.return_value = ["r1", "r2"]
        router.register("test", "data", mock_normalizer)
        asset = _make_asset()
        result = router.normalize_batch("test", "data", [{"a": 1}, {"b": 2}], asset)
        assert result == ["r1", "r2"]
        mock_normalizer.normalize_batch.assert_called_once()


# ── BinanceTickNormalizer ────────────────────────────────────────────────────


class TestBinanceTickNormalizer:
    """Tests for BinanceTickNormalizer."""

    normalizer = BinanceTickNormalizer()
    asset = _make_asset()

    def _base_payload(self) -> dict[str, object]:
        return {
            "s": "BTCUSDT",
            "T": 1704725100000,  # 2024-01-08 14:45:00 UTC
            "p": "45000.50",
            "q": "0.01",
            "m": False,
        }

    def test_normalize_returns_normalized_tick(self) -> None:
        tick = self.normalizer.normalize(self._base_payload(), self.asset)
        assert isinstance(tick, NormalizedTick)
        assert tick.symbol == "BTCUSDT"
        assert tick.market == Market.CRYPTO
        assert tick.price == Decimal("45000.50")
        assert tick.volume == Decimal("0.01")
        assert tick.side == TradeSide.BUY

    def test_sell_side(self) -> None:
        payload = {**self._base_payload(), "m": True}
        tick = self.normalizer.normalize(payload, self.asset)
        assert tick.side == TradeSide.SELL

    def test_timestamp_ms(self) -> None:
        tick = self.normalizer.normalize(self._base_payload(), self.asset)
        assert tick.timestamp_ms == 1704725100000

    def test_session_tagged(self) -> None:
        tick = self.normalizer.normalize(self._base_payload(), self.asset)
        assert tick.session == Session.US_PRIME

    def test_bid_ask(self) -> None:
        payload: dict[str, Any] = {
            **self._base_payload(),
            "b": "44999.0",
            "a": "45001.0",
        }
        tick = self.normalizer.normalize(payload, self.asset)
        assert tick.bid == Decimal("44999.0")
        assert tick.ask == Decimal("45001.0")


# ── AlpacaTickNormalizer ─────────────────────────────────────────────────────


class TestAlpacaTickNormalizer:
    """Tests for AlpacaTickNormalizer."""

    normalizer = AlpacaTickNormalizer()
    asset = _make_asset(symbol="AAPL", exchange="NYSE", asset_class=AssetClass.EQUITY)

    def _base_payload(self) -> dict[str, object]:
        return {
            "S": "AAPL",
            "t": "2024-01-08T14:30:00.000000000Z",
            "p": 185.5,
            "s": 100,
        }

    def test_normalize_returns_normalized_tick(self) -> None:
        tick = self.normalizer.normalize(self._base_payload(), self.asset)
        assert isinstance(tick, NormalizedTick)
        assert tick.symbol == "AAPL"
        assert tick.market == Market.EQUITY
        assert tick.price == Decimal("185.5")
        assert tick.volume == Decimal("100")
        assert tick.side == TradeSide.UNKNOWN

    def test_nanosecond_timestamp(self) -> None:
        payload = {**self._base_payload(), "t": "2024-01-08T14:30:00.123456789Z"}
        tick = self.normalizer.normalize(payload, self.asset)
        assert tick.timestamp_ms > 0

    def test_session_tagged(self) -> None:
        tick = self.normalizer.normalize(self._base_payload(), self.asset)
        assert tick.session == Session.US_PRIME


# ── BinanceBarNormalizer ─────────────────────────────────────────────────────


class TestBinanceBarNormalizer:
    """Tests for BinanceBarNormalizer."""

    normalizer = BinanceBarNormalizer()
    asset = _make_asset()

    def _kline(self) -> list[Any]:
        return [
            1609459200000,  # open_time_ms (2021-01-01 00:00:00 UTC)
            "29000.0",  # open
            "29500.0",  # high
            "28800.0",  # low
            "29200.0",  # close
            "1500.5",  # volume
            1609459259999,  # close_time_ms
            "43514500.0",  # quote_volume
            12345,  # num_trades
            "750.2",  # taker_buy_base_vol
            "21757250.0",  # taker_buy_quote_vol
            "0",  # ignore
        ]

    def test_normalize_returns_bar(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert isinstance(bar, Bar)

    def test_ohlcv_prices(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert bar.open == Decimal("29000.0")
        assert bar.high == Decimal("29500.0")
        assert bar.low == Decimal("28800.0")
        assert bar.close == Decimal("29200.0")
        assert bar.volume == Decimal("1500.5")

    def test_trade_count(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert bar.trade_count == 12345

    def test_timestamp_utc_aware(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert bar.timestamp.tzinfo is not None
        assert bar.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_vwap_calculated(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        expected_vwap = Decimal("43514500.0") / Decimal("1500.5")
        assert bar.vwap is not None
        assert bar.vwap == expected_vwap

    def test_vwap_none_when_zero_volume(self) -> None:
        kline = self._kline()
        kline[5] = "0"  # zero volume
        kline[7] = "0"  # zero quote volume
        bar = self.normalizer.normalize(kline, self.asset)
        assert bar.vwap is None

    def test_bar_type_and_size(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert bar.bar_type == BarType.TIME
        assert bar.bar_size == BarSize.M1

    def test_custom_bar_size(self) -> None:
        normalizer = BinanceBarNormalizer(bar_size=BarSize.H1)
        bar = normalizer.normalize(self._kline(), self.asset)
        assert bar.bar_size == BarSize.H1

    def test_asset_id_assigned(self) -> None:
        bar = self.normalizer.normalize(self._kline(), self.asset)
        assert bar.asset_id == self.asset.asset_id


# ── Stubs ────────────────────────────────────────────────────────────────────


class TestStubs:
    """Verify all stub normalizers raise NotImplementedError."""

    asset = _make_asset()

    def test_polygon_bar_raises(self) -> None:
        with pytest.raises(NotImplementedError, match=r"Phase 2\.5"):
            PolygonBarNormalizer().normalize({}, self.asset)

    def test_ibkr_bar_raises(self) -> None:
        with pytest.raises(NotImplementedError, match=r"Phase 2\.6"):
            IBKRBarNormalizer().normalize({}, self.asset)

    def test_fred_macro_raises(self) -> None:
        with pytest.raises(NotImplementedError, match=r"Phase 2\.7"):
            FREDMacroNormalizer().normalize({}, self.asset)

    def test_calendar_event_raises(self) -> None:
        with pytest.raises(NotImplementedError, match=r"Phase 2\.8"):
            CalendarEventNormalizer().normalize({}, self.asset)


# ── Backward Compatibility ───────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Verify legacy imports from normalizer.py still work."""

    def test_import_binance_normalizer(self) -> None:
        from services.s01_data_ingestion.normalizer import BinanceNormalizer

        norm = BinanceNormalizer()
        payload: dict[str, Any] = {
            "s": "BTCUSDT",
            "T": 1704725100000,
            "p": "45000.50",
            "q": "0.01",
            "m": False,
        }
        tick = norm.normalize(payload)
        assert isinstance(tick, NormalizedTick)
        assert tick.symbol == "BTCUSDT"
        assert tick.price == Decimal("45000.50")

    def test_import_alpaca_normalizer(self) -> None:
        from services.s01_data_ingestion.normalizer import AlpacaNormalizer

        norm = AlpacaNormalizer()
        payload: dict[str, Any] = {
            "S": "AAPL",
            "t": "2024-01-08T14:30:00.000000000Z",
            "p": 185.5,
            "s": 100,
        }
        tick = norm.normalize(payload)
        assert isinstance(tick, NormalizedTick)
        assert tick.symbol == "AAPL"

    def test_import_normalizer_factory(self) -> None:
        from services.s01_data_ingestion.normalizer import NormalizerFactory

        norm = NormalizerFactory.create(Market.CRYPTO)
        assert isinstance(norm, object)

    def test_import_session_tagger(self) -> None:
        from services.s01_data_ingestion.normalizer import SessionTagger

        tagger = SessionTagger()
        ts = datetime(2024, 1, 8, 14, 30, tzinfo=UTC)
        assert tagger.tag(ts) == Session.US_PRIME
