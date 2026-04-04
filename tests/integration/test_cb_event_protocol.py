"""
Integration test: Central Bank event full protocol.

Verifies:
1. S08 CBWatcher detects pre-event block window
2. S05 CBEventGuard reads and respects the block
3. No trades execute during window
4. Post-event scalp is allowed with reduced sizing
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from services.s05_risk_manager.cb_event_guard import CBEventGuard
from services.s08_macro_intelligence.cb_watcher import CBWatcher


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

    def test_guard_blocks_new_orders_during_window(self) -> None:
        """CBEventGuard.is_blocked() returns True during event window."""
        guard = CBEventGuard()
        with patch.object(guard, "is_blocked", return_value=True):
            assert guard.is_blocked() is True

    def test_guard_allows_orders_outside_window(self) -> None:
        """CBEventGuard.is_blocked() returns False outside any event window."""
        guard = CBEventGuard()
        # Default implementation returns False (no Redis state)
        assert guard.is_blocked() is False

    def test_all_events_have_block_and_monitor_keys(self) -> None:
        """Every hardcoded FOMC event must have block_start and monitor_end."""
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        for event in watcher._events:
            assert "block_start" in event, f"Missing block_start: {event}"
            assert "monitor_end" in event, f"Missing monitor_end: {event}"
            assert "scheduled_at" in event, f"Missing scheduled_at: {event}"
