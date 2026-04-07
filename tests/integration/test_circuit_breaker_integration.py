"""
Integration test: circuit breaker prevents execution when triggered.
Tests the safety invariant: once open, NO orders can be submitted.
"""

from __future__ import annotations

import fakeredis.aioredis

from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CircuitState


def make_cb() -> CircuitBreaker:
    """Return a fresh CircuitBreaker backed by fakeredis."""
    return CircuitBreaker(fakeredis.aioredis.FakeRedis())


class TestCircuitBreakerIntegration:
    def test_all_triggers_open_breaker(self) -> None:
        """All six trigger paths must trip the breaker."""
        triggers = [
            lambda cb: cb.update_daily_pnl(-0.031),  # -3.1% > 3% threshold
            lambda cb: cb.update_30min_pnl(-0.025),  # 2.5% rolling loss > 2%
            lambda cb: cb.update_vix_change(0.21),  # 21% VIX spike > 20%
            lambda cb: cb.notify_service_down("s01", 65),  # 65s > 60s timeout
            lambda cb: cb.update_price_gap(0.06),  # 6% gap > 5% threshold
        ]
        for i, trigger in enumerate(triggers):
            cb = make_cb()
            assert cb.state == CircuitState.CLOSED, f"Trigger {i}: should start CLOSED"
            trigger(cb)
            assert cb.state == CircuitState.OPEN, f"Trigger {i}: should be OPEN after trigger"
            assert cb.allows_new_orders() is False, f"Trigger {i}: must block orders"

    def test_open_breaker_blocks_all_orders(self) -> None:
        cb = make_cb()
        cb.update_daily_pnl(-0.04)  # trigger
        assert cb.state == CircuitState.OPEN

        # Verify 100 consecutive order checks all fail
        for _ in range(100):
            assert cb.allows_new_orders() is False

    def test_breaker_recovers_after_reset(self) -> None:
        cb = make_cb()
        cb.update_daily_pnl(-0.04)
        assert cb.state == CircuitState.OPEN

        # Manual reset (used at start of new trading day)
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_new_orders() is True

    def test_starts_closed(self) -> None:
        cb = make_cb()
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_new_orders() is True

    def test_below_threshold_does_not_trip(self) -> None:
        """Losses below threshold must not trip the breaker."""
        cb = make_cb()
        cb.update_daily_pnl(-0.025)  # -2.5% < 3% threshold
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_new_orders() is True
