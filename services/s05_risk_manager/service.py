"""
S05 Risk Manager Service -- The Last Line of Defense.

Subscribes to ZMQ ORDER_CANDIDATE topic from S04 Fusion Engine.
For each candidate, runs the full Chain of Responsibility (5 steps, fail-fast).

Chain order (fail-fast):
    STEP 1  CB Event Guard          (temporal -- O(1) Redis lookup)
    STEP 2  Circuit Breaker         (state machine -- O(1) Redis lookup)
    STEP 3  Meta-Label Gate         (statistical -- O(1) Redis lookup)
    STEP 4  Position Rules x4       (arithmetic -- O(1) pure)
    STEP 5  Exposure Monitor x4     (portfolio -- O(n) positions)

Reference:
    Gamma, E. et al. (1994). Design Patterns. Chain of Responsibility, p. 223.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.base_service import BaseService
from core.models.order import OrderCandidate
from core.models.signal import Direction
from core.models.tick import Session
from core.state import SystemRiskMonitor
from core.topics import Topics
from services.s05_risk_manager.cb_event_guard import CBEventGuard
from services.s05_risk_manager.circuit_breaker import CircuitBreaker
from services.s05_risk_manager.exposure_monitor import (
    check_correlation,
    check_max_positions,
    check_per_class_exposure,
    check_total_exposure,
)
from services.s05_risk_manager.fail_closed import FailClosedGuard
from services.s05_risk_manager.meta_label_gate import MetaLabelGate
from services.s05_risk_manager.models import (
    CB_SCALP_SIZE_MULTIPLIER,
    REDIS_DECISION_HISTORY_KEY,
    REDIS_DECISION_HISTORY_MAX,
    REDIS_RISK_DECISION_TTL,
    BlockReason,
    Position,
    RiskDecision,
    RuleResult,
)
from services.s05_risk_manager.position_rules import (
    apply_crypto_multiplier,
    apply_session_multiplier,
    check_max_risk_per_trade,
    check_max_size,
    check_min_rr,
    check_stop_loss_present,
)


class RiskManagerService(BaseService):
    """S05 Risk Manager -- Chain of Responsibility pipeline."""

    service_id = "s05_risk_manager"

    def __init__(self) -> None:
        super().__init__(self.service_id)
        self._cb_guard: CBEventGuard | None = None
        self._circuit_breaker: CircuitBreaker | None = None
        self._meta_gate: MetaLabelGate | None = None
        self._monitor: SystemRiskMonitor | None = None
        self._fail_closed: FailClosedGuard | None = None
        self._risk_heartbeat_task: asyncio.Task[None] | None = None

    async def on_start(self) -> None:
        """Initialize Redis-backed components after state is connected.

        The fail-closed guard and its heartbeat refresher are initialized
        eagerly (ADR-0006 §D2 + Consequences): the first heartbeat lands on
        Redis *before* :meth:`run` subscribes to ``ORDER_CANDIDATE``, so the
        very first incoming order observes ``HEALTHY`` (or the correctly
        reported ``DEGRADED`` / ``UNAVAILABLE`` if Redis is already sick).
        """
        redis = self.state.client
        self._cb_guard = CBEventGuard(redis)
        self._circuit_breaker = CircuitBreaker(redis)
        self._meta_gate = MetaLabelGate(redis)
        self._monitor = SystemRiskMonitor(redis, self.bus)
        self._fail_closed = FailClosedGuard(self._monitor)
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
        """Bring the risk chain online and dispatch order candidates.

        BaseService already opened the PUB socket and started the heartbeat
        loop; here we initialise the Redis-backed risk components and then
        block on :meth:`bus.subscribe` until shutdown.
        """
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

    async def process_order_candidate(self, candidate: OrderCandidate) -> RiskDecision:
        """Run the full chain and return a RiskDecision.

        STEP 0 is the fail-closed guard (ADR-0006 §D3): it runs BEFORE the
        context load so a missing ``risk:heartbeat`` rejects the order in
        O(1) without attempting any further Redis reads. If the guard
        passes but the context load itself fails (a key-level freshness
        issue not yet reflected in the heartbeat), the order is also
        rejected with ``BlockReason.SYSTEM_UNAVAILABLE`` per ADR §D4.
        """
        assert self._cb_guard is not None
        assert self._circuit_breaker is not None
        assert self._meta_gate is not None
        assert self._fail_closed is not None

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
            return await self._build_blocked(
                candidate, rule_results, rationale, r0.block_reason, kelly_raw, meta_confidence
            )

        # Context load — any failure rejects with SYSTEM_UNAVAILABLE (ADR-0006 §D4).
        try:
            ctx = await self._load_context_parallel(candidate.symbol)
        except Exception as exc:
            self.logger.critical(
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
            return await self._build_blocked(
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
            return await self._build_blocked(
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
            return await self._build_blocked(
                candidate, rule_results, rationale, r2.block_reason, kelly_raw, meta_confidence
            )

        # STEP 3: Meta-Label Gate + Kelly modulation
        r3, meta_confidence, kelly_final = await self._meta_gate.check(candidate.symbol, kelly_raw)
        rule_results.append(r3)
        rationale.append(r3.reason)
        if not r3.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r3.block_reason, kelly_raw, meta_confidence
            )

        # STEP 4: Position Rules (4 blockers + 2 size modifiers)
        r_sl = check_stop_loss_present(candidate)
        rule_results.append(r_sl)
        rationale.append(r_sl.reason)
        if not r_sl.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_sl.block_reason, kelly_raw, meta_confidence
            )

        r_rr = check_min_rr(candidate)
        rule_results.append(r_rr)
        rationale.append(r_rr.reason)
        if not r_rr.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_rr.block_reason, kelly_raw, meta_confidence
            )

        r_risk = check_max_risk_per_trade(candidate, ctx["capital"])
        rule_results.append(r_risk)
        rationale.append(r_risk.reason)
        if not r_risk.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_risk.block_reason, kelly_raw, meta_confidence
            )

        r_sz = check_max_size(candidate, ctx["capital"])
        rule_results.append(r_sz)
        rationale.append(r_sz.reason)
        if not r_sz.passed:
            return await self._build_blocked(
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
            return await self._build_blocked(
                candidate, rule_results, rationale, r_pos.block_reason, kelly_raw, meta_confidence
            )

        r_exp = check_total_exposure(candidate, positions, capital)
        rule_results.append(r_exp)
        rationale.append(r_exp.reason)
        if not r_exp.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_exp.block_reason, kelly_raw, meta_confidence
            )

        r_cls = check_per_class_exposure(candidate, positions, capital)
        rule_results.append(r_cls)
        rationale.append(r_cls.reason)
        if not r_cls.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_cls.block_reason, kelly_raw, meta_confidence
            )

        r_corr = check_correlation(candidate, positions, corr)
        rule_results.append(r_corr)
        rationale.append(r_corr.reason)
        if not r_corr.passed:
            return await self._build_blocked(
                candidate, rule_results, rationale, r_corr.block_reason, kelly_raw, meta_confidence
            )

        return await self._build_approved(
            candidate,
            rule_results,
            rationale,
            kelly_raw,
            kelly_final,
            meta_confidence,
            current_size,
        )

    async def _build_approved(
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
        await self._audit(decision)
        return decision

    async def _build_blocked(
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
        await self._audit(decision)
        return decision

    async def _audit(self, decision: RiskDecision) -> None:
        """Write decision to Redis audit trail (key + history list)."""
        try:
            data = decision.model_dump_json()
            await asyncio.gather(
                self.state.set(
                    f"risk:audit:{decision.order_id}",
                    json.loads(data),
                    ttl=REDIS_RISK_DECISION_TTL,
                ),
                self.state.lpush(REDIS_DECISION_HISTORY_KEY, data),
                return_exceptions=True,
            )
            await self.state.ltrim(REDIS_DECISION_HISTORY_KEY, 0, REDIS_DECISION_HISTORY_MAX - 1)
        except Exception as exc:
            self.logger.error("audit_write_failed", error=str(exc))

    async def _load_context_parallel(self, symbol: str) -> dict[str, Any]:
        """Batch all Redis reads in parallel before the chain starts.

        Fail-loud per ADR-0006 §D4: if any required key is missing, ``None``,
        or malformed, the call raises :class:`RuntimeError`. No ``_safe()``
        helper, no heuristic defaults. :meth:`process_order_candidate`
        converts any raise here into a ``BlockReason.SYSTEM_UNAVAILABLE``
        rejection. The :class:`FailClosedGuard` (STEP 0) is expected to
        intercept system-level unavailability upstream of this method.
        """
        keys = (
            "portfolio:capital",
            "pnl:daily",
            "pnl:intraday_30m",
            "macro:vix_current",
            "macro:vix_1h_ago",
            "portfolio:positions",
            "correlation:matrix",
            "session:current",
        )
        results = await asyncio.gather(*(self.state.get(k) for k in keys))

        def _require(name: str, value: Any | None) -> Any:  # noqa: ANN401
            if value is None:
                raise RuntimeError(f"required pre-trade context key missing or None: {name}")
            return value

        cap_raw = _require("portfolio:capital", results[0])
        if not isinstance(cap_raw, dict) or "available" not in cap_raw:
            raise RuntimeError(f"portfolio:capital malformed: {cap_raw!r}")
        capital = Decimal(str(cap_raw["available"]))

        daily_pnl = Decimal(str(_require("pnl:daily", results[1])))
        intraday_30m = Decimal(str(_require("pnl:intraday_30m", results[2])))
        vix_current = float(_require("macro:vix_current", results[3]))
        vix_1h_ago = float(_require("macro:vix_1h_ago", results[4]))

        raw_pos = _require("portfolio:positions", results[5])
        if not isinstance(raw_pos, list):
            raise RuntimeError(
                f"portfolio:positions malformed: expected list, got {type(raw_pos).__name__}"
            )
        positions: list[Position] = []
        for p in raw_pos:
            try:
                positions.append(Position.model_validate(p))
            except Exception as exc:
                # Per-element parse failure is not fatal (broker feeds may
                # include unknown-type entries); log and skip.
                self.logger.debug("position_decode_failed", error=str(exc))

        corr_raw = _require("correlation:matrix", results[6])
        if not isinstance(corr_raw, dict):
            raise RuntimeError(
                f"correlation:matrix malformed: expected dict, got {type(corr_raw).__name__}"
            )
        corr: dict[tuple[str, str], float] = {}
        for k, v in corr_raw.items():
            parts = str(k).split(":")
            if len(parts) != 2:
                continue
            try:
                corr[(parts[0], parts[1])] = float(v)
            except (ValueError, TypeError) as exc:
                self.logger.debug(
                    "correlation_decode_failed",
                    key=str(k),
                    error=str(exc),
                )

        session_raw = _require("session:current", results[7])
        try:
            session: Session = Session(str(session_raw))
        except ValueError as exc:
            raise RuntimeError(f"session:current invalid value: {session_raw!r}") from exc

        return {
            "capital": capital,
            "daily_pnl": daily_pnl,
            "intraday_loss_30m": intraday_30m,
            "vix_current": vix_current,
            "vix_1h_ago": vix_1h_ago,
            "service_last_seen": {},
            "positions": positions,
            "correlation_matrix": corr,
            "session": session,
        }

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
