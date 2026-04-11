"""Integration test for SEC EDGAR fundamentals connector.

Requires network access. Marked with @pytest.mark.integration and
@pytest.mark.network. Downloads real data from SEC EDGAR APIs.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import FundamentalPoint

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
class TestEDGARLiveIntegration:
    """Integration tests that download real data from SEC EDGAR."""

    @pytest.mark.asyncio
    async def test_fetch_aapl_fundamentals(self) -> None:
        """Fetch AAPL fundamentals from SEC EDGAR (real network call)."""
        from services.s01_data_ingestion.connectors.edgar_connector import EDGARConnector

        conn = EDGARConnector(user_agent="APEX/CashMachine test@example.com")
        all_points: list[FundamentalPoint] = []
        async for batch in conn.fetch_fundamentals(
            "AAPL",
            ["10-K"],
            datetime(2022, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        ):
            all_points.extend(batch)

        assert len(all_points) > 0
        metric_names = {p.metric_name for p in all_points}
        assert "revenue" in metric_names
        assert "net_income" in metric_names

    @pytest.mark.asyncio
    async def test_ticker_to_cik_resolution(self) -> None:
        """Resolve real ticker to CIK via SEC EDGAR."""
        from services.s01_data_ingestion.connectors.edgar_connector import EDGARConnector

        conn = EDGARConnector(user_agent="APEX/CashMachine test@example.com")
        cik = await conn.ticker_to_cik("AAPL")
        assert cik == 320193

    @pytest.mark.asyncio
    async def test_fetch_filings_list(self) -> None:
        """Fetch real filing list for AAPL."""
        from services.s01_data_ingestion.connectors.edgar_connector import EDGARConnector

        conn = EDGARConnector(user_agent="APEX/CashMachine test@example.com")
        filings = await conn.fetch_filings(
            "AAPL",
            ["10-K", "10-Q"],
            datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert len(filings) > 0
        forms = {f["form"] for f in filings}
        assert "10-K" in forms or "10-Q" in forms
