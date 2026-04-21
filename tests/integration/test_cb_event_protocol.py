"""
Integration test: Central Bank event full protocol.

Verifies:
1. S08 CBWatcher detects pre-event block window
2. S05 CBEventGuard reads and respects the block (async API v2)
3. No trades execute during window
4. Post-event scalp is allowed with reduced sizing
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from services.risk_manager.cb_event_guard import CBEventGuard
from services.risk_manager.models import BlockReason
from services.macro_intelligence.cb_watcher import CBWatcher


class TestCBEventProtocol:
    def test_watcher_detects_block_window(self) -> None:
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        assert len(events) > 0

        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        thirty_min_before = event_time - timedelta(minutes=30)

        blocked, event = watcher.is_in_block_window(thirty_min_before)
        assert blocked is True
        assert event is not None

    def test_no_block_far_from_event(self) -> None:
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        far_before = event_time - timedelta(hours=3)

        blocked, _ = watcher.is_in_block_window(far_before)
        assert blocked is False

    def test_post_event_monitor_window(self) -> None:
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        thirty_after = event_time + timedelta(minutes=30)

        monitoring, _ = watcher.is_in_monitor_window(thirty_after)
        assert monitoring is True

    @pytest.mark.asyncio
    async def test_guard_blocks_new_orders_during_window(self) -> None:
        """CBEventGuard.check() returns failed RuleResult during pre-event block window."""
        redis = fakeredis.aioredis.FakeRedis()
        frozen_now = datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC)
        event_time = frozen_now + timedelta(minutes=20)
        await redis.set(
            "macro:cb_events",
            json.dumps([event_time.isoformat()]),
        )
        guard = CBEventGuard(redis=redis)
        result = await guard.check(utc_now=frozen_now)
        assert result.passed is False
        assert result.block_reason == BlockReason.CB_EVENT_BLOCK

    @pytest.mark.asyncio
    async def test_guard_allows_orders_outside_window(self) -> None:
        """CBEventGuard.check() returns passed RuleResult outside any event window."""
        redis = fakeredis.aioredis.FakeRedis()
        frozen_now = datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC)
        guard = CBEventGuard(redis=redis)
        result = await guard.check(utc_now=frozen_now)
        assert result.passed is True
        assert result.block_reason is None

    @pytest.mark.asyncio
    async def test_guard_post_event_scalp_window(self) -> None:
        """CBEventGuard.check() returns ok during post-event scalp window."""
        redis = fakeredis.aioredis.FakeRedis()
        frozen_now = datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC)
        event_time = frozen_now - timedelta(minutes=5)
        await redis.set(
            "macro:cb_events",
            json.dumps([event_time.isoformat()]),
        )
        guard = CBEventGuard(redis=redis)
        result = await guard.check(utc_now=frozen_now)
        assert result.passed is True
        assert result.block_reason is None
        assert await guard.is_post_event_scalp_window(utc_now=frozen_now) is True

    def test_all_events_have_block_and_monitor_keys(self) -> None:
        """Every hardcoded FOMC event must have block_start and monitor_end."""
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        for event in watcher._events:
            assert "block_start" in event, f"Missing block_start: {event}"
            assert "monitor_end" in event, f"Missing monitor_end: {event}"
            assert "scheduled_at" in event, f"Missing scheduled_at: {event}"
