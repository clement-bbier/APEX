"""
Exposure Monitor -- Portfolio-Level Risk Controls (Phase 6).

All functions are pure: they receive positions as a list, not via Redis.
Redis reading happens in service.py before the chain starts.

Rules enforced:
    1. check_max_positions:      no more than MAX_POSITIONS (6) open simultaneously
    2. check_total_exposure:     total notional <= MAX_TOTAL_EXPOSURE_PCT (20%) of capital
    3. check_per_class_exposure: per-class (crypto/equity) <= MAX_CLASS_EXPOSURE_PCT (12%)
    4. check_correlation:        rho > 0.75 with any open position -> block

Reference:
    Markowitz, H. (1952). Portfolio Selection. Journal of Finance, 7(1), 77-91.
    Lopez de Prado, M. (2018). AFML, Ch. 16. Portfolio construction under constraints.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.order import OrderCandidate
from services.s05_risk_manager.models import (
    CORRELATION_BLOCK_THRESHOLD,
    MAX_CLASS_EXPOSURE_PCT,
    MAX_POSITIONS,
    MAX_TOTAL_EXPOSURE_PCT,
    BlockReason,
    Position,
    RuleResult,
)

_CRYPTO_SUFFIXES: frozenset[str] = frozenset({"USDT", "BTC", "ETH", "BNB"})


def _is_crypto(symbol: str) -> bool:
    return any(symbol.upper().endswith(sfx) for sfx in _CRYPTO_SUFFIXES)


def _asset_class(symbol: str) -> str:
    return "crypto" if _is_crypto(symbol) else "equity"


def check_max_positions(positions: list[Position]) -> RuleResult:
    """Enforce maximum number of simultaneous open positions (MAX_POSITIONS = 6).

    Args:
        positions: Currently open positions.

    Returns:
        RuleResult.fail if len(positions) >= MAX_POSITIONS; ok otherwise.
    """
    if len(positions) >= MAX_POSITIONS:
        return RuleResult.fail(
            rule_name="check_max_positions",
            block_reason=BlockReason.MAX_POSITIONS_EXCEEDED,
            reason=f"open positions {len(positions)} >= max {MAX_POSITIONS}",
            open_count=len(positions),
            max_positions=MAX_POSITIONS,
        )
    return RuleResult.ok(
        rule_name="check_max_positions",
        reason=f"{len(positions)}/{MAX_POSITIONS} positions",
    )


def check_total_exposure(
    order: OrderCandidate, positions: list[Position], capital: Decimal
) -> RuleResult:
    """Verify total notional (existing + new) does not exceed 20% of capital.

    Formula: (sum(pos_i.size x pos_i.entry) + order.size x order.entry) / capital <= 0.20

    Args:
        order:     Proposed order.
        positions: Currently open positions.
        capital:   Total portfolio capital.

    Returns:
        RuleResult.fail if combined exposure > MAX_TOTAL_EXPOSURE_PCT; ok otherwise.
    """
    if capital <= Decimal("0"):
        return RuleResult.ok(rule_name="check_total_exposure", reason="capital=0 skipped")

    existing_notional = sum(p.size * p.entry_price for p in positions)
    new_notional = order.size * order.entry
    total_notional = existing_notional + new_notional
    exposure_pct = total_notional / capital

    if exposure_pct > MAX_TOTAL_EXPOSURE_PCT:
        return RuleResult.fail(
            rule_name="check_total_exposure",
            block_reason=BlockReason.MAX_TOTAL_EXPOSURE,
            reason=f"total exposure {exposure_pct:.1%} > max {MAX_TOTAL_EXPOSURE_PCT:.0%}",
            exposure_pct=float(exposure_pct),
            max_exposure=MAX_TOTAL_EXPOSURE_PCT,
        )
    return RuleResult.ok(rule_name="check_total_exposure", reason=f"{exposure_pct:.1%} of capital")


def check_per_class_exposure(
    order: OrderCandidate, positions: list[Position], capital: Decimal
) -> RuleResult:
    """Verify per-asset-class exposure does not exceed 12% of capital.

    Crypto: symbols ending in USDT/BTC/ETH/BNB. All others: equity.

    Args:
        order:     Proposed order.
        positions: Currently open positions.
        capital:   Total portfolio capital.

    Returns:
        RuleResult.fail if class exposure > MAX_CLASS_EXPOSURE_PCT; ok otherwise.
    """
    if capital <= Decimal("0"):
        return RuleResult.ok(rule_name="check_per_class_exposure", reason="capital=0 skipped")

    new_class = _asset_class(order.symbol)
    class_notional = sum(
        p.size * p.entry_price for p in positions if _asset_class(p.symbol) == new_class
    )
    class_notional += order.size * order.entry
    class_pct = class_notional / capital

    if class_pct > MAX_CLASS_EXPOSURE_PCT:
        return RuleResult.fail(
            rule_name="check_per_class_exposure",
            block_reason=BlockReason.MAX_CLASS_EXPOSURE,
            reason=f"{new_class} exposure {class_pct:.1%} > max {MAX_CLASS_EXPOSURE_PCT:.0%}",
            asset_class=new_class,
            class_pct=float(class_pct),
        )
    return RuleResult.ok(
        rule_name="check_per_class_exposure", reason=f"{new_class} {class_pct:.1%}"
    )


def check_correlation(
    order: OrderCandidate,
    positions: list[Position],
    correlation_matrix: dict[tuple[str, str], float],
) -> RuleResult:
    """Block if new order has rho > 0.75 with any open position.

    Falls through OK if the symbol pair is not in correlation_matrix
    (fail-safe: missing data != block).

    Args:
        order:              Proposed order.
        positions:          Currently open positions.
        correlation_matrix: Symmetric dict (sym_a, sym_b) -> Pearson rho.

    Returns:
        RuleResult.fail if any pair exceeds CORRELATION_BLOCK_THRESHOLD; ok otherwise.

    Reference:
        Markowitz, H. (1952). Journal of Finance, 7(1), 77-91.
    """
    sym_new = order.symbol.upper()
    for pos in positions:
        sym_pos = pos.symbol.upper()
        if sym_new == sym_pos:
            # Same symbol -- trivially correlated (rho=1), always block
            rho = 1.0
        else:
            key1 = (sym_new, sym_pos)
            key2 = (sym_pos, sym_new)
            if key1 in correlation_matrix:
                rho = correlation_matrix[key1]
            elif key2 in correlation_matrix:
                rho = correlation_matrix[key2]
            else:
                continue  # Missing pair -> fail-safe: allow

        if rho > CORRELATION_BLOCK_THRESHOLD:
            return RuleResult.fail(
                rule_name="check_correlation",
                block_reason=BlockReason.HIGH_CORRELATION,
                reason=f"rho({sym_new},{sym_pos})={rho:.3f} > {CORRELATION_BLOCK_THRESHOLD}",
                rho=rho,
                symbol_a=sym_new,
                symbol_b=sym_pos,
            )

    return RuleResult.ok(rule_name="check_correlation", reason="no high-correlation pair")
