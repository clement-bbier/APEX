"""
S05 Risk Manager — Internal Pydantic Models.

All models are frozen (immutable). A RuleResult captures the pass/fail
outcome of a single rule. A RiskDecision carries the full audit trail.
A NullOrder is returned instead of raising exceptions on failure.

Design: Null Object Pattern (Gang of Four) — callers never check 'if order:'
but always check 'if order.is_approved'. This eliminates None-check code paths
and makes the chain fully composable.

Reference:
    Fowler, M. (2002). Patterns of Enterprise Application Architecture. Addison-Wesley.
    — Null Object pattern, p. 496.
    Gamma, E. et al. (1994). Design Patterns. Addison-Wesley.
    — Chain of Responsibility, p. 223.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field, model_validator


class CircuitBreakerState(StrEnum):
    """States of the circuit breaker state machine."""

    CLOSED = "CLOSED"  # Normal — trading allowed
    HALF_OPEN = "HALF_OPEN"  # Recovery probe — one order allowed
    OPEN = "OPEN"  # Tripped — all trading blocked


class BlockReason(StrEnum):
    """Canonical reason codes for blocked orders. Used in audit trail and dashboard."""

    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    DAILY_DRAWDOWN_EXCEEDED = "daily_drawdown_exceeded"
    INTRADAY_LOSS_EXCEEDED = "intraday_loss_exceeded"
    VIX_SPIKE = "vix_spike"
    SERVICE_DOWN = "service_down"
    CB_EVENT_BLOCK = "cb_event_block"
    MAX_RISK_PER_TRADE = "max_risk_per_trade"
    NO_STOP_LOSS = "no_stop_loss"
    MIN_RR_NOT_MET = "min_rr_not_met"
    MAX_SIZE_EXCEEDED = "max_size_exceeded"
    MAX_POSITIONS_EXCEEDED = "max_positions_exceeded"
    MAX_TOTAL_EXPOSURE = "max_total_exposure"
    MAX_CLASS_EXPOSURE = "max_class_exposure"
    HIGH_CORRELATION = "high_correlation"
    META_LABEL_CONFIDENCE_TOO_LOW = "meta_label_confidence_too_low"
    KELLY_FRACTION_TOO_SMALL = "kelly_fraction_too_small"


class RuleResult(BaseModel):
    """
    Outcome of a single risk rule evaluation.

    Immutable. Contains both the pass/fail decision and the rationale,
    enabling a complete audit trail for every checked order.
    Every rule in the chain returns a RuleResult — never raises.
    """

    model_config = {"frozen": True}

    rule_name: str
    passed: bool
    reason: str
    block_reason: BlockReason | None = None
    meta: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @classmethod
    def ok(cls, rule_name: str, reason: str = "passed") -> RuleResult:
        return cls(rule_name=rule_name, passed=True, reason=reason)

    @classmethod
    def fail(
        cls,
        rule_name: str,
        block_reason: BlockReason,
        reason: str,
        **meta: str | int | float | bool,
    ) -> RuleResult:
        return cls(
            rule_name=rule_name,
            passed=False,
            block_reason=block_reason,
            reason=reason,
            meta=dict(meta),
        )


class RiskDecision(BaseModel):
    """
    Final decision of the Risk Manager chain for one OrderCandidate.

    Contains the full audit trail: all rule results, final decision,
    the (possibly adjusted) Kelly fraction, and the final approved size.
    Written to Redis for every decision — approved or blocked — for 7 days.
    Published on ZMQ (RISK_APPROVED or RISK_BLOCKED topic).
    """

    model_config = {"frozen": True}

    order_id: str
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved: bool
    rule_results: list[RuleResult]
    first_failure: BlockReason | None = None
    kelly_fraction_raw: float  # Before meta-label modulation
    kelly_fraction_final: float  # After all modulations
    meta_label_confidence: float  # [0.0, 1.0] from MetaLabeler
    final_size: Decimal  # Approved position size (0 if blocked)
    rationale: list[str]  # Human-readable decision trail

    @model_validator(mode="after")
    def validate_consistency(self) -> RiskDecision:
        if self.approved and self.final_size <= Decimal("0"):
            raise ValueError("Approved order must have final_size > 0")
        if not self.approved and self.first_failure is None:
            raise ValueError("Blocked order must have first_failure set")
        return self


class CircuitBreakerSnapshot(BaseModel):
    """Serializable snapshot of circuit breaker state — stored in Redis."""

    model_config = {"frozen": True}

    state: CircuitBreakerState
    tripped_at: datetime | None = None
    tripped_reason: BlockReason | None = None
    daily_pnl: Decimal = Decimal("0")
    daily_loss_pct: float = 0.0
    intraday_loss_30m: Decimal = Decimal("0")
    consecutive_losses: int = 0
    recovery_attempts: int = 0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Position(BaseModel):
    """An open position held in the portfolio. Used by ExposureMonitor."""

    model_config = {"frozen": True}

    symbol: str
    size: Decimal = Field(..., gt=Decimal("0"))
    entry_price: Decimal = Field(..., gt=Decimal("0"))
    asset_class: str = "equity"  # "equity" or "crypto"


# ── Risk Constants (all from DEVELOPMENT_PLAN.md Section 6) ────────────────────

MAX_DAILY_LOSS_PCT: Final[Decimal] = Decimal("0.03")  # 3% daily drawdown → trip CB
MAX_INTRADAY_LOSS_30M_PCT: Final[Decimal] = Decimal("0.02")  # 2% in 30min → trip CB
VIX_SPIKE_THRESHOLD_PCT: Final[float] = 0.20  # VIX +20% in 1h → trip CB (float: VIX is float)
SERVICE_DOWN_SECONDS: Final[int] = 60  # Data/Signal down > 60s → trip
CB_BLOCK_MINUTES_BEFORE: Final[int] = 45  # Block window before CB event
CB_SCALP_MINUTES_AFTER: Final[int] = 15  # Post-event reduced scalp window
CB_SCALP_SIZE_MULTIPLIER: Final[Decimal] = Decimal("0.50")  # Half size post-event
MAX_POSITIONS: Final[int] = 6  # Max simultaneous open positions
MAX_TOTAL_EXPOSURE_PCT: Final[Decimal] = Decimal("0.20")  # 20% of capital max notional
MAX_CLASS_EXPOSURE_PCT: Final[Decimal] = Decimal("0.12")  # 12% per asset class
MAX_RISK_PER_TRADE_PCT: Final[Decimal] = Decimal("0.005")  # 0.5% capital risk per trade
MAX_POSITION_SIZE_PCT: Final[Decimal] = Decimal("0.10")  # 10% of capital max size
MIN_RR_RATIO: Final[Decimal] = Decimal("1.5")  # Min reward/risk to enter
CRYPTO_SIZE_MULTIPLIER: Final[Decimal] = Decimal("0.70")  # Crypto vol adjustment × 0.70
MIN_META_CONFIDENCE_TO_TRADE: Final[float] = 0.52  # Below → hard block (float: confidence is float)
MIN_KELLY_FRACTION: Final[float] = 0.01  # Below after modulation → block (float: kelly is float)
CORRELATION_BLOCK_THRESHOLD: Final[float] = 0.75  # rho > 0.75 (float: correlation is float)
HALF_OPEN_RECOVERY_MINUTES: Final[int] = 30  # Cooldown before HALF_OPEN attempt
REDIS_CB_KEY: Final[str] = "risk:circuit_breaker:state"
REDIS_CB_TTL: Final[int] = 86400  # 24h TTL for CB state
REDIS_RISK_DECISION_TTL: Final[int] = 604800  # 7 days TTL for audit
REDIS_DECISION_HISTORY_KEY: Final[str] = "risk:decision_history"
REDIS_DECISION_HISTORY_MAX: Final[int] = 500
