"""Integration test for Binance backfill pipeline.

Requires network access and optionally TimescaleDB.
Marked with @pytest.mark.integration and @pytest.mark.network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from core.models.data import Bar, BarSize
from services.data_ingestion.connectors.binance_historical import (
    BinanceHistoricalConnector,
)
from services.data_ingestion.normalizers.binance_bar import BinanceBarNormalizer

_HAS_NETWORK = os.environ.get("APEX_NETWORK_TESTS", "0") == "1"
_HAS_TIMESCALE = bool(os.environ.get("TIMESCALE_HOST"))

skip_no_network = pytest.mark.skipif(not _HAS_NETWORK, reason="APEX_NETWORK_TESTS not set")


@pytest.mark.integration
@pytest.mark.network
@skip_no_network
class TestBinanceBackfillIntegration:
    """Integration tests that download real data from Binance."""

    @pytest.mark.asyncio
    async def test_fetch_one_day_klines(self) -> None:
        """Download one day of 1m klines from Binance public archive."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 2, tzinfo=UTC)

        all_bars: list[Bar] = []
        async for batch in connector.fetch_bars("BTCUSDT", BarSize.M1, start, end):
            all_bars.extend(batch)

        # 1440 minutes in a day
        assert len(all_bars) == 1440
        assert all(isinstance(b, Bar) for b in all_bars)
        assert all(b.bar_size == BarSize.M1 for b in all_bars)

    @pytest.mark.asyncio
    async def test_fetch_bars_returns_valid_ohlcv(self) -> None:
        """Verify OHLCV data integrity: high >= low, volume >= 0."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 2, tzinfo=UTC)

        async for batch in connector.fetch_bars("BTCUSDT", BarSize.M1, start, end):
            for bar in batch:
                assert bar.high >= bar.low, f"high < low at {bar.timestamp}"
                assert bar.volume >= 0, f"negative volume at {bar.timestamp}"
            break  # Only check first batch
