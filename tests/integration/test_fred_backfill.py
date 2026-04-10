"""Integration test for FRED macro backfill pipeline.

Requires network access AND a valid FRED_API_KEY.
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import MacroPoint

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"
_HAS_FRED_KEY = bool(os.environ.get("FRED_API_KEY", ""))

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")
skip_no_fred = pytest.mark.skipif(not _HAS_FRED_KEY, reason="FRED_API_KEY not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
@skip_no_fred
class TestFREDBackfillIntegration:
    """Integration tests that download real data from FRED."""

    @pytest.mark.asyncio
    async def test_fetch_fedfunds_one_year(self) -> None:
        """Download ~1 year of FEDFUNDS from FRED."""
        from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

        connector = FREDConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points: list[MacroPoint] = []
        async for batch in connector.fetch_series("FEDFUNDS", start, end):
            all_points.extend(batch)

        assert len(all_points) >= 10
        assert all(isinstance(p, MacroPoint) for p in all_points)
        assert all(p.series_id == "FEDFUNDS" for p in all_points)
        assert all(p.timestamp.tzinfo is not None for p in all_points)

    @pytest.mark.asyncio
    async def test_fetch_metadata_fedfunds(self) -> None:
        """Fetch FEDFUNDS metadata from FRED."""
        from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

        connector = FREDConnector()
        meta = await connector.fetch_metadata("FEDFUNDS")

        assert meta.series_id == "FEDFUNDS"
        assert meta.source == "FRED"
        assert meta.name  # non-empty
