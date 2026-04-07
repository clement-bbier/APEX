"""
Integration test: circuit breaker prevents execution when triggered.
Tests the safety invariant: once open, NO orders can be submitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis

from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CircuitState

_CAPITAL = Decimal("100_000")


def make_cb() -> CircuitBreaker:
    """Return a fresh CircuitBreaker with an isolated FakeRedis instance."""
    return CircuitBreaker(fakeredis.aioredis.FakeRedis())


class TestCircuitBreakerIntegration:
    async def test_all_triggers_open_breaker(self) -> None:
        """All trigger paths must trip the breaker to OPEN."""
        trigger_cases = [
            (
                {
                    "current_daily_pnl": Decimal("-3100"),
                    "starting_capital": _CAPITAL,
                    "intraday_loss_30m": Decimal("0"),
                    "vix_current": 20.0,
                    "vix_1h_ago": 20.0,
                    "service_last_seen": {},
                },
                "daily -3.1%",
            ),
            (
                {
                    "current_daily_pnl": Decimal("0"),
                    "starting_capital": _CAPITAL,
                    "intraday_loss_30m": Decimal("-2500"),
                    "vix_current": 20.0,
                    "vix_1h_ago": 20.0,
                    "service_last_seen": {},
                },
                "30min -2.5%",
            ),
            (
                {
                    "current_daily_pnl": Decimal("0"),
                    "starting_capital": _CAPITAL,
                    "intraday_loss_30m": Decimal("0"),
                    "vix_current": 12.1,
                    "vix_1h_ago": 10.0,
                    "service_last_seen": {},
                },
                "VIX +21%",
            ),
            (
                {
                    "current_daily_pnl": Decimal("0"),
                    "starting_capital": _CAPITAL,
                    "intraday_loss_30m": Decimal("0"),
                    "vix_current": 20.0,
                    "vix_1h_ago": 20.0,
                    "service_last_seen": {"s01": datetime.now(UTC) - timedelta(seconds=65)},
                },
                "service down 65s",
            ),
        ]
        for kwargs, desc in trigger_cases:
            cb = make_cb()
            snap = await cb.get_snapshot()
            assert snap.state == CircuitState.CLOSED, f"{desc}: should start CLOSED"
            result = await cb.check(**kwargs)
            assert not result.passed, f"{desc}: check should fail"
            snap = await cb.get_snapshot()
            assert snap.state == CircuitState.OPEN, f"{desc}: should be OPEN after trigger"

    async def test_open_breaker_blocks_all_orders(self) -> None:
        cb = make_cb()
        await cb.check(
            current_daily_pnl=Decimal("-4000"),
            starting_capital=_CAPITAL,
            intraday_loss_30m=Decimal("0"),
            vix_current=20.0,
            vix_1h_ago=20.0,
            service_last_seen={},
        )
        snap = await cb.get_snapshot()
        assert snap.state == CircuitState.OPEN

        # Verify 100 consecutive healthy checks all fail while OPEN
        for _ in range(100):
            result = await cb.check(
                current_daily_pnl=Decimal("0"),
                starting_capital=_CAPITAL,
                intraday_loss_30m=Decimal("0"),
                vix_current=20.0,
                vix_1h_ago=20.0,
                service_last_seen={},
            )
            assert result.passed is False

    async def test_reset_daily_preserves_open_state(self) -> None:
        cb = make_cb()
        await cb.check(
            current_daily_pnl=Decimal("-4000"),
            starting_capital=_CAPITAL,
            intraday_loss_30m=Decimal("0"),
            vix_current=20.0,
            vix_1h_ago=20.0,
            service_last_seen={},
        )
        snap = await cb.get_snapshot()
        assert snap.state == CircuitState.OPEN

        # reset_daily() clears daily P&L but preserves OPEN state
        await cb.reset_daily()
        snap = await cb.get_snapshot()
        assert snap.state == CircuitState.OPEN
        assert snap.daily_pnl == Decimal("0")

    async def test_starts_closed(self) -> None:
        cb = make_cb()
        snap = await cb.get_snapshot()
        assert snap.state == CircuitState.CLOSED
        result = await cb.check(
            current_daily_pnl=Decimal("0"),
            starting_capital=_CAPITAL,
            intraday_loss_30m=Decimal("0"),
            vix_current=20.0,
            vix_1h_ago=20.0,
            service_last_seen={},
        )
        assert result.passed is True

    async def test_below_threshold_does_not_trip(self) -> None:
        """Losses below threshold must not trip the breaker."""
        cb = make_cb()
        result = await cb.check(
            current_daily_pnl=Decimal("-2500"),  # -2.5% < 3% threshold
            starting_capital=_CAPITAL,
            intraday_loss_30m=Decimal("0"),
            vix_current=20.0,
            vix_1h_ago=20.0,
            service_last_seen={},
        )
        snap = await cb.get_snapshot()
        assert snap.state == CircuitState.CLOSED
        assert result.passed is True

