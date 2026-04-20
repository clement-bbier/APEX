"""
Position Rules -- Per-Order Validation (Phase 6 rewrite).

Each function validates one specific property of an OrderCandidate.
All functions are pure: no Redis, no ZMQ, no I/O. No side effects.

Rule pipeline:
    1. check_stop_loss_present  -- structural: cannot trade without a valid stop
    2. check_min_rr             -- structural: RR >= 1.5
    3. check_max_risk_per_trade -- capital: max 0.5%% risk per trade
    4. check_max_size           -- capital: 10%% position size ceiling
    5. apply_crypto_multiplier  -- asset modifier: crypto x 0.70 (not a blocker)
    6. apply_session_multiplier -- timing modifier: prime window x 1.10 (not a blocker)

Reference:
    Kelly, J.L. (1956). Bell System Technical Journal, 35(4), 917-926.
    Vince, R. (1992). The Mathematics of Money Management. Wiley.
    Tharp, V.K. (1998). Trade Your Way to Financial Freedom. McGraw-Hill.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.order import OrderCandidate
from core.models.signal import Direction
from core.models.tick import Session
from services.s05_risk_manager.models import (
    CRYPTO_SIZE_MULTIPLIER,
    MAX_POSITION_SIZE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MIN_RR_RATIO,
    BlockReason,
    RuleResult,
)

_CRYPTO_SUFFIXES: frozenset[str] = frozenset({"USDT", "BTC", "ETH", "BNB"})
_PRIME_SESSIONS: frozenset[Session] = frozenset({Session.US_PRIME})
_SESSION_PRIME_MULTIPLIER: float = 1.10


def _is_crypto(symbol: str) -> bool:
    return any(symbol.upper().endswith(sfx) for sfx in _CRYPTO_SUFFIXES)


def check_stop_loss_present(order: OrderCandidate) -> RuleResult:
    """Verify stop loss exists and is directionally correct.

    LONG: stop_loss < entry. SHORT: stop_loss > entry.
    """
    if order.stop_loss <= 0:
        return RuleResult.fail(
            rule_name="check_stop_loss_present",
            block_reason=BlockReason.NO_STOP_LOSS,
            reason="stop_loss must be > 0",
        )
    if order.direction == Direction.LONG and order.stop_loss >= order.entry:
        return RuleResult.fail(
            rule_name="check_stop_loss_present",
            block_reason=BlockReason.NO_STOP_LOSS,
            reason=f"LONG: stop_loss {order.stop_loss} must be < entry {order.entry}",
        )
    if order.direction == Direction.SHORT and order.stop_loss <= order.entry:
        return RuleResult.fail(
            rule_name="check_stop_loss_present",
            block_reason=BlockReason.NO_STOP_LOSS,
            reason=f"SHORT: stop_loss {order.stop_loss} must be > entry {order.entry}",
        )
    return RuleResult.ok(rule_name="check_stop_loss_present")


def check_min_rr(order: OrderCandidate) -> RuleResult:
    """Verify RR = |target_scalp - entry| / |entry - stop_loss| >= 1.5.

    Reference:
        Lopez de Prado (2018). AFML Ch. 11. Minimum RR for positive EV.
    """
    sl_distance = abs(order.entry - order.stop_loss)
    if sl_distance == Decimal("0"):
        return RuleResult.fail(
            rule_name="check_min_rr",
            block_reason=BlockReason.MIN_RR_NOT_MET,
            reason="zero SL distance",
        )
    tp_distance = abs(order.target_scalp - order.entry)
    rr = tp_distance / sl_distance
    if rr < MIN_RR_RATIO:
        return RuleResult.fail(
            rule_name="check_min_rr",
            block_reason=BlockReason.MIN_RR_NOT_MET,
            reason=f"RR {rr:.3f} < minimum {MIN_RR_RATIO}",
            rr=float(rr),
        )
    return RuleResult.ok(rule_name="check_min_rr", reason=f"RR {rr:.3f}")


def check_max_risk_per_trade(order: OrderCandidate, capital: Decimal) -> RuleResult:
    """Verify |entry - stop_loss| x size <= capital x 0.005.

    Reference:
        Vince, R. (1992). Mathematics of Money Management. Wiley.
    """
    if capital <= Decimal("0"):
        return RuleResult.ok(rule_name="check_max_risk_per_trade", reason="capital=0 skipped")
    sl_distance = abs(order.entry - order.stop_loss)
    monetary_risk = sl_distance * order.size
    max_risk = capital * MAX_RISK_PER_TRADE_PCT
    if monetary_risk > max_risk:
        return RuleResult.fail(
            rule_name="check_max_risk_per_trade",
            block_reason=BlockReason.MAX_RISK_PER_TRADE,
            reason=f"risk {monetary_risk:.4f} > max {max_risk:.4f}",
            monetary_risk=float(monetary_risk),
            max_risk=float(max_risk),
        )
    return RuleResult.ok(rule_name="check_max_risk_per_trade", reason=f"risk {monetary_risk:.4f}")


def check_max_size(order: OrderCandidate, capital: Decimal) -> RuleResult:
    """Verify size x entry <= capital x 0.10."""
    if capital <= Decimal("0"):
        return RuleResult.ok(rule_name="check_max_size", reason="capital=0 skipped")
    notional = order.size * order.entry
    max_notional = capital * MAX_POSITION_SIZE_PCT
    if notional > max_notional:
        return RuleResult.fail(
            rule_name="check_max_size",
            block_reason=BlockReason.MAX_SIZE_EXCEEDED,
            reason=f"notional {notional:.2f} > max {max_notional:.2f}",
            notional=float(notional),
            max_notional=float(max_notional),
        )
    return RuleResult.ok(rule_name="check_max_size", reason=f"notional {notional:.2f}")


def apply_crypto_multiplier(order: OrderCandidate) -> tuple[Decimal, RuleResult]:
    """Apply CRYPTO_SIZE_MULTIPLIER (0.70) for crypto symbols."""
    if _is_crypto(order.symbol):
        adjusted = order.size * CRYPTO_SIZE_MULTIPLIER
        return adjusted, RuleResult.ok(
            rule_name="apply_crypto_multiplier",
            reason=f"crypto x {CRYPTO_SIZE_MULTIPLIER}",
        )
    return order.size, RuleResult.ok(
        rule_name="apply_crypto_multiplier",
        reason="equity: no adjustment",
    )


def apply_session_multiplier(order: OrderCandidate, session: Session) -> tuple[Decimal, RuleResult]:
    """Apply x1.10 bonus during prime sessions (US_PRIME)."""
    if session in _PRIME_SESSIONS:
        adjusted = order.size * Decimal(str(_SESSION_PRIME_MULTIPLIER))
        return adjusted, RuleResult.ok(
            rule_name="apply_session_multiplier",
            reason=f"prime session x {_SESSION_PRIME_MULTIPLIER}",
        )
    return order.size, RuleResult.ok(
        rule_name="apply_session_multiplier",
        reason=f"{session}: no bonus",
    )
