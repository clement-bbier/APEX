"""Unit tests for CircuitBreaker: all state transitions."""

from __future__ import annotations

import time

import pytest

from core.config import Settings
from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def settings() -> Settings:
    """Minimal Settings for circuit breaker tests."""
    return Settings(
        max_daily_drawdown_pct=3.0,
        cb_vix_spike_pct=20.0,
        cb_price_gap_pct=5.0,
    )


@pytest.fixture
def cb(settings: Settings) -> CircuitBreaker:
    """Fresh CircuitBreaker in CLOSED state."""
    return CircuitBreaker(settings)


class TestCircuitBreakerTransitions:
    """Test all state machine transitions."""

    def test_initial_state_is_closed(self, cb: CircuitBreaker) -> None:
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed is True
        assert cb.is_open is False

    def test_trip_opens_breaker(self, cb: CircuitBreaker) -> None:
        cb.trip("daily_drawdown")
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True
        assert cb.trip_reason == "daily_drawdown"

    def test_open_stays_open_before_cooldown(self, cb: CircuitBreaker) -> None:
        cb.trip("test")
        transitioned = cb.attempt_reset()
        # Should not transition yet (15 min hasn't elapsed)
        assert transitioned is False
        assert cb.state == CircuitState.OPEN

    def test_open_transitions_to_half_open_after_cooldown(self, cb: CircuitBreaker) -> None:
        cb.trip("test")
        # Monkey-patch _tripped_at to simulate 16 minutes ago
        cb._tripped_at = time.monotonic() - (16 * 60)
        transitioned = cb.attempt_reset()
        assert transitioned is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self, cb: CircuitBreaker) -> None:
        cb.trip("test")
        cb._tripped_at = time.monotonic() - (16 * 60)
        cb.attempt_reset()  # OPEN → HALF_OPEN
        cb.record_trade_result(success=True)
        transitioned = cb.attempt_reset()
        assert transitioned is True
        assert cb.state == CircuitState.CLOSED
        assert cb.trip_reason == ""

    def test_half_open_stays_on_failure(self, cb: CircuitBreaker) -> None:
        cb.trip("test")
        cb._tripped_at = time.monotonic() - (16 * 60)
        cb.attempt_reset()  # OPEN → HALF_OPEN
        cb.record_trade_result(success=False)
        transitioned = cb.attempt_reset()
        assert transitioned is False
        assert cb.state == CircuitState.HALF_OPEN

    def test_check_daily_drawdown_trips(self, cb: CircuitBreaker) -> None:
        assert cb.check_daily_drawdown(-4.0) is True  # exceeds 3%
        assert cb.check_daily_drawdown(-2.9) is False  # within limit

    def test_check_vix_spike(self, cb: CircuitBreaker) -> None:
        # 21% increase: above 20% threshold
        assert cb.check_vix_spike(vix_now=24.2, vix_1h_ago=20.0) is True
        # 10% increase: below threshold
        assert cb.check_vix_spike(vix_now=22.0, vix_1h_ago=20.0) is False

    def test_check_price_gap(self, cb: CircuitBreaker) -> None:
        assert cb.check_price_gap(prev_price=100.0, curr_price=106.0) is True
        assert cb.check_price_gap(prev_price=100.0, curr_price=104.9) is False

    def test_check_rolling_loss(self, cb: CircuitBreaker) -> None:
        assert cb.check_rolling_loss([1.0, 0.5, 0.6]) is True  # sum > 2.0
        assert cb.check_rolling_loss([0.5, 0.5]) is False  # sum = 1.0

    def test_vix_spike_zero_baseline_safe(self, cb: CircuitBreaker) -> None:
        """Zero VIX baseline should not trip the breaker."""
        assert cb.check_vix_spike(vix_now=30.0, vix_1h_ago=0.0) is False
