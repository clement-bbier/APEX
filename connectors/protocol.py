"""Protocols for market-data and execution providers.

Adapters implementing these Protocols plug into APEX without touching
core/ or services/. The split between ``MarketDataProvider`` and
``ExecutionProvider`` matches the real-world provider landscape:

- Alpaca, IBKR → both (``BrokerProvider``)
- Polygon, Databento → market data only
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from connectors.types import (
    Account,
    Bar,
    BarInterval,
    OrderRequest,
    OrderStatus,
    Position,
    Tick,
)


@runtime_checkable
class MarketDataProvider(Protocol):
    """Abstract market-data provider.

    Implementations: ``AlpacaConnector``, ``IBKRConnector``,
    ``PolygonConnector`` (and, later, ``DatabentoConnector`` for
    tick-level microstructure).
    """

    def subscribe_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Yield live ticks for the requested symbols until cancelled."""
        ...

    def subscribe_bars(self, symbols: list[str], interval: BarInterval) -> AsyncIterator[Bar]:
        """Yield live bars at the requested interval until cancelled."""
        ...

    async def get_historical_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: BarInterval,
    ) -> list[Bar]:
        """Fetch a closed historical [start, end) bar range."""
        ...


@runtime_checkable
class ExecutionProvider(Protocol):
    """Abstract execution provider for paper/live order submission."""

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        """Submit an order. Returns the initial broker state."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel by broker order id. Returns True on acknowledged cancel."""
        ...

    async def get_positions(self) -> list[Position]:
        """Return the current open-position book."""
        ...

    async def get_account(self) -> Account:
        """Return account-level balances and buying power."""
        ...


@runtime_checkable
class BrokerProvider(MarketDataProvider, ExecutionProvider, Protocol):
    """Combined market-data + execution provider.

    Implementations: ``AlpacaConnector`` (paper + live),
    ``IBKRConnector`` (paper + live). Pure data providers like
    ``PolygonConnector`` implement only ``MarketDataProvider``.
    """
