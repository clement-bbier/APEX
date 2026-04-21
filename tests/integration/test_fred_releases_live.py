"""Integration test for FRED releases connector.

Requires network access AND a valid FRED_API_KEY.
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import EconomicEvent

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"
_HAS_FRED_KEY = bool(os.environ.get("FRED_API_KEY", ""))

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")
skip_no_fred = pytest.mark.skipif(not _HAS_FRED_KEY, reason="FRED_API_KEY not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
@skip_no_fred
class TestFREDReleasesLive:
    """Integration tests that fetch real release dates from FRED."""

    @pytest.mark.asyncio
    async def test_fetch_releases_all_series(self) -> None:
        """Fetch release dates for all priority series."""
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        connector = FREDReleasesConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_events: list[EconomicEvent] = []
        async for batch in connector.fetch_events(start, end):
            all_events.extend(batch)

        assert len(all_events) >= 10
        assert all(isinstance(e, EconomicEvent) for e in all_events)
        assert all(e.scheduled_time.tzinfo is not None for e in all_events)

        event_types = {e.event_type for e in all_events}
        assert "us_data_release_nfp" in event_types
