"""Unit tests for S04 FusionEngine.

Tests: compute_confluence_bonus, compute_final_score, select_strategy.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.regime import (
    MacroContext,
    Regime,
    RiskMode,
    SessionContext,
    TrendRegime,
    VolRegime,
)
from core.models.signal import Direction, MTFContext, Signal, SignalType
from services.fusion_engine.fusion import FusionEngine


def _macro(event_active: bool = False) -> MacroContext:
    return MacroContext(timestamp_ms=1_000_000, macro_mult=1.0, event_active=event_active)


def _session(is_us_prime: bool = False) -> SessionContext:
    return SessionContext(timestamp_ms=1_000_000, is_us_prime=is_us_prime)


def _r(
    trend: TrendRegime = TrendRegime.TRENDING_UP,
    vol: VolRegime = VolRegime.NORMAL,
    risk: RiskMode = RiskMode.NORMAL,
    macro_mult: float = 1.0,
    is_us_prime: bool = False,
) -> Regime:
    return Regime(
        timestamp_ms=1_000_000,
        trend_regime=trend,
        vol_regime=vol,
        risk_mode=risk,
        macro=_macro(),
        session=_session(is_us_prime=is_us_prime),
        macro_mult=macro_mult,
    )


def _s(
    strength: float = 0.8,
    direction: Direction = Direction.LONG,
    triggers: list[str] | None = None,
    alignment_score: float = 1.0,
    session_bonus: float = 1.0,
) -> Signal:
    mtf = MTFContext(alignment_score=alignment_score, session_bonus=session_bonus)
    return Signal(
        signal_id="test-001",
        symbol="BTCUSDT",
        timestamp_ms=1_000_000,
        direction=direction,
        strength=strength,
        signal_type=SignalType.COMPOSITE,
        triggers=triggers or [],
        entry=Decimal("45000"),
        stop_loss=Decimal("44000") if direction == Direction.LONG else Decimal("46000"),
        take_profit=[Decimal("46000"), Decimal("47000")]
        if direction == Direction.LONG
        else [Decimal("44000"), Decimal("43000")],
        mtf_context=mtf,
    )


class TestConfluenceBonus:
    engine = FusionEngine()

    def test_zero_triggers(self) -> None:
        assert self.engine.compute_confluence_bonus([]) == 0.0

    def test_one_trigger(self) -> None:
        assert self.engine.compute_confluence_bonus(["rsi"]) == 0.50

    def test_two_triggers(self) -> None:
        assert self.engine.compute_confluence_bonus(["rsi", "ofi"]) == 1.00

    def test_three_plus_triggers(self) -> None:
        assert self.engine.compute_confluence_bonus(["rsi", "ofi", "bb"]) == 1.35


class TestFinalScore:
    engine = FusionEngine()

    def test_basic_score(self) -> None:
        signal = _s(strength=0.8, triggers=["rsi", "ofi"])
        regime = _r(macro_mult=1.0)
        # |0.8| * 1.0 * 1.0 * 1.0 * 1.0 * 1.0 = 0.8
        score = self.engine.compute_final_score(signal, regime)
        assert abs(score - 0.8) < 1e-9

    def test_prime_bonus(self) -> None:
        signal = _s(strength=1.0, triggers=["rsi", "ofi"])
        regime = _r(macro_mult=1.0, is_us_prime=True)
        # |1.0| * 1.0 * 1.0 * 1.0 * 1.0 * 1.10 = 1.10
        score = self.engine.compute_final_score(signal, regime)
        assert abs(score - 1.10) < 1e-9

    def test_score_capped_at_two(self) -> None:
        signal = _s(strength=1.0, triggers=["a", "b", "c"])
        regime = _r(macro_mult=1.0, is_us_prime=True)
        # Uncapped = 1.0 * 1.0 * 1.35 * 1.0 * 1.0 * 1.10 = 1.485 — still under 2.0
        score = self.engine.compute_final_score(signal, regime)
        assert score <= 2.0

    def test_reduced_macro_mult(self) -> None:
        signal = _s(strength=1.0, triggers=["rsi"])
        regime = _r(macro_mult=0.5)
        # |1.0| * 0.5 * 0.5 * 1.0 * 1.0 * 1.0 = 0.25
        score = self.engine.compute_final_score(signal, regime)
        assert abs(score - 0.25) < 1e-9

    def test_no_mtf_context(self) -> None:
        signal = Signal(
            signal_id="no-mtf",
            symbol="AAPL",
            timestamp_ms=1_000_000,
            direction=Direction.LONG,
            strength=0.5,
            entry=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=[Decimal("105"), Decimal("110")],
        )
        regime = _r(macro_mult=1.0)
        # |0.5| * 1.0 * 0.0 (no triggers) * 1.0 * 0.7 (default align) * 1.0 = 0.0
        score = self.engine.compute_final_score(signal, regime)
        assert score == 0.0


class TestSelectStrategy:
    engine = FusionEngine()

    def test_trending_up_returns_momentum(self) -> None:
        regime = _r(trend=TrendRegime.TRENDING_UP)
        assert self.engine.select_strategy(regime) == "momentum_scalp"

    def test_trending_down_returns_momentum(self) -> None:
        regime = _r(trend=TrendRegime.TRENDING_DOWN)
        assert self.engine.select_strategy(regime) == "momentum_scalp"

    def test_ranging_returns_mean_reversion(self) -> None:
        regime = _r(trend=TrendRegime.RANGING)
        assert self.engine.select_strategy(regime) == "mean_reversion"

    def test_crisis_returns_blocked(self) -> None:
        regime = _r(risk=RiskMode.CRISIS)
        assert self.engine.select_strategy(regime) == "blocked"
