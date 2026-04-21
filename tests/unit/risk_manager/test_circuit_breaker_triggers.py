"""Circuit breaker trigger tests -- all 4 trigger conditions.

Tests verify each trigger in isolation. No real Redis, no network I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis
import pytest

from services.risk_manager.circuit_breaker import CircuitBreaker
from services.risk_manager.models import (
    BlockReason,
    CircuitBreakerState,
)

_CAPITAL = Decimal("100_000")
_NOW = datetime.now(UTC)


def _make_cb() -> CircuitBreaker:
    redis = fakeredis.aioredis.FakeRedis()
    return CircuitBreaker(redis)


@pytest.mark.asyncio
async def test_intraday_loss_30m_trips() -> None:
    """2.1% 30-min loss exceeds 2% threshold."""
    cb = _make_cb()
    result = await cb.check(
        current_daily_pnl=Decimal("0"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("-2100"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={},
    )
    assert not result.passed
    assert result.block_reason == BlockReason.INTRADAY_LOSS_EXCEEDED
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.OPEN


@pytest.mark.asyncio
async def test_service_down_trips() -> None:
    """s01 last seen 61 seconds ago -- exceeds 60s threshold."""
    cb = _make_cb()
    stale_time = datetime.now(UTC) - timedelta(seconds=61)
    result = await cb.check(
        current_daily_pnl=Decimal("0"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={"s01": stale_time},
    )
    assert not result.passed
    assert result.block_reason == BlockReason.SERVICE_DOWN


@pytest.mark.asyncio
async def test_service_down_under_threshold_passes() -> None:
    """s01 last seen 59 seconds ago -- below 60s threshold."""
    cb = _make_cb()
    recent = datetime.now(UTC) - timedelta(seconds=59)
    result = await cb.check(
        current_daily_pnl=Decimal("0"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={"s01": recent},
    )
    assert result.passed


@pytest.mark.asyncio
async def test_multiple_healthy_checks_stay_closed() -> None:
    """Ten consecutive healthy checks remain CLOSED."""
    cb = _make_cb()
    for _ in range(10):
        result = await cb.check(
            current_daily_pnl=Decimal("500"),
            starting_capital=_CAPITAL,
            intraday_loss_30m=Decimal("0"),
            vix_current=18.0,
            vix_1h_ago=19.0,
            service_last_seen={},
        )
        assert result.passed
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_zero_capital_does_not_crash() -> None:
    """Edge case: starting_capital = 0 must not divide by zero."""
    cb = _make_cb()
    result = await cb.check(
        current_daily_pnl=Decimal("-1000"),
        starting_capital=Decimal("0"),
        intraday_loss_30m=Decimal("-500"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={},
    )
    # Should not raise; state is CLOSED since capital checks are skipped
    assert result.passed


@pytest.mark.asyncio
async def test_profitable_day_never_trips() -> None:
    """A profitable day (+5%) must never trigger drawdown breaker."""
    cb = _make_cb()
    result = await cb.check(
        current_daily_pnl=Decimal("5000"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={},
    )
    assert result.passed


@pytest.mark.asyncio
async def test_reset_daily_clears_pnl_preserves_state() -> None:
    """reset_daily() zeros P&L counters but keeps state (CLOSED stays CLOSED)."""
    cb = _make_cb()
    # Simulate some P&L
    await cb.check(
        current_daily_pnl=Decimal("-1000"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={},
    )
    await cb.reset_daily()
    snap = await cb.get_snapshot()
    assert snap.daily_pnl == Decimal("0")
    assert snap.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_consecutive_losses_tracked() -> None:
    """Each trip increments consecutive_losses counter."""
    cb = _make_cb()
    # Trip once
    await cb.check(
        current_daily_pnl=Decimal("-3100"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen={},
    )
    snap = await cb.get_snapshot()
    assert snap.consecutive_losses == 1
    assert snap.state == CircuitBreakerState.OPEN
