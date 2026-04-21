"""Risk-chain orchestrator for S05 (Chain of Responsibility).

Extracted from ``service.py`` as part of the Batch D SOLID-S decomposition
(STRATEGIC_AUDIT_2026-04-17 ACTION 25). This module owns the fail-fast
execution of the 5-step risk chain, with the 5.1 Fail-Closed Guard
sitting as STEP 0.

Chain order (fail-fast):

- STEP 0  Fail-Closed Guard    (ADR-0006 §D3 — heartbeat gate in O(1))
- STEP 1  CB Event Guard       (temporal — O(1) Redis lookup)
- STEP 2  Circuit Breaker      (state machine — O(1) Redis lookup)
- STEP 3  Meta-Label Gate      (statistical — O(1) Redis lookup)
- STEP 4  Position Rules ×4    (arithmetic — O(1) pure)
- STEP 5  Exposure Monitor ×4  (portfolio — O(n) positions)

Reference: Gamma, E. et al. (1994). Design Patterns. Chain of
Responsibility, p. 223.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.logger import get_logger
from core.models.order import OrderCandidate
from core.models.tick import Session
from services.risk_manager.cb_event_guard import CBEventGuard
from services.risk_manager.circuit_breaker import CircuitBreaker
from services.risk_manager.decision_builder import RiskDecisionBuilder
from services.risk_manager.exposure_monitor import (
    check_correlation,
    check_max_positions,
    check_per_class_exposure,
    check_total_exposure,
)
from services.risk_manager.fail_closed import FailClosedGuard
from services.risk_manager.meta_label_gate import MetaLabelGate
from services.risk_manager.models import (
    CB_SCALP_SIZE_MULTIPLIER,
    BlockReason,
    Position,
    RiskDecision,
    RuleResult,
)
from services.risk_manager.position_rules import (
    apply_crypto_multiplier,
    apply_session_multiplier,
    check_max_risk_per_trade,
    check_max_size,
    check_min_rr,
    check_stop_loss_present,
)

logger = get_logger("risk_manager.chain_orchestrator")


class RiskChainOrchestrator:
    """Runs the full S05 fail-fast risk chain for a single ``OrderCandidate``.

    Constructor injection of all collaborators keeps this class unit-testable
    in isolation (fake guards, fake context loader, fake builder). No direct
    Redis or bus dependency here — those live in the collaborators.

    Args:
        fail_closed: 5.1 Fail-Closed guard. STEP 0 of the chain.
        cb_guard: Central-bank event guard. STEP 1.
        circuit_breaker: Portfolio circuit breaker. STEP 2.
        meta_gate: Meta-label gate + Kelly modulation. STEP 3.
        context_load_fn: Callable ``(symbol) -> awaitable[dict]`` that
            returns the pre-trade context. Accepting a callable (rather
            than a :class:`ContextLoader` instance) keeps the test seam
            at ``service._load_context_parallel`` intact after the
            refactor.
        decision_builder: RiskDecision constructor + audit writer.
    """

    def __init__(
        self,
        *,
        fail_closed: FailClosedGuard,
        cb_guard: CBEventGuard,
        circuit_breaker: CircuitBreaker,
        meta_gate: MetaLabelGate,
        context_load_fn: Callable[[str], Awaitable[dict[str, Any]]],
        decision_builder: RiskDecisionBuilder,
    ) -> None:
        self._fail_closed = fail_closed
        self._cb_guard = cb_guard
        self._circuit_breaker = circuit_breaker
        self._meta_gate = meta_gate
        self._context_load_fn = context_load_fn
        self._builder = decision_builder

    async def process(self, candidate: OrderCandidate) -> RiskDecision:
        """Run the full chain and return a :class:`RiskDecision`.

        STEP 0 is the fail-closed guard (ADR-0006 §D3): it runs BEFORE
        the context load so a missing ``risk:heartbeat`` rejects the
        order in O(1) without attempting any further Redis reads. If
        the guard passes but the context load itself fails (a key-level
        freshness issue not yet reflected in the heartbeat), the order
        is also rejected with :attr:`BlockReason.SYSTEM_UNAVAILABLE`
        per ADR §D4.
        """
        rule_results: list[RuleResult] = []
        rationale: list[str] = []
        kelly_raw = candidate.kelly_fraction
        meta_confidence: float = 0.52
        kelly_final: float = kelly_raw

        # STEP 0: Fail-Closed Guard (ADR-0006 §D3) — BEFORE any context load.
        state, r0 = await self._fail_closed.check(candidate.order_id, candidate.symbol)
        rule_results.append(r0)
        rationale.append(r0.reason)
        if not r0.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r0.block_reason, kelly_raw, meta_confidence
            )

        # Context load — any failure rejects with SYSTEM_UNAVAILABLE (ADR-0006 §D4).
        try:
            ctx = await self._context_load_fn(candidate.symbol)
        except Exception as exc:
            logger.critical(
                "risk_system_unavailable_rejection",
                rejection_reason=BlockReason.SYSTEM_UNAVAILABLE.value,
                state=state.value,
                order_id=candidate.order_id,
                symbol=candidate.symbol,
                timestamp_utc=datetime.now(UTC).isoformat(),
                error=str(exc),
                phase="context_load",
            )
            r_load = RuleResult.fail(
                rule_name="context_load",
                block_reason=BlockReason.SYSTEM_UNAVAILABLE,
                reason=f"context load failed: {exc}",
                error=str(exc),
            )
            rule_results.append(r_load)
            rationale.append(r_load.reason)
            return await self._builder.build_blocked(
                candidate,
                rule_results,
                rationale,
                r_load.block_reason,
                kelly_raw,
                meta_confidence,
            )

        # STEP 1: CB Event Guard
        r1 = await self._cb_guard.check()
        rule_results.append(r1)
        rationale.append(r1.reason)
        if not r1.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r1.block_reason, kelly_raw, meta_confidence
            )
        in_scalp_window = await self._cb_guard.is_post_event_scalp_window()

        # STEP 2: Circuit Breaker
        r2 = await self._circuit_breaker.check(
            current_daily_pnl=ctx["daily_pnl"],
            starting_capital=ctx["capital"],
            intraday_loss_30m=ctx["intraday_loss_30m"],
            vix_current=ctx["vix_current"],
            vix_1h_ago=ctx["vix_1h_ago"],
            service_last_seen=ctx["service_last_seen"],
        )
        rule_results.append(r2)
        rationale.append(r2.reason)
        if not r2.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r2.block_reason, kelly_raw, meta_confidence
            )

        # STEP 3: Meta-Label Gate + Kelly modulation
        r3, meta_confidence, kelly_final = await self._meta_gate.check(candidate.symbol, kelly_raw)
        rule_results.append(r3)
        rationale.append(r3.reason)
        if not r3.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r3.block_reason, kelly_raw, meta_confidence
            )

        # STEP 4: Position Rules (4 blockers + 2 size modifiers)
        r_sl = check_stop_loss_present(candidate)
        rule_results.append(r_sl)
        rationale.append(r_sl.reason)
        if not r_sl.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_sl.block_reason, kelly_raw, meta_confidence
            )

        r_rr = check_min_rr(candidate)
        rule_results.append(r_rr)
        rationale.append(r_rr.reason)
        if not r_rr.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_rr.block_reason, kelly_raw, meta_confidence
            )

        r_risk = check_max_risk_per_trade(candidate, ctx["capital"])
        rule_results.append(r_risk)
        rationale.append(r_risk.reason)
        if not r_risk.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_risk.block_reason, kelly_raw, meta_confidence
            )

        r_sz = check_max_size(candidate, ctx["capital"])
        rule_results.append(r_sz)
        rationale.append(r_sz.reason)
        if not r_sz.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_sz.block_reason, kelly_raw, meta_confidence
            )

        # Size modifiers (non-blocking)
        current_size, r_crypto = apply_crypto_multiplier(candidate)
        rule_results.append(r_crypto)
        session: Session = ctx.get("session", Session.US_NORMAL)
        current_size, r_sess = apply_session_multiplier(candidate, session)
        rule_results.append(r_sess)
        if in_scalp_window:
            current_size = current_size * CB_SCALP_SIZE_MULTIPLIER
            rationale.append(f"post_event_scalp x{CB_SCALP_SIZE_MULTIPLIER}")

        # STEP 5: Exposure Monitor
        positions: list[Position] = ctx["positions"]
        capital: Decimal = ctx["capital"]
        corr: dict[tuple[str, str], float] = ctx["correlation_matrix"]

        r_pos = check_max_positions(positions)
        rule_results.append(r_pos)
        rationale.append(r_pos.reason)
        if not r_pos.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_pos.block_reason, kelly_raw, meta_confidence
            )

        r_exp = check_total_exposure(candidate, positions, capital)
        rule_results.append(r_exp)
        rationale.append(r_exp.reason)
        if not r_exp.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_exp.block_reason, kelly_raw, meta_confidence
            )

        r_cls = check_per_class_exposure(candidate, positions, capital)
        rule_results.append(r_cls)
        rationale.append(r_cls.reason)
        if not r_cls.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_cls.block_reason, kelly_raw, meta_confidence
            )

        r_corr = check_correlation(candidate, positions, corr)
        rule_results.append(r_corr)
        rationale.append(r_corr.reason)
        if not r_corr.passed:
            return await self._builder.build_blocked(
                candidate, rule_results, rationale, r_corr.block_reason, kelly_raw, meta_confidence
            )

        return await self._builder.build_approved(
            candidate,
            rule_results,
            rationale,
            kelly_raw,
            kelly_final,
            meta_confidence,
            current_size,
        )

    # ---------------------------------------------------------------- helpers
    # Kept for future-wire opportunities; no behavioural change vs the pre-
    # refactor service method.  Delegates to the context_loader so a caller
    # holding only the orchestrator can still load context in isolation.
    async def load_context(self, symbol: str) -> dict[str, Any]:
        return await self._context_load_fn(symbol)
