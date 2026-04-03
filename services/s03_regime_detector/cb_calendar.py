"""Central bank calendar for APEX Trading System - S03 Regime Detector.

Pre-populates known 2024-2025 FOMC, ECB, BOJ, and BOE decision dates and
computes block/scalp windows around each event.  Phase 2 will fetch live
schedules from an API; for now the list is hardcoded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from core.models.regime import CentralBankEvent


class CBCalendar:
    """Central-bank event calendar.

    On construction the hardcoded schedule is parsed and
    :class:`~core.models.regime.CentralBankEvent` objects are built with
    pre-computed block/scalp windows.  Call :meth:`load_schedule` to
    refresh (or eventually fetch from an API).
    """

    # ------------------------------------------------------------------
    # Hardcoded 2024-2025 event schedule (approximate dates, 14:00 UTC)
    # ------------------------------------------------------------------
    _RAW_SCHEDULE: ClassVar[list[tuple[str, str, str]]] = [
        # (institution, event_type, "YYYY-MM-DD HH:MM")
        # ── FOMC 2024 ──────────────────────────────────────────────────
        ("FOMC", "rate_decision", "2024-01-31 19:00"),
        ("FOMC", "rate_decision", "2024-03-20 18:00"),
        ("FOMC", "rate_decision", "2024-05-01 18:00"),
        ("FOMC", "rate_decision", "2024-06-12 18:00"),
        ("FOMC", "rate_decision", "2024-07-31 18:00"),
        ("FOMC", "rate_decision", "2024-09-18 18:00"),
        ("FOMC", "rate_decision", "2024-11-07 19:00"),
        ("FOMC", "rate_decision", "2024-12-18 19:00"),
        # ── FOMC 2025 ──────────────────────────────────────────────────
        ("FOMC", "rate_decision", "2025-01-29 19:00"),
        ("FOMC", "rate_decision", "2025-03-19 18:00"),
        ("FOMC", "rate_decision", "2025-05-07 18:00"),
        ("FOMC", "rate_decision", "2025-06-18 18:00"),
        ("FOMC", "rate_decision", "2025-07-30 18:00"),
        ("FOMC", "rate_decision", "2025-09-17 18:00"),
        ("FOMC", "rate_decision", "2025-10-29 18:00"),
        ("FOMC", "rate_decision", "2025-12-10 19:00"),
        # ── ECB 2024 ───────────────────────────────────────────────────
        ("ECB", "rate_decision", "2024-01-25 13:15"),
        ("ECB", "rate_decision", "2024-03-07 13:15"),
        ("ECB", "rate_decision", "2024-04-11 13:15"),
        ("ECB", "rate_decision", "2024-06-06 13:15"),
        ("ECB", "rate_decision", "2024-07-18 13:15"),
        ("ECB", "rate_decision", "2024-09-12 13:15"),
        ("ECB", "rate_decision", "2024-10-17 13:15"),
        ("ECB", "rate_decision", "2024-12-12 13:15"),
        # ── ECB 2025 ───────────────────────────────────────────────────
        ("ECB", "rate_decision", "2025-01-30 13:15"),
        ("ECB", "rate_decision", "2025-03-06 13:15"),
        ("ECB", "rate_decision", "2025-04-17 13:15"),
        ("ECB", "rate_decision", "2025-06-05 13:15"),
        ("ECB", "rate_decision", "2025-07-24 13:15"),
        ("ECB", "rate_decision", "2025-09-11 13:15"),
        ("ECB", "rate_decision", "2025-10-30 13:15"),
        ("ECB", "rate_decision", "2025-12-18 13:15"),
        # ── BOJ 2024 ───────────────────────────────────────────────────
        ("BOJ", "rate_decision", "2024-01-23 03:00"),
        ("BOJ", "rate_decision", "2024-03-19 03:00"),
        ("BOJ", "rate_decision", "2024-04-26 03:00"),
        ("BOJ", "rate_decision", "2024-06-14 03:00"),
        ("BOJ", "rate_decision", "2024-07-31 03:00"),
        ("BOJ", "rate_decision", "2024-09-20 03:00"),
        ("BOJ", "rate_decision", "2024-10-31 03:00"),
        ("BOJ", "rate_decision", "2024-12-19 03:00"),
        # ── BOJ 2025 ───────────────────────────────────────────────────
        ("BOJ", "rate_decision", "2025-01-24 03:00"),
        ("BOJ", "rate_decision", "2025-03-19 03:00"),
        ("BOJ", "rate_decision", "2025-04-30 03:00"),
        ("BOJ", "rate_decision", "2025-06-17 03:00"),
        ("BOJ", "rate_decision", "2025-07-31 03:00"),
        ("BOJ", "rate_decision", "2025-09-19 03:00"),
        ("BOJ", "rate_decision", "2025-10-29 03:00"),
        ("BOJ", "rate_decision", "2025-12-18 03:00"),
        # ── BOE 2024 ───────────────────────────────────────────────────
        ("BOE", "rate_decision", "2024-02-01 12:00"),
        ("BOE", "rate_decision", "2024-03-21 12:00"),
        ("BOE", "rate_decision", "2024-05-09 12:00"),
        ("BOE", "rate_decision", "2024-06-20 12:00"),
        ("BOE", "rate_decision", "2024-08-01 12:00"),
        ("BOE", "rate_decision", "2024-09-19 12:00"),
        ("BOE", "rate_decision", "2024-11-07 12:00"),
        ("BOE", "rate_decision", "2024-12-19 12:00"),
        # ── BOE 2025 ───────────────────────────────────────────────────
        ("BOE", "rate_decision", "2025-02-06 12:00"),
        ("BOE", "rate_decision", "2025-03-20 12:00"),
        ("BOE", "rate_decision", "2025-05-08 12:00"),
        ("BOE", "rate_decision", "2025-06-19 12:00"),
        ("BOE", "rate_decision", "2025-08-07 12:00"),
        ("BOE", "rate_decision", "2025-09-18 12:00"),
        ("BOE", "rate_decision", "2025-11-06 12:00"),
        ("BOE", "rate_decision", "2025-12-18 12:00"),
    ]

    def __init__(self) -> None:
        """Build the event list from the hardcoded schedule."""
        self._events: list[CentralBankEvent] = []
        for institution, event_type, dt_str in self._RAW_SCHEDULE:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            self._events.append(self.build_event(institution, event_type, dt))

    # ── Public API ────────────────────────────────────────────────────────────

    async def load_schedule(self) -> None:
        """Load or refresh the CB event schedule.

        Currently parses the hardcoded list.
        Phase 2: fetch from an economic-calendar API and merge.
        """
        self._events.clear()
        for institution, event_type, dt_str in self._RAW_SCHEDULE:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            self._events.append(self.build_event(institution, event_type, dt))

    def next_event(self) -> CentralBankEvent | None:
        """Return the next upcoming central-bank event from now.

        Returns:
            The earliest future :class:`CentralBankEvent`, or ``None`` if
            all known events are in the past.
        """
        now = datetime.now(tz=UTC)
        future = [e for e in self._events if e.scheduled_at > now]
        if not future:
            return None
        return min(future, key=lambda e: e.scheduled_at)

    def active_block(self) -> bool:
        """Return ``True`` if the current time is inside any event's pre-block window.

        The pre-block window begins 45 minutes before each event and ends at
        the scheduled event time.

        Returns:
            ``True`` when trading should be blocked.
        """
        return any(e.is_active_block for e in self._events)

    def post_event_scalp_active(self) -> bool:
        """Return ``True`` if within any event's post-scalp window (60 min after).

        Returns:
            ``True`` when post-event scalp trades are permitted.
        """
        return any(e.is_post_event_scalp for e in self._events)

    def events_within_hours(self, hours: int) -> list[CentralBankEvent]:
        """Return all events scheduled within the next ``hours`` hours.

        Args:
            hours: Look-ahead window in hours.

        Returns:
            List of :class:`CentralBankEvent` objects scheduled within the window.
        """
        now = datetime.now(tz=UTC)
        cutoff = now + timedelta(hours=hours)
        return [e for e in self._events if now <= e.scheduled_at <= cutoff]

    def build_event(
        self,
        institution: str,
        event_type: str,
        scheduled_at: datetime,
    ) -> CentralBankEvent:
        """Build a :class:`CentralBankEvent` with pre-computed windows.

        Args:
            institution:   e.g. ``"FOMC"``, ``"ECB"``, ``"BOJ"``, ``"BOE"``.
            event_type:    e.g. ``"rate_decision"``.
            scheduled_at:  UTC datetime of the event.

        Returns:
            A fully-populated :class:`CentralBankEvent`.
        """
        block_start = scheduled_at - timedelta(minutes=45)
        scalp_start = scheduled_at
        scalp_end = scheduled_at + timedelta(minutes=60)
        return CentralBankEvent(
            institution=institution,
            event_type=event_type,
            scheduled_at=scheduled_at,
            is_high_impact=True,
            block_window_start=block_start,
            post_event_scalp_start=scalp_start,
            post_event_scalp_end=scalp_end,
        )
