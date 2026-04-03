"""Session tracker for APEX Trading System - S03 Regime Detector.

Maps a UTC millisecond timestamp to a :class:`~core.models.regime.SessionContext`
that captures the current trading session, its sizing multiplier, and US-market
flags used downstream by the Fusion Engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.models.regime import SessionContext


class SessionTracker:
    """Classify UTC timestamps into trading sessions and produce multipliers.

    Sessions (all times UTC):
    - us_prime   : 14:30-15:30 **and** 20:00-21:00  → mult 1.3
    - us_normal  : 14:30-21:00 (outside prime slots) → mult 1.0
    - london     : 08:00-10:00                        → mult 1.1
    - asian      : 00:00-02:00                        → mult 0.7
    - weekend    : Saturday or Sunday                 → mult 0.5
    - after_hours: everything else                    → mult 0.8
    """

    def get_session(self, timestamp_ms: int) -> SessionContext:
        """Return a :class:`SessionContext` for the given UTC millisecond timestamp.

        Args:
            timestamp_ms: UTC epoch time in milliseconds.

        Returns:
            A fully-populated :class:`SessionContext` instance.
        """
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC)

        # Weekend check (Mon=0 … Sun=6)
        if dt.weekday() >= 5:
            return SessionContext(
                timestamp_ms=timestamp_ms,
                session="weekend",
                session_mult=0.5,
                is_us_prime=False,
                is_us_open=False,
            )

        hour = dt.hour
        minute = dt.minute
        # Express time-of-day as fractional hours for easier comparison.
        tod = hour + minute / 60.0

        # US prime windows: 14:30-15:30 and 20:00-21:00 UTC
        is_us_prime_morning = 14.5 <= tod < 15.5
        is_us_prime_close = 20.0 <= tod < 21.0
        is_us_prime = is_us_prime_morning or is_us_prime_close

        # Full US regular session: 14:30-21:00 UTC
        is_us_open = 14.5 <= tod < 21.0

        if is_us_prime:
            return SessionContext(
                timestamp_ms=timestamp_ms,
                session="us_prime",
                session_mult=1.3,
                is_us_prime=True,
                is_us_open=True,
            )

        if is_us_open:
            return SessionContext(
                timestamp_ms=timestamp_ms,
                session="us_normal",
                session_mult=1.0,
                is_us_prime=False,
                is_us_open=True,
            )

        # London session: 08:00-10:00 UTC
        if 8.0 <= tod < 10.0:
            return SessionContext(
                timestamp_ms=timestamp_ms,
                session="london",
                session_mult=1.1,
                is_us_prime=False,
                is_us_open=False,
            )

        # Asian session: 00:00-02:00 UTC
        if 0.0 <= tod < 2.0:
            return SessionContext(
                timestamp_ms=timestamp_ms,
                session="asian",
                session_mult=0.7,
                is_us_prime=False,
                is_us_open=False,
            )

        # After-hours / other
        return SessionContext(
            timestamp_ms=timestamp_ms,
            session="after_hours",
            session_mult=0.8,
            is_us_prime=False,
            is_us_open=False,
        )
