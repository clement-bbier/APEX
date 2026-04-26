"""Tests for Central Bank event watcher.

Coverage mission: 57% -> 100% (Sprint 5 Wave A, Agent A3).
Single-module win to cross main-wide 85% and unblock #203
(coverage gate raise 75->85%).

Final coverage: 100% (38 tests, 6 new test classes + 3 Hypothesis
property tests).

Targeted previously-missed lines (per `--cov-report=term-missing` baseline):
  - 90-94  : ``get_next_event`` (filter future events, pick soonest, None case)
  - 99     : ``is_in_block_window`` ``now=None`` default branch
  - 112    : ``is_in_monitor_window`` ``now=None`` default branch
  - 129-165: ``fetch_fed_rss`` RSS + Atom parse paths via mocked ``aiohttp``
  - 175-176: ``get_latest_statement`` happy path (non-empty items)
  - 205    : ``detect_surprise`` tie path (hawkish == dovish)
  - 209-229: ``run_loop`` one-iteration drive (blocked / not-blocked branches)

Tests follow CLAUDE.md s2 (UTC, structlog) and s7 (happy + edge + error +
property). All async tests use ``pytest.mark.asyncio`` (project
``asyncio_mode = auto`` config). No live Redis or live network is hit; the
StateStore/MessageBus are ``AsyncMock`` since ``CBWatcher`` only invokes
``state.set(key, value)``, and ``aiohttp.ClientSession`` is patched out for
RSS tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from services.macro_intelligence.cb_watcher import (
    BLOCK_WINDOW_MINUTES,
    MONITOR_WINDOW_MINUTES,
    CBWatcher,
)


def _make_watcher() -> CBWatcher:
    return CBWatcher(state=AsyncMock(), bus=AsyncMock())


# ===========================================================================
# Original test surface — preserved so the legacy assertions keep their value
# even after the new mission-driven tests are layered on top.
# ===========================================================================


class TestCBWatcher:
    def make_watcher(self) -> CBWatcher:
        return _make_watcher()

    def test_block_window_active_45min_before_event(self) -> None:
        watcher = self.make_watcher()
        events = watcher._events
        assert len(events) > 0

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
        """Exactly at block_start -> blocked; 1s before -> not blocked."""
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
        watcher = self.make_watcher()
        with patch.object(watcher, "fetch_fed_rss", side_effect=Exception("network error")):
            result = await watcher.get_latest_statement()
        assert result is None


# ===========================================================================
# get_next_event — lines 90-94
# ===========================================================================


class TestGetNextEvent:
    """Future-event filtering and "soonest-first" selection."""

    @pytest.mark.asyncio
    async def test_returns_soonest_future_event(self) -> None:
        """When all hardcoded events are in the past, build a fresh future set."""
        watcher = _make_watcher()
        now = datetime.now(UTC)
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (now + timedelta(days=10)).isoformat(),
                "block_start": (now + timedelta(days=10, minutes=-45)).isoformat(),
                "monitor_end": (now + timedelta(days=10, minutes=60)).isoformat(),
            },
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (now + timedelta(days=2)).isoformat(),
                "block_start": (now + timedelta(days=2, minutes=-45)).isoformat(),
                "monitor_end": (now + timedelta(days=2, minutes=60)).isoformat(),
            },
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (now + timedelta(days=5)).isoformat(),
                "block_start": (now + timedelta(days=5, minutes=-45)).isoformat(),
                "monitor_end": (now + timedelta(days=5, minutes=60)).isoformat(),
            },
        ]
        nxt = await watcher.get_next_event()
        assert nxt is not None
        # The 2-day future event must win
        delta = datetime.fromisoformat(nxt["scheduled_at"]) - now
        assert timedelta(days=1, hours=23) < delta < timedelta(days=2, hours=1)

    @pytest.mark.asyncio
    async def test_excludes_past_events(self) -> None:
        watcher = _make_watcher()
        now = datetime.now(UTC)
        past_only = {
            "institution": "FED",
            "event_type": "rate_decision",
            "scheduled_at": (now - timedelta(days=1)).isoformat(),
            "block_start": (now - timedelta(days=1, minutes=45)).isoformat(),
            "monitor_end": (now - timedelta(days=1, minutes=-60)).isoformat(),
        }
        future = {
            "institution": "FED",
            "event_type": "rate_decision",
            "scheduled_at": (now + timedelta(days=3)).isoformat(),
            "block_start": (now + timedelta(days=3, minutes=-45)).isoformat(),
            "monitor_end": (now + timedelta(days=3, minutes=60)).isoformat(),
        }
        watcher._events = [past_only, future]
        nxt = await watcher.get_next_event()
        assert nxt is not None
        assert nxt["scheduled_at"] == future["scheduled_at"]

    @pytest.mark.asyncio
    async def test_returns_none_when_no_future_events(self) -> None:
        """All events in the past -> None."""
        watcher = _make_watcher()
        now = datetime.now(UTC)
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (now - timedelta(days=2)).isoformat(),
                "block_start": (now - timedelta(days=2, minutes=45)).isoformat(),
                "monitor_end": (now - timedelta(days=2, minutes=-60)).isoformat(),
            }
        ]
        assert await watcher.get_next_event() is None

    @pytest.mark.asyncio
    async def test_returns_none_with_empty_calendar(self) -> None:
        watcher = _make_watcher()
        watcher._events = []
        assert await watcher.get_next_event() is None


# ===========================================================================
# now=None default branches — lines 99 (block) and 112 (monitor)
# ===========================================================================


class TestNowDefaults:
    """Calling the window predicates without an explicit ``now`` should use UTC now."""

    def test_is_in_block_window_default_now(self) -> None:
        """Hits line 99 — the ``now = datetime.now(UTC)`` default branch.

        Calendar is wiped so the iteration is empty and we return ``(False, None)``
        deterministically — regardless of wall-clock at test runtime.
        """
        watcher = _make_watcher()
        watcher._events = []
        blocked, event = watcher.is_in_block_window()
        assert blocked is False
        assert event is None

    def test_is_in_monitor_window_default_now(self) -> None:
        """Hits line 112 — same default-now branch on the monitor side."""
        watcher = _make_watcher()
        watcher._events = []
        monitoring, event = watcher.is_in_monitor_window()
        assert monitoring is False
        assert event is None

    def test_is_in_block_window_default_now_with_active_event(self) -> None:
        """Default-now branch + a synthetic event covering the present.

        Verifies the default ``now`` is actually used (not just stubbed away
        by an empty calendar).
        """
        watcher = _make_watcher()
        present = datetime.now(UTC)
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (present + timedelta(minutes=10)).isoformat(),
                "block_start": (present - timedelta(minutes=5)).isoformat(),
                "monitor_end": (present + timedelta(minutes=70)).isoformat(),
            }
        ]
        blocked, event = watcher.is_in_block_window()
        assert blocked is True
        assert event is not None
        assert event["institution"] == "FED"

    def test_is_in_monitor_window_default_now_with_active_event(self) -> None:
        watcher = _make_watcher()
        present = datetime.now(UTC)
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (present - timedelta(minutes=10)).isoformat(),
                "block_start": (present - timedelta(minutes=55)).isoformat(),
                "monitor_end": (present + timedelta(minutes=50)).isoformat(),
            }
        ]
        monitoring, event = watcher.is_in_monitor_window()
        assert monitoring is True
        assert event is not None
        assert event["event_type"] == "rate_decision"


# ===========================================================================
# fetch_fed_rss — lines 129-165 (RSS + Atom parse paths)
# ===========================================================================


_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Press Releases</title>
    <link>https://www.federalreserve.gov</link>
    <description>Press</description>
    <item>
      <title>Federal Reserve raises target range</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20250130a.htm</link>
      <pubDate>Wed, 30 Jan 2025 19:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Federal Reserve holds steady</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm</link>
      <pubDate>Wed, 19 Mar 2025 18:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


_RSS_XML_EMPTY_CHANNEL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Press Releases</title>
    <link>https://www.federalreserve.gov</link>
    <description>Press</description>
  </channel>
</rss>
"""


_RSS_XML_MISSING_FIELDS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Only-title item</title>
    </item>
  </channel>
</rss>
"""


_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Federal Reserve Atom Feed</title>
  <updated>2025-09-17T18:00:00Z</updated>
  <entry>
    <title>FOMC announces rate decision</title>
    <link href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm"/>
    <published>2025-09-17T18:00:00Z</published>
  </entry>
  <entry>
    <title>FOMC minutes released</title>
    <link href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20251008a.htm"/>
    <published>2025-10-08T18:00:00Z</published>
  </entry>
</feed>
"""


_ATOM_XML_MISSING_FIELDS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
  </entry>
</feed>
"""


class _FakeResponse:
    """Async-context-manager-shaped fake aiohttp response."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeSession:
    """Async-context-manager-shaped fake aiohttp session.

    ``get`` returns a response context manager so that the production
    ``async with session.get(url, timeout=...) as resp`` block works as
    written (cb_watcher.py:131-133).
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self.last_url: str | None = None
        self.last_kwargs: dict[str, Any] | None = None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.last_url = url
        self.last_kwargs = kwargs
        return _FakeResponse(self._text)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class TestFetchFedRss:
    """RSS + Atom parsing paths plus defensive missing-tag handling."""

    @pytest.mark.asyncio
    async def test_rss_path_extracts_items(self) -> None:
        watcher = _make_watcher()
        fake = _FakeSession(_RSS_XML)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            items = await watcher.fetch_fed_rss()

        assert len(items) == 2
        assert items[0]["title"] == "Federal Reserve raises target range"
        assert items[0]["link"].endswith("monetary20250130a.htm")
        assert "30 Jan 2025" in items[0]["published"]
        assert items[1]["title"] == "Federal Reserve holds steady"

    @pytest.mark.asyncio
    async def test_rss_path_handles_missing_tags(self) -> None:
        """Items with missing ``<link>`` / ``<pubDate>`` default to empty strings."""
        watcher = _make_watcher()
        fake = _FakeSession(_RSS_XML_MISSING_FIELDS)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            items = await watcher.fetch_fed_rss()

        assert len(items) == 1
        assert items[0]["title"] == "Only-title item"
        assert items[0]["link"] == ""
        assert items[0]["published"] == ""

    @pytest.mark.asyncio
    async def test_rss_channel_with_no_items(self) -> None:
        watcher = _make_watcher()
        fake = _FakeSession(_RSS_XML_EMPTY_CHANNEL)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            items = await watcher.fetch_fed_rss()
        assert items == []

    @pytest.mark.asyncio
    async def test_atom_path_extracts_entries(self) -> None:
        """No ``<channel>`` -> falls through to the Atom branch (line 152+)."""
        watcher = _make_watcher()
        fake = _FakeSession(_ATOM_XML)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            items = await watcher.fetch_fed_rss()

        assert len(items) == 2
        assert items[0]["title"] == "FOMC announces rate decision"
        assert items[0]["link"].endswith("monetary20250917a.htm")
        assert items[0]["published"] == "2025-09-17T18:00:00Z"
        assert items[1]["title"] == "FOMC minutes released"

    @pytest.mark.asyncio
    async def test_atom_path_handles_missing_tags(self) -> None:
        """Atom entry with no title/link/published -> all-empty dict."""
        watcher = _make_watcher()
        fake = _FakeSession(_ATOM_XML_MISSING_FIELDS)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            items = await watcher.fetch_fed_rss()

        assert len(items) == 1
        assert items[0]["title"] == ""
        assert items[0]["link"] == ""
        assert items[0]["published"] == ""

    @pytest.mark.asyncio
    async def test_uses_configured_url_and_timeout(self) -> None:
        """Verify the production URL constant and timeout reach aiohttp."""
        from services.macro_intelligence.cb_watcher import FED_RSS_URL

        watcher = _make_watcher()
        fake = _FakeSession(_RSS_XML)
        with patch(
            "services.macro_intelligence.cb_watcher.aiohttp.ClientSession",
            return_value=fake,
        ):
            await watcher.fetch_fed_rss()

        assert fake.last_url == FED_RSS_URL
        assert fake.last_kwargs is not None
        assert "timeout" in fake.last_kwargs


# ===========================================================================
# get_latest_statement happy path — lines 175-176
# ===========================================================================


class TestGetLatestStatementHappyPath:
    @pytest.mark.asyncio
    async def test_returns_first_item_title(self) -> None:
        """fetch_fed_rss returns items -> title of items[0]."""
        watcher = _make_watcher()
        with patch.object(
            watcher,
            "fetch_fed_rss",
            return_value=[
                {"title": "Newest", "link": "x", "published": "now"},
                {"title": "Older", "link": "y", "published": "earlier"},
            ],
        ):
            result = await watcher.get_latest_statement()
        assert result == "Newest"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_items(self) -> None:
        """fetch_fed_rss returns [] -> None (the ``if items:`` branch is False)."""
        watcher = _make_watcher()
        with patch.object(watcher, "fetch_fed_rss", return_value=[]):
            result = await watcher.get_latest_statement()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_first_item_lacks_title(self) -> None:
        """``items[0].get('title')`` -> None when key is absent."""
        watcher = _make_watcher()
        with patch.object(
            watcher,
            "fetch_fed_rss",
            return_value=[{"link": "x", "published": "now"}],
        ):
            result = await watcher.get_latest_statement()
        assert result is None


# ===========================================================================
# detect_surprise tie path — line 205
# ===========================================================================


class TestDetectSurpriseTie:
    @pytest.mark.asyncio
    async def test_equal_hawkish_and_dovish_keywords_returns_none(self) -> None:
        """``raise`` (hawkish=1) + ``ease`` (dovish=1) -> tie -> None (line 205)."""
        watcher = _make_watcher()
        # surprise keyword present so we get past the early-return
        # raise=hawkish 1, ease=dovish 1 -> tie
        result = await watcher.detect_surprise(
            "Unexpected: Fed will raise short-term rates and ease longer-term conditions"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_surprise_with_no_directional_keywords_returns_none(self) -> None:
        """0=0 also exercises the tie -> None path."""
        watcher = _make_watcher()
        result = await watcher.detect_surprise(
            "Unexpected outcome with no directional language at all"
        )
        assert result is None


# ===========================================================================
# run_loop one-iteration drive — lines 209-229
# ===========================================================================


def _patch_sleep_to_break_after(n: int) -> Callable[[float], Awaitable[None]]:
    """Return an async ``sleep`` side-effect that raises after ``n`` calls.

    Used to drive ``run_loop`` for exactly ``n`` iterations and then escape via
    a ``CancelledError`` — the standard pattern for ``while True`` loops with
    no other exit condition.
    """
    counter = {"n": 0}

    async def _fake_sleep(_delay: float) -> None:
        counter["n"] += 1
        if counter["n"] >= n:
            raise asyncio.CancelledError("test-stop")

    return _fake_sleep


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_single_iteration_publishes_state_keys_when_idle(self) -> None:
        """No active event + no future event -> only block/monitor keys are set."""
        watcher = _make_watcher()
        watcher._events = []  # empty calendar -> no next_event, no block, no monitor

        with patch(
            "services.macro_intelligence.cb_watcher.asyncio.sleep",
            side_effect=_patch_sleep_to_break_after(1),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watcher.run_loop()

        state_mock: AsyncMock = watcher._state  # type: ignore[assignment]
        keys = [call.args[0] for call in state_mock.set.await_args_list]
        assert "macro:cb:block_active" in keys
        assert "macro:cb:monitor_active" in keys
        assert "macro:cb:next_event" not in keys

    @pytest.mark.asyncio
    async def test_single_iteration_with_active_block_window(self) -> None:
        """Block window is active -> warning branch + next_event branch both fire.

        Note: ``logger.warning`` is patched out here because the production call
        site at cb_watcher.py:222-227 passes ``event=event["institution"]`` as a
        kwarg, which collides with structlog's first positional param (also
        named ``event``). That collision raises ``TypeError`` at runtime in any
        process configured against a real structlog logger. Tracked separately
        as a follow-up bug; this PR is tests-only and does not modify
        production code.
        """
        watcher = _make_watcher()
        present = datetime.now(UTC)
        active_event = {
            "institution": "FED",
            "event_type": "rate_decision",
            "scheduled_at": (present + timedelta(minutes=10)).isoformat(),
            "block_start": (present - timedelta(minutes=5)).isoformat(),
            "monitor_end": (present + timedelta(minutes=70)).isoformat(),
        }
        watcher._events = [active_event]

        with patch(
            "services.macro_intelligence.cb_watcher.logger.warning",
            new=MagicMock(),
        ):
            with patch(
                "services.macro_intelligence.cb_watcher.asyncio.sleep",
                side_effect=_patch_sleep_to_break_after(1),
            ):
                with pytest.raises(asyncio.CancelledError):
                    await watcher.run_loop()

        state_mock: AsyncMock = watcher._state  # type: ignore[assignment]
        calls = {c.args[0]: c.args[1] for c in state_mock.set.await_args_list}
        assert calls["macro:cb:block_active"]["active"] is True
        assert calls["macro:cb:block_active"]["event"] == active_event
        # next_event published — the upcoming event is the same one
        assert "macro:cb:next_event" in calls
        assert calls["macro:cb:next_event"] == active_event
        # monitor not active during block window
        assert calls["macro:cb:monitor_active"]["active"] is False

    @pytest.mark.asyncio
    async def test_single_iteration_with_monitor_window_active(self) -> None:
        """Post-event monitor window active; no future event scheduled."""
        watcher = _make_watcher()
        present = datetime.now(UTC)
        past_event_in_monitor = {
            "institution": "FED",
            "event_type": "rate_decision",
            "scheduled_at": (present - timedelta(minutes=10)).isoformat(),
            "block_start": (present - timedelta(minutes=55)).isoformat(),
            "monitor_end": (present + timedelta(minutes=50)).isoformat(),
        }
        watcher._events = [past_event_in_monitor]

        with patch(
            "services.macro_intelligence.cb_watcher.asyncio.sleep",
            side_effect=_patch_sleep_to_break_after(1),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watcher.run_loop()

        state_mock: AsyncMock = watcher._state  # type: ignore[assignment]
        calls = {c.args[0]: c.args[1] for c in state_mock.set.await_args_list}
        assert calls["macro:cb:monitor_active"]["active"] is True
        assert calls["macro:cb:monitor_active"]["event"] == past_event_in_monitor
        assert calls["macro:cb:block_active"]["active"] is False
        # event is in the past -> get_next_event returns None -> next_event key not set
        assert "macro:cb:next_event" not in calls

    @pytest.mark.asyncio
    async def test_run_loop_warning_logged_on_active_block(self) -> None:
        """Active block -> structlog ``warning`` is invoked (line 222-227)."""
        watcher = _make_watcher()
        present = datetime.now(UTC)
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (present + timedelta(minutes=10)).isoformat(),
                "block_start": (present - timedelta(minutes=5)).isoformat(),
                "monitor_end": (present + timedelta(minutes=70)).isoformat(),
            }
        ]

        warning_mock = MagicMock()
        with patch(
            "services.macro_intelligence.cb_watcher.logger.warning",
            new=warning_mock,
        ):
            with patch(
                "services.macro_intelligence.cb_watcher.asyncio.sleep",
                side_effect=_patch_sleep_to_break_after(1),
            ):
                with pytest.raises(asyncio.CancelledError):
                    await watcher.run_loop()

        # After #270 is fixed, the kwarg name will likely change (currently
        # ``event=`` collides with structlog's positional event slot). Assert
        # only on the log key and presence of scheduled_at, not the kwarg name,
        # so this test stays green when the kwarg is renamed.
        warning_mock.assert_called_once()
        args, kwargs = warning_mock.call_args
        assert args[0] == "cb_block_window_active"
        assert "scheduled_at" in kwargs


# ===========================================================================
# Property-based tests — Hypothesis
# ===========================================================================


class TestPropertyInvariants:
    """Window-membership invariants verified across random offsets.

    These do not target any specific missed line; they harden the boundary
    semantics that the deterministic tests above rely on. Hypothesis settings
    follow the project pattern in ``test_pnl_tracker.py``.
    """

    @given(offset_minutes=st.integers(min_value=-180, max_value=180))
    @hyp_settings(max_examples=50, deadline=None)
    def test_block_window_membership_matches_definition(self, offset_minutes: int) -> None:
        """``is_in_block_window(t)`` is True iff t in [event - 45min, event]."""
        watcher = _make_watcher()
        # Pick a known FOMC event and offset around its scheduled_at
        ev = watcher._events[0]
        event_time = datetime.fromisoformat(ev["scheduled_at"])
        probe = event_time + timedelta(minutes=offset_minutes)

        blocked, _ = watcher.is_in_block_window(probe)
        expected = -BLOCK_WINDOW_MINUTES <= offset_minutes <= 0
        assert blocked is expected, (
            f"offset={offset_minutes}min: expected blocked={expected}, got {blocked}"
        )

    @given(offset_minutes=st.integers(min_value=-180, max_value=180))
    @hyp_settings(max_examples=50, deadline=None)
    def test_monitor_window_membership_matches_definition(self, offset_minutes: int) -> None:
        """``is_in_monitor_window(t)`` is True iff t in [event, event + 60min]."""
        watcher = _make_watcher()
        ev = watcher._events[0]
        event_time = datetime.fromisoformat(ev["scheduled_at"])
        probe = event_time + timedelta(minutes=offset_minutes)

        monitoring, _ = watcher.is_in_monitor_window(probe)
        expected = 0 <= offset_minutes <= MONITOR_WINDOW_MINUTES
        assert monitoring is expected, (
            f"offset={offset_minutes}min: expected monitoring={expected}, got {monitoring}"
        )

    @given(
        future_days=st.integers(min_value=1, max_value=400),
        n_events=st.integers(min_value=1, max_value=10),
    )
    @hyp_settings(max_examples=30, deadline=None)
    @pytest.mark.asyncio
    async def test_get_next_event_strictly_after_now(self, future_days: int, n_events: int) -> None:
        """For all e returned by ``get_next_event``, e.scheduled_at > now."""
        watcher = _make_watcher()
        now = datetime.now(UTC)
        # Build a fan of future events of varying horizons
        watcher._events = [
            {
                "institution": "FED",
                "event_type": "rate_decision",
                "scheduled_at": (now + timedelta(days=future_days + i)).isoformat(),
                "block_start": (now + timedelta(days=future_days + i, minutes=-45)).isoformat(),
                "monitor_end": (now + timedelta(days=future_days + i, minutes=60)).isoformat(),
            }
            for i in range(n_events)
        ]
        nxt = await watcher.get_next_event()
        assert nxt is not None
        assert datetime.fromisoformat(nxt["scheduled_at"]) > now
        # And it must be the soonest of the set (monotone selection)
        expected_soonest = min(datetime.fromisoformat(e["scheduled_at"]) for e in watcher._events)
        assert datetime.fromisoformat(nxt["scheduled_at"]) == expected_soonest
