"""Integration test for ECB calendar scraper.

Requires network access to scrape the ECB Governing Council calendar.
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
class TestECBScraperLive:
    """Integration tests that scrape the real ECB calendar."""

    @pytest.mark.asyncio
    async def test_fetch_ecb_events(self) -> None:
        """Scrape ECB calendar and verify events are returned."""
        from services.s01_data_ingestion.connectors.ecb_scraper import ECBScraper

        scraper = ECBScraper()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)

        all_events: list[EconomicEvent] = []
        async for batch in scraper.fetch_events(start, end):
            all_events.extend(batch)

        assert len(all_events) >= 4
        assert all(isinstance(e, EconomicEvent) for e in all_events)
        assert all(e.event_type == "ecb_governing_council" for e in all_events)
        assert all(e.scheduled_time.tzinfo is not None for e in all_events)
