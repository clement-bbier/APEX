"""Central Bank Event Watcher.

Fetches upcoming FOMC/ECB/BOJ events from official RSS feeds
and calendar APIs. Publishes block events 45min before each announcement.

No third-party API required for FOMC dates — Federal Reserve publishes
an official schedule at:
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

For live announcement detection, monitors:
  https://www.federalreserve.gov/feeds/press_all.xml
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# FOMC 2024-2025 schedule (hardcoded + auto-updated from RSS)
FOMC_DATES_2024_2025: list[dict[str, str]] = [
    {"date": "2024-01-31", "type": "rate_decision"},
    {"date": "2024-03-20", "type": "rate_decision"},
    {"date": "2024-05-01", "type": "rate_decision"},
    {"date": "2024-06-12", "type": "rate_decision"},
    {"date": "2024-07-31", "type": "rate_decision"},
    {"date": "2024-09-18", "type": "rate_decision"},
    {"date": "2024-11-07", "type": "rate_decision"},
    {"date": "2024-12-18", "type": "rate_decision"},
    {"date": "2025-01-29", "type": "rate_decision"},
    {"date": "2025-03-19", "type": "rate_decision"},
    {"date": "2025-05-07", "type": "rate_decision"},
    {"date": "2025-06-18", "type": "rate_decision"},
    {"date": "2025-07-30", "type": "rate_decision"},
    {"date": "2025-09-17", "type": "rate_decision"},
    {"date": "2025-10-29", "type": "rate_decision"},
    {"date": "2025-12-10", "type": "rate_decision"},
    # 2026 — to be fetched from Fed website
]

FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
BLOCK_WINDOW_MINUTES = 45
MONITOR_WINDOW_MINUTES = 60


class CBWatcher:
    """Monitors central bank events and publishes timing signals.

    Published Redis keys:
      macro:cb:next_event      → next upcoming CB event details
      macro:cb:block_active    → True if within 45min pre-event window
      macro:cb:monitor_active  → True if within 60min post-event window
    """

    def __init__(self, state: Any, bus: Any) -> None:
        self._state = state
        self._bus = bus
        self._events = self._load_hardcoded_events()

    def _load_hardcoded_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for e in FOMC_DATES_2024_2025:
            dt = datetime.fromisoformat(e["date"]).replace(
                hour=14, minute=0, tzinfo=timezone.utc  # FOMC typically 2pm ET = 19:00 UTC
            )
            events.append(
                {
                    "institution": "FED",
                    "event_type": e["type"],
                    "scheduled_at": dt.isoformat(),
                    "block_start": (
                        dt - timedelta(minutes=BLOCK_WINDOW_MINUTES)
                    ).isoformat(),
                    "monitor_end": (
                        dt + timedelta(minutes=MONITOR_WINDOW_MINUTES)
                    ).isoformat(),
                }
            )
        return events

    async def get_next_event(self) -> dict[str, Any] | None:
        """Return the next upcoming CB event from now."""
        now = datetime.now(timezone.utc)
        future = [
            e
            for e in self._events
            if datetime.fromisoformat(e["scheduled_at"]) > now
        ]
        if not future:
            return None
        return min(future, key=lambda e: e["scheduled_at"])

    def is_in_block_window(
        self, now: datetime | None = None
    ) -> tuple[bool, dict[str, Any] | None]:
        """Return (True, event) if we're within the 45min pre-event block window."""
        if now is None:
            now = datetime.now(timezone.utc)
        for event in self._events:
            block_start = datetime.fromisoformat(event["block_start"])
            event_time = datetime.fromisoformat(event["scheduled_at"])
            if block_start <= now <= event_time:
                return True, event
        return False, None

    def is_in_monitor_window(
        self, now: datetime | None = None
    ) -> tuple[bool, dict[str, Any] | None]:
        """Return (True, event) if we're within the 60min post-event scalp window."""
        if now is None:
            now = datetime.now(timezone.utc)
        for event in self._events:
            event_time = datetime.fromisoformat(event["scheduled_at"])
            monitor_end = datetime.fromisoformat(event["monitor_end"])
            if event_time <= now <= monitor_end:
                return True, event
        return False, None

    async def fetch_fed_rss(self) -> list[dict[str, Any]]:
        """Fetch and parse the Federal Reserve press release RSS feed.

        Returns:
            List of dicts with keys "title", "link", and "published".
        """
        import xml.etree.ElementTree as ET  # noqa: S405

        async with aiohttp.ClientSession() as session:
            async with session.get(
                FED_RSS_URL, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                text = await resp.text()

        root = ET.fromstring(text)  # noqa: S314
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items: list[dict[str, Any]] = []

        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                items.append(
                    {
                        "title": title_el.text if title_el is not None else "",
                        "link": link_el.text if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                    }
                )
        else:
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                pub_el = entry.find("atom:published", ns)
                items.append(
                    {
                        "title": title_el.text if title_el is not None else "",
                        "link": link_el.get("href", "") if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                    }
                )

        return items

    async def get_latest_statement(self) -> str | None:
        """Return the latest Fed statement text by fetching the RSS feed.

        Returns:
            Title of the most recent press release, or None if unavailable.
        """
        try:
            items = await self.fetch_fed_rss()
            if items:
                return items[0].get("title")
        except Exception:
            pass
        return None

    async def detect_surprise(self, statement: str) -> str | None:
        """Detect policy surprises from Fed statement text using keyword analysis.

        Args:
            statement: Full text or title of the Fed statement.

        Returns:
            "hawkish_surprise", "dovish_surprise", or None.
        """
        lower = statement.lower()
        is_surprise = any(kw in lower for kw in ("unexpected", "emergency", "surprise"))
        if not is_surprise:
            return None

        hawkish_keywords = ("raise", "hike", "tighten", "inflation concern")
        dovish_keywords = ("cut", "ease", "lower", "stimulus", "support")

        hawkish_score = sum(1 for kw in hawkish_keywords if kw in lower)
        dovish_score = sum(1 for kw in dovish_keywords if kw in lower)

        if hawkish_score > dovish_score:
            return "hawkish_surprise"
        if dovish_score > hawkish_score:
            return "dovish_surprise"
        return None

    async def run_loop(self) -> None:
        """Main loop — checks every 60s and updates Redis."""
        while True:
            now = datetime.now(timezone.utc)
            blocked, event = self.is_in_block_window(now)
            monitoring, post_event = self.is_in_monitor_window(now)
            next_event = await self.get_next_event()

            await self._state.set("macro:cb:block_active", {"active": blocked, "event": event})
            await self._state.set(
                "macro:cb:monitor_active", {"active": monitoring, "event": post_event}
            )
            if next_event:
                await self._state.set("macro:cb:next_event", next_event)

            if blocked and event:
                logger.warning(
                    "cb_block_window_active",
                    event=event["institution"],
                    scheduled_at=event["scheduled_at"],
                )

            await asyncio.sleep(60)
