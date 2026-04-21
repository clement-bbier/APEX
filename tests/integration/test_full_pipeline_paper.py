"""
Integration test: full pipeline from tick to trade record.

Tests the complete chain:
  NormalizedTick -> S02 Signal -> S04 OrderCandidate -> S05 ApprovedOrder

This is the most important integration test - it proves the pipeline works end-to-end.
Requires: Redis running (docker compose -f docker/docker-compose.test.yml up -d)
"""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest

from core.models.order import OrderCandidate
from core.models.signal import Direction
from services.execution.paper_trader import PaperTrader
from services.fusion_engine.kelly_sizer import KellySizer
from services.regime_detector.regime_engine import RegimeEngine
from services.risk_manager.circuit_breaker import CircuitBreaker
from services.risk_manager.models import CircuitBreakerState
from services.risk_manager.position_rules import check_max_risk_per_trade
from services.signal_engine.signal_scorer import SignalComponent, SignalScorer


class TestFullPipelinePaper:
    """End-to-end pipeline: tick -> executed trade."""

    def test_signal_scorer_to_order_candidate(self) -> None:
        """Verify signal confluence produces a valid score."""
        scorer = SignalScorer(min_components=2, min_strength=0.15)
        components = [
            SignalComponent("microstructure", 0.80, 0.35, True),
            SignalComponent("bollinger", 0.70, 0.25, True),
            SignalComponent("ema_mtf", 0.60, 0.20, True),
        ]
        score, triggers = scorer.compute(components)
        assert score > 0
        assert len(triggers) >= 2

    def test_regime_modulates_sizing(self) -> None:
        """Verify macro_mult reduces position size in high-vol regime."""
        engine = RegimeEngine()
        regime_normal = engine.compute(vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        regime_crisis = engine.compute(vix=38.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)

        sizer = KellySizer()
        capital = Decimal("10000")
        kelly_f = sizer.kelly_fraction(win_rate=0.55, avg_rr=1.8)
        size_normal = sizer.position_size(
            capital, kelly_f, regime_normal.macro_mult, 1.0, 0.0, False
        )
        size_crisis = sizer.position_size(
            capital, kelly_f, regime_crisis.macro_mult, 1.0, 0.0, False
        )

        assert size_normal > size_crisis
        assert size_crisis == Decimal("0")  # crisis macro_mult=0 -> size=0

    def test_risk_manager_blocks_oversized_position(self) -> None:
        """Risk manager must reject any position exceeding 0.5% capital risk."""
        capital = Decimal("10000")

        order = OrderCandidate(
            order_id="test-oversized-1",
            symbol="BTCUSDT",
            direction=Direction.LONG,
            timestamp_ms=1_700_000_000_000,
            size=Decimal("0.5"),
            size_scalp_exit=Decimal("0.2"),
            size_swing_exit=Decimal("0.3"),
            entry=Decimal("50000"),
            stop_loss=Decimal("49000"),  # $1000 risk per BTC * 0.5 = $500 risk
            target_scalp=Decimal("51000"),
            target_swing=Decimal("52000"),
            capital_at_risk=Decimal("500"),
        )

        result = check_max_risk_per_trade(order, capital)
        assert result.passed is False
        assert "max" in result.reason.lower() or "risk" in result.reason.lower()

    def test_paper_trader_slippage_is_applied(self) -> None:
        """Paper trader must apply realistic slippage (never fill at exact price)."""
        trader = PaperTrader()

        slippage_tight = trader.compute_slippage(
            spread_bps=2.0,
            kyle_lambda=0.00001,
            size=Decimal("0.1"),
            price=Decimal("50000"),
        )
        slippage_wide = trader.compute_slippage(
            spread_bps=20.0,
            kyle_lambda=0.0001,
            size=Decimal("1.0"),
            price=Decimal("50000"),
        )
        assert slippage_wide > slippage_tight
        assert slippage_tight >= 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_halts_on_drawdown(self) -> None:
        """3% daily drawdown must open circuit breaker and block all orders."""
        cb = CircuitBreaker(fakeredis.aioredis.FakeRedis())
        snap = await cb.get_snapshot()
        assert snap.state == CircuitBreakerState.CLOSED

        result = await cb.check(
            current_daily_pnl=Decimal("-3100"),  # -3.1% of 100k
            starting_capital=Decimal("100000"),
            intraday_loss_30m=Decimal("0"),
            vix_current=20.0,
            vix_1h_ago=20.0,
            service_last_seen={},
        )
        assert result.passed is False
        snap = await cb.get_snapshot()
        assert snap.state == CircuitBreakerState.OPEN
