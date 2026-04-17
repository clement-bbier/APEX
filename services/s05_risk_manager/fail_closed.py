"""Fail-Closed Pre-Trade Guard — STEP 0 of the S05 risk chain.

Wraps every :class:`~core.models.order.OrderCandidate` with a synchronous
:class:`~core.state.SystemRiskState` check. When the system risk state is
not ``HEALTHY``, emits a critical structlog rejection event and returns a
:meth:`~services.s05_risk_manager.models.RuleResult.fail` carrying
:attr:`~services.s05_risk_manager.models.BlockReason.SYSTEM_UNAVAILABLE`.

See docs/adr/ADR-0006-fail-closed-risk-controls.md §D3 and §D8.

Reference:
    SEC Rule 15c3-5 (Market Access Rule), 17 CFR § 240.15c3-5.
    Knight Capital Group post-mortem (2012-08-01), SEC Release No. 70694.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import structlog

from core.state import SystemRiskMonitor, SystemRiskState
from services.s05_risk_manager.models import BlockReason, RuleResult

logger = structlog.get_logger(__name__)


class FailClosedGuard:
    """Outermost shell of the S05 risk chain — first gate, latency < 1 ms.

    Calls :meth:`SystemRiskMonitor.current_state` on every ``OrderCandidate``
    and maps the observed :class:`SystemRiskState` to a :class:`RuleResult`.
    When state is not ``HEALTHY``, emits a critical ``structlog`` rejection
    event matching the 5-field contract in ADR-0006 §D8 and returns
    :meth:`RuleResult.fail` with :attr:`BlockReason.SYSTEM_UNAVAILABLE`.

    The guard is pure-function-style: it owns no mutable state and performs
    no retries. All state lives in :class:`SystemRiskMonitor`. This keeps
    the guard trivially composable with any future
    :class:`SystemRiskMonitor`-compatible backend (e.g. the in-memory
    event-sourced state introduced by sub-phase 5.2) without touching the
    guard's contract.

    Args:
        monitor: :class:`SystemRiskMonitor` instance that owns the
            ``risk:heartbeat`` Redis read path and publishes transitions on
            :attr:`~core.topics.Topics.RISK_SYSTEM_STATE_CHANGE`.
    """

    RULE_NAME: str = "fail_closed_guard"

    def __init__(self, monitor: SystemRiskMonitor) -> None:
        self._monitor = monitor

    async def check(self, order_id: str, symbol: str) -> tuple[SystemRiskState, RuleResult]:
        """Synchronous per-order state check.

        Args:
            order_id: UUID of the incoming ``OrderCandidate``. Emitted in
                the rejection log so every blocked order is traceable.
            symbol: Symbol of the incoming order (same rationale).

        Returns:
            ``(state, rule_result)``. ``rule_result.passed`` is ``True``
            iff ``state == HEALTHY``; otherwise the result carries
            :attr:`BlockReason.SYSTEM_UNAVAILABLE` and the S05 service will
            short-circuit into the canonical blocked-order path.
        """
        state, heartbeat_age_seconds, redis_reachable = await self._monitor.current_state()

        if state == SystemRiskState.HEALTHY:
            return state, RuleResult.ok(
                rule_name=self.RULE_NAME,
                reason="system risk state is healthy",
            )

        logger.critical(
            "risk_system_unavailable_rejection",
            rejection_reason=BlockReason.SYSTEM_UNAVAILABLE.value,
            state=state.value,
            order_id=order_id,
            symbol=symbol,
            timestamp_utc=datetime.now(UTC).isoformat(),
        )

        meta_age = heartbeat_age_seconds if math.isfinite(heartbeat_age_seconds) else -1.0
        return state, RuleResult.fail(
            rule_name=self.RULE_NAME,
            block_reason=BlockReason.SYSTEM_UNAVAILABLE,
            reason=f"system risk state is {state.value}",
            state=state.value,
            heartbeat_age_seconds=meta_age,
            redis_reachable=redis_reachable,
        )
