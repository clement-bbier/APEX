"""Integration test for BoJ macro backfill pipeline.

Requires network access (BoJ CSVs are public, no API key needed).
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import MacroPoint

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")


@pytest.mark.integration
class TestBoJOffline:
    """Tests that don't need network — BoJ metadata is from a curated registry."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_policy_rate(self) -> None:
        """Fetch BoJ policy rate metadata (no network needed)."""
        from services.data_ingestion.connectors.boj_connector import BoJConnector

        connector = BoJConnector()
        meta = await connector.fetch_metadata("boj_policy_rate")

        assert meta.series_id == "boj_policy_rate"
        assert meta.source == "BOJ"
        assert meta.frequency == "monthly"


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
class TestBoJBackfillIntegration:
    """Integration tests that download real data from BoJ."""

    @pytest.mark.asyncio
    async def test_fetch_policy_rate(self) -> None:
        """Download BoJ policy rate CSV."""
        from services.data_ingestion.connectors.boj_connector import BoJConnector

        connector = BoJConnector()
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points: list[MacroPoint] = []
        async for batch in connector.fetch_series("boj_policy_rate", start, end):
            all_points.extend(batch)

        assert len(all_points) >= 10
        assert all(isinstance(p, MacroPoint) for p in all_points)
