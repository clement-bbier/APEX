"""Integration test for Yahoo Finance backfill pipeline.

Requires network access (Yahoo Finance is free, no API key needed).
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import Bar, BarSize
from services.s01_data_ingestion.connectors.yahoo_historical import (
    YahooHistoricalConnector,
)

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
class TestYahooBackfillIntegration:
    """Integration tests that download real data from Yahoo Finance."""

    @pytest.mark.asyncio
    async def test_fetch_one_month_spx_daily(self) -> None:
        """Download ~1 month of ^GSPC daily bars from Yahoo Finance."""
        connector = YahooHistoricalConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 2, 1, tzinfo=UTC)

        all_bars: list[Bar] = []
        async for batch in connector.fetch_bars("^GSPC", BarSize.D1, start, end):
            all_bars.extend(batch)

        # ~21 trading days in January 2024
        assert len(all_bars) >= 19
        assert len(all_bars) <= 23
        assert all(isinstance(b, Bar) for b in all_bars)
        assert all(b.bar_size == BarSize.D1 for b in all_bars)

    @pytest.mark.asyncio
    async def test_fetch_bars_valid_ohlcv(self) -> None:
        """Verify OHLCV data integrity: high >= low, volume >= 0."""
        connector = YahooHistoricalConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 2, 1, tzinfo=UTC)

        async for batch in connector.fetch_bars("^GSPC", BarSize.D1, start, end):
            for bar in batch:
                assert bar.high >= bar.low
                assert bar.volume >= 0
                assert bar.open > 0
                assert bar.close > 0
            break  # one batch is enough for validation
