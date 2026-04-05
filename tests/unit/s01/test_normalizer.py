"""Unit tests for S01 Data Ingestion normalizers.

Tests: SessionTagger, BinanceNormalizer, AlpacaNormalizer, NormalizerFactory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.models.tick import Market, Session, TradeSide
from services.s01_data_ingestion.normalizer import (
    AlpacaNormalizer,
    BinanceNormalizer,
    NormalizerFactory,
    SessionTagger,
)


def _utc(hour: int, minute: int, weekday: int = 0) -> datetime:
    """Build a UTC datetime on a specific weekday (0=Mon, 5=Sat, 6=Sun)."""
    # Use a reference Monday: 2024-01-08 (Monday).
    base_monday_ordinal = datetime(2024, 1, 8, tzinfo=UTC).toordinal()
    ordinal = base_monday_ordinal + weekday
    d = datetime.fromordinal(ordinal)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


class TestSessionTagger:
    """Tests for SessionTagger.tag()."""

    tagger = SessionTagger()

    def test_weekend_saturday(self) -> None:
        ts = _utc(12, 0, weekday=5)  # Saturday
        assert self.tagger.tag(ts) == Session.WEEKEND

    def test_weekend_sunday(self) -> None:
        ts = _utc(15, 0, weekday=6)  # Sunday
        assert self.tagger.tag(ts) == Session.WEEKEND

    def test_us_prime_open(self) -> None:
        ts = _utc(14, 30, weekday=1)  # Tuesday 14:30 UTC = prime open start
        assert self.tagger.tag(ts) == Session.US_PRIME

    def test_us_prime_close(self) -> None:
        ts = _utc(20, 30, weekday=2)  # Wednesday 20:30 UTC = prime close window
        assert self.tagger.tag(ts) == Session.US_PRIME

    def test_us_normal(self) -> None:
        ts = _utc(16, 0, weekday=1)  # Tuesday 16:00 UTC = normal US session
        assert self.tagger.tag(ts) == Session.US_NORMAL

    def test_london_session(self) -> None:
        ts = _utc(9, 0, weekday=1)  # Tuesday 09:00 UTC = London
        assert self.tagger.tag(ts) == Session.LONDON

    def test_asian_session(self) -> None:
        ts = _utc(1, 0, weekday=1)  # Tuesday 01:00 UTC = Asian
        assert self.tagger.tag(ts) == Session.ASIAN

    def test_after_hours(self) -> None:
        ts = _utc(22, 0, weekday=1)  # Tuesday 22:00 UTC = after hours
        assert self.tagger.tag(ts) == Session.AFTER_HOURS


class TestBinanceNormalizer:
    """Tests for BinanceNormalizer.normalize()."""

    normalizer = BinanceNormalizer()

    def _base_payload(self) -> dict[str, object]:
        return {
            "s": "BTCUSDT",
            "T": 1704725100000,  # 2024-01-08 14:45:00 UTC (US prime open window)
            "p": "45000.50",
            "q": "0.01",
            "m": False,  # buyer is aggressor → BUY
        }

    def test_buy_side(self) -> None:
        payload = self._base_payload()
        tick = self.normalizer.normalize(payload)
        assert tick.side == TradeSide.BUY
        assert tick.symbol == "BTCUSDT"
        assert tick.market == Market.CRYPTO
        assert tick.price == Decimal("45000.50")
        assert tick.volume == Decimal("0.01")

    def test_sell_side(self) -> None:
        payload = {**self._base_payload(), "m": True}
        tick = self.normalizer.normalize(payload)
        assert tick.side == TradeSide.SELL

    def test_bid_ask_populated(self) -> None:
        payload = {**self._base_payload(), "b": "44999.0", "a": "45001.0"}
        tick = self.normalizer.normalize(payload)
        assert tick.bid == Decimal("44999.0")
        assert tick.ask == Decimal("45001.0")

    def test_missing_timestamp_raises(self) -> None:
        payload = {k: v for k, v in self._base_payload().items() if k not in ("T", "t")}
        with pytest.raises(ValueError, match="missing timestamp"):
            self.normalizer.normalize(payload)

    def test_session_tagged(self) -> None:
        # 2024-01-08 14:30:00 UTC = Monday US prime open
        payload = self._base_payload()
        tick = self.normalizer.normalize(payload)
        assert tick.session == Session.US_PRIME


class TestAlpacaNormalizer:
    """Tests for AlpacaNormalizer.normalize()."""

    normalizer = AlpacaNormalizer()

    def _base_payload(self) -> dict[str, object]:
        return {
            "S": "AAPL",
            "t": "2024-01-08T14:30:00.000000000Z",
            "p": 185.5,
            "s": 100,
        }

    def test_basic_normalization(self) -> None:
        tick = self.normalizer.normalize(self._base_payload())
        assert tick.symbol == "AAPL"
        assert tick.market == Market.EQUITY
        assert tick.price == Decimal("185.5")
        assert tick.volume == Decimal("100")
        assert tick.side == TradeSide.UNKNOWN

    def test_nanosecond_timestamp(self) -> None:
        payload = {**self._base_payload(), "t": "2024-01-08T14:30:00.123456789Z"}
        tick = self.normalizer.normalize(payload)
        assert tick.timestamp_ms > 0

    def test_symbol_uppercase(self) -> None:
        payload = {**self._base_payload(), "S": "msft"}
        tick = self.normalizer.normalize(payload)
        assert tick.symbol == "MSFT"

    def test_session_tagged(self) -> None:
        tick = self.normalizer.normalize(self._base_payload())
        assert tick.session == Session.US_PRIME


class TestNormalizerFactory:
    """Tests for NormalizerFactory.create()."""

    def test_crypto_returns_binance(self) -> None:
        norm = NormalizerFactory.create(Market.CRYPTO)
        assert isinstance(norm, BinanceNormalizer)

    def test_equity_returns_alpaca(self) -> None:
        norm = NormalizerFactory.create(Market.EQUITY)
        assert isinstance(norm, AlpacaNormalizer)

    def test_unknown_market_raises(self) -> None:
        with pytest.raises(ValueError, match="No normalizer"):
            NormalizerFactory.create("unknown_market")  # type: ignore[arg-type]
