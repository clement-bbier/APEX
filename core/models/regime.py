"""Regime and macro context models for APEX Trading System.

Defines Regime, MacroContext, CentralBankEvent, and SessionContext.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TrendRegime(str, Enum):
    """Macro trend regime."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    BREAKOUT = "breakout"


class VolRegime(str, Enum):
    """Volatility regime based on VIX thresholds."""

    LOW = "low"         # VIX < 15
    NORMAL = "normal"   # VIX 15-25
    HIGH = "high"       # VIX 25-35
    CRISIS = "crisis"   # VIX > 35


class RiskMode(str, Enum):
    """System-wide risk mode derived from regime."""

    NORMAL = "normal"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    BLOCKED = "blocked"   # No new positions
    CRISIS = "crisis"     # Emergency close positions


class CentralBankEvent(BaseModel):
    """Single central bank calendar event.

    Used by cb_calendar.py and cb_event_guard.py.
    """

    model_config = ConfigDict(frozen=True)

    institution: str = Field(..., description="e.g. FOMC, ECB, BOJ, BOE, SNB")
    event_type: str = Field(..., description="e.g. rate_decision, minutes, speech")
    scheduled_at: datetime = Field(..., description="UTC datetime of the event")
    is_high_impact: bool = Field(default=True)

    # Window metadata (populated after parsing)
    block_window_start: Optional[datetime] = Field(
        default=None,
        description="45 minutes before event: no new entries",
    )
    post_event_scalp_start: Optional[datetime] = Field(
        default=None,
        description="When post-event scalp window opens",
    )
    post_event_scalp_end: Optional[datetime] = Field(
        default=None,
        description="60 minutes after event: scalp allowed with reduced size",
    )

    @property
    def is_active_block(self) -> bool:
        """Check if current time is in the pre-event block window."""
        now = datetime.utcnow()
        if self.block_window_start is None:
            return False
        return self.block_window_start <= now < self.scheduled_at

    @property
    def is_post_event_scalp(self) -> bool:
        """Check if current time is in the post-event scalp window."""
        now = datetime.utcnow()
        if self.post_event_scalp_start is None or self.post_event_scalp_end is None:
            return False
        return self.post_event_scalp_start <= now < self.post_event_scalp_end


class MacroContext(BaseModel):
    """Aggregated macro environment snapshot.

    Updated every 30 seconds by S03 Regime Detector.
    """

    model_config = ConfigDict(frozen=True)

    timestamp_ms: int = Field(..., description="Snapshot time UTC ms")
    vix: Optional[float] = Field(default=None, description="CBOE VIX level")
    dxy: Optional[float] = Field(default=None, description="US Dollar Index")
    yield_spread_10y2y: Optional[float] = Field(
        default=None, description="10Y-2Y yield spread (negative = inversion)"
    )
    macro_mult: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Macro multiplier applied to position sizing [0.0→1.0]",
    )
    event_active: bool = Field(
        default=False, description="True if inside a CB event block window"
    )
    post_event_scalp: bool = Field(
        default=False, description="True if inside post-event scalp window"
    )


class SessionContext(BaseModel):
    """Current trading session context.

    Updated by session_tracker.py in S03.
    """

    model_config = ConfigDict(frozen=True)

    timestamp_ms: int
    session: str = Field(default="unknown", description="Current session label")
    session_mult: float = Field(
        default=1.0,
        ge=0.5,
        le=1.5,
        description="Session multiplier for sizing/signal weighting",
    )
    is_us_prime: bool = Field(
        default=False, description="True during 09:30-10:30 ET and 15:00-16:00 ET"
    )
    is_us_open: bool = Field(
        default=False, description="True during regular US market hours"
    )


class Regime(BaseModel):
    """Comprehensive market regime snapshot published by S03.

    Written to Redis every 30s and on change.
    ZMQ topic: regime.update
    """

    model_config = ConfigDict(frozen=True)

    timestamp_ms: int = Field(..., description="Regime snapshot time UTC ms")
    trend_regime: TrendRegime = Field(default=TrendRegime.RANGING)
    vol_regime: VolRegime = Field(default=VolRegime.NORMAL)
    risk_mode: RiskMode = Field(default=RiskMode.NORMAL)

    # Sub-contexts
    macro: MacroContext
    session: SessionContext

    # Central bank
    cb_calendar: list[CentralBankEvent] = Field(default_factory=list)
    next_cb_event: Optional[CentralBankEvent] = None

    # Composite score
    macro_mult: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Composite macro multiplier"
    )
    session_mult: float = Field(
        default=1.0, ge=0.5, le=1.5, description="Session multiplier"
    )

    @property
    def combined_mult(self) -> float:
        """Combined macro × session multiplier."""
        return self.macro_mult * self.session_mult

    @property
    def is_tradeable(self) -> bool:
        """True if system can place new positions in this regime."""
        return self.risk_mode not in (RiskMode.BLOCKED, RiskMode.CRISIS)
