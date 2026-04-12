"""Signal models for APEX Trading System.

Defines Signal, TechnicalFeatures, and MTFContext Pydantic v2 models.
Signals are immutable and carry full context for traceability.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Direction(StrEnum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SignalType(StrEnum):
    """Source of the signal for attribution."""

    OFI = "ofi"
    CVD = "cvd"
    RSI_DIV = "rsi_divergence"
    BB_BOUNCE = "bb_bounce"
    BB_BREAKOUT = "bb_breakout"
    EMA_CROSS = "ema_cross"
    VWAP_BOUNCE = "vwap_bounce"
    GEX_MAGNET = "gex_magnet"
    STOP_CLUSTER = "stop_cluster"
    LIQ_CASCADE = "liquidation_cascade"
    FUNDING_EXTREME = "funding_extreme"
    MACRO_MOMENTUM = "macro_momentum"
    COMPOSITE = "composite"


class MTFContext(BaseModel):
    """Multi-timeframe alignment context.

    Records the directional stance on each timeframe and produces
    an overall alignment score in [0, 1].
    """

    model_config = ConfigDict(frozen=True)

    tf_1d: Direction | None = None
    tf_4h: Direction | None = None
    tf_1h: Direction | None = None
    tf_15m: Direction | None = None
    tf_5m: Direction | None = None
    alignment_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of active timeframes aligned with signal direction",
    )
    session_bonus: float = Field(
        default=1.0,
        ge=0.5,
        le=1.5,
        description="Session multiplier (US prime=1.20, overnight=0.70)",
    )


class TechnicalFeatures(BaseModel):
    """Technical indicator snapshot at signal generation time."""

    model_config = ConfigDict(frozen=True)

    # RSI
    rsi_1m: float | None = None
    rsi_5m: float | None = None
    rsi_15m: float | None = None

    # Bollinger Bands
    bb_upper: Decimal | None = None
    bb_middle: Decimal | None = None
    bb_lower: Decimal | None = None
    bb_squeeze: bool = False

    # EMAs
    ema_8: Decimal | None = None
    ema_21: Decimal | None = None
    ema_55: Decimal | None = None

    # VWAP
    vwap: Decimal | None = None

    # ATR
    atr_14: Decimal | None = None

    # Volume Profile
    poc: Decimal | None = None  # Point of Control
    vah: Decimal | None = None  # Value Area High
    val: Decimal | None = None  # Value Area Low

    # Microstructure
    ofi: float | None = None  # Order Flow Imbalance
    cvd: float | None = None  # Cumulative Volume Delta
    kyle_lambda: float | None = None  # Price impact coefficient


class Signal(BaseModel):
    """Trading signal produced by the Signal Engine.

    Immutable model published on ZMQ topic: signal.technical.{SYMBOL}
    Contains everything needed for fusion, risk, and execution.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    signal_id: str = Field(..., description="Unique signal identifier")
    symbol: str = Field(..., description="Uppercase trading symbol")
    timestamp_ms: int = Field(..., gt=0, description="Signal generation time UTC ms")

    # Direction and strength
    direction: Direction = Field(..., description="Trade direction")
    strength: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Signal strength in [-1, 1]; negative=short, positive=long",
    )

    # Signal source
    signal_type: SignalType = Field(default=SignalType.COMPOSITE)
    triggers: list[str] = Field(
        default_factory=list,
        description="List of conditions that fired (e.g. 'RSI_oversold', 'OFI_positive')",
    )

    # Price levels
    entry: Decimal = Field(..., gt=Decimal("0"), description="Suggested entry price")
    stop_loss: Decimal = Field(..., gt=Decimal("0"), description="Mandatory stop loss")
    take_profit: list[Decimal] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="[target_scalp, target_swing] take-profit levels",
    )

    # Quality metrics
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Signal confidence score",
    )

    # Hedge metadata
    hedge_signal: bool = Field(
        default=False,
        description="Whether a counter-directional hedge is recommended",
    )

    # Context
    features: TechnicalFeatures | None = None
    mtf_context: MTFContext | None = None

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        """Ensure symbol is uppercase."""
        return v.upper()

    @model_validator(mode="after")
    def validate_price_levels(self) -> Signal:
        """Validate stop loss and take profit are sensible relative to entry."""
        if self.direction == Direction.LONG:
            if self.stop_loss >= self.entry:
                raise ValueError(
                    f"Long signal stop_loss {self.stop_loss} must be below entry {self.entry}"
                )
            if self.take_profit[0] <= self.entry:
                raise ValueError(
                    f"Long signal take_profit[0] {self.take_profit[0]} "
                    f"must be above entry {self.entry}"
                )
        elif self.direction == Direction.SHORT:
            if self.stop_loss <= self.entry:
                raise ValueError(
                    f"Short signal stop_loss {self.stop_loss} must be above entry {self.entry}"
                )
            if self.take_profit[0] >= self.entry:
                raise ValueError(
                    f"Short signal take_profit[0] {self.take_profit[0]} "
                    f"must be below entry {self.entry}"
                )
        return self

    @property
    def risk_reward(self) -> Decimal | None:
        """Compute risk/reward ratio using scalp target."""
        risk = abs(self.entry - self.stop_loss)
        reward = abs(self.take_profit[0] - self.entry)
        if risk == 0:
            return None
        return reward / risk
