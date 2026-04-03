"""Tick data models for APEX Trading System.

Defines RawTick and NormalizedTick Pydantic v2 models used throughout the system.
All monetary values use Python Decimal for precision.
All timestamps are UTC milliseconds.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Market(StrEnum):
    """Supported trading markets."""

    CRYPTO = "crypto"
    EQUITY = "equity"


class TradeSide(StrEnum):
    """Trade side: buy or sell aggressor."""

    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class Session(StrEnum):
    """Trading session context."""

    US_PRIME = "us_prime"  # 09:30-10:30 ET and 15:00-16:00 ET
    US_NORMAL = "us_normal"  # Regular US market hours outside prime windows
    AFTER_HOURS = "after_hours"  # Pre/post US market
    LONDON = "london"  # 08:00-10:00 UTC
    ASIAN = "asian"  # 00:00-02:00 UTC
    WEEKEND = "weekend"  # Saturday/Sunday crypto
    UNKNOWN = "unknown"


class RawTick(BaseModel):
    """Raw tick data as received from a broker/exchange.

    Immutable Pydantic v2 model representing the unprocessed feed event.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading symbol, e.g. BTCUSDT or AAPL")
    market: Market = Field(..., description="Market type: crypto or equity")
    timestamp_ms: int = Field(..., gt=0, description="Event timestamp UTC milliseconds")
    price: Decimal = Field(..., gt=Decimal("0"), description="Trade price")
    volume: Decimal = Field(..., ge=Decimal("0"), description="Trade volume")
    side: TradeSide = Field(default=TradeSide.UNKNOWN, description="Aggressor side")
    bid: Decimal | None = Field(default=None, description="Best bid price")
    ask: Decimal | None = Field(default=None, description="Best ask price")
    raw_data: dict | None = Field(default=None, description="Original broker payload")

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_uppercase(cls, v: str) -> str:
        """Ensure symbol is uppercase."""
        return v.upper()

    @field_validator("price", "volume", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal:
        """Convert numeric types to Decimal."""
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v  # type: ignore[return-value]


class NormalizedTick(BaseModel):
    """Normalized tick enriched with microstructure and session context.

    Created by the normalizer from a RawTick.
    Immutable - transformations always produce new instances.
    Published on ZMQ topic: tick.{market}.{SYMBOL}
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    symbol: str = Field(..., description="Uppercase trading symbol")
    market: Market = Field(..., description="Market type")
    timestamp_ms: int = Field(..., gt=0, description="UTC milliseconds")

    # Price data
    price: Decimal = Field(..., gt=Decimal("0"))
    volume: Decimal = Field(..., ge=Decimal("0"))
    side: TradeSide = Field(default=TradeSide.UNKNOWN)

    # Order book
    bid: Decimal | None = Field(default=None)
    ask: Decimal | None = Field(default=None)
    spread_bps: Decimal | None = Field(
        default=None,
        description="Bid-ask spread in basis points: (ask-bid)/mid × 10000",
    )

    # Session context
    session: Session = Field(default=Session.UNKNOWN)

    # Source reference
    source_tick: RawTick | None = Field(default=None, description="Parent RawTick for traceability")

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        """Ensure symbol is uppercase."""
        return v.upper()

    @model_validator(mode="after")
    def compute_spread_bps(self) -> NormalizedTick:
        """Compute spread in basis points if bid/ask present and spread not set."""
        # Pydantic frozen models cannot be mutated; spread must be pre-computed
        # This validator serves as a consistency check.
        if self.bid is not None and self.ask is not None and self.spread_bps is None:
            mid = (self.bid + self.ask) / Decimal("2")
            if mid > 0:
                # Use object.__setattr__ because model is frozen
                object.__setattr__(
                    self,
                    "spread_bps",
                    ((self.ask - self.bid) / mid * Decimal("10000")).quantize(Decimal("0.01")),
                )
        return self

    @property
    def mid_price(self) -> Decimal | None:
        """Compute mid price from bid/ask."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / Decimal("2")
        return None
