"""Integration test: Alpaca backfill pipeline (network-dependent).

Requires:
    - APEX_NETWORK_TESTS=1
    - Valid ALPACA_API_KEY and ALPACA_SECRET_KEY in environment
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("APEX_NETWORK_TESTS") != "1",
        reason="APEX_NETWORK_TESTS != 1",
    ),
    pytest.mark.skipif(
        not os.environ.get("ALPACA_API_KEY"),
        reason="ALPACA_API_KEY not set",
    ),
]


@pytest.mark.asyncio
async def test_alpaca_fetch_aapl_bars() -> None:
    """Fetch 1 day of AAPL 1m bars from Alpaca and verify structure."""
    from datetime import UTC, datetime

    from core.config import Settings
    from core.models.data import Bar, BarSize
    from services.s01_data_ingestion.connectors.alpaca_historical import (
        AlpacaHistoricalConnector,
    )

    settings = Settings()
    connector = AlpacaHistoricalConnector(settings)

    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 3, tzinfo=UTC)

    all_bars: list[Bar] = []
    async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
        all_bars.extend(batch)

    assert len(all_bars) > 0
    assert all(isinstance(b, Bar) for b in all_bars)
    assert all(b.open > 0 for b in all_bars)
