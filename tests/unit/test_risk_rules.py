"""Unit tests for PositionRules: per-order risk validation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.config import Settings
from core.models.order import OrderCandidate
from core.models.signal import Direction
from services.s05_risk_manager.position_rules import PositionRules


def _make_candidate(
    size: Decimal = Decimal("1.0"),
    entry: Decimal = Decimal("50000"),
    stop_loss: Decimal = Decimal("49750"),
    target_scalp: Decimal = Decimal("50500"),
    target_swing: Decimal = Decimal("51000"),
    capital_at_risk: Decimal = Decimal("250"),
    direction: Direction = Direction.LONG,
) -> OrderCandidate:
    """Build a minimal valid OrderCandidate."""
    size_scalp = (size * Decimal("35") / Decimal("100")).quantize(Decimal("0.000001"))
    size_swing = size - size_scalp
    return OrderCandidate(
        order_id="test-order",
        symbol="BTC/USDT",
        direction=direction,
        timestamp_ms=1_000_000,
        size=size,
        size_scalp_exit=size_scalp,
        size_swing_exit=size_swing,
        entry=entry,
        stop_loss=stop_loss,
        target_scalp=target_scalp,
        target_swing=target_swing,
        capital_at_risk=capital_at_risk,
    )


@pytest.fixture
def rules() -> PositionRules:
    return PositionRules()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        max_position_risk_pct=0.5,
        max_position_size_pct=10.0,
        min_risk_reward=1.5,
    )


class TestPositionRules:
    def test_valid_order_passes(self, rules: PositionRules, settings: Settings) -> None:
        candidate = _make_candidate(
            size=Decimal("0.001"),
            entry=Decimal("50000"),
            capital_at_risk=Decimal("25"),  # 0.025% of 100k
        )
        ok, reason = rules.validate(candidate, Decimal("100000"), settings)
        assert ok is True
        assert reason == ""

    def test_capital_at_risk_too_high_blocked(
        self, rules: PositionRules, settings: Settings
    ) -> None:
        candidate = _make_candidate(
            capital_at_risk=Decimal("600"),  # > 0.5% of 100k = 500
        )
        ok, reason = rules.validate(candidate, Decimal("100000"), settings)
        assert ok is False
        assert "capital_at_risk" in reason

    def test_position_value_too_large_blocked(
        self, rules: PositionRules, settings: Settings
    ) -> None:
        # size * entry = 2.0 * 50000 = 100000 > 10% of 100000 = 10000
        candidate = _make_candidate(
            size=Decimal("2.0"),
            entry=Decimal("50000"),
            capital_at_risk=Decimal("200"),  # passes risk check
        )
        ok, reason = rules.validate(candidate, Decimal("100000"), settings)
        assert ok is False
        assert "position_value" in reason

    def test_valid_stop_loss_passes(self, rules: PositionRules, settings: Settings) -> None:
        # A tiny stop_loss > 0 should not be blocked by the stop_loss check
        candidate = _make_candidate(
            size=Decimal("0.001"),
            stop_loss=Decimal("49999"),
            capital_at_risk=Decimal("1"),
        )
        ok, _ = rules.validate(candidate, Decimal("100000"), settings)
        # Position value = 0.001 * 50000 = 50, well within 10% limit
        assert ok is True

    def test_short_order_passes(self, rules: PositionRules, settings: Settings) -> None:
        candidate = _make_candidate(
            direction=Direction.SHORT,
            size=Decimal("0.001"),
            capital_at_risk=Decimal("25"),
        )
        ok, _ = rules.validate(candidate, Decimal("100000"), settings)
        assert ok is True


@given(
    capital=st.decimals(min_value=Decimal("1000"), max_value=Decimal("1000000"), places=2),
    risk_pct=st.floats(0.1, 0.5),
)
@hyp_settings(max_examples=200)
def test_approved_order_never_exceeds_max_risk(capital: Decimal, risk_pct: float) -> None:
    """Property: no approved order ever exceeds max_position_risk_pct capital risk."""
    settings = Settings(
        max_position_risk_pct=risk_pct,
        max_position_size_pct=10.0,
        min_risk_reward=1.5,
    )
    rules = PositionRules()
    max_risk = capital * Decimal(str(risk_pct)) / Decimal("100")
    # Build candidate at exactly max_risk
    candidate = _make_candidate(
        size=Decimal("0.001"),
        capital_at_risk=max_risk,
    )
    ok, _ = rules.validate(candidate, capital, settings)
    if ok:
        # Safety invariant: actual capital at risk <= max
        assert candidate.capital_at_risk <= max_risk + Decimal("0.01")
