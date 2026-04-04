"""Session tracker tests - all sessions, DST transitions, weekends."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.s03_regime_detector.session_tracker import (
    SESSION_MULTIPLIERS,
    Session,
    SessionTracker,
)


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Build a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class TestSessionClassification:
    def tracker(self) -> SessionTracker:
        return SessionTracker()

    def test_us_open_session(self) -> None:
        # 9:35 AM ET winter (EST = UTC-5) -> 14:35 UTC
        ts = utc(2024, 1, 15, 14, 35)
        assert self.tracker().get_session(ts) == Session.US_OPEN

    def test_us_open_session_summer_dst(self) -> None:
        # Summer: EDT = UTC-4, so 9:35 AM ET = 13:35 UTC (June 17 = Monday)
        ts = utc(2024, 6, 17, 13, 35)
        assert self.tracker().get_session(ts) == Session.US_OPEN

    def test_us_morning_session(self) -> None:
        # 11:00 AM ET winter = 16:00 UTC
        ts = utc(2024, 1, 15, 16, 0)
        assert self.tracker().get_session(ts) == Session.US_MORNING

    def test_us_close_session(self) -> None:
        # 3:30 PM ET winter = 20:30 UTC
        ts = utc(2024, 1, 15, 20, 30)
        assert self.tracker().get_session(ts) == Session.US_CLOSE

    def test_lunch_session_is_low_mult(self) -> None:
        # 12:30 PM ET winter = 17:30 UTC
        ts = utc(2024, 1, 15, 17, 30)
        tracker = self.tracker()
        session = tracker.get_session(ts)
        assert session == Session.US_LUNCH
        assert tracker.get_multiplier(session) == 0.60

    def test_us_afternoon_session(self) -> None:
        # 2:00 PM ET winter = 19:00 UTC
        ts = utc(2024, 1, 15, 19, 0)
        assert self.tracker().get_session(ts) == Session.US_AFTERNOON

    def test_weekend_is_weekend(self) -> None:
        # Saturday 2024-01-13
        ts = utc(2024, 1, 13, 14, 0)
        assert self.tracker().get_session(ts) == Session.WEEKEND

    def test_sunday_is_weekend(self) -> None:
        ts = utc(2024, 1, 14, 14, 0)
        assert self.tracker().get_session(ts) == Session.WEEKEND

    def test_asian_session(self) -> None:
        ts = utc(2024, 1, 15, 2, 0)  # 2 AM UTC
        assert self.tracker().get_session(ts) == Session.ASIAN

    def test_london_session(self) -> None:
        ts = utc(2024, 1, 15, 9, 0)  # 9 AM UTC
        assert self.tracker().get_session(ts) == Session.LONDON

    def test_after_hours(self) -> None:
        # 6 PM ET winter = 23:00 UTC (outside all named sessions)
        ts = utc(2024, 1, 15, 23, 0)
        assert self.tracker().get_session(ts) == Session.AFTER_HOURS

    def test_dst_spring_forward(self) -> None:
        """DST transition: 2024-03-10, clocks spring forward at 2 AM ET.
        First weekday after: 2024-03-11 (Monday), EDT = UTC-4.
        9:35 AM EDT = 13:35 UTC.
        """
        after_dst = utc(2024, 3, 11, 13, 35)
        assert self.tracker().get_session(after_dst) == Session.US_OPEN

    def test_dst_fall_back(self) -> None:
        """DST transition: 2024-11-03, clocks fall back at 2 AM ET.
        First weekday after: 2024-11-04 (Monday), EST = UTC-5.
        9:35 AM EST = 14:35 UTC.
        """
        after_dst = utc(2024, 11, 4, 14, 35)
        assert self.tracker().get_session(after_dst) == Session.US_OPEN

    def test_prime_windows(self) -> None:
        tracker = self.tracker()
        # US Open is prime (9:35 AM ET winter = 14:35 UTC)
        assert tracker.is_prime_window(utc(2024, 1, 15, 14, 35)) is True
        # Lunch is not prime
        assert tracker.is_prime_window(utc(2024, 1, 15, 17, 30)) is False

    def test_all_session_multipliers_valid_range(self) -> None:
        for session, mult in SESSION_MULTIPLIERS.items():
            assert 0.0 < mult <= 2.0, f"Session {session} has invalid mult {mult}"

    def test_requires_timezone_aware_datetime(self) -> None:
        naive = datetime(2024, 1, 15, 14, 35)
        with pytest.raises(AssertionError):
            self.tracker().get_session(naive)

    def test_get_next_prime_window_returns_future(self) -> None:
        tracker = self.tracker()
        now = utc(2024, 1, 15, 20, 0)  # After close on a weekday
        nxt = tracker.get_next_prime_window(now)
        assert nxt > now

    def test_get_next_prime_window_skips_weekend(self) -> None:
        tracker = self.tracker()
        # Friday after close
        now = utc(2024, 1, 19, 22, 0)  # Friday 5 PM ET
        nxt = tracker.get_next_prime_window(now)
        assert nxt.weekday() not in (5, 6)  # Not Saturday or Sunday
