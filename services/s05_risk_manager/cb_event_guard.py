"""Central-bank event guard for APEX Trading System - S05 Risk Manager.

Reads the CB calendar from Redis and determines whether trading should be
blocked (pre-event) or allowed with a reduced size (post-event scalp).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from core.config import get_settings
from core.models.regime import CentralBankEvent
from core.state import StateStore

_CB_KEY = "cb:calendar"


class CBEventGuard:
    """Guard that enforces CB-event trading restrictions.

    Reads the serialised :class:`~core.models.regime.CentralBankEvent` list
    from Redis key ``cb:calendar`` (populated by S03 Regime Detector) and
    checks the current time against each event's windows.

    Return values from :meth:`check`:

    - ``(False, 0.0)`` – inside a pre-event block window; trading blocked.
    - ``(True, cb_event_post_size_mult)`` – inside a post-event scalp window;
      trading allowed at reduced size.
    - ``(True, 1.0)`` – no active window; normal operation.
    """

    async def check(self, state: StateStore) -> tuple[bool, float]:
        """Check the current CB-event status.

        Args:
            state: Connected :class:`~core.state.StateStore` instance.

        Returns:
            ``(allowed, size_multiplier)`` tuple.
        """
        settings = get_settings()
        raw = await state.get(_CB_KEY)

        events: list[CentralBankEvent] = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    if isinstance(item, str):
                        item = json.loads(item)
                    events.append(CentralBankEvent.model_validate(item))
                except Exception:
                    continue
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        try:
                            events.append(CentralBankEvent.model_validate(item))
                        except Exception:
                            continue
            except Exception:
                pass

        now = datetime.now(tz=UTC)

        for event in events:
            # Pre-event block window
            if event.block_window_start is not None:
                block_start = _ensure_utc(event.block_window_start)
                scheduled = _ensure_utc(event.scheduled_at)
                if block_start <= now < scheduled:
                    return False, 0.0

            # Post-event scalp window
            if event.post_event_scalp_start is not None and event.post_event_scalp_end is not None:
                scalp_start = _ensure_utc(event.post_event_scalp_start)
                scalp_end = _ensure_utc(event.post_event_scalp_end)
                if scalp_start <= now < scalp_end:
                    return True, settings.cb_event_post_size_mult

        return True, 1.0


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC).

    Args:
        dt: Datetime object, possibly naive.

    Returns:
        Timezone-aware datetime in UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
