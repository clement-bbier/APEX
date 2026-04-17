"""Decision-envelope constructor + audit writer for S05 Risk Manager.

Extracted from ``service.py`` as part of the Batch D SOLID-S decomposition
(STRATEGIC_AUDIT_2026-04-17 ACTION 25). Responsible for producing the
immutable :class:`RiskDecision` envelope and persisting it to the Redis
audit trail. Does not make policy decisions; consumes rule results from
the :class:`chain_orchestrator.RiskChainOrchestrator`.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from core.logger import get_logger
from core.models.order import OrderCandidate
from services.s05_risk_manager.models import (
    REDIS_DECISION_HISTORY_KEY,
    REDIS_DECISION_HISTORY_MAX,
    REDIS_RISK_DECISION_TTL,
    BlockReason,
    RiskDecision,
    RuleResult,
)

logger = get_logger("s05_risk_manager.decision_builder")


class RiskDecisionBuilder:
    """Constructs :class:`RiskDecision` envelopes and writes the audit trail.

    Args:
        state: Redis state store used for the audit writes. Must expose
            ``set(key, value, ttl=...)``, ``lpush(key, value)``, and
            ``ltrim(key, start, end)`` as awaitables.
    """

    def __init__(self, state: Any) -> None:  # noqa: ANN401
        self._state = state

    async def build_approved(
        self,
        candidate: OrderCandidate,
        rule_results: list[RuleResult],
        rationale: list[str],
        kelly_raw: float,
        kelly_final: float,
        meta_confidence: float,
        final_size: Decimal,
    ) -> RiskDecision:
        decision = RiskDecision(
            order_id=candidate.order_id,
            symbol=candidate.symbol,
            approved=True,
            rule_results=rule_results,
            first_failure=None,
            kelly_fraction_raw=kelly_raw,
            kelly_fraction_final=kelly_final,
            meta_label_confidence=meta_confidence,
            final_size=final_size,
            rationale=rationale,
        )
        await self.audit(decision)
        return decision

    async def build_blocked(
        self,
        candidate: OrderCandidate,
        rule_results: list[RuleResult],
        rationale: list[str],
        first_failure: BlockReason | None,
        kelly_raw: float,
        meta_confidence: float,
    ) -> RiskDecision:
        decision = RiskDecision(
            order_id=candidate.order_id,
            symbol=candidate.symbol,
            approved=False,
            rule_results=rule_results,
            first_failure=first_failure,
            kelly_fraction_raw=kelly_raw,
            kelly_fraction_final=0.0,
            meta_label_confidence=meta_confidence,
            final_size=Decimal("0"),
            rationale=rationale,
        )
        await self.audit(decision)
        return decision

    async def audit(self, decision: RiskDecision) -> None:
        """Write decision to Redis audit trail (key + history list)."""
        try:
            data = decision.model_dump(mode="json")
            await asyncio.gather(
                self._state.set(
                    f"risk:audit:{decision.order_id}",
                    data,
                    ttl=REDIS_RISK_DECISION_TTL,
                ),
                self._state.lpush(REDIS_DECISION_HISTORY_KEY, data),
            )
            await self._state.ltrim(REDIS_DECISION_HISTORY_KEY, 0, REDIS_DECISION_HISTORY_MAX - 1)
        except Exception as exc:
            logger.error("audit_write_failed", error=str(exc))
