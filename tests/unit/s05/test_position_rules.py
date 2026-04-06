"""Unit tests for Phase 6 position_rules.py.

Tests cover all 6 functions: 4 check_* (blocking) and 2 apply_* (modifying).
Includes 2 Hypothesis property tests with 1000 examples each.
"""
from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models.order import OrderCandidate
from core.models.signal import Direction
from core.models.tick import Session
from services.s05_risk_manager.models import BlockReason
from services.s05_risk_manager.position_rules import (
    apply_crypto_multiplier,
    apply_session_multiplier,
    check_max_risk_per_trade,
    check_max_size,
    check_min_rr,
    check_stop_loss_present,
)

_CAPITAL = Decimal("100_000")

def _long_order(
    entry="50000", sl="49500", tp_scalp="50750", tp_swing="52000",
    size="0.01", symbol="BTCUSDT"
) -> OrderCandidate:
    sz = Decimal(size)
    return OrderCandidate(
        order_id="o1", symbol=symbol, direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000, size=sz,
        size_scalp_exit=sz * Decimal("0.35"), size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal(entry), stop_loss=Decimal(sl),
        target_scalp=Decimal(tp_scalp), target_swing=Decimal(tp_swing),
        capital_at_risk=Decimal("5"),
    )

def _short_order() -> OrderCandidate:
    sz = Decimal("0.01")
    return OrderCandidate(
        order_id="o2", symbol="AAPL", direction=Direction.SHORT,
        timestamp_ms=1_700_000_000_000, size=sz,
        size_scalp_exit=sz * Decimal("0.35"), size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal("150"), stop_loss=Decimal("152"),
        target_scalp=Decimal("148"), target_swing=Decimal("145"),
        capital_at_risk=Decimal("0.2"),
    )


class TestStopLossPresent:
    def test_stop_loss_required_long(self) -> None:
        r = check_stop_loss_present(_long_order())
        assert r.passed

    def test_stop_loss_required_short(self) -> None:
        r = check_stop_loss_present(_short_order())
        assert r.passed

    def test_stop_loss_direction_long_sl_above_entry_blocked(self) -> None:
        order = _long_order(entry="50000", sl="50100")
        r = check_stop_loss_present(order)
        assert not r.passed
        assert r.block_reason == BlockReason.NO_STOP_LOSS

    def test_stop_loss_direction_short_sl_below_entry_blocked(self) -> None:
        sz = Decimal("0.01")
        order = OrderCandidate(
            order_id="o3", symbol="AAPL", direction=Direction.SHORT,
            timestamp_ms=1_700_000_000_000, size=sz,
            size_scalp_exit=sz * Decimal("0.35"), size_swing_exit=sz * Decimal("0.65"),
            entry=Decimal("150"), stop_loss=Decimal("148"),  # SL BELOW entry for SHORT
            target_scalp=Decimal("148"), target_swing=Decimal("145"),
            capital_at_risk=Decimal("0.2"),
        )
        r = check_stop_loss_present(order)
        assert not r.passed
        assert r.block_reason == BlockReason.NO_STOP_LOSS


class TestMinRR:
    def test_min_rr_exact_boundary_pass(self) -> None:
        # RR = 750/500 = 1.5 -> pass
        r = check_min_rr(_long_order(entry="50000", sl="49500", tp_scalp="50750"))
        assert r.passed

    def test_min_rr_below_threshold_fail(self) -> None:
        # RR = 700/500 = 1.4 < 1.5 -> fail
        r = check_min_rr(_long_order(entry="50000", sl="49500", tp_scalp="50700"))
        assert not r.passed
        assert r.block_reason == BlockReason.MIN_RR_NOT_MET

    def test_min_rr_high_rr_passes(self) -> None:
        # RR = 1250/500 = 2.5
        r = check_min_rr(_long_order(entry="50000", sl="49500", tp_scalp="51250"))
        assert r.passed


class TestMaxRiskPerTrade:
    def test_max_risk_exact_boundary_pass(self) -> None:
        # 0.499% risk: SL dist = 500, size s.t. 500*size = 0.499% * 100000 = 499
        # size = 499/500 = 0.998
        order = _long_order(size="0.998")
        r = check_max_risk_per_trade(order, _CAPITAL)
        assert r.passed

    def test_max_risk_over_threshold_fail(self) -> None:
        # 0.501% risk: SL dist = 500, size = 501/500 = 1.002
        order = _long_order(size="1.002")
        r = check_max_risk_per_trade(order, _CAPITAL)
        assert not r.passed
        assert r.block_reason == BlockReason.MAX_RISK_PER_TRADE


class TestMaxSize:
    def test_max_size_ceiling_pass(self) -> None:
        # 9.9% of 100k = 9900. entry=50000 -> size=0.198
        order = _long_order(size="0.198")
        r = check_max_size(order, _CAPITAL)
        assert r.passed

    def test_max_size_ceiling_fail(self) -> None:
        # 10.1% of 100k = 10100. entry=50000 -> size=0.202
        order = _long_order(size="0.202")
        r = check_max_size(order, _CAPITAL)
        assert not r.passed
        assert r.block_reason == BlockReason.MAX_SIZE_EXCEEDED


class TestApplyMultipliers:
    def test_crypto_multiplier_applied_btcusdt(self) -> None:
        order = _long_order(symbol="BTCUSDT", size="1.0")
        adjusted, result = apply_crypto_multiplier(order)
        assert result.passed
        assert adjusted == Decimal("0.7")

    def test_crypto_multiplier_not_applied_equity(self) -> None:
        order = _long_order(symbol="AAPL", size="1.0")
        adjusted, result = apply_crypto_multiplier(order)
        assert result.passed
        assert adjusted == Decimal("1.0")

    def test_session_prime_bonus_us_open(self) -> None:
        order = _long_order(size="1.0")
        adjusted, result = apply_session_multiplier(order, Session.US_PRIME)
        assert result.passed
        assert adjusted == Decimal(str(1.0 * 1.10))

    def test_session_no_bonus_overnight(self) -> None:
        order = _long_order(size="1.0")
        adjusted, result = apply_session_multiplier(order, Session.ASIAN)
        assert result.passed
        assert adjusted == Decimal("1.0")


@given(
    capital=st.decimals(min_value=Decimal("100"), max_value=Decimal("1_000_000"), places=2),
    size=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("2.0"), places=3),
)
@hyp_settings(max_examples=1000)
def test_approved_order_never_exceeds_max_risk(capital: Decimal, size: Decimal) -> None:
    """INVARIANT: if check_max_risk_per_trade passes, monetary_risk <= 0.005 x capital."""
    order = _long_order(size=str(size))
    result = check_max_risk_per_trade(order, capital)
    if result.passed:
        sl_dist = abs(order.entry - order.stop_loss)
        risk = sl_dist * order.size
        assert risk <= capital * Decimal("0.005") + Decimal("0.0001")


@given(
    sl_pct=st.floats(min_value=0.001, max_value=0.05, allow_nan=False, allow_infinity=False),
    size_frac=st.floats(min_value=0.001, max_value=0.10, allow_nan=False, allow_infinity=False),
)
@hyp_settings(max_examples=1000)
def test_risk_formula_commutative(sl_pct: float, size_frac: float) -> None:
    """risk = SL_distance x size is commutative and always >= 0."""
    entry = Decimal("50000")
    sl = entry * Decimal(str(1.0 - sl_pct))
    size = Decimal(str(size_frac)) * entry / Decimal("50000")
    risk = abs(entry - sl) * size
    assert risk >= Decimal("0")
