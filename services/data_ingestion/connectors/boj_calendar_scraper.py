"""Bank of Japan Monetary Policy Meeting calendar scraper.

Scrapes the official BoJ MPM schedule page to extract meeting dates.

References:
    Lucca & Moench (2015) JF — pre-FOMC drift has analogues at BoJ
    Nakamura & Steinsson (2018) AER — "High-Frequency Identification
        of Monetary Non-Neutrality"
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from core.models.data import EconomicEvent
from services.data_ingestion.connectors.calendar_base import CalendarConnector

logger = structlog.get_logger(__name__)

_BOJ_SCHEDULE_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
_REQUEST_TIMEOUT = 30.0

# BoJ announces around 03:00 UTC (12:00 JST), sometimes extends to day 2
_BOJ_ANNOUNCE_HOUR = 3
_BOJ_ANNOUNCE_MINUTE = 0

_MONTH_MAP: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Pattern: "January 23, 24" or "Jan. 23-24" or "March 13, 14, 2025"
_BOJ_DATE_RE = re.compile(
    r"([A-Za-z]+)\.?\s+(\d{1,2})(?:\s*[,\-\u2013]\s*(\d{1,2}))?",
)

# Pattern for standalone year in heading or context
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class BoJCalendarFetchError(Exception):
    """Raised when BoJ calendar scraping fails."""


class BoJCalendarScraper(CalendarConnector):
    """Scrapes the Bank of Japan MPM schedule page.

    Extracts Monetary Policy Meeting dates from the official BoJ HTML.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "boj_calendar_scraper"

    async def fetch_events(
        self,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[EconomicEvent]]:
        """Yield batches of BoJ MPM events.

        Args:
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`EconomicEvent` for BoJ meetings.
        """
        html = await self._fetch_html()
        events = self._parse_events(html, start, end)
        if events:
            yield events

    async def _fetch_html(self) -> str:
        """Download the BoJ MPM schedule page."""
        if self._client is not None:
            resp = await self._client.get(
                _BOJ_SCHEDULE_URL,
                timeout=_REQUEST_TIMEOUT,
            )
        else:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(
                    _BOJ_SCHEDULE_URL,
                    timeout=_REQUEST_TIMEOUT,
                )
        if resp.status_code != 200:
            msg = f"BoJ calendar HTTP {resp.status_code}"
            raise BoJCalendarFetchError(msg)
        return resp.text

    def _parse_events(
        self,
        html: str,
        start: datetime,
        end: datetime,
    ) -> list[EconomicEvent]:
        """Parse BoJ MPM meeting events from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        events: list[EconomicEvent] = []

        # BoJ page typically has tables with meeting dates organised by year.
        # Try table-based extraction first, then fallback to text scanning.
        self._extract_from_tables(soup, start, end, events)

        if not events:
            self._extract_from_text(soup, start, end, events)

        if not events:
            logger.warning("boj_no_events_parsed", html_length=len(html))

        logger.info(
            "boj_events_parsed",
            count=len(events),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return events

    def _extract_from_tables(
        self,
        soup: BeautifulSoup,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Extract meeting dates from table structures."""
        # Find year context from headings or table headers
        current_year: int | None = None

        heading_tags = {"h2", "h3", "h4", "h5", "caption"}
        for element in soup.find_all(["h2", "h3", "h4", "h5", "caption", "tr", "li", "p"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue

            # Update year context from headings
            year_match = _YEAR_RE.search(text)
            tag_name = getattr(element, "name", None)
            if year_match and tag_name in heading_tags:
                current_year = int(year_match.group(1))
                continue

            # If we find a year in the text itself, use it
            if year_match:
                current_year = int(year_match.group(1))

            if current_year is None:
                continue

            self._parse_meeting_text(text, current_year, start, end, events)

    def _extract_from_text(
        self,
        soup: BeautifulSoup,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Fallback: scan all text for meeting date patterns."""
        full_text = soup.get_text(" ", strip=True)
        year_match = _YEAR_RE.search(full_text)
        if year_match is None:
            return
        year = int(year_match.group(1))
        self._parse_meeting_text(full_text, year, start, end, events)

    def _parse_meeting_text(
        self,
        text: str,
        year: int,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Parse meeting date patterns from a text fragment."""
        for match in _BOJ_DATE_RE.finditer(text):
            month_name = match.group(1).lower()
            month = _MONTH_MAP.get(month_name)
            if month is None:
                continue

            day_end = int(match.group(3)) if match.group(3) else int(match.group(2))

            # Use the last day of the meeting for the announcement
            event_time = datetime(
                year,
                month,
                day_end,
                _BOJ_ANNOUNCE_HOUR,
                _BOJ_ANNOUNCE_MINUTE,
                tzinfo=UTC,
            )
            if not (start <= event_time < end):
                continue

            # Avoid duplicates
            if any(e.event_type == "boj_mpm" and e.scheduled_time == event_time for e in events):
                continue

            events.append(
                EconomicEvent(
                    event_type="boj_mpm",
                    scheduled_time=event_time,
                    impact_score=3,
                    source="boj_calendar_scraper",
                )
            )
