"""Unit tests for ECBScraper.

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
from services.data_ingestion.connectors.ecb_scraper import (
    ECBCalendarFetchError,
    ECBScraper,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_ecb_html() -> str:
    return (FIXTURES / "ecb_calendar_2024.html").read_text(encoding="utf-8")


def _make_response(html: str, status_code: int = 200) -> httpx.Response:
    resp = httpx.Response(
        status_code=status_code, text=html, request=httpx.Request("GET", "http://x")
    )
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────


class TestECBScraperConnectorName:
    def test_connector_name(self) -> None:
        scraper = ECBScraper()
        assert scraper.connector_name == "ecb_scraper"


class TestECBScraperParseFixture:
    @pytest.fixture
    def html(self) -> str:
        return _load_ecb_html()

    @pytest.fixture
    def scraper(self) -> ECBScraper:
        return ECBScraper()

    def test_parse_fixture_html_returns_events(self, scraper: ECBScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        assert len(events) > 0
        assert all(isinstance(e, EconomicEvent) for e in events)

    def test_extract_governing_council_dates(self, scraper: ECBScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        # 7 monetary meetings × 2 events + 1 non-monetary × 1 event = 15
        assert len(events) == 15

    def test_monetary_meetings_emit_two_events(self, scraper: ECBScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        rate_decisions = [e for e in events if e.event_type == "ecb_rate_decision"]
        press_confs = [e for e in events if e.event_type == "ecb_press_conference"]
        assert len(rate_decisions) == 7
        assert len(press_confs) == 7

    def test_non_monetary_excluded_from_rate_decision(
        self,
        scraper: ECBScraper,
        html: str,
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        gc_only = [e for e in events if e.event_type == "ecb_governing_council"]
        # Only 1 non-monetary GC meeting in the fixture (July 17)
        assert len(gc_only) == 1
        assert gc_only[0].impact_score == 2

    def test_date_range_filtering(self, scraper: ECBScraper, html: str) -> None:
        start = datetime(2024, 6, 1, tzinfo=UTC)
        end = datetime(2024, 7, 1, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert start <= e.scheduled_time < end

    def test_all_events_utc_aware(self, scraper: ECBScraper, html: str) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        events = scraper._parse_events(html, start, end)
        for e in events:
            assert e.scheduled_time.tzinfo is not None


class TestECBScraperFetch:
    @pytest.mark.asyncio
    async def test_404_raises(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            return_value=_make_response("", status_code=404),
        )
        scraper = ECBScraper(client=mock_client)
        with pytest.raises(ECBCalendarFetchError, match="HTTP 404"):
            async for _ in scraper.fetch_events(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            ):
                pass
