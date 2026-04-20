"""Unit tests for S04 HedgeTrigger.

Tests: GEX pinning, CB event, RSI divergence, Bollinger Band extreme,
and no-hedge baseline.
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
from core.models.signal import Direction, Signal, SignalType, TechnicalFeatures
from services.s04_fusion_engine.hedge_trigger import HedgeTrigger


def _macro(event_active: bool = False) -> MacroContext:
    return MacroContext(timestamp_ms=1_000_000, macro_mult=1.0, event_active=event_active)


def _session() -> SessionContext:
    return SessionContext(timestamp_ms=1_000_000)


def _regime(event_active: bool = False) -> Regime:
    return Regime(
        timestamp_ms=1_000_000,
        trend_regime=TrendRegime.TRENDING_UP,
        vol_regime=VolRegime.NORMAL,
        risk_mode=RiskMode.NORMAL,
        macro=_macro(event_active=event_active),
        session=_session(),
    )


def _signal(direction: Direction = Direction.LONG, entry: str = "45000") -> Signal:
    entry_d = Decimal(entry)
    if direction == Direction.LONG:
        sl = entry_d - Decimal("1000")
        tp = [entry_d + Decimal("1000"), entry_d + Decimal("2000")]
    else:
        sl = entry_d + Decimal("1000")
        tp = [entry_d - Decimal("1000"), entry_d - Decimal("2000")]
    return Signal(
        signal_id="hedge-test",
        symbol="BTCUSDT",
        timestamp_ms=1_000_000,
        direction=direction,
        strength=0.8,
        signal_type=SignalType.COMPOSITE,
        entry=entry_d,
        stop_loss=sl,
        take_profit=tp,
    )


class TestHedgeTrigger:
    trigger = HedgeTrigger()

    def test_no_hedge_when_no_conditions(self) -> None:
        signal = _signal(Direction.LONG)
        features = TechnicalFeatures(rsi_1m=50.0)
        regime = _regime(event_active=False)
        should, direction, size = self.trigger.should_hedge(
            signal, features, regime, Decimal("1000")
        )
        assert should is False
        assert direction is None
        assert size is None

    def test_gex_pinning_triggers_hedge(self) -> None:
        signal = _signal(Direction.LONG)
        features = TechnicalFeatures(ofi=0.05)  # < 0.1 threshold
        regime = _regime(event_active=False)
        should, direction, size = self.trigger.should_hedge(
            signal, features, regime, Decimal("1000")
        )
        assert should is True
        assert direction == Direction.SHORT
        assert size == Decimal("300")  # 1000 * 0.3

    def test_cb_event_triggers_hedge(self) -> None:
        signal = _signal(Direction.LONG)
        features = TechnicalFeatures()
        regime = _regime(event_active=True)
        should, direction, size = self.trigger.should_hedge(
            signal, features, regime, Decimal("2000")
        )
        assert should is True
        assert direction == Direction.SHORT
        assert size == Decimal("600")  # 2000 * 0.3

    def test_rsi_divergence_long_signal(self) -> None:
        # LONG signal + RSI > 70 → divergence → hedge
        signal = _signal(Direction.LONG)
        features = TechnicalFeatures(rsi_1m=75.0)
        regime = _regime()
        should, direction, _ = self.trigger.should_hedge(signal, features, regime, Decimal("500"))
        assert should is True
        assert direction == Direction.SHORT

    def test_bb_extreme_short_signal(self) -> None:
        # SHORT signal + price <= bb_lower → hedge
        signal = _signal(Direction.SHORT, entry="44000")
        features = TechnicalFeatures(
            bb_upper=Decimal("46000"),
            bb_lower=Decimal("44000"),  # price == bb_lower
        )
        regime = _regime()
        should, direction, _ = self.trigger.should_hedge(signal, features, regime, Decimal("500"))
        assert should is True
        assert direction == Direction.LONG
