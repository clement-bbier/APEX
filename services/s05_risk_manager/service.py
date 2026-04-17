"""
S05 Risk Manager Service -- The Last Line of Defense.

Subscribes to ZMQ ORDER_CANDIDATE topic from S04 Fusion Engine. For each
candidate, the :class:`chain_orchestrator.RiskChainOrchestrator` runs the
full 6-step Chain of Responsibility (STEP 0 Fail-Closed + STEPS 1-5
risk rules) with fail-fast semantics per ADR-0006.

The service itself is a thin lifecycle + dispatch layer. Chain logic,
context loading, and decision construction all live in sibling modules
(``chain_orchestrator.py``, ``context_loader.py``, ``decision_builder.py``)
per the Batch D SOLID-S decomposition (STRATEGIC_AUDIT_2026-04-17
ACTION 25).

Reference:
    Gamma, E. et al. (1994). Design Patterns. Chain of Responsibility, p. 223.
"""

from __future__ import annotations

import asyncio
import time
import uuid as _uuid
from decimal import Decimal
from typing import Any

from core.base_service import BaseService
from core.models.order import OrderCandidate
from core.models.signal import Direction
from core.state import SystemRiskMonitor
from core.topics import Topics
from services.s05_risk_manager.cb_event_guard import CBEventGuard
from services.s05_risk_manager.chain_orchestrator import RiskChainOrchestrator
from services.s05_risk_manager.circuit_breaker import CircuitBreaker
from services.s05_risk_manager.context_loader import ContextLoader
from services.s05_risk_manager.decision_builder import RiskDecisionBuilder
from services.s05_risk_manager.fail_closed import FailClosedGuard
from services.s05_risk_manager.meta_label_gate import MetaLabelGate
from services.s05_risk_manager.models import RiskDecision


class RiskManagerService(BaseService):
    """S05 Risk Manager -- thin lifecycle + dispatch wrapper."""

    service_id = "s05_risk_manager"

    def __init__(self) -> None:
        super().__init__(self.service_id)
        self._cb_guard: CBEventGuard | None = None
        self._circuit_breaker: CircuitBreaker | None = None
        self._meta_gate: MetaLabelGate | None = None
        self._monitor: SystemRiskMonitor | None = None
        self._fail_closed: FailClosedGuard | None = None
        self._context_loader: ContextLoader | None = None
        self._decision_builder: RiskDecisionBuilder | None = None
        self._orchestrator: RiskChainOrchestrator | None = None
        self._risk_heartbeat_task: asyncio.Task[None] | None = None

    async def on_start(self) -> None:
        """Initialize Redis-backed components after state is connected.

        The fail-closed guard and its heartbeat refresher are initialized
        eagerly (ADR-0006 §D2 + Consequences): the first heartbeat lands
        on Redis *before* :meth:`run` subscribes to ``ORDER_CANDIDATE``,
        so the very first incoming order observes ``HEALTHY`` (or the
        correctly reported ``DEGRADED`` / ``UNAVAILABLE`` if Redis is
        already sick).
        """
        redis = self.state.client
        self._cb_guard = CBEventGuard(redis)
        self._circuit_breaker = CircuitBreaker(redis)
        self._meta_gate = MetaLabelGate(redis)
        self._monitor = SystemRiskMonitor(redis, self.bus)
        self._fail_closed = FailClosedGuard(self._monitor)
        self._context_loader = ContextLoader(self.state)
        self._decision_builder = RiskDecisionBuilder(self.state)
        self._orchestrator = RiskChainOrchestrator(
            fail_closed=self._fail_closed,
            cb_guard=self._cb_guard,
            circuit_breaker=self._circuit_breaker,
            meta_gate=self._meta_gate,
            context_load_fn=lambda sym: self._load_context_parallel(sym),
            decision_builder=self._decision_builder,
        )
        # ADR-0006 §D2 Consequences: eager heartbeat BEFORE subscribe.
        await self._monitor.write_heartbeat()
        self._risk_heartbeat_task = asyncio.create_task(self._monitor.run_heartbeat_loop())
        snap = await self._circuit_breaker.get_snapshot()
        self.logger.info(
            "risk_manager_started",
            cb_state=snap.state.value,
            daily_pnl=str(snap.daily_pnl),
        )

    def get_subscribe_topics(self) -> list[str]:
        return [Topics.ORDER_CANDIDATE]

    async def run(self) -> None:
        """Bring the risk chain online and dispatch order candidates."""
        await self.on_start()
        topics = self.get_subscribe_topics()
        self.logger.info("risk_manager_subscribing", topics=topics)
        try:
            await self.bus.subscribe(topics, self.on_message)
        except asyncio.CancelledError:
            self.logger.info("risk_manager_subscribe_cancelled")
            raise

    async def stop(self) -> None:
        """Cancel the fail-closed heartbeat loop, then delegate to BaseService."""
        task = self._risk_heartbeat_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._risk_heartbeat_task = None
        await super().stop()

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Process an incoming order candidate."""
        try:
            candidate = OrderCandidate.model_validate(data)
            decision = await self.process_order_candidate(candidate)
            decision_dict = decision.model_dump(mode="json")
            tasks: list[Any] = [self.bus.publish(Topics.RISK_AUDIT, decision_dict)]
            if decision.approved:
                tasks.append(self.bus.publish(Topics.RISK_APPROVED, decision_dict))
            else:
                tasks.append(self.bus.publish(Topics.RISK_BLOCKED, decision_dict))
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            self.logger.error("on_message_error", topic=topic, error=str(exc))

    def _ensure_orchestrator(self) -> RiskChainOrchestrator:
        """Lazily build the orchestrator from wired collaborators.

        Supports both the production path (``on_start`` assigns
        ``_orchestrator``) and unit-test fixtures that wire collaborators
        individually while bypassing ``on_start``.
        """
        orch: RiskChainOrchestrator | None = getattr(self, "_orchestrator", None)
        if orch is not None:
            return orch
        fc = getattr(self, "_fail_closed", None)
        cbg = getattr(self, "_cb_guard", None)
        cb = getattr(self, "_circuit_breaker", None)
        mg = getattr(self, "_meta_gate", None)
        if fc is None:
            raise RuntimeError("FailClosedGuard not initialised")
        if cbg is None:
            raise RuntimeError("CBEventGuard not initialised")
        if cb is None:
            raise RuntimeError("CircuitBreaker not initialised")
        if mg is None:
            raise RuntimeError("MetaLabelGate not initialised")
        loader = getattr(self, "_context_loader", None)
        if loader is None:
            loader = ContextLoader(self.state)
            self._context_loader = loader
        builder = getattr(self, "_decision_builder", None)
        if builder is None:
            builder = RiskDecisionBuilder(self.state)
            self._decision_builder = builder
        self._orchestrator = RiskChainOrchestrator(
            fail_closed=fc,
            cb_guard=cbg,
            circuit_breaker=cb,
            meta_gate=mg,
            context_load_fn=lambda sym: self._load_context_parallel(sym),
            decision_builder=builder,
        )
        return self._orchestrator

    async def process_order_candidate(self, candidate: OrderCandidate) -> RiskDecision:
        """Run the full chain and return a :class:`RiskDecision`.

        Thin delegate kept as public API for existing tests
        (``tests/unit/s05/test_service_no_fallbacks.py`` and siblings).
        Actual logic lives in :class:`RiskChainOrchestrator`.
        """
        return await self._ensure_orchestrator().process(candidate)

    async def _load_context_parallel(self, symbol: str) -> dict[str, Any]:
        """Backward-compat shim for tests that call the old private method.

        Delegates to :class:`ContextLoader`. New call sites should use
        ``self._context_loader.load(symbol)`` directly.
        """
        loader = getattr(self, "_context_loader", None)
        if loader is None:
            loader = ContextLoader(self.state)
            self._context_loader = loader
        return await loader.load(symbol)

    async def _benchmark_latency(self) -> None:
        """Benchmark chain latency at startup. Target: p99 < 5ms."""
        try:
            sz = Decimal("0.01")
            synthetic = OrderCandidate(
                order_id=str(_uuid.uuid4()),
                symbol="AAPL",
                direction=Direction.LONG,
                timestamp_ms=1_700_000_000_000,
                size=sz,
                size_scalp_exit=sz * Decimal("0.35"),
                size_swing_exit=sz * Decimal("0.65"),
                entry=Decimal("150"),
                stop_loss=Decimal("148"),
                target_scalp=Decimal("152.25"),
                target_swing=Decimal("155"),
                capital_at_risk=Decimal("2"),
                kelly_fraction=0.25,
            )
            times: list[float] = []
            for _ in range(100):
                t0 = time.monotonic()
                await self.process_order_candidate(synthetic)
                times.append((time.monotonic() - t0) * 1000)
            times.sort()
            p99 = times[98]
            self.logger.info(
                "risk_chain_latency_benchmark",
                p50_ms=round(times[49], 2),
                p95_ms=round(times[94], 2),
                p99_ms=round(p99, 2),
                target_ms=5.0,
                ok=(p99 < 5.0),
            )
        except Exception as exc:
            self.logger.warning("benchmark_failed", error=str(exc))


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
