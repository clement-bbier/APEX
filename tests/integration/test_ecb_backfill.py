"""Integration test for ECB macro backfill pipeline.

Requires network access (ECB API is free, no API key needed).
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
@pytest.mark.network
@skip_no_network
class TestECBBackfillIntegration:
    """Integration tests that download real data from ECB."""

    @pytest.mark.asyncio
    async def test_fetch_eurusd_daily(self) -> None:
        """Download ~1 month of EUR/USD daily from ECB."""
        from services.s01_data_ingestion.connectors.ecb_connector import ECBConnector

        connector = ECBConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 2, 1, tzinfo=UTC)

        all_points: list[MacroPoint] = []
        async for batch in connector.fetch_series("EXR/D.USD.EUR.SP00.A", start, end):
            all_points.extend(batch)

        assert len(all_points) >= 15  # ~22 business days
        assert all(isinstance(p, MacroPoint) for p in all_points)
        assert all(p.timestamp.tzinfo is not None for p in all_points)

    @pytest.mark.asyncio
    async def test_fetch_metadata_eurusd(self) -> None:
        """Fetch EUR/USD metadata from ECB."""
        from services.s01_data_ingestion.connectors.ecb_connector import ECBConnector

        connector = ECBConnector()
        meta = await connector.fetch_metadata("EXR/D.USD.EUR.SP00.A")

        assert meta.series_id == "EXR/D.USD.EUR.SP00.A"
        assert meta.source == "ECB"
