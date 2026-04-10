"""Session tagger — shared across normalizers and backtesting.

Re-exports :class:`SessionTagger` which was originally defined in the
monolithic ``normalizer.py``.  This module is the canonical home going forward.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.models.tick import Session


class SessionTagger:
    """Tags a UTC :class:`datetime` with the appropriate :class:`Session` value.

    Session windows (all times UTC):

    * **Weekend**   - Saturday or Sunday (weekday >= 5)
    * **US Prime**  - 14:30-15:30 (open prime) *or* 20:00-21:00 (close prime)
    * **US Normal** - 14:30-21:00 outside the prime windows
    * **London**    - 08:00-10:00
    * **Asian**     - 00:00-02:00
    * **After Hours / Unknown** - everything else
    """

    _US_OPEN_HM = (14, 30)
    _US_CLOSE_HM = (21, 0)
    _PRIME_OPEN_START_HM = (14, 30)
    _PRIME_OPEN_END_HM = (15, 30)
    _PRIME_CLOSE_START_HM = (20, 0)
    _PRIME_CLOSE_END_HM = (21, 0)
    _LONDON_START_HM = (8, 0)
    _LONDON_END_HM = (10, 0)
    _ASIAN_START_HM = (0, 0)
    _ASIAN_END_HM = (2, 0)

    @staticmethod
    def _to_minutes(hour: int, minute: int) -> int:
        """Convert (hour, minute) to total minutes since midnight."""
        return hour * 60 + minute

    def tag(self, ts: datetime) -> Session:
        """Return the :class:`Session` for *ts* (must be UTC-aware or naive UTC).

        Args:
            ts: UTC timestamp to classify.

        Returns:
            The matching :class:`Session` value.
        """
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC)

        if ts.weekday() >= 5:
            return Session.WEEKEND

        total = self._to_minutes(ts.hour, ts.minute)

        prime_open_start = self._to_minutes(*self._PRIME_OPEN_START_HM)
        prime_open_end = self._to_minutes(*self._PRIME_OPEN_END_HM)
        prime_close_start = self._to_minutes(*self._PRIME_CLOSE_START_HM)
        prime_close_end = self._to_minutes(*self._PRIME_CLOSE_END_HM)
        us_open = self._to_minutes(*self._US_OPEN_HM)
        us_close = self._to_minutes(*self._US_CLOSE_HM)
        london_start = self._to_minutes(*self._LONDON_START_HM)
        london_end = self._to_minutes(*self._LONDON_END_HM)
        asian_start = self._to_minutes(*self._ASIAN_START_HM)
        asian_end = self._to_minutes(*self._ASIAN_END_HM)

        if (prime_open_start <= total < prime_open_end) or (
            prime_close_start <= total < prime_close_end
        ):
            return Session.US_PRIME

        if us_open <= total < us_close:
            return Session.US_NORMAL

        if london_start <= total < london_end:
            return Session.LONDON

        if asian_start <= total < asian_end:
            return Session.ASIAN

        return Session.AFTER_HOURS
