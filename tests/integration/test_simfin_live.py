"""Integration test for SimFin fundamentals connector.

Requires network access AND a valid SIMFIN_API_KEY.
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import FundamentalPoint

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"
_HAS_SIMFIN_KEY = bool(os.environ.get("SIMFIN_API_KEY", ""))

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")
skip_no_simfin = pytest.mark.skipif(not _HAS_SIMFIN_KEY, reason="SIMFIN_API_KEY not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
@skip_no_simfin
class TestSimFinLiveIntegration:
    """Integration tests that download real data from SimFin API."""

    @pytest.mark.asyncio
    async def test_fetch_aapl_financials(self) -> None:
        """Fetch AAPL P&L from SimFin (real network call)."""
        from services.data_ingestion.connectors.simfin_connector import SimFinConnector

        conn = SimFinConnector()
        result = await conn.fetch_financials("AAPL", "PL", "fy")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_aapl_ratios(self) -> None:
        """Fetch AAPL financial ratios from SimFin (real network call)."""
        from services.data_ingestion.connectors.simfin_connector import SimFinConnector

        conn = SimFinConnector()
        result = await conn.fetch_ratios("AAPL")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_fundamentals_generator(self) -> None:
        """Fetch AAPL fundamentals through the full generator interface."""
        from services.data_ingestion.connectors.simfin_connector import SimFinConnector

        conn = SimFinConnector()
        all_points: list[FundamentalPoint] = []
        async for batch in conn.fetch_fundamentals(
            "AAPL",
            ["10-K"],
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        ):
            all_points.extend(batch)

        assert len(all_points) > 0
        metric_names = {p.metric_name for p in all_points}
        assert "revenue" in metric_names or "net_income" in metric_names
