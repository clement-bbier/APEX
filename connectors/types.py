"""Pydantic models for the provider-agnostic connector layer.

All models are frozen (immutable) and use ``Decimal`` for prices/sizes
and timezone-aware UTC datetimes, per APEX code-conventions §2.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

type BarInterval = Literal["1m", "5m", "15m", "1h", "1d"]
type OrderSide = Literal["buy", "sell"]
type OrderType = Literal["market", "limit", "stop", "stop_limit"]
type TimeInForce = Literal["day", "gtc", "ioc", "fok"]
type OrderStatusValue = Literal["pending", "accepted", "filled", "partial", "canceled", "rejected"]


class Tick(BaseModel):
    """Single market-data tick (quote + optional trade print)."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    exchange: str
    ts: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    last_price: Decimal | None = None
    last_size: Decimal | None = None


class Bar(BaseModel):
    """OHLCV bar at a fixed interval."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    ts: datetime
    interval: BarInterval
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    vwap: Decimal | None = None
    trade_count: int | None = None


class OrderRequest(BaseModel):
    """Provider-agnostic order submission envelope."""

    model_config = ConfigDict(frozen=True)
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = "day"


class OrderStatus(BaseModel):
    """Order lifecycle state returned by the broker."""

    model_config = ConfigDict(frozen=True)
    broker_order_id: str
    client_order_id: str
    status: OrderStatusValue
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    submitted_at: datetime
    updated_at: datetime


class Position(BaseModel):
    """Open position from the broker's current book."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    unrealized_pnl: Decimal
    market_value: Decimal


class Account(BaseModel):
    """Account-level financial snapshot."""

    model_config = ConfigDict(frozen=True)
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    currency: str = "USD"
