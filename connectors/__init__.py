"""APEX market-data and execution provider abstractions.

This package defines a Protocol-based boundary for every external
broker/data vendor. Concrete connectors live in ``connectors/alpaca/``,
``connectors/ibkr/``, and ``connectors/polygon/``.

Phase B Gate 2A will replace the ``NotImplementedError`` stubs with
real SDK calls.
"""

from connectors.protocol import (
    BrokerProvider,
    ExecutionProvider,
    MarketDataProvider,
)
from connectors.types import (
    Account,
    Bar,
    OrderRequest,
    OrderStatus,
    Position,
    Tick,
)

__all__ = [
    "Account",
    "Bar",
    "BrokerProvider",
    "ExecutionProvider",
    "MarketDataProvider",
    "OrderRequest",
    "OrderStatus",
    "Position",
    "Tick",
]
