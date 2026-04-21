"""Tests for CBEventGuard (Phase 6).

Uses fakeredis -- no real Redis, no network I/O.
Time is controlled via utc_now parameter injection.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import fakeredis.aioredis
import pytest

from services.risk_manager.cb_event_guard import CBEventGuard
from services.risk_manager.models import BlockReason

_NOW = datetime(2026, 4, 5, 14, 0, 0, tzinfo=UTC)
_EVENT = datetime(2026, 4, 5, 14, 40, 0, tzinfo=UTC)  # 40min from _NOW


async def _guard_with_events(events_iso: list[str]) -> CBEventGuard:
    redis = fakeredis.aioredis.FakeRedis()
    await redis.set("macro:cb_events", json.dumps(events_iso))
    return CBEventGuard(redis)


@pytest.mark.asyncio
async def test_inside_block_window_blocked() -> None:
    """35min before event is inside the 45min block window."""
    guard = await _guard_with_events([_EVENT.isoformat()])
    now = _EVENT - timedelta(minutes=35)
    result = await guard.check(utc_now=now)
    assert not result.passed
    assert result.block_reason == BlockReason.CB_EVENT_BLOCK


@pytest.mark.asyncio
async def test_outside_block_window_passes() -> None:
    """50min before event is outside the 45min block window."""
    guard = await _guard_with_events([_EVENT.isoformat()])
    now = _EVENT - timedelta(minutes=50)
    result = await guard.check(utc_now=now)
    assert result.passed


@pytest.mark.asyncio
async def test_at_block_start_exact_boundary() -> None:
    """Exactly 45min before event = first blocked minute."""
    guard = await _guard_with_events([_EVENT.isoformat()])
    now = _EVENT - timedelta(minutes=45)
    result = await guard.check(utc_now=now)
    assert not result.passed
    assert result.block_reason == BlockReason.CB_EVENT_BLOCK


@pytest.mark.asyncio
async def test_post_event_scalp_window_detected() -> None:
    """7 minutes after event is inside the 15min scalp window."""
    guard = await _guard_with_events([_EVENT.isoformat()])
    now = _EVENT + timedelta(minutes=7)
    result = await guard.check(utc_now=now)
    assert result.passed
    is_scalp = await guard.is_post_event_scalp_window(utc_now=now)
    assert is_scalp


@pytest.mark.asyncio
async def test_post_event_window_ended_passes() -> None:
    """16 minutes after event -- scalp window over, normal trading."""
    guard = await _guard_with_events([_EVENT.isoformat()])
    now = _EVENT + timedelta(minutes=16)
    result = await guard.check(utc_now=now)
    assert result.passed
    is_scalp = await guard.is_post_event_scalp_window(utc_now=now)
    assert not is_scalp


@pytest.mark.asyncio
async def test_no_events_passes() -> None:
    """Empty event list: no block."""
    redis = fakeredis.aioredis.FakeRedis()
    guard = CBEventGuard(redis)
    result = await guard.check(utc_now=_NOW)
    assert result.passed


@pytest.mark.asyncio
async def test_past_events_ignored() -> None:
    """Event from yesterday must not trigger any window."""
    yesterday_event = _NOW - timedelta(hours=25)
    guard = await _guard_with_events([yesterday_event.isoformat()])
    result = await guard.check(utc_now=_NOW)
    assert result.passed


@pytest.mark.asyncio
async def test_far_future_event_ignored() -> None:
    """Event in 48h is outside the 24h lookahead window."""
    future_event = _NOW + timedelta(hours=48)
    guard = await _guard_with_events([future_event.isoformat()])
    result = await guard.check(utc_now=_NOW)
    assert result.passed
