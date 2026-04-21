"""Polygon.io connector — market data only (no execution).

Stub only. Phase B Gate 2A will implement the actual methods using
``polygon-api-client``. Polygon does NOT provide execution — it is used
purely as an alternative / supplementary market-data source (especially
for historical research).

Free "starter" tier: 2y of historical equity bars, end-of-day data,
limited minute-bar rate. Upgrade to paid for real-time ticks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, SecretStr

from connectors.types import Bar, BarInterval, Tick

_NOT_IMPLEMENTED_MSG: Final = (
    "PolygonConnector is a Phase B Gate 2A stub; see connectors/polygon/README.md"
)


class PolygonConfig(BaseModel):
    """Static configuration for Polygon.io REST + websocket endpoints."""

    model_config = ConfigDict(frozen=True)
    api_key: SecretStr
    base_url: str = "https://api.polygon.io"
    websocket_url: str = "wss://socket.polygon.io"


class PolygonConnector:
    """Polygon implementation of :class:`connectors.protocol.MarketDataProvider`.

    Note: does NOT implement ``ExecutionProvider`` — Polygon is a
    market-data vendor only.
    """

    def __init__(self, config: PolygonConfig) -> None:
        self._config = config

    async def subscribe_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
        yield  # pragma: no cover  -- async-generator yield (unreachable)

    async def subscribe_bars(self, symbols: list[str], interval: BarInterval) -> AsyncIterator[Bar]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
        yield  # pragma: no cover  -- async-generator yield (unreachable)

    async def get_historical_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: BarInterval,
    ) -> list[Bar]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
