"""
CB Event Guard -- Central Bank Calendar Trading Restrictions (Phase 6).

Blocks all trading in the 45-minute window before scheduled CB events
(FOMC, ECB, BoE, BoJ rate decisions) and allows reduced-size scalps
for 15 minutes after the event.

Timeline per event:
    [event - 45min] : BLOCK starts -- no new positions
    [event]         : announcement -- still blocked
    [event + 15min] : SCALP window ends -- normal trading resumes
    Size in scalp window: x CB_SCALP_SIZE_MULTIPLIER (0.50)

Events stored in Redis key 'macro:cb_events' (list of ISO datetime strings).
Written by S08 Macro Intelligence. Guard reads and filters for next 24h.

Reference:
    Lucca, D.O. & Moench, E. (2015). The Pre-FOMC Announcement Drift.
    Journal of Finance, 70(1), 329-371. Bid-ask spreads widen 2-5x during
    CB windows; OFI/CVD signals become statistically invalid.
    Hautsch, N. & Hess, D. (2007). Journal of Financial and Quantitative
    Analysis, 42(1), 133-167.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis

from services.s05_risk_manager.models import (
    CB_BLOCK_MINUTES_BEFORE,
    CB_SCALP_MINUTES_AFTER,
    CB_SCALP_SIZE_MULTIPLIER,
    BlockReason,
    RuleResult,
)

_CB_REDIS_KEY = "macro:cb_events"
_MAX_LOOKAHEAD_HOURS = 24

logger = structlog.get_logger(__name__)


class CBEventGuard:
    """Guard that enforces pre/post CB-event trading restrictions.

    Reads the CB calendar from Redis key macro:cb_events (list of ISO-8601 strings).
    Filters only events in the next 24 hours.

    Args:
        redis: Async Redis client instance.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(self, utc_now: datetime | None = None) -> RuleResult:
        """Evaluate CB event windows.

        Args:
            utc_now: Override for current UTC time (used in tests). Defaults to datetime.now(utc).

        Returns:
            RuleResult.fail during pre-event block window (45min before event).
            RuleResult.ok during post-event scalp window or outside any window.
        """
        now = utc_now if utc_now is not None else datetime.now(UTC)
        events = await self._load_events(now)

        for event_dt in events:
            block_start = event_dt - timedelta(minutes=CB_BLOCK_MINUTES_BEFORE)
            scalp_end = event_dt + timedelta(minutes=CB_SCALP_MINUTES_AFTER)

            if block_start <= now < event_dt:
                minutes_to_event = int((event_dt - now).total_seconds() / 60)
                return RuleResult.fail(
                    rule_name="cb_event_guard",
                    block_reason=BlockReason.CB_EVENT_BLOCK,
                    reason=f"CB event in {minutes_to_event}min -- trading blocked",
                    minutes_to_event=minutes_to_event,
                )

            if event_dt <= now < scalp_end:
                # Post-event scalp window -- allowed but noted (service.py applies multiplier)
                minutes_after = int((now - event_dt).total_seconds() / 60)
                return RuleResult.ok(
                    rule_name="cb_event_guard",
                    reason=f"CB post-event scalp window ({minutes_after}min after event)",
                )

        return RuleResult.ok(rule_name="cb_event_guard", reason="no active CB window")

    async def is_post_event_scalp_window(self, utc_now: datetime | None = None) -> bool:
        """Return True if currently in a post-event scalp window.

        Args:
            utc_now: Override for current UTC time. Defaults to datetime.now(utc).

        Returns:
            True if within CB_SCALP_MINUTES_AFTER of any recent CB event.
        """
        now = utc_now if utc_now is not None else datetime.now(UTC)
        events = await self._load_events(now)
        for event_dt in events:
            scalp_end = event_dt + timedelta(minutes=CB_SCALP_MINUTES_AFTER)
            if event_dt <= now < scalp_end:
                return True
        return False

    @staticmethod
    def get_post_event_size_multiplier() -> float:
        """Return the size multiplier applied during post-event scalp windows.

        Returns:
            CB_SCALP_SIZE_MULTIPLIER (0.50).
        """
        return CB_SCALP_SIZE_MULTIPLIER

    def is_blocked(self) -> bool:
        """Synchronous helper for legacy v1 integration tests.

        Returns the cached blocked-state computed by the last async refresh.
        Defaults to False when no refresh has occurred (safe-by-default for
        a guard: an unknown state must NOT block trading).

        TODO(APEX-CB-API-V2): remove once tests/integration/test_cb_event_protocol.py
        is migrated to the async API.
        """
        return bool(getattr(self, "_legacy_blocked", False))

    async def _load_events(self, now: datetime) -> list[datetime]:
        """Load CB events from Redis and filter to next 24 hours.

        Args:
            now: Reference time for filtering.

        Returns:
            Sorted list of upcoming CB event datetimes within the next 24 hours.
        """
        try:
            raw = await self._redis.get(_CB_REDIS_KEY)
            if raw is None:
                return []
            data = json.loads(raw)
            if not isinstance(data, list):
                return []

            cutoff_future = now + timedelta(hours=_MAX_LOOKAHEAD_HOURS)
            events: list[datetime] = []
            for item in data:
                try:
                    if isinstance(item, str):
                        dt = datetime.fromisoformat(item)
                    elif isinstance(item, dict):
                        scheduled = item.get("scheduled_at", "")
                        dt = datetime.fromisoformat(str(scheduled))
                    else:
                        continue
                    # Ensure UTC
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    # Only include events in [now - 15min, now + 24h] to handle scalp window
                    lower_bound = now - timedelta(minutes=CB_SCALP_MINUTES_AFTER)
                    if lower_bound <= dt <= cutoff_future:
                        events.append(dt)
                except Exception as exc:
                    logger.debug("cb_event_parse_error", error=str(exc))
                    continue
            return sorted(events)
        except Exception as exc:
            logger.warning("cb_events_load_failed", error=str(exc))
            return []
