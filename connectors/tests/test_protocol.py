"""Protocol conformance tests — type-level only, no live calls."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest
from pydantic import SecretStr, ValidationError

from connectors.alpaca import AlpacaConfig, AlpacaConnector
from connectors.ibkr import IBKRConfig, IBKRConnector
from connectors.polygon import PolygonConfig, PolygonConnector
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


def _alpaca() -> AlpacaConnector:
    return AlpacaConnector(AlpacaConfig(api_key=SecretStr("x"), api_secret=SecretStr("y")))


def _ibkr() -> IBKRConnector:
    return IBKRConnector(IBKRConfig())


def _polygon() -> PolygonConnector:
    return PolygonConnector(PolygonConfig(api_key=SecretStr("x")))


def test_alpaca_is_broker_provider() -> None:
    assert isinstance(_alpaca(), BrokerProvider)
    assert isinstance(_alpaca(), MarketDataProvider)
    assert isinstance(_alpaca(), ExecutionProvider)


def test_ibkr_is_broker_provider() -> None:
    assert isinstance(_ibkr(), BrokerProvider)
    assert isinstance(_ibkr(), MarketDataProvider)
    assert isinstance(_ibkr(), ExecutionProvider)


def test_polygon_is_market_data_only() -> None:
    mkt = _polygon()
    assert isinstance(mkt, MarketDataProvider)
    # Must NOT satisfy ExecutionProvider -- Polygon has no trading API.
    assert not isinstance(mkt, ExecutionProvider)
    assert not isinstance(mkt, BrokerProvider)


def test_types_are_frozen() -> None:
    tick = Tick(
        symbol="AAPL",
        exchange="NASDAQ",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        tick.symbol = "MSFT"


def test_types_hints_resolve() -> None:
    # Sanity-check that the Pydantic models' type hints resolve without error.
    for cls in (Tick, Bar, OrderRequest, OrderStatus, Position, Account):
        hints = get_type_hints(cls)
        assert hints, f"{cls.__name__} has no hints"


def test_order_request_decimal_enforced() -> None:
    req = OrderRequest(
        client_order_id="abc",
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        order_type="market",
    )
    assert req.quantity == Decimal("10")
