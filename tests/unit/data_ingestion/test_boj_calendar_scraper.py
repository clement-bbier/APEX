"""Unit tests for BoJCalendarScraper.

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
from services.s01_data_ingestion.connectors.boj_calendar_scraper import (
    BoJCalendarFetchError,
    BoJCalendarScraper,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_boj_html() -> str:
    return (FIXTURES / "boj_calendar_2024.html").read_text(encoding="utf-8")


def _make_response(html: str, status_code: int = 200) -> httpx.Response:
    resp = httpx.Response(
        status_code=status_code, text=html, request=httpx.Request("GET", "http://x")
    )
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────


class TestBoJScraperConnectorName:
    def test_connector_name(self) -> None:
        scraper = BoJCalendarScraper()
        assert scraper.connector_name == "boj_calendar_scraper"


class TestBoJScraperParseFixture:
    @pytest.fixture
    def html(self) -> str:
        return _load_boj_html()

    @pytest.fixture
    def scraper(self) -> BoJCalendarScraper:
        return BoJCalendarScraper()

    def test_parse_fixture_html_returns_events(
        self,
        scraper: BoJCalendarScraper,
        html: str,
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        assert len(events) > 0
        assert all(isinstance(e, EconomicEvent) for e in events)

    def test_extract_mpm_dates(self, scraper: BoJCalendarScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        # Synthetic fixture has 8 BoJ MPM meetings
        assert len(events) == 8

    def test_all_events_boj_type(self, scraper: BoJCalendarScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert e.event_type == "boj_mpm"
            assert e.impact_score == 3

    def test_date_range_filtering(self, scraper: BoJCalendarScraper, html: str) -> None:
        start = datetime(2024, 6, 1, tzinfo=UTC)
        end = datetime(2024, 7, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert start <= e.scheduled_time < end

    def test_all_events_utc_aware(self, scraper: BoJCalendarScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert e.scheduled_time.tzinfo is not None


class TestBoJScraperFetch:
    @pytest.mark.asyncio
    async def test_404_raises(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            return_value=_make_response("", status_code=404),
        )
        scraper = BoJCalendarScraper(client=mock_client)
        with pytest.raises(BoJCalendarFetchError, match="HTTP 404"):
            async for _ in scraper.fetch_events(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            ):
                pass
