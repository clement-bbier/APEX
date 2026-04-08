"""
Circuit Breaker -- Catastrophic Loss Prevention State Machine.

Three-state circuit breaker (CLOSED -> OPEN -> HALF_OPEN) that halts
all trading when loss thresholds are exceeded. Redis-persisted state
ensures a service restart does NOT reset a tripped breaker.

State transitions:
    CLOSED    -> OPEN      : any trigger condition exceeded
    OPEN      -> HALF_OPEN : after HALF_OPEN_RECOVERY_MINUTES cooldown
    HALF_OPEN -> CLOSED    : probe order succeeds (PnL >= 0)
    HALF_OPEN -> OPEN      : probe order fails (PnL < 0) -> reset cooldown

Trigger conditions (evaluated in priority order):
    1. Daily drawdown   > MAX_DAILY_LOSS_PCT (3%)
    2. 30min loss       > MAX_INTRADAY_LOSS_30M_PCT (2%)
    3. VIX spike        > VIX_SPIKE_THRESHOLD_PCT (+20% in 1h)
    4. Critical service down > SERVICE_DOWN_SECONDS (60s)

The CB event trigger (#5 in MANIFEST) is handled separately
by CBEventGuard (OBJ-4) -- cleaner separation of concerns.

Reference:
    Nygard, M.T. (2007). Release It! Pragmatic Bookshelf. Ch. 5.
    NYSE Rule 80B (market-wide circuit breakers) -- institutional precedent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from redis.asyncio import Redis

from services.s05_risk_manager.models import (
    HALF_OPEN_RECOVERY_MINUTES,
    MAX_DAILY_LOSS_PCT,
    MAX_INTRADAY_LOSS_30M_PCT,
    REDIS_CB_KEY,
    REDIS_CB_TTL,
    SERVICE_DOWN_SECONDS,
    VIX_SPIKE_THRESHOLD_PCT,
    BlockReason,
    CircuitBreakerSnapshot,
    CircuitBreakerState,
    RuleResult,
)

logger = structlog.get_logger(__name__)


class CircuitBreaker:
    """Redis-persisted three-state circuit breaker.

    All state mutations are persisted in Redis with a 24h TTL.
    A service restart does NOT reset a tripped breaker.

    Args:
        redis: Async Redis client instance.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(
        self,
        current_daily_pnl: Decimal,
        starting_capital: Decimal,
        intraday_loss_30m: Decimal,
        vix_current: float,
        vix_1h_ago: float,
        service_last_seen: dict[str, datetime],
    ) -> RuleResult:
        """Evaluate all triggers and return a RuleResult.

        Args:
            current_daily_pnl:  Today's cumulative P&L (negative = loss).
            starting_capital:   Capital at start of day (Decimal("0") safe).
            intraday_loss_30m:  Cumulative loss in last 30 minutes (negative = loss).
            vix_current:        Current VIX level.
            vix_1h_ago:         VIX level one hour ago.
            service_last_seen:  Map of service_id -> last heartbeat datetime.

        Returns:
            RuleResult.ok if CLOSED/HALF_OPEN and no triggers.
            RuleResult.fail with appropriate BlockReason otherwise.
        """
        snapshot = await self._load_snapshot()
        now = datetime.now(UTC)

        if snapshot.state == CircuitBreakerState.OPEN:
            snapshot = await self._try_half_open(snapshot, now)

        if snapshot.state == CircuitBreakerState.OPEN:
            return RuleResult.fail(
                rule_name="circuit_breaker",
                block_reason=BlockReason.CIRCUIT_BREAKER_OPEN,
                reason=(
                    f"Circuit breaker OPEN since {snapshot.tripped_at}: {snapshot.tripped_reason}"
                ),
            )

        # HALF_OPEN: allow probe order through without re-evaluating triggers.
        # record_trade_result() handles the HALF_OPEN -> CLOSED/OPEN transition.
        if snapshot.state == CircuitBreakerState.HALF_OPEN:
            return RuleResult.ok(rule_name="circuit_breaker", reason="CB HALF_OPEN probe allowed")

        trigger = self._evaluate_triggers(
            current_daily_pnl=current_daily_pnl,
            starting_capital=starting_capital,
            intraday_loss_30m=intraday_loss_30m,
            vix_current=vix_current,
            vix_1h_ago=vix_1h_ago,
            service_last_seen=service_last_seen,
            now=now,
        )

        if trigger is not None:
            await self._trip(snapshot, trigger, current_daily_pnl, starting_capital)
            return RuleResult.fail(
                rule_name="circuit_breaker",
                block_reason=trigger,
                reason=f"Circuit breaker tripped: {trigger.value}",
            )

        return RuleResult.ok(rule_name="circuit_breaker", reason=f"CB {snapshot.state.value}")

    async def record_trade_result(self, pnl: Decimal) -> None:
        """Update CB state after a probe trade (HALF_OPEN only).

        HALF_OPEN + pnl >= 0 -> CLOSED
        HALF_OPEN + pnl < 0  -> OPEN (reset cooldown)

        Args:
            pnl: Net P&L of the probe trade.
        """
        snapshot = await self._load_snapshot()
        if snapshot.state != CircuitBreakerState.HALF_OPEN:
            return

        now = datetime.now(UTC)
        if pnl >= Decimal("0"):
            new_snap = CircuitBreakerSnapshot(
                state=CircuitBreakerState.CLOSED,
                tripped_at=None,
                tripped_reason=None,
                daily_pnl=snapshot.daily_pnl + pnl,
                daily_loss_pct=snapshot.daily_loss_pct,
                intraday_loss_30m=Decimal("0"),
                consecutive_losses=0,
                recovery_attempts=snapshot.recovery_attempts,
                last_updated=now,
            )
            logger.info("circuit_breaker_closed", probe_pnl=str(pnl))
        else:
            new_snap = CircuitBreakerSnapshot(
                state=CircuitBreakerState.OPEN,
                tripped_at=now,
                tripped_reason=snapshot.tripped_reason,
                daily_pnl=snapshot.daily_pnl + pnl,
                daily_loss_pct=snapshot.daily_loss_pct,
                intraday_loss_30m=snapshot.intraday_loss_30m,
                consecutive_losses=snapshot.consecutive_losses + 1,
                recovery_attempts=snapshot.recovery_attempts + 1,
                last_updated=now,
            )
            logger.warning("circuit_breaker_probe_failed", probe_pnl=str(pnl))

        await self._save_snapshot(new_snap)

    async def get_snapshot(self) -> CircuitBreakerSnapshot:
        """Return the current persisted snapshot."""
        return await self._load_snapshot()

    async def reset_daily(self) -> None:
        """Reset daily P&L counters at market open. Preserves OPEN/HALF_OPEN state."""
        snapshot = await self._load_snapshot()
        new_snap = CircuitBreakerSnapshot(
            state=snapshot.state,
            tripped_at=snapshot.tripped_at,
            tripped_reason=snapshot.tripped_reason,
            daily_pnl=Decimal("0"),
            daily_loss_pct=0.0,
            intraday_loss_30m=Decimal("0"),
            consecutive_losses=snapshot.consecutive_losses,
            recovery_attempts=snapshot.recovery_attempts,
            last_updated=datetime.now(UTC),
        )
        await self._save_snapshot(new_snap)

    def _evaluate_triggers(
        self,
        current_daily_pnl: Decimal,
        starting_capital: Decimal,
        intraday_loss_30m: Decimal,
        vix_current: float,
        vix_1h_ago: float,
        service_last_seen: dict[str, datetime],
        now: datetime,
    ) -> BlockReason | None:
        """Pure function: evaluate all triggers. Returns BlockReason or None."""
        # 1. Daily drawdown
        if starting_capital > Decimal("0"):
            daily_loss_pct = float(-current_daily_pnl / starting_capital)
            if daily_loss_pct > MAX_DAILY_LOSS_PCT:
                return BlockReason.DAILY_DRAWDOWN_EXCEEDED

        # 2. 30-minute intraday loss
        if starting_capital > Decimal("0"):
            intraday_pct = float(-intraday_loss_30m / starting_capital)
            if intraday_pct > MAX_INTRADAY_LOSS_30M_PCT:
                return BlockReason.INTRADAY_LOSS_EXCEEDED

        # 3. VIX spike
        if vix_1h_ago > 0:
            vix_change = (vix_current - vix_1h_ago) / vix_1h_ago
            if vix_change > VIX_SPIKE_THRESHOLD_PCT:
                return BlockReason.VIX_SPIKE

        # 4. Critical service down
        for _svc_id, last_seen in service_last_seen.items():
            elapsed = (now - last_seen).total_seconds()
            if elapsed > SERVICE_DOWN_SECONDS:
                return BlockReason.SERVICE_DOWN

        return None

    async def _trip(
        self,
        snapshot: CircuitBreakerSnapshot,
        reason: BlockReason,
        daily_pnl: Decimal,
        starting_capital: Decimal,
    ) -> CircuitBreakerSnapshot:
        """Trip the breaker to OPEN, persist snapshot, and return it."""
        now = datetime.now(UTC)
        daily_loss_pct = (
            float(-daily_pnl / starting_capital) if starting_capital > Decimal("0") else 0.0
        )
        new_snap = CircuitBreakerSnapshot(
            state=CircuitBreakerState.OPEN,
            tripped_at=now,
            tripped_reason=reason,
            daily_pnl=daily_pnl,
            daily_loss_pct=daily_loss_pct,
            intraday_loss_30m=snapshot.intraday_loss_30m,
            consecutive_losses=snapshot.consecutive_losses + 1,
            recovery_attempts=snapshot.recovery_attempts,
            last_updated=now,
        )
        await self._save_snapshot(new_snap)
        logger.warning("circuit_breaker_tripped", reason=reason.value)
        return new_snap

    async def _try_half_open(
        self, snapshot: CircuitBreakerSnapshot, now: datetime
    ) -> CircuitBreakerSnapshot:
        """Transition OPEN -> HALF_OPEN if cooldown has elapsed."""
        if snapshot.tripped_at is None:
            return snapshot
        cooldown = timedelta(minutes=HALF_OPEN_RECOVERY_MINUTES)
        if now - snapshot.tripped_at >= cooldown:
            new_snap = CircuitBreakerSnapshot(
                state=CircuitBreakerState.HALF_OPEN,
                tripped_at=snapshot.tripped_at,
                tripped_reason=snapshot.tripped_reason,
                daily_pnl=snapshot.daily_pnl,
                daily_loss_pct=snapshot.daily_loss_pct,
                intraday_loss_30m=snapshot.intraday_loss_30m,
                consecutive_losses=snapshot.consecutive_losses,
                recovery_attempts=snapshot.recovery_attempts + 1,
                last_updated=now,
            )
            await self._save_snapshot(new_snap)
            logger.info("circuit_breaker_half_open")
            return new_snap
        return snapshot

    async def _load_snapshot(self) -> CircuitBreakerSnapshot:
        """Load snapshot from Redis. Returns CLOSED default if not found."""
        try:
            raw = await self._redis.get(REDIS_CB_KEY)
            if raw is None:
                return CircuitBreakerSnapshot(state=CircuitBreakerState.CLOSED)
            data = json.loads(raw)
            return CircuitBreakerSnapshot.model_validate(data)
        except Exception as exc:
            logger.warning("cb_load_failed", error=str(exc))
            return CircuitBreakerSnapshot(state=CircuitBreakerState.CLOSED)

    async def _save_snapshot(self, snapshot: CircuitBreakerSnapshot) -> None:
        """Persist snapshot to Redis with 24h TTL."""
        try:
            await self._redis.setex(
                REDIS_CB_KEY,
                REDIS_CB_TTL,
                snapshot.model_dump_json(),
            )
        except Exception as exc:
            logger.error("cb_save_failed", error=str(exc))
