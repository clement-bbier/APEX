"""Interactive Brokers connector — TWS / IB Gateway, multi-asset.

Stub only. Phase B Gate 3 will implement the actual methods using
``ib_insync`` (or ``ibapi`` directly if we drop the wrapper). This file
defines the class shape + config + auth pattern so that orchestration
code can type-check against it today.

Coverage: equities (US + international), FX, futures, options (full
chain), bonds. Paper and live accounts both supported.
Limitations: requires TWS or IB Gateway to be running locally (or
inside a container) and reachable on the configured host/port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

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
    "IBKRConnector is a Phase B Gate 3 stub; see connectors/ibkr/README.md"
)


class IBKRConfig(BaseModel):
    """Static configuration for a TWS or IB Gateway endpoint."""

    model_config = ConfigDict(frozen=True)
    host: str = "127.0.0.1"
    port: int = Field(
        default=7497,
        description="7497 paper TWS, 7496 live TWS, 4002 gateway paper",
    )
    client_id: int = Field(default=1, description="Unique per concurrent TWS session")
    account: str | None = Field(default=None, description="Optional explicit IB account code")
    read_only: bool = Field(
        default=True,
        description="Paper-safe default; set False for live trading",
    )


class IBKRConnector:
    """IBKR implementation of :class:`connectors.protocol.BrokerProvider`."""

    def __init__(self, config: IBKRConfig) -> None:
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
