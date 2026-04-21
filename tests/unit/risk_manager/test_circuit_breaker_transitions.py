"""Circuit breaker state transition tests.

Tests verify the CLOSED/OPEN/HALF_OPEN state machine using fakeredis.
No real Redis, no network I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis
import pytest

from services.risk_manager.circuit_breaker import CircuitBreaker
from services.risk_manager.models import (
    HALF_OPEN_RECOVERY_MINUTES,
    BlockReason,
    CircuitBreakerState,
)

_CAPITAL = Decimal("100_000")
_NO_SERVICES: dict[str, datetime] = {}


def _make_cb() -> tuple[CircuitBreaker, fakeredis.aioredis.FakeRedis]:
    redis = fakeredis.aioredis.FakeRedis()
    return CircuitBreaker(redis), redis


@pytest.mark.asyncio
async def test_initial_state_is_closed() -> None:
    cb, _ = _make_cb()
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_daily_drawdown_trips_to_open() -> None:
    cb, _ = _make_cb()
    # -3.1% loss on 100k capital
    result = await cb.check(
        current_daily_pnl=Decimal("-3100"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen=_NO_SERVICES,
    )
    assert not result.passed
    assert result.block_reason == BlockReason.DAILY_DRAWDOWN_EXCEEDED
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.OPEN


@pytest.mark.asyncio
async def test_daily_drawdown_under_threshold_stays_closed() -> None:
    cb, _ = _make_cb()
    # -2.9% loss — below 3% threshold
    result = await cb.check(
        current_daily_pnl=Decimal("-2900"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen=_NO_SERVICES,
    )
    assert result.passed
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_vix_spike_trips() -> None:
    cb, _ = _make_cb()
    # VIX: 25 -> 36, change = +44% > 20% threshold
    result = await cb.check(
        current_daily_pnl=Decimal("0"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=36.0,
        vix_1h_ago=25.0,
        service_last_seen=_NO_SERVICES,
    )
    assert not result.passed
    assert result.block_reason == BlockReason.VIX_SPIKE


@pytest.mark.asyncio
async def test_vix_under_threshold_passes() -> None:
    cb, _ = _make_cb()
    # VIX: 25 -> 26, change = +4% < 20% threshold
    result = await cb.check(
        current_daily_pnl=Decimal("0"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=26.0,
        vix_1h_ago=25.0,
        service_last_seen=_NO_SERVICES,
    )
    assert result.passed


@pytest.mark.asyncio
async def test_probe_success_transitions_to_closed() -> None:
    """HALF_OPEN + probe PnL > 0 -> CLOSED."""
    cb, redis = _make_cb()

    # First trip
    await cb.check(
        current_daily_pnl=Decimal("-3100"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen=_NO_SERVICES,
    )
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.OPEN

    # Force transition to HALF_OPEN by backdating tripped_at
    from services.risk_manager.models import (
        REDIS_CB_KEY,
        CircuitBreakerSnapshot,
    )

    old = await cb.get_snapshot()
    past = datetime.now(UTC) - timedelta(minutes=HALF_OPEN_RECOVERY_MINUTES + 1)
    patched = CircuitBreakerSnapshot(
        state=CircuitBreakerState.OPEN,
        tripped_at=past,
        tripped_reason=old.tripped_reason,
        daily_pnl=old.daily_pnl,
        daily_loss_pct=old.daily_loss_pct,
        last_updated=past,
    )
    await redis.setex(REDIS_CB_KEY, 86400, patched.model_dump_json())

    # Now probe with no new triggers -> transitions to HALF_OPEN then check passes
    result = await cb.check(
        current_daily_pnl=Decimal("-3100"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen=_NO_SERVICES,
    )
    snap2 = await cb.get_snapshot()
    assert snap2.state == CircuitBreakerState.HALF_OPEN

    # Record profitable probe
    await cb.record_trade_result(Decimal("50"))
    snap3 = await cb.get_snapshot()
    assert snap3.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_probe_failure_stays_open() -> None:
    """HALF_OPEN + probe PnL < 0 -> OPEN (reset cooldown)."""
    cb, redis = _make_cb()

    # Trip CB
    await cb.check(
        current_daily_pnl=Decimal("-3100"),
        starting_capital=_CAPITAL,
        intraday_loss_30m=Decimal("0"),
        vix_current=20.0,
        vix_1h_ago=20.0,
        service_last_seen=_NO_SERVICES,
    )

    # Force HALF_OPEN state
    from services.risk_manager.models import (
        REDIS_CB_KEY,
        CircuitBreakerSnapshot,
    )

    past = datetime.now(UTC) - timedelta(minutes=HALF_OPEN_RECOVERY_MINUTES + 1)
    patched = CircuitBreakerSnapshot(
        state=CircuitBreakerState.HALF_OPEN,
        tripped_at=past,
        tripped_reason=BlockReason.DAILY_DRAWDOWN_EXCEEDED,
        daily_pnl=Decimal("-3100"),
        last_updated=past,
    )
    await redis.setex(REDIS_CB_KEY, 86400, patched.model_dump_json())

    # Record failing probe
    await cb.record_trade_result(Decimal("-100"))
    snap = await cb.get_snapshot()
    assert snap.state == CircuitBreakerState.OPEN
