"""S05 Risk Manager service for APEX Trading System.

Subscribes to ``order.candidate`` messages, runs every order through a
multi-layer validation pipeline, and publishes approved or blocked orders.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

from core.base_service import BaseService
from core.config import get_settings
from core.models.order import ApprovedOrder, NullOrder, OrderCandidate, OrderType
from services.s05_risk_manager.cb_event_guard import CBEventGuard
from services.s05_risk_manager.circuit_breaker import CircuitBreaker
from services.s05_risk_manager.exposure_monitor import ExposureMonitor
from services.s05_risk_manager.position_rules import PositionRules

_CANDIDATE_TOPIC = "order.candidate"
_APPROVED_TOPIC = "order.approved"
_BLOCKED_TOPIC = "order.blocked"
_CB_CHECK_INTERVAL_S: int = 30


class RiskManagerService(BaseService):
    """Validates order candidates and routes them to approval or blocking.

    For each ``order.candidate`` message:

    1. :class:`~.circuit_breaker.CircuitBreaker` – abort immediately if open.
    2. :class:`~.position_rules.PositionRules` – check per-trade risk limits.
    3. :class:`~.exposure_monitor.ExposureMonitor` – check portfolio exposure.
    4. :class:`~.cb_event_guard.CBEventGuard` – enforce CB-event windows.

    Approved orders are published on ``order.approved`` and stored in Redis.
    Blocked orders are published on ``order.blocked``.

    A background task runs every 30 seconds to check the daily P&L from
    Redis and trip the circuit breaker if the drawdown limit is breached.
    """

    service_id = "s05_risk_manager"

    def __init__(self) -> None:
        """Initialize risk components and ZMQ pub/sub."""
        super().__init__(self.service_id)
        settings = get_settings()
        self._breaker = CircuitBreaker(settings)
        self._rules = PositionRules()
        self._exposure = ExposureMonitor()
        self._cb_guard = CBEventGuard()
        self.bus.init_publisher()

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Parse an incoming order candidate and run the validation pipeline.

        Args:
            topic: ZMQ topic string.
            data:  JSON-decoded message payload.
        """
        try:
            candidate = OrderCandidate.model_validate(data)
            await self._validate(candidate)
        except Exception as exc:
            self.logger.error(
                "Error processing order candidate",
                topic=topic,
                error=str(exc),
                exc_info=exc,
            )

    async def run(self) -> None:
        """Subscribe to candidate topics and start the periodic CB check."""
        self.logger.info("RiskManagerService starting", service=self.service_id)
        cb_task = asyncio.create_task(self._periodic_circuit_check())
        try:
            await self.bus.subscribe([_CANDIDATE_TOPIC], self.on_message)
        except asyncio.CancelledError:
            self.logger.info("RiskManagerService subscribe loop cancelled")
            cb_task.cancel()
            raise

    # ── Validation pipeline ───────────────────────────────────────────────────

    async def _validate(self, candidate: OrderCandidate) -> None:
        """Run the full validation pipeline for one order candidate.

        Args:
            candidate: The order candidate to validate.
        """
        now_ms = int(time.time() * 1000)
        settings = get_settings()
        capital: Decimal = settings.initial_capital

        # ── 1. Circuit breaker ─────────────────────────────────────────────────
        self._breaker.attempt_reset()
        if self._breaker.is_open:
            await self._block(
                candidate,
                now_ms,
                reason=f"circuit breaker open: {self._breaker.trip_reason}",
                blocker="circuit_breaker",
            )
            return

        # ── 2. Position rules ──────────────────────────────────────────────────
        ok, reason = self._rules.validate(candidate, capital, settings)
        if not ok:
            await self._block(candidate, now_ms, reason=reason, blocker="position_rules")
            return

        # ── 3. Exposure monitor ────────────────────────────────────────────────
        ok, reason = await self._exposure.check_exposure(candidate, self.state, capital, settings)
        if not ok:
            await self._block(candidate, now_ms, reason=reason, blocker="exposure_monitor")
            return

        # ── 4. CB event guard ──────────────────────────────────────────────────
        allowed, size_mult = await self._cb_guard.check(self.state)
        if not allowed:
            await self._block(
                candidate, now_ms, reason="CB event pre-block active", blocker="cb_event_guard"
            )
            return

        # ── Approve ────────────────────────────────────────────────────────────
        adjusted_size = candidate.size * Decimal(str(size_mult))
        approved = ApprovedOrder(
            candidate=candidate,
            approved_at_ms=now_ms,
            regime_mult=size_mult,
            adjusted_size=adjusted_size,
            order_type=OrderType.LIMIT,
            notes=([f"post_event_scalp size_mult={size_mult}"] if size_mult < 1.0 else []),
        )

        approved_dict = approved.model_dump(mode="json")
        await asyncio.gather(
            self.bus.publish(_APPROVED_TOPIC, approved_dict),
            self.state.set(f"approved:{candidate.order_id}", approved_dict),
        )

        self.logger.info(
            "Order approved",
            order_id=candidate.order_id,
            symbol=candidate.symbol,
            size=str(adjusted_size),
            size_mult=size_mult,
        )

    async def _block(
        self,
        candidate: OrderCandidate,
        now_ms: int,
        reason: str,
        blocker: str,
    ) -> None:
        """Publish a :class:`~core.models.order.NullOrder` to signal a block.

        Args:
            candidate: The order being blocked.
            now_ms:    Current timestamp in UTC milliseconds.
            reason:    Human-readable block reason.
            blocker:   Name of the component that triggered the block.
        """
        null_order = NullOrder(
            candidate_id=candidate.order_id,
            blocked_at_ms=now_ms,
            reason=reason,
            blocker=blocker,
        )
        await self.bus.publish(_BLOCKED_TOPIC, null_order.model_dump(mode="json"))
        self.logger.info(
            "Order blocked",
            order_id=candidate.order_id,
            symbol=candidate.symbol,
            blocker=blocker,
            reason=reason,
        )

    # ── Periodic circuit-breaker check ────────────────────────────────────────

    async def _periodic_circuit_check(self) -> None:
        """Periodically read daily P&L from Redis and trip the breaker if needed."""
        while self._running:
            try:
                await asyncio.sleep(_CB_CHECK_INTERVAL_S)
                daily_pnl_raw = await self.state.get("pnl:daily_pct")
                if daily_pnl_raw is not None:
                    daily_pnl_pct = float(daily_pnl_raw)
                    if self._breaker.check_daily_drawdown(daily_pnl_pct):
                        self._breaker.trip(f"daily drawdown {daily_pnl_pct:.2f}% exceeded limit")
                        await self.state.set(
                            "circuit_breaker:state",
                            "open",
                        )
                        self.logger.warning(
                            "Circuit breaker tripped",
                            reason=self._breaker.trip_reason,
                        )
                    elif self._breaker.is_open:
                        self._breaker.attempt_reset()
                        await self.state.set(
                            "circuit_breaker:state",
                            self._breaker.state.value,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(
                    "Periodic circuit check error",
                    error=str(exc),
                    exc_info=exc,
                )
