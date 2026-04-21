"""Unit tests for S04 StrategySelector.

Tests: is_active, get_size_multiplier.
"""

from __future__ import annotations

from core.models.regime import (
    MacroContext,
    Regime,
    RiskMode,
    SessionContext,
    TrendRegime,
    VolRegime,
)
from services.fusion_engine.strategy import StrategySelector


def _macro() -> MacroContext:
    return MacroContext(timestamp_ms=1_000_000, macro_mult=1.0)


def _session() -> SessionContext:
    return SessionContext(timestamp_ms=1_000_000)


def _r(
    trend: TrendRegime = TrendRegime.TRENDING_UP,
    vol: VolRegime = VolRegime.NORMAL,
    risk: RiskMode = RiskMode.NORMAL,
) -> Regime:
    return Regime(
        timestamp_ms=1_000_000,
        trend_regime=trend,
        vol_regime=vol,
        risk_mode=risk,
        macro=_macro(),
        session=_session(),
    )


class TestIsActive:
    selector = StrategySelector()

    def test_momentum_scalp_active_in_trend(self) -> None:
        regime = _r(trend=TrendRegime.TRENDING_UP, vol=VolRegime.NORMAL)
        assert self.selector.is_active("momentum_scalp", regime) is True

    def test_momentum_scalp_inactive_in_ranging(self) -> None:
        regime = _r(trend=TrendRegime.RANGING, vol=VolRegime.NORMAL)
        assert self.selector.is_active("momentum_scalp", regime) is False

    def test_mean_reversion_active_in_ranging(self) -> None:
        regime = _r(trend=TrendRegime.RANGING, vol=VolRegime.LOW)
        assert self.selector.is_active("mean_reversion", regime) is True

    def test_all_blocked_in_crisis(self) -> None:
        regime = _r(risk=RiskMode.CRISIS)
        for strategy in ("momentum_scalp", "mean_reversion", "spike_scalp", "short_momentum"):
            assert self.selector.is_active(strategy, regime) is False

    def test_unknown_strategy_inactive(self) -> None:
        regime = _r()
        assert self.selector.is_active("nonexistent_strategy", regime) is False


class TestMultiplier:
    selector = StrategySelector()

    def test_momentum_scalp_multiplier(self) -> None:
        regime = _r()
        assert self.selector.get_size_multiplier("momentum_scalp", regime) == 1.0

    def test_mean_reversion_multiplier(self) -> None:
        regime = _r()
        assert self.selector.get_size_multiplier("mean_reversion", regime) == 0.8

    def test_crisis_always_zero(self) -> None:
        regime = _r(risk=RiskMode.CRISIS)
        assert self.selector.get_size_multiplier("momentum_scalp", regime) == 0.0

    def test_unknown_strategy_zero(self) -> None:
        regime = _r()
        assert self.selector.get_size_multiplier("unknown_strat", regime) == 0.0
