"""Alpaca Markets connector — paper trading + market data.

Stub only. Phase B Gate 2A will implement the actual methods using the
``alpaca-py`` SDK. This file defines the class shape + config loading +
auth pattern so that orchestration code can type-check against it today.

Free tier: paper trading, real-time equity + crypto data, historical bars.
Limitations: no FX, limited options, limited fundamentals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from connectors.types import (
    Account,
    Bar,
    BarInterval,
    OrderRequest,
    OrderStatus,
    Position,
    Tick,
)

_NOT_IMPLEMENTED_MSG: Final = (
    "AlpacaConnector is a Phase B Gate 2A stub; see connectors/alpaca/README.md"
)


class AlpacaConfig(BaseModel):
    """Static configuration for an Alpaca paper or live account."""

    model_config = ConfigDict(frozen=True)
    api_key: SecretStr
    api_secret: SecretStr
    base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Paper: paper-api.alpaca.markets; Live: api.alpaca.markets",
    )
    data_url: str = Field(default="https://data.alpaca.markets")


class AlpacaConnector:
    """Alpaca implementation of :class:`connectors.protocol.BrokerProvider`."""

    def __init__(self, config: AlpacaConfig) -> None:
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

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_account(self) -> Account:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
