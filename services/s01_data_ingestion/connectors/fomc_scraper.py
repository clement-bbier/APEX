"""FOMC calendar scraper — fetches Federal Reserve meeting dates.

Scrapes the official Fed FOMC calendar page to extract meeting dates,
statement times, minutes release dates, and press conference times.

References:
    Lucca & Moench (2015) JF — "The Pre-FOMC Announcement Drift"
    Bernanke & Kuttner (2005) JF — "What Explains the Stock Market's
        Reaction to Federal Reserve Policy?"
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog
from bs4 import BeautifulSoup, Tag

from core.models.data import EconomicEvent
from services.s01_data_ingestion.connectors.calendar_base import CalendarConnector

logger = structlog.get_logger(__name__)

_FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_REQUEST_TIMEOUT = 30.0

# Typical FOMC times (UTC):
# Statement release: 18:00 UTC (14:00 ET)
# Press conference: 18:30 UTC (14:30 ET)
# Minutes release: 18:00 UTC (14:00 ET), ~3 weeks after meeting
_STATEMENT_HOUR = 18
_STATEMENT_MINUTE = 0
_PRESS_CONF_HOUR = 18
_PRESS_CONF_MINUTE = 30
_MINUTES_HOUR = 18
_MINUTES_MINUTE = 0

# Month name → number mapping
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
}

# Pattern for date ranges like "January 28-29" or "March 17-18*"
_DATE_RANGE_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})(?:\s*[-\u2013]\s*(\d{1,2}))?\s*\*?",
)

# Pattern for minutes release lines like "May 28, 2025"
_MINUTES_DATE_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})",
)


class FOMCFetchError(Exception):
    """Raised when FOMC calendar scraping fails."""


class FOMCScraper(CalendarConnector):
    """Scrapes the Federal Reserve FOMC calendar page.

    Extracts meeting dates, statement release times, press conference
    indicators, and minutes release dates from the official Fed HTML.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "fomc_scraper"

    async def fetch_events(
        self,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[EconomicEvent]]:
        """Yield batches of FOMC calendar events.

        Args:
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`EconomicEvent` for FOMC meetings.
        """
        html = await self._fetch_html()
        events = self._parse_events(html, start, end)
        if events:
            yield events

    async def _fetch_html(self) -> str:
        """Download the FOMC calendar page."""
        if self._client is not None:
            resp = await self._client.get(
                _FOMC_CALENDAR_URL,
                timeout=_REQUEST_TIMEOUT,
            )
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _FOMC_CALENDAR_URL,
                    timeout=_REQUEST_TIMEOUT,
                )
        if resp.status_code != 200:
            msg = f"FOMC calendar HTTP {resp.status_code}"
            raise FOMCFetchError(msg)
        return resp.text

    def _parse_events(
        self,
        html: str,
        start: datetime,
        end: datetime,
    ) -> list[EconomicEvent]:
        """Parse FOMC meeting events from the calendar HTML.

        The Fed page organises events by year in panels. Each panel has
        a year header and rows listing meeting dates, notation indicators
        (* for press conference, notation for video), and minutes dates.
        """
        soup = BeautifulSoup(html, "html.parser")
        events: list[EconomicEvent] = []

        # The page uses div.panel with year headers and meeting rows.
        # Each year section has class "panel panel-default".
        found_panels = soup.find_all("div", class_="panel")
        panel_tags: list[Tag] = [
            p for p in found_panels if isinstance(p, Tag)
        ]
        if not panel_tags:
            # Fallback: treat the whole document as a single panel
            panel_tags = [soup]

        for panel in panel_tags:
            year = self._extract_year(panel)
            if year is None:
                continue
            # Quick year-level filter
            if year < start.year - 1 or year > end.year + 1:
                continue

            self._parse_panel_events(panel, year, start, end, events)

        if not events:
            logger.warning("fomc_no_events_parsed", html_length=len(html))

        logger.info(
            "fomc_events_parsed",
            count=len(events),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return events

    def _extract_year(self, panel: Tag) -> int | None:
        """Extract year from a panel header."""
        heading = panel.find(class_="panel-heading")
        if heading is None:
            heading = panel.find(["h4", "h3", "h5"])
        if heading is None:
            return None
        text = heading.get_text(strip=True)
        m = re.search(r"(\d{4})", text)
        return int(m.group(1)) if m else None

    def _parse_panel_events(
        self,
        panel: Tag,
        year: int,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Parse meeting rows from a single year panel."""
        # Find all month/date entries in the panel
        rows = panel.find_all("div", class_="fomc-meeting")
        if not rows:
            # Alternative: look for rows in table or other structure
            rows = panel.find_all("tr")

        for row in rows:
            text = row.get_text(" ", strip=True)
            if not text:
                continue
            self._parse_meeting_row(text, year, start, end, events)

    def _parse_meeting_row(
        self,
        text: str,
        year: int,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Parse a single meeting row text into EconomicEvent(s)."""
        # Try to match date range pattern: "January 28-29"
        match = _DATE_RANGE_RE.search(text)
        if not match:
            return

        month_name = match.group(1).lower()
        month = _MONTH_MAP.get(month_name)
        if month is None:
            return

        day_start = int(match.group(2))
        day_end = int(match.group(3)) if match.group(3) else day_start

        # Use the last day of the meeting for the statement date
        meeting_date = day_end

        # Check for unscheduled / notation meeting (typically marked "unscheduled")
        lower_text = text.lower()
        if "unscheduled" in lower_text or "notation" in lower_text:
            return

        # Statement event
        stmt_time = datetime(
            year,
            month,
            meeting_date,
            _STATEMENT_HOUR,
            _STATEMENT_MINUTE,
            tzinfo=UTC,
        )
        if start <= stmt_time < end:
            events.append(
                EconomicEvent(
                    event_type="fomc_statement",
                    scheduled_time=stmt_time,
                    impact_score=3,
                    source="fomc_scraper",
                )
            )

        # Press conference — indicated by asterisk (*) in the text
        has_press_conf = "*" in text
        if has_press_conf:
            pc_time = datetime(
                year,
                month,
                meeting_date,
                _PRESS_CONF_HOUR,
                _PRESS_CONF_MINUTE,
                tzinfo=UTC,
            )
            if start <= pc_time < end:
                events.append(
                    EconomicEvent(
                        event_type="fomc_press_conference",
                        scheduled_time=pc_time,
                        impact_score=3,
                        source="fomc_scraper",
                    )
                )

        # Minutes release — look for "Minutes released" or a date after the meeting
        minutes_match = _MINUTES_DATE_RE.search(text[match.end() :])
        if minutes_match:
            min_month_name = minutes_match.group(1).lower()
            min_month = _MONTH_MAP.get(min_month_name)
            if min_month is not None:
                min_day = int(minutes_match.group(2))
                min_year = int(minutes_match.group(3))
                min_time = datetime(
                    min_year,
                    min_month,
                    min_day,
                    _MINUTES_HOUR,
                    _MINUTES_MINUTE,
                    tzinfo=UTC,
                )
                if start <= min_time < end:
                    events.append(
                        EconomicEvent(
                            event_type="fomc_minutes",
                            scheduled_time=min_time,
                            impact_score=3,
                            source="fomc_scraper",
                        )
                    )
