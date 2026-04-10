"""Integration test for FOMC calendar scraper.

Requires network access to scrape the Federal Reserve FOMC calendar.
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import EconomicEvent

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
class TestFOMCScraperLive:
    """Integration tests that scrape the real Fed FOMC calendar."""

    @pytest.mark.asyncio
    async def test_fetch_fomc_events(self) -> None:
        """Scrape FOMC calendar and verify events are returned."""
        from services.s01_data_ingestion.connectors.fomc_scraper import FOMCScraper

        scraper = FOMCScraper()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)

        all_events: list[EconomicEvent] = []
        async for batch in scraper.fetch_events(start, end):
            all_events.extend(batch)

        assert len(all_events) >= 8
        assert all(isinstance(e, EconomicEvent) for e in all_events)
        assert all(e.scheduled_time.tzinfo is not None for e in all_events)

        event_types = {e.event_type for e in all_events}
        assert "fomc_statement" in event_types
