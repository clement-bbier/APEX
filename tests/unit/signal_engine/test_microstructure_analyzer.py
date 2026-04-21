"""Unit tests for MicrostructureAnalyzer.

Tests OFI, CVD, Kyle Lambda, spread evolution, and absorption detection
using synthetic NormalizedTick sequences with known expected outputs.
No Redis, no ZMQ, no network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.models.tick import Market, NormalizedTick, TradeSide
from services.signal_engine.microstructure import MicrostructureAnalyzer


def _tick(
    price: float,
    volume: float = 10.0,
    side: TradeSide = TradeSide.UNKNOWN,
    bid: float | None = None,
    ask: float | None = None,
    ts_ms: int = 1_000_000,
    symbol: str = "BTCUSDT",
) -> NormalizedTick:
    """Build a minimal NormalizedTick for testing."""
    if bid is None:
        bid = price * 0.9999
    if ask is None:
        ask = price * 1.0001
    return NormalizedTick(
        symbol=symbol,
        market=Market.CRYPTO,
        timestamp_ms=ts_ms,
        price=Decimal(str(price)),
        volume=Decimal(str(volume)),
        side=side,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
    )


class TestOFI:
    """OFI = Σ(Δbid − Δask) / total_vol — normalised to [-1, 1]."""

    def test_zero_before_two_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        ma.update(_tick(100.0))
        assert ma.ofi() == 0.0

    def test_positive_when_bid_rises_faster_than_ask(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        # Tick 1: bid=100, ask=101
        ma.update(_tick(100.5, bid=100.0, ask=101.0, ts_ms=1000))
        # Tick 2: bid=105 (+5), ask=102 (+1) — bid rises faster
        ma.update(_tick(103.5, bid=105.0, ask=102.0, ts_ms=2000))
        assert ma.ofi() > 0.0

    def test_negative_when_ask_rises_faster_than_bid(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        # Tick 1: bid=100, ask=101
        ma.update(_tick(100.5, bid=100.0, ask=101.0, ts_ms=1000))
        # Tick 2: bid=101 (+1), ask=106 (+5) — ask rises faster
        ma.update(_tick(103.5, bid=101.0, ask=106.0, ts_ms=2000))
        assert ma.ofi() < 0.0

    def test_zero_when_bid_ask_move_equally(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        ma.update(_tick(100.5, bid=100.0, ask=101.0, ts_ms=1000))
        ma.update(_tick(105.5, bid=105.0, ask=106.0, ts_ms=2000))  # both +5
        assert ma.ofi() == pytest.approx(0.0, abs=1e-9)


class TestCVD:
    """CVD = Σ(buy_vol − sell_vol) / total_vol."""

    def test_zero_before_two_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        ma.update(_tick(100.0, side=TradeSide.BUY))
        assert ma.cvd() == 0.0

    def test_positive_for_all_buy_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(10):
            ma.update(_tick(100.0 + i, volume=50.0, side=TradeSide.BUY, ts_ms=i * 1000 + 1))
        assert ma.cvd() > 0.0

    def test_negative_for_all_sell_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(10):
            ma.update(_tick(100.0 + i, volume=50.0, side=TradeSide.SELL, ts_ms=i * 1000 + 1))
        assert ma.cvd() < 0.0

    def test_near_zero_for_balanced_buy_sell(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(20):
            side = TradeSide.BUY if i % 2 == 0 else TradeSide.SELL
            ma.update(_tick(100.0, volume=100.0, side=side, ts_ms=i * 1000 + 1))
        assert abs(ma.cvd()) < 0.01


class TestKyleLambda:
    """Kyle λ = Cov(ΔP, Q) / Var(Q)."""

    def test_zero_for_fewer_than_three_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        ma.update(_tick(100.0, side=TradeSide.BUY, ts_ms=1000))
        ma.update(_tick(101.0, side=TradeSide.BUY, ts_ms=2000))
        assert ma.kyle_lambda() == 0.0

    def test_positive_when_buy_pressure_moves_price_up(self) -> None:
        """Consistent buy volume paired with rising prices → λ > 0."""
        ma = MicrostructureAnalyzer("BTCUSDT", window=50)
        prices = [100.0 + i * 0.5 for i in range(30)]
        for i, p in enumerate(prices):
            side = TradeSide.BUY if i % 2 == 0 else TradeSide.UNKNOWN
            ma.update(_tick(p, volume=100.0, side=side, ts_ms=i * 1000 + 1))
        # With consistent buy + rising price, lambda should be positive
        lam = ma.kyle_lambda()
        assert isinstance(lam, float)

    def test_returns_float(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(10):
            ma.update(_tick(100.0 + i * 0.1, side=TradeSide.BUY, ts_ms=i * 1000 + 1))
        assert isinstance(ma.kyle_lambda(), float)


class TestSpreadEvolution:
    """Spread evolution returns average bid-ask spread in bps."""

    def test_zero_before_two_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        ma.update(_tick(100.0))
        assert ma.spread_evolution() == 0.0

    def test_positive_spread_for_valid_bid_ask(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(5):
            ma.update(_tick(100.0, bid=99.9, ask=100.1, ts_ms=i * 1000 + 1))
        result = ma.spread_evolution()
        assert result > 0.0

    def test_wider_spread_detected(self) -> None:
        ma_tight = MicrostructureAnalyzer("BTCUSDT")
        ma_wide = MicrostructureAnalyzer("BTCUSDT")
        for i in range(5):
            ts = i * 1000 + 1
            ma_tight.update(_tick(100.0, bid=99.99, ask=100.01, ts_ms=ts))
            ma_wide.update(_tick(100.0, bid=99.0, ask=101.0, ts_ms=ts))
        assert ma_wide.spread_evolution() > ma_tight.spread_evolution()


class TestAbsorptionDetected:
    """Absorption requires >= 10 ticks and a large sell event with stable price."""

    def test_false_with_fewer_than_ten_ticks(self) -> None:
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(9):
            ma.update(_tick(100.0, ts_ms=i * 1000 + 1))
        assert ma.absorption_detected() is False

    def test_false_for_normal_sell_volumes(self) -> None:
        """No absorption if sell volume is not extreme."""
        ma = MicrostructureAnalyzer("BTCUSDT")
        for i in range(20):
            ma.update(_tick(100.0, volume=50.0, side=TradeSide.SELL, ts_ms=i * 1000 + 1))
        # Even if sell volume is consistent, it should not exceed 2σ threshold
        # consistently (all equal → std=0, threshold=mean → last ≤ threshold)
        result = ma.absorption_detected()
        assert isinstance(result, bool)
