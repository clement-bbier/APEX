"""Tests for Central Bank event watcher."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from services.s08_macro_intelligence.cb_watcher import CBWatcher


class TestCBWatcher:
    def make_watcher(self) -> CBWatcher:
        return CBWatcher(state=AsyncMock(), bus=AsyncMock())

    def test_block_window_active_45min_before_event(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        assert len(events) > 0

        # Simulate being 30min before the first event
        first_event = datetime.fromisoformat(events[0]["scheduled_at"])
        simulated_now = first_event - timedelta(minutes=30)

        blocked, event = watcher.is_in_block_window(simulated_now)
        assert blocked is True
        assert event is not None

    def test_not_blocked_outside_window(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        first_event = datetime.fromisoformat(events[0]["scheduled_at"])
        before_window = first_event - timedelta(hours=2)

        blocked, _ = watcher.is_in_block_window(before_window)
        assert blocked is False

    def test_monitor_window_active_after_event(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        first_event = datetime.fromisoformat(events[0]["scheduled_at"])
        after_event = first_event + timedelta(minutes=30)

        monitoring, _ = watcher.is_in_monitor_window(after_event)
        assert monitoring is True

    def test_not_monitoring_before_event(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        first_event = datetime.fromisoformat(events[0]["scheduled_at"])
        before_event = first_event - timedelta(minutes=10)

        monitoring, _ = watcher.is_in_monitor_window(before_event)
        assert monitoring is False

    def test_events_loaded_from_hardcoded_list(self) -> None:
        watcher = self.make_watcher()
        assert len(watcher._events) >= 16  # at least 2024+2025 dates

    def test_each_event_has_required_keys(self) -> None:
        watcher = self.make_watcher()
        required = {"institution", "event_type", "scheduled_at", "block_start", "monitor_end"}
        for event in watcher._events:
            assert required.issubset(event.keys()), f"Missing keys in event: {event}"

    def test_block_window_boundaries(self) -> None:
        """Exactly at block_start → blocked; 1s before → not blocked."""
        watcher = self.make_watcher()
        events = watcher._events
        block_start = datetime.fromisoformat(events[0]["block_start"])

        blocked_at_start, _ = watcher.is_in_block_window(block_start)
        assert blocked_at_start is True

        just_before = block_start - timedelta(seconds=1)
        blocked_before, _ = watcher.is_in_block_window(just_before)
        assert blocked_before is False

    def test_not_blocked_after_event(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        first_event = datetime.fromisoformat(events[0]["scheduled_at"])
        after = first_event + timedelta(minutes=1)

        blocked, _ = watcher.is_in_block_window(after)
        assert blocked is False

    # ── detect_surprise ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_detect_surprise_no_surprise_keyword(self) -> None:
        watcher = self.make_watcher()
        result = await watcher.detect_surprise("Fed holds rates steady at 5.25%")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_surprise_hawkish(self) -> None:
        watcher = self.make_watcher()
        result = await watcher.detect_surprise(
            "Unexpected emergency decision to raise rates by 75bp"
        )
        assert result == "hawkish_surprise"

    @pytest.mark.asyncio
    async def test_detect_surprise_dovish(self) -> None:
        watcher = self.make_watcher()
        result = await watcher.detect_surprise(
            "Surprise stimulus package: Fed will cut rates and ease conditions"
        )
        assert result == "dovish_surprise"

    @pytest.mark.asyncio
    async def test_get_latest_statement_returns_none_on_error(self) -> None:
        """Should return None when RSS fetch fails."""
        from unittest.mock import patch

        watcher = self.make_watcher()
        with patch.object(watcher, "fetch_fed_rss", side_effect=Exception("network error")):
            result = await watcher.get_latest_statement()
        assert result is None
