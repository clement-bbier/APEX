"""Order models for APEX Trading System.

Defines OrderCandidate, ApprovedOrder, ExecutedOrder, TradeRecord, and NullOrder.
All order objects are immutable Pydantic v2 models.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.models.signal import Direction, Signal


class OrderStatus(StrEnum):
    """Lifecycle status of an order."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    BLOCKED = "blocked"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(StrEnum):
    """Execution order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    OCO = "oco"


class OrderCandidate(BaseModel):
    """Order proposal from the Fusion Engine, pending risk validation.

    Published on ZMQ topic: order.candidate
    """

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., description="Unique order identifier")
    symbol: str = Field(..., description="Uppercase trading symbol")
    direction: Direction = Field(..., description="Trade direction")
    timestamp_ms: int = Field(..., gt=0, description="Proposal time UTC ms")
    strategy_id: str = Field(
        default="default",
        description=(
            "Per-strategy identifier (Charter §5.5, ADR-0007 §D6). "
            "Default 'default' preserves the legacy single-strategy path "
            "until Phase B wraps it as LegacyConfluenceStrategy."
        ),
    )

    # Sizing
    size: Decimal = Field(..., gt=Decimal("0"), description="Total position size in base units")
    size_scalp_exit: Decimal = Field(
        ..., gt=Decimal("0"), description="Fraction to exit at scalp target (30-40%)"
    )
    size_swing_exit: Decimal = Field(
        ..., gt=Decimal("0"), description="Fraction to exit at swing target (60-70%)"
    )

    # Price levels
    entry: Decimal = Field(..., gt=Decimal("0"))
    stop_loss: Decimal = Field(..., gt=Decimal("0"))
    target_scalp: Decimal = Field(..., gt=Decimal("0"))
    target_swing: Decimal = Field(..., gt=Decimal("0"))

    # Capital at risk
    capital_at_risk: Decimal = Field(
        ..., gt=Decimal("0"), description="Max loss amount in quote currency"
    )

    # Hedge
    hedge_direction: Direction | None = None
    hedge_size: Decimal | None = None

    # Scoring
    fusion_score: float = Field(
        default=0.0,
        ge=0.0,
        description="Final fusion score used for sizing",
    )
    kelly_fraction: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Quarter-Kelly fraction applied",
    )

    # Lineage
    source_signal: Signal | None = None
    linked_order_id: str | None = Field(default=None, description="ID of hedge counterpart order")

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, v: str) -> str:
        """Reject strategy_ids that break ZMQ topics, Redis keys, or filesystem paths.

        Mirrors the Signal.validate_strategy_id validator (see
        ``core/models/signal.py``) so every order-path model applies the same
        structural guarantees per Charter §5.5 and ADR-0007 §D6. Empty strings,
        whitespace, forward/backslashes and quote characters are rejected, and
        length is capped at 64 so downstream Redis keys
        (``kelly:{strategy_id}:{symbol}`` etc.) and filesystem paths
        (``services/strategies/{strategy_id}/``) stay bounded and safe.
        """
        if not v:
            raise ValueError("strategy_id must be non-empty")
        if len(v) > 64:
            raise ValueError(f"strategy_id length {len(v)} exceeds max 64 characters")
        if any(c.isspace() for c in v):
            raise ValueError(
                "strategy_id contains whitespace; "
                "ASCII and Unicode whitespace (incl. NBSP \\u00A0) are not permitted"
            )
        forbidden = set("/\\'\"")
        bad = sorted(set(v) & forbidden)
        if bad:
            raise ValueError(
                f"strategy_id contains forbidden characters {bad!r}; "
                "slashes and quotes are not permitted"
            )
        return v

    @model_validator(mode="after")
    def validate_exit_sizes(self) -> OrderCandidate:
        """Scalp + swing exit sizes must sum to total size (within rounding tolerance)."""
        tolerance = Decimal("0.0001")
        total_exits = self.size_scalp_exit + self.size_swing_exit
        if abs(total_exits - self.size) > tolerance:
            raise ValueError(
                f"size_scalp_exit ({self.size_scalp_exit}) + size_swing_exit "
                f"({self.size_swing_exit}) = {total_exits} != size ({self.size})"
            )
        return self


class ApprovedOrder(BaseModel):
    """Order approved by the Risk Manager.

    Published on ZMQ topic: order.approved
    Carries the original OrderCandidate plus risk metadata.
    """

    model_config = ConfigDict(frozen=True)

    candidate: OrderCandidate
    approved_at_ms: int = Field(..., gt=0, description="Approval timestamp UTC ms")
    regime_mult: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Regime-based size multiplier"
    )
    adjusted_size: Decimal = Field(
        ..., gt=Decimal("0"), description="Final approved size after regime adjustment"
    )
    order_type: OrderType = Field(default=OrderType.LIMIT)
    notes: list[str] = Field(default_factory=list)
    strategy_id: str = Field(
        default="default",
        description="Per-strategy identifier (Charter §5.5, ADR-0007 §D6).",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_and_validate_strategy_id(cls, data: object) -> object:
        """Derive strategy_id from nested candidate when omitted; reject mismatches.

        Prevents silent strategy_id divergence between ApprovedOrder and its
        nested OrderCandidate. Critical for multi-strat PnL attribution
        (Charter §5.5).
        """
        if not isinstance(data, dict):
            return data
        candidate = data.get("candidate")
        candidate_strategy_id: str | None = None
        if isinstance(candidate, OrderCandidate):
            candidate_strategy_id = candidate.strategy_id
        elif isinstance(candidate, dict):
            raw = candidate.get("strategy_id")
            if isinstance(raw, str):
                candidate_strategy_id = raw
        if candidate_strategy_id is None:
            return data
        provided = data.get("strategy_id")
        if provided is None or provided == "":
            data["strategy_id"] = candidate_strategy_id
            return data
        if provided != candidate_strategy_id:
            raise ValueError(
                f"ApprovedOrder.strategy_id={provided!r} must match "
                f"candidate.strategy_id={candidate_strategy_id!r}; silent divergence "
                "would corrupt multi-strategy PnL attribution"
            )
        return data

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, v: str) -> str:
        """Reject strategy_ids that break ZMQ topics, Redis keys, or filesystem paths.

        Enforces the same overall strategy-id safety constraints used across
        order/signal models per Charter §5.5 and ADR-0007 §D6. This validator
        rejects empty values, Unicode whitespace (via c.isspace()), slashes,
        quotes, and length > 64 so downstream Redis keys
        (kelly:{strategy_id}:{symbol} etc.) and filesystem paths
        (services/strategies/{strategy_id}/) stay bounded and safe.
        """
        if not v:
            raise ValueError("strategy_id must be non-empty")
        if len(v) > 64:
            raise ValueError(f"strategy_id length {len(v)} exceeds max 64 characters")
        if any(c.isspace() for c in v):
            raise ValueError(
                "strategy_id contains whitespace; whitespace (ASCII or Unicode) is not permitted"
            )
        forbidden = set("/\\'\"")
        bad = sorted(set(v) & forbidden)
        if bad:
            raise ValueError(
                f"strategy_id contains forbidden characters {bad!r}; "
                "slashes and quotes are not permitted"
            )
        return v

    @property
    def order_id(self) -> str:
        """Delegate to candidate."""
        return self.candidate.order_id

    @property
    def symbol(self) -> str:
        """Delegate to candidate."""
        return self.candidate.symbol


class ExecutedOrder(BaseModel):
    """Order execution record from the execution service.

    Published on ZMQ topic: order.filled
    """

    model_config = ConfigDict(frozen=True)

    approved_order: ApprovedOrder
    broker_order_id: str = Field(..., description="Broker-assigned order ID")
    fill_price: Decimal = Field(..., gt=Decimal("0"), description="Actual fill price")
    fill_size: Decimal = Field(..., gt=Decimal("0"), description="Actual filled size")
    fill_timestamp_ms: int = Field(..., gt=0, description="Fill timestamp UTC ms")
    slippage_bps: Decimal = Field(default=Decimal("0"), description="Slippage in basis points")
    commission: Decimal = Field(
        default=Decimal("0"), description="Commission charged in quote currency"
    )
    is_paper: bool = Field(default=True, description="True if simulated paper trade")
    strategy_id: str = Field(
        default="default",
        description="Per-strategy identifier (Charter §5.5, ADR-0007 §D6).",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_and_validate_strategy_id(cls, data: object) -> object:
        """Derive strategy_id from nested approved_order when omitted; reject mismatches.

        Prevents silent strategy_id divergence between ExecutedOrder and its
        nested ApprovedOrder (which in turn propagates from OrderCandidate).
        Critical for multi-strat PnL attribution (Charter §5.5).
        """
        if not isinstance(data, dict):
            return data
        approved = data.get("approved_order")
        approved_strategy_id: str | None = None
        if isinstance(approved, ApprovedOrder):
            approved_strategy_id = approved.strategy_id
        elif isinstance(approved, dict):
            raw = approved.get("strategy_id")
            if isinstance(raw, str):
                approved_strategy_id = raw
        if approved_strategy_id is None:
            return data
        provided = data.get("strategy_id")
        if provided is None or provided == "":
            data["strategy_id"] = approved_strategy_id
            return data
        if provided != approved_strategy_id:
            raise ValueError(
                f"ExecutedOrder.strategy_id={provided!r} must match "
                f"approved_order.strategy_id={approved_strategy_id!r}; silent divergence "
                "would corrupt multi-strategy PnL attribution"
            )
        return data

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, v: str) -> str:
        """Reject strategy_ids that break ZMQ topics, Redis keys, or filesystem paths.

        Enforces the same overall strategy-id safety constraints used across
        order/signal models per Charter §5.5 and ADR-0007 §D6. This validator
        rejects empty values, Unicode whitespace (via c.isspace()), slashes,
        quotes, and length > 64 so downstream Redis keys
        (kelly:{strategy_id}:{symbol} etc.) and filesystem paths
        (services/strategies/{strategy_id}/) stay bounded and safe.
        """
        if not v:
            raise ValueError("strategy_id must be non-empty")
        if len(v) > 64:
            raise ValueError(f"strategy_id length {len(v)} exceeds max 64 characters")
        if any(c.isspace() for c in v):
            raise ValueError(
                "strategy_id contains whitespace; whitespace (ASCII or Unicode) is not permitted"
            )
        forbidden = set("/\\'\"")
        bad = sorted(set(v) & forbidden)
        if bad:
            raise ValueError(
                f"strategy_id contains forbidden characters {bad!r}; "
                "slashes and quotes are not permitted"
            )
        return v

    @property
    def order_id(self) -> str:
        """Delegate to approved order."""
        return self.approved_order.order_id

    @property
    def symbol(self) -> str:
        """Delegate to approved order."""
        return self.approved_order.symbol


class TradeRecord(BaseModel):
    """Complete trade lifecycle record stored in Redis/DB.

    Written by S09 Feedback Loop after a position closes.
    Used for performance analytics and Kelly parameter updates.
    """

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., description="Unique trade ID")
    symbol: str
    direction: Direction
    entry_timestamp_ms: int
    exit_timestamp_ms: int
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal

    # PnL
    gross_pnl: Decimal
    net_pnl: Decimal
    commission: Decimal
    slippage_cost: Decimal

    # Attribution context
    signal_type: str = Field(default="", description="Signal type at entry")
    regime_at_entry: str = Field(default="", description="Regime label at entry")
    session_at_entry: str = Field(default="", description="Session at entry")
    mtf_alignment_score: float = Field(default=0.0)
    fusion_score_at_entry: float = Field(default=0.0)

    # Exit reason
    exit_reason: str = Field(
        default="", description="stop_loss / take_profit_scalp / take_profit_swing / manual"
    )

    strategy_id: str = Field(
        default="default",
        description="Per-strategy identifier (Charter §5.5, ADR-0007 §D6).",
    )

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, v: str) -> str:
        """Reject strategy_ids that break ZMQ topics, Redis keys, or filesystem paths.

        Enforces the same overall strategy-id safety constraints used across
        order/signal models per Charter §5.5 and ADR-0007 §D6. This validator
        rejects empty values, Unicode whitespace (via c.isspace()), slashes,
        quotes, and length > 64 so downstream Redis keys
        (kelly:{strategy_id}:{symbol} etc.) and filesystem paths
        (services/strategies/{strategy_id}/) stay bounded and safe.
        """
        if not v:
            raise ValueError("strategy_id must be non-empty")
        if len(v) > 64:
            raise ValueError(f"strategy_id length {len(v)} exceeds max 64 characters")
        if any(c.isspace() for c in v):
            raise ValueError(
                "strategy_id contains whitespace; whitespace (ASCII or Unicode) is not permitted"
            )
        forbidden = set("/\\'\"")
        bad = sorted(set(v) & forbidden)
        if bad:
            raise ValueError(
                f"strategy_id contains forbidden characters {bad!r}; "
                "slashes and quotes are not permitted"
            )
        return v

    @property
    def is_winner(self) -> bool:
        """True if net PnL > 0."""
        return self.net_pnl > 0

    @property
    def r_multiple(self) -> Decimal | None:
        """Return PnL as multiple of initial risk (R)."""
        risk = abs(self.entry_price - self.exit_price)
        if risk == 0 or self.size == 0:
            return None
        return self.net_pnl / (risk * self.size)


class NullOrder(BaseModel):
    """Sentinel order representing a blocked or no-action decision.

    Published on ZMQ topic: order.blocked
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    blocked_at_ms: int
    reason: str = Field(..., description="Why this order was blocked")
    blocker: str = Field(..., description="Which rule/guard triggered the block")
