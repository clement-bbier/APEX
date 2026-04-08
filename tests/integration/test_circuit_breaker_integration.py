"""
Integration test: circuit breaker prevents execution when triggered.
Tests the safety invariant: once OPEN, NO orders can be submitted.

Migrated from the legacy synchronous v1 API to the canonical async v2
``CircuitBreaker.check()`` / ``get_snapshot()`` surface (issue #9).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis
import pytest

from services.s05_risk_manager.circuit_breaker import CircuitBreaker
from services.s05_risk_manager.models import (
    HALF_OPEN_RECOVERY_MINUTES,
    BlockReason,
    CircuitBreakerSnapshot,
    CircuitBreakerState,
)


def make_cb() -> CircuitBreaker:
    """Return a fresh CircuitBreaker backed by an isolated fakeredis."""
    return CircuitBreaker(fakeredis.aioredis.FakeRedis())


# ── neutral inputs that never trip any trigger ─────────────────────────
NEUTRAL_KWARGS: dict[str, object] = {
    "current_daily_pnl": Decimal("0"),
    "starting_capital": Decimal("100000"),
    "intraday_loss_30m": Decimal("0"),
    "vix_current": 20.0,
    "vix_1h_ago": 20.0,
    "service_last_seen": {},
}


def _kwargs(**overrides: object) -> dict[str, object]:
    return {**NEUTRAL_KWARGS, **overrides}


class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_all_triggers_open_breaker(self) -> None:
        """Each v2 trigger path must trip the breaker to OPEN."""
        # Map: human label -> kwargs override that should trip the CB.
        # NB: the legacy "price gap" trigger does not exist in the v2 API
        # (see circuit_breaker.py docstring -- only 4 triggers are wired).
        triggers: list[tuple[str, dict[str, object], BlockReason]] = [
            (
                "daily_drawdown",
                {
                    "current_daily_pnl": Decimal("-3100"),  # -3.1% of 100k
                    "starting_capital": Decimal("100000"),
                },
                BlockReason.DAILY_DRAWDOWN_EXCEEDED,
            ),
            (
                "intraday_30m",
                {
                    "intraday_loss_30m": Decimal("-2500"),  # -2.5% of 100k
                    "starting_capital": Decimal("100000"),
                },
                BlockReason.INTRADAY_LOSS_EXCEEDED,
            ),
            (
                "vix_spike",
                {"vix_current": 24.2, "vix_1h_ago": 20.0},  # +21%
                BlockReason.VIX_SPIKE,
            ),
            (
                "service_down",
                {
                    "service_last_seen": {
                        "s01": datetime.now(UTC) - timedelta(seconds=65),
                    },
                },
                BlockReason.SERVICE_DOWN,
            ),
        ]

        for label, override, expected_reason in triggers:
            cb = make_cb()
            initial = await cb.get_snapshot()
            assert initial.state == CircuitBreakerState.CLOSED, f"{label}: should start CLOSED"

            result = await cb.check(**_kwargs(**override))  # type: ignore[arg-type]
            assert result.passed is False, f"{label}: check() must fail"
            assert result.block_reason == expected_reason, (
                f"{label}: wrong block reason {result.block_reason}"
            )

            snap = await cb.get_snapshot()
            assert snap.state == CircuitBreakerState.OPEN, (
                f"{label}: state should be OPEN, got {snap.state}"
            )

    @pytest.mark.asyncio
    async def test_open_breaker_blocks_all_orders(self) -> None:
        cb = make_cb()
        # Trip via daily drawdown (-4%).
        await cb.check(
            **_kwargs(
                current_daily_pnl=Decimal("-4000"),
                starting_capital=Decimal("100000"),
            )  # type: ignore[arg-type]
        )
        snap = await cb.get_snapshot()
        assert snap.state == CircuitBreakerState.OPEN

        # 100 consecutive checks with neutral inputs must all be blocked.
        for _ in range(100):
            result = await cb.check(**NEUTRAL_KWARGS)  # type: ignore[arg-type]
            assert result.passed is False
            assert result.block_reason == BlockReason.CIRCUIT_BREAKER_OPEN

    @pytest.mark.asyncio
    async def test_breaker_recovers_after_reset(self) -> None:
        """OPEN -> HALF_OPEN (after cooldown) -> CLOSED (probe success)."""
        cb = make_cb()
        await cb.check(
            **_kwargs(
                current_daily_pnl=Decimal("-4000"),
                starting_capital=Decimal("100000"),
            )  # type: ignore[arg-type]
        )
        tripped = await cb.get_snapshot()
        assert tripped.state == CircuitBreakerState.OPEN

        # Simulate cooldown elapsing by rewriting tripped_at into the past.
        past = datetime.now(UTC) - timedelta(minutes=HALF_OPEN_RECOVERY_MINUTES + 1)
        rewound = CircuitBreakerSnapshot(
            state=CircuitBreakerState.OPEN,
            tripped_at=past,
            tripped_reason=tripped.tripped_reason,
            daily_pnl=tripped.daily_pnl,
            daily_loss_pct=tripped.daily_loss_pct,
            intraday_loss_30m=tripped.intraday_loss_30m,
            consecutive_losses=tripped.consecutive_losses,
            recovery_attempts=tripped.recovery_attempts,
            last_updated=past,
        )
        await cb._save_snapshot(rewound)

        # Next check() transitions OPEN -> HALF_OPEN and lets a probe through.
        probe_result = await cb.check(**NEUTRAL_KWARGS)  # type: ignore[arg-type]
        assert probe_result.passed is True
        half_open = await cb.get_snapshot()
        assert half_open.state == CircuitBreakerState.HALF_OPEN

        # A successful probe trade closes the breaker.
        await cb.record_trade_result(Decimal("100"))
        closed = await cb.get_snapshot()
        assert closed.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_starts_closed(self) -> None:
        cb = make_cb()
        snap = await cb.get_snapshot()
        assert snap.state == CircuitBreakerState.CLOSED

        result = await cb.check(**NEUTRAL_KWARGS)  # type: ignore[arg-type]
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_below_threshold_does_not_trip(self) -> None:
        """Losses below thresholds must not trip the breaker."""
        cb = make_cb()
        result = await cb.check(
            **_kwargs(
                current_daily_pnl=Decimal("-2500"),  # -2.5% < 3% threshold
                starting_capital=Decimal("100000"),
            )  # type: ignore[arg-type]
        )
        assert result.passed is True
        snap = await cb.get_snapshot()
        assert snap.state == CircuitBreakerState.CLOSED
