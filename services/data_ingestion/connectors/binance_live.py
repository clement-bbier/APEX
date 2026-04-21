"""Binance live data connector stub.

Placeholder for interface coherence. The actual live streaming is handled
by :mod:`services.data_ingestion.binance_feed` (WebSocket-based).
Full implementation planned for Phase 2.6.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from core.models.data import Bar, BarSize, DbTick
from services.data_ingestion.connectors.base import DataConnector


class BinanceLiveConnector(DataConnector):
    """Stub connector for Binance live data.

    Live streaming uses :class:`BinanceFeed` directly (WebSocket-based).
    This class exists solely for interface coherence with :class:`DataConnector`.
    """

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "binance_live"

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Not implemented — use BinanceFeed for live streaming."""
        raise NotImplementedError(
            "BinanceLiveConnector: stream-based, use binance_feed.py directly. "
            "Full implementation in Phase 2.6"
        )
        # Make the type checker happy: this is unreachable but required
        # for the function to be recognized as an async generator.
        yield []  # pragma: no cover

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Not implemented — use BinanceFeed for live streaming."""
        raise NotImplementedError(
            "BinanceLiveConnector: stream-based, use binance_feed.py directly. "
            "Full implementation in Phase 2.6"
        )
        yield []  # pragma: no cover
