"""Unit tests for FOMCScraper.

Mock strategy: patch httpx.AsyncClient.get to return fixture HTML.
BeautifulSoup parses the real fixture for deterministic tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core.models.data import EconomicEvent
from services.data_ingestion.connectors.fomc_scraper import (
    FOMCFetchError,
    FOMCScraper,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_fomc_html() -> str:
    return (FIXTURES / "fomc_calendar_2024.html").read_text(encoding="utf-8")


def _make_response(html: str, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code, text=html, request=httpx.Request("GET", "http://x")
    )
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────


class TestFOMCScraperConnectorName:
    """Test connector_name property."""

    def test_connector_name(self) -> None:
        scraper = FOMCScraper()
        assert scraper.connector_name == "fomc_scraper"


class TestFOMCScraperParseFixture:
    """Test parsing of fixture HTML."""

    @pytest.fixture
    def html(self) -> str:
        return _load_fomc_html()

    @pytest.fixture
    def scraper(self) -> FOMCScraper:
        return FOMCScraper()

    def test_parse_fixture_html_returns_events(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        assert len(events) > 0
        assert all(isinstance(e, EconomicEvent) for e in events)

    def test_extract_meeting_dates(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        statements = [e for e in events if e.event_type == "fomc_statement"]
        # 2024 fixture has 8 FOMC meetings
        assert len(statements) == 8

    def test_extract_event_types(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        event_types = {e.event_type for e in events}
        assert "fomc_statement" in event_types
        assert "fomc_press_conference" in event_types
        assert "fomc_minutes" in event_types

    def test_press_conference_on_starred_meetings(
        self,
        scraper: FOMCScraper,
        html: str,
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        press_confs = [e for e in events if e.event_type == "fomc_press_conference"]
        # Starred meetings in fixture: Jan, Mar, Jun, Sep, Nov, Dec = 6
        assert len(press_confs) == 6

    def test_all_events_utc_aware(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert e.scheduled_time.tzinfo is not None

    def test_all_events_high_impact(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert e.impact_score == 3

    def test_cross_month_meeting_uses_last_day(self, scraper: FOMCScraper, html: str) -> None:
        """'April 30 - May 1' must produce statement on May 1, not April 30."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        statements = [e for e in events if e.event_type == "fomc_statement"]
        may_stmts = [s for s in statements if s.scheduled_time.month == 5]
        assert len(may_stmts) == 1
        assert may_stmts[0].scheduled_time.day == 1

    def test_date_range_filtering(self, scraper: FOMCScraper, html: str) -> None:
        start = datetime(2024, 6, 1, tzinfo=UTC)
        end = datetime(2024, 7, 1, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert start <= e.scheduled_time < end


class TestFOMCScraperFetch:
    """Test fetch_events HTTP integration."""

    @pytest.mark.asyncio
    async def test_404_raises(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            return_value=_make_response("", status_code=404),
        )
        scraper = FOMCScraper(client=mock_client)
        with pytest.raises(FOMCFetchError, match="HTTP 404"):
            async for _ in scraper.fetch_events(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            ):
                pass
