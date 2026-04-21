"""Session Tracker - Intraday session classification with DST support.

Sessions drive session_mult [0.5, 1.5] in S04 FusionEngine.
Getting sessions wrong = systematic undersizing during prime windows.

US sessions follow America/New_York timezone (handles EST/EDT automatically).
Crypto sessions follow UTC (24/7 market, no DST).

Session schedule (all times in LOCAL timezone):
  US_OPEN     : 09:30-10:30 ET  -> mult = 1.30 (prime, highest edge)
  US_MORNING  : 10:30-12:00 ET  -> mult = 1.00
  US_LUNCH    : 12:00-13:30 ET  -> mult = 0.60 (avoid - low edge)
  US_AFTERNOON: 13:30-15:00 ET  -> mult = 1.10
  US_CLOSE    : 15:00-16:00 ET  -> mult = 1.20 (prime)
  AFTER_HOURS : 16:00-09:30 ET  -> mult = 0.50
  ASIAN       : 00:00-08:00 UTC -> mult = 0.70 (crypto only)
  LONDON      : 08:00-13:30 UTC -> mult = 0.90 (crypto only)
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo  # Python 3.9+ standard library


class Session(StrEnum):
    """Trading session identifiers."""

    US_OPEN = "us_open"
    US_MORNING = "us_morning"
    US_LUNCH = "us_lunch"
    US_AFTERNOON = "us_afternoon"
    US_CLOSE = "us_close"
    AFTER_HOURS = "after_hours"
    ASIAN = "asian"
    LONDON = "london"
    WEEKEND = "weekend"


SESSION_MULTIPLIERS: dict[Session, float] = {
    Session.US_OPEN: 1.30,
    Session.US_MORNING: 1.00,
    Session.US_LUNCH: 0.60,
    Session.US_AFTERNOON: 1.10,
    Session.US_CLOSE: 1.20,
    Session.AFTER_HOURS: 0.50,
    Session.ASIAN: 0.70,
    Session.LONDON: 0.90,
    Session.WEEKEND: 0.40,
}

PRIME_SESSIONS = {Session.US_OPEN, Session.US_CLOSE}

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = UTC


class SessionTracker:
    """Maps any UTC datetime to the current trading session.

    Uses America/New_York for US sessions (auto-handles EST/EDT transitions).
    """

    def get_session(self, utc_now: datetime) -> Session:
        """Classify the current session for a UTC timestamp.

        Args:
            utc_now: UTC-aware datetime (must have tzinfo set).

        Returns:
            Session enum for current market session.
        """
        assert utc_now.tzinfo is not None, "utc_now must be timezone-aware"

        # Weekend check (UTC-based, simple)
        if utc_now.weekday() >= 5:  # Saturday=5, Sunday=6
            return Session.WEEKEND

        # Convert to NY time for US session classification (DST-safe via ZoneInfo)
        ny_now = utc_now.astimezone(NY_TZ)
        ny_time = ny_now.time()

        if time(9, 30) <= ny_time < time(10, 30):
            return Session.US_OPEN
        if time(10, 30) <= ny_time < time(12, 0):
            return Session.US_MORNING
        if time(12, 0) <= ny_time < time(13, 30):
            return Session.US_LUNCH
        if time(13, 30) <= ny_time < time(15, 0):
            return Session.US_AFTERNOON
        if time(15, 0) <= ny_time < time(16, 0):
            return Session.US_CLOSE

        # Outside US hours - classify by UTC for crypto
        utc_time = utc_now.time().replace(tzinfo=None)
        if time(0, 0) <= utc_time < time(8, 0):
            return Session.ASIAN
        if time(8, 0) <= utc_time < time(13, 30):
            return Session.LONDON

        return Session.AFTER_HOURS

    def get_multiplier(self, session: Session) -> float:
        """Return the sizing multiplier for a session.

        Args:
            session: Session enum value.

        Returns:
            Float multiplier in [0.40, 1.30].
        """
        return SESSION_MULTIPLIERS[session]

    def is_prime_window(self, utc_now: datetime) -> bool:
        """Return True if current time is in US_OPEN or US_CLOSE prime window.

        Args:
            utc_now: UTC-aware datetime.

        Returns:
            True if in a prime trading window.
        """
        return self.get_session(utc_now) in PRIME_SESSIONS

    def get_next_prime_window(self, utc_now: datetime) -> datetime:
        """Return the UTC datetime of the next US_OPEN session start.

        Args:
            utc_now: UTC-aware datetime.

        Returns:
            UTC datetime of next 09:30 ET opening (skips weekends).
        """
        from datetime import timedelta

        candidate = utc_now.astimezone(NY_TZ).replace(hour=9, minute=30, second=0, microsecond=0)
        candidate_utc = candidate.astimezone(UTC_TZ)

        if candidate_utc <= utc_now:
            candidate_utc += timedelta(days=1)

        # Skip weekends
        while candidate_utc.weekday() >= 5:
            candidate_utc += timedelta(days=1)

        return candidate_utc
