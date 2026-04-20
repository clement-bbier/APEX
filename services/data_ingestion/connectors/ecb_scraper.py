"""ECB Governing Council calendar scraper.

Scrapes the official ECB calendar page to extract Governing Council
meeting dates for monetary policy decisions.

References:
    Lucca & Moench (2015) JF — pre-event drift applies to ECB as well
    Altavilla et al. (2019) — "Measuring Euro Area Monetary Policy"
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from core.models.data import EconomicEvent
from services.s01_data_ingestion.connectors.calendar_base import CalendarConnector

logger = structlog.get_logger(__name__)

_ECB_CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
_REQUEST_TIMEOUT = 30.0

# ECB typically announces at 12:15 UTC (13:15 CET) with press conference at 12:45 UTC
_ECB_DECISION_HOUR = 12
_ECB_DECISION_MINUTE = 15
_ECB_PRESS_CONF_HOUR = 12
_ECB_PRESS_CONF_MINUTE = 45

# Month name → number
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

# Pattern: "17 January 2025" or "17 Jan 2025"
_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


def _is_monetary_meeting(row_text: str) -> bool:
    """Detect if an ECB Governing Council row is a monetary policy meeting.

    Monetary meetings explicitly mention "monetary policy".
    Non-monetary meetings are labeled "non-monetary" or "non monetary".
    """
    text_lower = row_text.lower()
    if "non-monetary" in text_lower or "non monetary" in text_lower:
        return False
    if "monetary policy" in text_lower:
        return True
    # Default: assume monetary if it mentions Governing Council
    return "governing council" in text_lower


class ECBCalendarFetchError(Exception):
    """Raised when ECB calendar scraping fails."""


class ECBScraper(CalendarConnector):
    """Scrapes the ECB Governing Council calendar page.

    Extracts meeting dates for monetary policy decisions from the
    official ECB calendar HTML.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "ecb_scraper"

    async def fetch_events(
        self,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[EconomicEvent]]:
        """Yield batches of ECB Governing Council events.

        Args:
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`EconomicEvent` for ECB meetings.
        """
        html = await self._fetch_html()
        events = self._parse_events(html, start, end)
        if events:
            yield events

    async def _fetch_html(self) -> str:
        """Download the ECB calendar page."""
        if self._client is not None:
            resp = await self._client.get(
                _ECB_CALENDAR_URL,
                timeout=_REQUEST_TIMEOUT,
            )
        else:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(
                    _ECB_CALENDAR_URL,
                    timeout=_REQUEST_TIMEOUT,
                )
        if resp.status_code != 200:
            msg = f"ECB calendar HTTP {resp.status_code}"
            raise ECBCalendarFetchError(msg)
        return resp.text

    def _parse_events(
        self,
        html: str,
        start: datetime,
        end: datetime,
    ) -> list[EconomicEvent]:
        """Parse ECB Governing Council meeting events from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        events: list[EconomicEvent] = []

        # The ECB page lists meetings in table rows or definition list items.
        # Look for date patterns in the page content.
        self._extract_from_table(soup, start, end, events)

        if not events:
            # Fallback: scan all text content for date patterns
            self._extract_from_text(soup, start, end, events)

        if not events:
            logger.warning("ecb_no_events_parsed", html_length=len(html))

        logger.info(
            "ecb_events_parsed",
            count=len(events),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return events

    def _extract_from_table(
        self,
        soup: BeautifulSoup,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Extract events from table rows."""
        for row in soup.find_all("tr"):
            text = row.get_text(" ", strip=True)
            is_monetary = _is_monetary_meeting(text)
            self._extract_dates_from_text(text, start, end, events, is_monetary)

    def _extract_from_text(
        self,
        soup: BeautifulSoup,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
    ) -> None:
        """Fallback: extract dates from any text content."""
        for element in soup.find_all(["p", "li", "td", "div", "span"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            lower = text.lower()
            if "governing council" not in lower and "monetary" not in lower:
                continue
            self._extract_dates_from_text(text, start, end, events, is_monetary=True)

    def _extract_dates_from_text(
        self,
        text: str,
        start: datetime,
        end: datetime,
        events: list[EconomicEvent],
        is_monetary: bool,
    ) -> None:
        """Extract date patterns from a text string and create events.

        For monetary policy meetings, emits both a rate decision event and
        a press conference event. For non-monetary meetings, emits a single
        governing council event.
        """
        for match in _DATE_RE.finditer(text):
            day = int(match.group(1))
            month_name = match.group(2).lower()
            month = _MONTH_MAP.get(month_name)
            if month is None:
                continue
            year = int(match.group(3))

            decision_time = datetime(
                year,
                month,
                day,
                _ECB_DECISION_HOUR,
                _ECB_DECISION_MINUTE,
                tzinfo=UTC,
            )
            if not (start <= decision_time < end):
                continue

            # Avoid duplicates (check any event at the same time)
            if any(e.scheduled_time == decision_time for e in events):
                continue

            if is_monetary:
                # Monetary meeting → rate decision + press conference
                events.append(
                    EconomicEvent(
                        event_type="ecb_rate_decision",
                        scheduled_time=decision_time,
                        impact_score=3,
                        source="ecb_scraper",
                    )
                )
                pc_time = datetime(
                    year,
                    month,
                    day,
                    _ECB_PRESS_CONF_HOUR,
                    _ECB_PRESS_CONF_MINUTE,
                    tzinfo=UTC,
                )
                events.append(
                    EconomicEvent(
                        event_type="ecb_press_conference",
                        scheduled_time=pc_time,
                        impact_score=3,
                        source="ecb_scraper",
                    )
                )
            else:
                # Non-monetary Governing Council meeting
                events.append(
                    EconomicEvent(
                        event_type="ecb_governing_council",
                        scheduled_time=decision_time,
                        impact_score=2,
                        source="ecb_scraper",
                    )
                )
