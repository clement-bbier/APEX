"""Extended circuit breaker tests covering all trigger conditions.

Tests use CircuitBreaker(Settings()) with default Settings values.
No Redis, no ZMQ, no network. All triggers are verified using the
actual API: check_*() methods + trip() + is_open / is_closed properties.
"""

from __future__ import annotations

from core.config import Settings
from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CircuitState


def _make_cb() -> CircuitBreaker:
    """Return a fresh CircuitBreaker with default Settings."""
    return CircuitBreaker(Settings())


class TestInitialState:
    def test_starts_closed(self) -> None:
        cb = _make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_is_closed_true_initially(self) -> None:
        cb = _make_cb()
        assert cb.is_closed is True

    def test_is_open_false_initially(self) -> None:
        cb = _make_cb()
        assert cb.is_open is False

    def test_trip_reason_empty_initially(self) -> None:
        cb = _make_cb()
        assert cb.trip_reason == ""


class TestTripAndState:
    def test_trip_sets_state_to_open(self) -> None:
        cb = _make_cb()
        cb.trip("test reason")
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    def test_trip_records_reason(self) -> None:
        cb = _make_cb()
        cb.trip("daily drawdown breached")
        assert cb.trip_reason == "daily drawdown breached"

    def test_after_trip_is_closed_false(self) -> None:
        cb = _make_cb()
        cb.trip("test")
        assert cb.is_closed is False


class TestDailyDrawdownCheck:
    """check_daily_drawdown: |pnl_pct| > max_daily_drawdown_pct (default 3.0)."""

    def test_returns_true_when_loss_exceeds_threshold(self) -> None:
        cb = _make_cb()
        # Default max_daily_drawdown_pct = 3.0; loss of -3.1% should trip
        assert cb.check_daily_drawdown(-3.1) is True

    def test_returns_false_when_loss_below_threshold(self) -> None:
        cb = _make_cb()
        assert cb.check_daily_drawdown(-2.9) is False

    def test_returns_true_for_exact_positive_gain_exceeding_threshold(self) -> None:
        cb = _make_cb()
        # Uses abs() so a gain of +3.1% also triggers (unlikely but tested)
        assert cb.check_daily_drawdown(3.1) is True

    def test_trip_after_check(self) -> None:
        cb = _make_cb()
        if cb.check_daily_drawdown(-3.5):
            cb.trip("daily drawdown")
        assert cb.is_open


class TestVIXSpikeCheck:
    """check_vix_spike: (vix_now - vix_ago) / vix_ago > cb_vix_spike_pct / 100.
    Default cb_vix_spike_pct = 20.0 (i.e., relative 20% spike).
    """

    def test_returns_true_for_spike_above_threshold(self) -> None:
        cb = _make_cb()
        # 20 → 24.2 = 21% spike > 20%
        assert cb.check_vix_spike(vix_now=24.2, vix_1h_ago=20.0) is True

    def test_returns_false_for_spike_below_threshold(self) -> None:
        cb = _make_cb()
        # 20 → 23.9 = 19.5% spike < 20%
        assert cb.check_vix_spike(vix_now=23.9, vix_1h_ago=20.0) is False

    def test_returns_false_for_zero_vix_ago(self) -> None:
        cb = _make_cb()
        assert cb.check_vix_spike(vix_now=30.0, vix_1h_ago=0.0) is False

    def test_returns_false_for_vix_drop(self) -> None:
        cb = _make_cb()
        assert cb.check_vix_spike(vix_now=18.0, vix_1h_ago=20.0) is False


class TestPriceGapCheck:
    """check_price_gap: |change%| > cb_price_gap_pct (default 5.0)."""

    def test_returns_true_for_gap_above_threshold(self) -> None:
        cb = _make_cb()
        # 100 → 106 = 6% gap > 5%
        assert cb.check_price_gap(prev_price=100.0, curr_price=106.0) is True

    def test_returns_false_for_gap_below_threshold(self) -> None:
        cb = _make_cb()
        # 100 → 104 = 4% gap < 5%
        assert cb.check_price_gap(prev_price=100.0, curr_price=104.0) is False

    def test_returns_true_for_downward_gap(self) -> None:
        cb = _make_cb()
        # 100 → 94 = 6% drop > 5%
        assert cb.check_price_gap(prev_price=100.0, curr_price=94.0) is True

    def test_returns_false_for_zero_prev_price(self) -> None:
        cb = _make_cb()
        assert cb.check_price_gap(prev_price=0.0, curr_price=106.0) is False


class TestRollingLossCheck:
    """check_rolling_loss: sum(recent_losses_pct) > 2.0."""

    def test_returns_true_when_sum_exceeds_threshold(self) -> None:
        cb = _make_cb()
        # 1.5 + 0.6 = 2.1 > 2.0
        assert cb.check_rolling_loss([1.5, 0.6]) is True

    def test_returns_false_when_sum_below_threshold(self) -> None:
        cb = _make_cb()
        # 0.9 + 0.9 = 1.8 < 2.0
        assert cb.check_rolling_loss([0.9, 0.9]) is False

    def test_returns_false_for_empty_list(self) -> None:
        cb = _make_cb()
        assert cb.check_rolling_loss([]) is False

    def test_returns_true_for_single_large_loss(self) -> None:
        cb = _make_cb()
        assert cb.check_rolling_loss([2.5]) is True


class TestAttemptReset:
    def test_state_remains_open_immediately_after_trip(self) -> None:
        cb = _make_cb()
        cb.trip("test")
        result = cb.attempt_reset()
        # 15-min cooldown not yet elapsed → should not transition
        assert result is False
        assert cb.is_open

    def test_half_open_to_closed_after_successful_trade(self) -> None:
        """HALF_OPEN → CLOSED after record_trade_result(True)."""
        from services.s05_risk_manager.circuit_breaker import CircuitState

        cb = _make_cb()
        cb.trip("test")
        # Force HALF_OPEN by direct state manipulation for testability
        object.__setattr__(cb, "_state", CircuitState.HALF_OPEN)
        cb.record_trade_result(True)
        cb.attempt_reset()
        assert cb.is_closed
