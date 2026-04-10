"""Universal data models for APEX Trading System TimescaleDB schema.

Defines Pydantic v2 models for all tables in the universal schema:
assets, bars, ticks, order_book_snapshots, macro_series, fundamentals,
corporate_events, economic_events, data_quality_log, ingestion_runs.

All monetary values use Python Decimal for precision.
All timestamps are UTC-aware datetime.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(v: object) -> object:
    """If *v* is a naive datetime, assume UTC and attach tzinfo."""
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v


# ── Enums ─────────────────────────────────────────────────────────────────────


class AssetClass(StrEnum):
    """Supported asset classes in the universal schema."""

    CRYPTO = "crypto"
    EQUITY = "equity"
    FOREX = "forex"
    COMMODITY = "commodity"
    BOND = "bond"
    OPTION = "option"
    FUTURE = "future"
    INDEX = "index"
    MACRO = "macro"


class BarType(StrEnum):
    """Bar aggregation type."""

    TIME = "time"
    TICK = "tick"
    VOLUME = "volume"
    DOLLAR = "dollar"


class BarSize(StrEnum):
    """Bar time-frame size."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1M"


class EventImpact(StrEnum):
    """Economic event impact level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Severity(StrEnum):
    """Data quality check severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IngestionStatus(StrEnum):
    """Ingestion run status."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


# ── Models ────────────────────────────────────────────────────────────────────


class Asset(BaseModel):
    """Asset registry entry — one row per (symbol, exchange) pair.

    Maps to the ``assets`` table in TimescaleDB.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique asset identifier")
    symbol: str = Field(..., min_length=1, description="Trading symbol, e.g. BTCUSDT or AAPL")
    exchange: str = Field(..., min_length=1, description="Exchange name, e.g. Binance, NYSE")
    asset_class: AssetClass = Field(..., description="Asset class category")
    currency: str = Field(..., min_length=1, description="Quote currency, e.g. USD, EUR")
    timezone: str = Field(default="UTC", description="Exchange timezone")
    tick_size: Decimal | None = Field(default=None, description="Minimum price increment")
    lot_size: Decimal | None = Field(default=None, description="Minimum volume increment")
    is_active: bool = Field(default=True, description="Whether the asset is currently tradeable")
    listing_date: date | None = Field(default=None, description="First listing date")
    delisting_date: date | None = Field(default=None, description="Delisting date if inactive")
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, description="Extra metadata (sector, industry, ISIN, etc.)"
    )
    created_at: datetime | None = Field(default=None, description="Row creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Row last-update timestamp")

    @field_validator("symbol", "exchange")
    @classmethod
    def must_be_uppercase(cls, v: str) -> str:
        """Ensure symbol and exchange are uppercase."""
        return v.upper()

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure datetime fields are UTC-aware."""
        return _ensure_utc(v)

    @field_validator("tick_size", "lot_size", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal | None:
        """Convert numeric types to Decimal."""
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v  # type: ignore[return-value]


class Bar(BaseModel):
    """OHLCV bar — maps to the ``bars`` hypertable.

    Supports time, tick, volume, and dollar bar types at any resolution.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID = Field(..., description="FK to assets")
    bar_type: BarType = Field(..., description="Aggregation method")
    bar_size: BarSize = Field(..., description="Time-frame resolution")
    timestamp: datetime = Field(..., description="Bar open timestamp (UTC)")
    open: Decimal = Field(..., gt=Decimal("0"), description="Open price")
    high: Decimal = Field(..., gt=Decimal("0"), description="High price")
    low: Decimal = Field(..., gt=Decimal("0"), description="Low price")
    close: Decimal = Field(..., gt=Decimal("0"), description="Close price")
    volume: Decimal = Field(..., ge=Decimal("0"), description="Volume")
    trade_count: int | None = Field(default=None, description="Number of trades in bar")
    vwap: Decimal | None = Field(default=None, description="Volume-weighted average price")
    adj_close: Decimal | None = Field(default=None, description="Split/dividend adjusted close")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure timestamp is UTC-aware."""
        return _ensure_utc(v)

    @field_validator("open", "high", "low", "close", "volume", "vwap", "adj_close", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal | None:
        """Convert numeric types to Decimal."""
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v  # type: ignore[return-value]


class DbTick(BaseModel):
    """Tick-level trade record — maps to the ``ticks`` hypertable.

    Named DbTick to avoid collision with NormalizedTick in tick.py.
    This is the persistence format; NormalizedTick is the in-flight format.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID = Field(..., description="FK to assets")
    timestamp: datetime = Field(..., description="Trade timestamp (UTC)")
    trade_id: str = Field(default="", description="Exchange-native trade ID")
    price: Decimal = Field(..., gt=Decimal("0"), description="Trade price")
    quantity: Decimal = Field(..., gt=Decimal("0"), description="Trade quantity")
    side: str = Field(default="unknown", description="Aggressor side: buy, sell, unknown")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure timestamp is UTC-aware."""
        return _ensure_utc(v)

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal | None:
        """Convert numeric types to Decimal."""
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v  # type: ignore[return-value]


class OrderBookLevel(BaseModel):
    """Single depth level of an order book snapshot.

    Maps to the ``order_book_snapshots`` table.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID = Field(..., description="FK to assets")
    timestamp: datetime = Field(..., description="Snapshot timestamp (UTC)")
    depth_level: int = Field(..., ge=1, description="Depth level (1=best)")
    bid_price: Decimal | None = Field(default=None, description="Bid price at this level")
    bid_size: Decimal | None = Field(default=None, description="Bid size at this level")
    ask_price: Decimal | None = Field(default=None, description="Ask price at this level")
    ask_size: Decimal | None = Field(default=None, description="Ask size at this level")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure timestamp is UTC-aware."""
        return _ensure_utc(v)

    @field_validator("bid_price", "bid_size", "ask_price", "ask_size", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal | None:
        """Convert numeric types to Decimal."""
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v  # type: ignore[return-value]


class MacroPoint(BaseModel):
    """Single data point in a macroeconomic time series.

    Maps to the ``macro_series`` table.
    """

    model_config = ConfigDict(frozen=True)

    series_id: str = Field(..., min_length=1, description="Series identifier, e.g. VIXCLS")
    timestamp: datetime = Field(..., description="Observation timestamp (UTC)")
    value: float = Field(..., description="Observation value")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure timestamp is UTC-aware."""
        return _ensure_utc(v)


class MacroSeriesMeta(BaseModel):
    """Metadata for a macroeconomic series.

    Maps to the ``macro_series_metadata`` table.
    """

    model_config = ConfigDict(frozen=True)

    series_id: str = Field(..., min_length=1, description="Series identifier")
    source: str = Field(..., min_length=1, description="Data source: FRED, ECB, BOJ, etc.")
    name: str = Field(..., min_length=1, description="Human-readable series name")
    frequency: str | None = Field(
        default=None, description="Observation frequency: daily, weekly, monthly, etc."
    )
    unit: str | None = Field(default=None, description="Unit: percent, index, billions_usd, etc.")
    description: str | None = Field(default=None, description="Free-text description")


class FundamentalPoint(BaseModel):
    """Single fundamental metric for an asset.

    Maps to the ``fundamentals`` table.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID = Field(..., description="FK to assets")
    report_date: date = Field(..., description="Report filing date")
    period_type: str = Field(..., min_length=1, description="quarterly or annual")
    metric_name: str = Field(..., min_length=1, description="Metric key, e.g. revenue, eps")
    value: float | None = Field(default=None, description="Metric value")
    currency: str | None = Field(default=None, description="Currency of the metric value")


class CorporateEvent(BaseModel):
    """Corporate event for an asset (split, dividend, merger, etc.).

    Maps to the ``corporate_events`` table.
    """

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique event identifier")
    asset_id: uuid.UUID = Field(..., description="FK to assets")
    event_date: date = Field(..., description="Event date")
    event_type: str = Field(
        ..., min_length=1, description="split, dividend, merger, delisting, ipo"
    )
    details_json: dict[str, Any] = Field(
        default_factory=dict, description="Event details (ratio, amount, etc.)"
    )


class EconomicEvent(BaseModel):
    """Scheduled economic event (FOMC, CPI, NFP, earnings, etc.).

    Maps to the ``economic_events`` table.
    """

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique event identifier")
    event_type: str = Field(..., min_length=1, description="FOMC, ECB_RATE, US_CPI, US_NFP, etc.")
    scheduled_time: datetime = Field(..., description="Scheduled release time (UTC)")
    actual: float | None = Field(default=None, description="Actual released value")
    consensus: float | None = Field(default=None, description="Market consensus expectation")
    prior: float | None = Field(default=None, description="Prior period value")
    impact_score: int = Field(default=1, ge=1, le=3, description="1=low, 2=medium, 3=high")
    related_asset_id: uuid.UUID | None = Field(
        default=None, description="Related asset (NULL for macro, asset_id for earnings)"
    )
    source: str | None = Field(default=None, description="Data source")

    @field_validator("scheduled_time", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure scheduled_time is UTC-aware."""
        return _ensure_utc(v)


class DataQualityEntry(BaseModel):
    """Data quality check log entry.

    Maps to the ``data_quality_log`` table.
    """

    model_config = ConfigDict(frozen=True)

    check_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique check identifier")
    timestamp: datetime | None = Field(default=None, description="Check timestamp (UTC)")
    check_type: str = Field(
        ..., min_length=1, description="gap, outlier, stale, duplicate, timestamp_future"
    )
    asset_id: uuid.UUID | None = Field(default=None, description="Related asset if applicable")
    severity: Severity = Field(..., description="Check severity level")
    details_json: dict[str, Any] = Field(default_factory=dict, description="Check details")
    resolved: bool = Field(default=False, description="Whether the issue has been resolved")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure timestamp is UTC-aware."""
        return _ensure_utc(v)


class IngestionRun(BaseModel):
    """Ingestion run tracking record.

    Maps to the ``ingestion_runs`` table.
    """

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique run identifier")
    connector: str = Field(
        ..., min_length=1, description="Connector name: binance, polygon, alpaca, fred, etc."
    )
    asset_id: uuid.UUID | None = Field(default=None, description="Target asset (NULL for macro)")
    started_at: datetime = Field(..., description="Run start timestamp (UTC)")
    finished_at: datetime | None = Field(default=None, description="Run end timestamp")
    status: IngestionStatus = Field(
        default=IngestionStatus.RUNNING, description="Current run status"
    )
    rows_inserted: int = Field(default=0, ge=0, description="Number of rows inserted")
    error_message: str | None = Field(default=None, description="Error message if failed")
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, description="Extra metadata (date_range, api_calls, etc.)"
    )

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> object:
        """Ensure datetime fields are UTC-aware."""
        return _ensure_utc(v)
