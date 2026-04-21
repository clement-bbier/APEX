"""Response schemas for the APEX Serving Layer API.

Pydantic v2 models used as FastAPI response_model types.
Each schema maps closely to a core data model but exposes only
the fields relevant to API consumers — no internal UUIDs leak
unless explicitly needed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.models.data import (
    Asset,
    Bar,
    DbTick,
    EconomicEvent,
    FundamentalPoint,
    MacroPoint,
    MacroSeriesMeta,
)

# ── Microstructure ───────────────────────────────────────────────────────────


class BarResponse(BaseModel):
    """OHLCV bar returned by /v1/bars."""

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID
    bar_type: str
    bar_size: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int | None = None
    vwap: Decimal | None = None

    @staticmethod
    def from_bar(bar: Bar) -> BarResponse:
        """Convert a core Bar model to an API response."""
        return BarResponse(
            asset_id=bar.asset_id,
            bar_type=bar.bar_type.value,
            bar_size=bar.bar_size.value,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            trade_count=bar.trade_count,
            vwap=bar.vwap,
        )


class TickResponse(BaseModel):
    """Tick-level trade returned by /v1/trades."""

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID
    timestamp: datetime
    trade_id: str
    price: Decimal
    quantity: Decimal
    side: str

    @staticmethod
    def from_tick(tick: DbTick) -> TickResponse:
        """Convert a core DbTick model to an API response."""
        return TickResponse(
            asset_id=tick.asset_id,
            timestamp=tick.timestamp,
            trade_id=tick.trade_id,
            price=tick.price,
            quantity=tick.quantity,
            side=tick.side,
        )


# ── Macro ────────────────────────────────────────────────────────────────────


class MacroPointResponse(BaseModel):
    """Macro data point returned by /v1/macro_series."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    timestamp: datetime
    value: float

    @staticmethod
    def from_point(point: MacroPoint) -> MacroPointResponse:
        """Convert a core MacroPoint to an API response."""
        return MacroPointResponse(
            series_id=point.series_id,
            timestamp=point.timestamp,
            value=point.value,
        )


class MacroMetadataResponse(BaseModel):
    """Macro series metadata returned by /v1/macro_series/metadata."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    source: str
    name: str
    frequency: str | None = None
    unit: str | None = None
    description: str | None = None

    @staticmethod
    def from_meta(meta: MacroSeriesMeta) -> MacroMetadataResponse:
        """Convert a core MacroSeriesMeta to an API response."""
        return MacroMetadataResponse(
            series_id=meta.series_id,
            source=meta.source,
            name=meta.name,
            frequency=meta.frequency,
            unit=meta.unit,
            description=meta.description,
        )


# ── Calendar ─────────────────────────────────────────────────────────────────


class EconomicEventResponse(BaseModel):
    """Economic event returned by /v1/economic_events."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    event_type: str
    scheduled_time: datetime
    actual: float | None = None
    consensus: float | None = None
    prior: float | None = None
    impact_score: int = Field(ge=1, le=3)
    source: str | None = None

    @staticmethod
    def from_event(event: EconomicEvent) -> EconomicEventResponse:
        """Convert a core EconomicEvent to an API response."""
        return EconomicEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            scheduled_time=event.scheduled_time,
            actual=event.actual,
            consensus=event.consensus,
            prior=event.prior,
            impact_score=event.impact_score,
            source=event.source,
        )


# ── Fundamentals ─────────────────────────────────────────────────────────────


class FundamentalResponse(BaseModel):
    """Fundamental metric returned by /v1/fundamentals."""

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID
    report_date: date
    period_type: str
    metric_name: str
    value: float | None = None
    currency: str | None = None

    @staticmethod
    def from_point(point: FundamentalPoint) -> FundamentalResponse:
        """Convert a core FundamentalPoint to an API response."""
        return FundamentalResponse(
            asset_id=point.asset_id,
            report_date=point.report_date,
            period_type=point.period_type,
            metric_name=point.metric_name,
            value=point.value,
            currency=point.currency,
        )


# ── Assets ───────────────────────────────────────────────────────────────────


class AssetResponse(BaseModel):
    """Asset registry entry returned by /v1/assets."""

    model_config = ConfigDict(frozen=True)

    asset_id: uuid.UUID
    symbol: str
    exchange: str
    asset_class: str
    currency: str
    timezone: str
    is_active: bool
    tick_size: Decimal | None = None
    lot_size: Decimal | None = None

    @staticmethod
    def from_asset(asset: Asset) -> AssetResponse:
        """Convert a core Asset to an API response."""
        return AssetResponse(
            asset_id=asset.asset_id,
            symbol=asset.symbol,
            exchange=asset.exchange,
            asset_class=asset.asset_class.value,
            currency=asset.currency,
            timezone=asset.timezone,
            is_active=asset.is_active,
            tick_size=asset.tick_size,
            lot_size=asset.lot_size,
        )


# ── Health ───────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(frozen=True)

    status: str
    database: bool
