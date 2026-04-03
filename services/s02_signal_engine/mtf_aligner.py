"""Multi-timeframe alignment for the APEX Trading System Signal Engine.

Tracks the directional stance on each standard timeframe and synthesises
an :class:`~core.models.signal.MTFContext` enriched with an alignment score
and a session-based bonus multiplier.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.models.signal import Direction, MTFContext

# Standard timeframes evaluated for alignment (highest to lowest)
_TIMEFRAMES: list[str] = ["1d", "4h", "1h", "15m", "5m"]


class MTFAligner:
    """Tracks and scores multi-timeframe directional alignment.

    Directional stances are updated incrementally via :meth:`update`.
    An alignment score in [0, 1] is computed as the fraction of populated
    timeframes that agree with a given *target_direction*.
    """

    def __init__(self) -> None:
        """Initialize empty timeframe-stance storage."""
        # Maps timeframe label → (direction string, strength float)
        self._stances: dict[str, tuple[str, float]] = {}

    def update(self, timeframe: str, direction: str, strength: float) -> None:
        """Record the current directional stance for a timeframe.

        Args:
            timeframe: Timeframe label, e.g. ``'5m'``, ``'1h'``, ``'1d'``.
            direction: Direction string — ``'long'``, ``'short'``, or
                ``'flat'``.
            strength: Normalised strength in [0, 1].
        """
        self._stances[timeframe] = (direction, max(0.0, min(1.0, strength)))

    def alignment_score(self, target_direction: str) -> float:
        """Fraction of populated standard timeframes aligned with *target_direction*.

        Only the five canonical timeframes (1d, 4h, 1h, 15m, 5m) are
        considered.  Timeframes with no recorded stance are excluded from the
        denominator.

        Args:
            target_direction: Direction to check alignment against.

        Returns:
            Alignment score in [0, 1], or ``0.0`` if no stances are set.
        """
        populated = [
            (tf, stance)
            for tf, stance in self._stances.items()
            if tf in _TIMEFRAMES
        ]
        if not populated:
            return 0.0
        aligned = sum(1 for _, (d, _) in populated if d == target_direction)
        return aligned / len(populated)

    def session_multiplier(self, timestamp_ms: int) -> float:
        """Return a session-quality bonus multiplier for a UTC timestamp.

        Session windows (UTC):

        * US open  14:30–15:30 → 1.20
        * US close 20:00–21:00 → 1.20
        * London   08:00–10:00 → 1.10
        * Asian    00:00–02:00 → 0.70
        * All other sessions   → 1.00

        Args:
            timestamp_ms: Event timestamp in UTC milliseconds.

        Returns:
            Multiplier float in the range [0.70, 1.20].
        """
        dt = datetime.fromtimestamp(timestamp_ms / 1_000.0, tz=timezone.utc)
        total_minutes = dt.hour * 60 + dt.minute

        # US open (14:30–15:30 UTC)
        if 14 * 60 + 30 <= total_minutes < 15 * 60 + 30:
            return 1.20
        # US close (20:00–21:00 UTC)
        if 20 * 60 <= total_minutes < 21 * 60:
            return 1.20
        # London open (08:00–10:00 UTC)
        if 8 * 60 <= total_minutes < 10 * 60:
            return 1.10
        # Asian session (00:00–02:00 UTC)
        if total_minutes < 2 * 60:
            return 0.70
        return 1.00

    def build_context(self, target_direction: str, timestamp_ms: int) -> MTFContext:
        """Construct a full :class:`MTFContext` for the given signal direction.

        Args:
            target_direction: Direction the signal is proposing (``'long'`` /
                ``'short'``).
            timestamp_ms: Signal generation timestamp in UTC milliseconds.

        Returns:
            Populated :class:`MTFContext` with per-timeframe stances,
            alignment score, and session bonus.
        """

        def _direction(tf: str) -> Direction | None:
            if tf not in self._stances:
                return None
            try:
                return Direction(self._stances[tf][0])
            except ValueError:
                return None

        return MTFContext(
            tf_1d=_direction("1d"),
            tf_4h=_direction("4h"),
            tf_1h=_direction("1h"),
            tf_15m=_direction("15m"),
            tf_5m=_direction("5m"),
            alignment_score=self.alignment_score(target_direction),
            session_bonus=self.session_multiplier(timestamp_ms),
        )
