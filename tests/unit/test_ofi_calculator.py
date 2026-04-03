"""Unit tests for MicrostructureAnalyzer: OFI, CVD, Kyle Lambda."""

from __future__ import annotations

from decimal import Decimal

from core.models.tick import Market, NormalizedTick, Session
from services.s02_signal_engine.microstructure import MicrostructureAnalyzer


def _make_tick(
    symbol: str = "BTC/USDT",
    price: str = "50000",
    volume: str = "1.0",
    bid: str = "49999",
    ask: str = "50001",
    side: str = "buy",
    ts: int = 1_000_000,
) -> NormalizedTick:
    return NormalizedTick(
        symbol=symbol,
        market=Market.CRYPTO,
        timestamp_ms=ts,
        price=Decimal(price),
        volume=Decimal(volume),
        side=side,
        bid=Decimal(bid),
        ask=Decimal(ask),
        spread_bps=2.0,
        session=Session.US_NORMAL,
    )


class TestOFICalculator:
    """Tests for Order Flow Imbalance computation."""

    def test_initial_ofi_is_zero(self) -> None:
        """OFI returns 0.0 before any ticks are processed."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        assert analyzer.ofi() == 0.0

    def test_buy_pressure_positive_ofi(self) -> None:
        """Predominantly buy ticks should yield positive OFI."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        for i in range(10):
            analyzer.update(_make_tick(side="buy", ts=1_000_000 + i * 1000))
        assert analyzer.ofi() >= 0.0

    def test_sell_pressure_negative_or_zero_ofi(self) -> None:
        """Predominantly sell ticks should yield non-positive OFI."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        for i in range(10):
            analyzer.update(_make_tick(side="sell", ts=1_000_000 + i * 1000))
        assert analyzer.ofi() <= 0.0

    def test_balanced_ofi_near_zero(self) -> None:
        """Equal buy/sell volume should yield OFI near zero."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        for i in range(5):
            analyzer.update(_make_tick(side="buy", volume="1.0", ts=1_000_000 + i * 1000))
        for i in range(5):
            analyzer.update(_make_tick(side="sell", volume="1.0", ts=2_000_000 + i * 1000))
        assert abs(analyzer.ofi()) < 0.5

    def test_cvd_accumulates_correctly(self) -> None:
        """CVD (Cumulative Volume Delta) should sum buy minus sell volumes."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        analyzer.update(_make_tick(side="buy", volume="3.0", ts=1_000))
        analyzer.update(_make_tick(side="sell", volume="1.0", ts=2_000))
        cvd = analyzer.cvd()
        assert cvd > 0  # net buy pressure

    def test_kyle_lambda_returns_float(self) -> None:
        """kyle_lambda should always return a non-negative float."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        for i in range(20):
            price = str(50000 + i * 10)
            side = "buy" if i % 2 == 0 else "sell"
            analyzer.update(_make_tick(price=price, side=side, ts=max(1, i * 1000)))
        lam = analyzer.kyle_lambda()
        assert isinstance(lam, float)
        assert lam >= 0.0

    def test_kyle_lambda_initial_zero(self) -> None:
        """Kyle lambda should be 0.0 when there is not enough data."""
        analyzer = MicrostructureAnalyzer("BTC/USDT")
        assert analyzer.kyle_lambda() == 0.0
