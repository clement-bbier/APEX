"""Circuit breaker state machine for APEX Trading System - S05 Risk Manager.

Implements a three-state machine (CLOSED → OPEN → HALF_OPEN → CLOSED) that
trips on drawdown, rolling loss, VIX spike, or price-gap conditions and
auto-resets after a 15-minute cool-down.
"""

from __future__ import annotations

import time
from enum import Enum

from core.config import Settings


class CircuitState(str, Enum):
    """Circuit breaker state machine states."""

    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


# Seconds the breaker must remain OPEN before transitioning to HALF_OPEN.
_RESET_DELAY_S: float = 15 * 60.0


class CircuitBreaker:
    """Three-state circuit breaker that halts trading on extreme adverse conditions.

    States:
    - ``CLOSED``    : Normal operation; new positions may be placed.
    - ``OPEN``      : Tripped; no new positions until cool-down expires.
    - ``HALF_OPEN`` : Tentative resume; one successful trade closes the breaker.

    The breaker is tripped (:meth:`trip`) when any of the following checks
    returns ``True``:

    - :meth:`check_daily_drawdown`
    - :meth:`check_rolling_loss`
    - :meth:`check_vix_spike`
    - :meth:`check_price_gap`
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the circuit breaker in the CLOSED state.

        Args:
            settings: Application settings used for threshold values.
        """
        self._settings = settings
        self._state: CircuitState = CircuitState.CLOSED
        self._tripped_at: float = 0.0
        self._trip_reason: str = ""
        self._last_trade_success: bool = False

    # ── Condition checks ──────────────────────────────────────────────────────

    def check_daily_drawdown(self, daily_pnl_pct: float) -> bool:
        """Return ``True`` if the daily drawdown exceeds the configured threshold.

        Args:
            daily_pnl_pct: Today's P&L as a percentage of capital (negative = loss).

        Returns:
            ``True`` when the breaker should be tripped.
        """
        return abs(daily_pnl_pct) > self._settings.max_daily_drawdown_pct

    def check_rolling_loss(self, recent_losses_pct: list[float]) -> bool:
        """Return ``True`` if total losses in the rolling window exceed 2 %.

        Args:
            recent_losses_pct: Per-trade loss percentages within the last 30 min
                               (positive values represent losses).

        Returns:
            ``True`` when the breaker should be tripped.
        """
        return sum(recent_losses_pct) > 2.0

    def check_vix_spike(self, vix_now: float, vix_1h_ago: float) -> bool:
        """Return ``True`` if VIX has spiked beyond the configured threshold.

        The spike is measured as a relative increase:
        ``(vix_now - vix_1h_ago) / vix_1h_ago > cb_vix_spike_pct / 100``.

        Args:
            vix_now:    Current VIX level.
            vix_1h_ago: VIX level one hour ago.

        Returns:
            ``True`` when the breaker should be tripped.
        """
        if vix_1h_ago <= 0:
            return False
        relative_change = (vix_now - vix_1h_ago) / vix_1h_ago
        return relative_change > self._settings.cb_vix_spike_pct / 100.0

    def check_price_gap(self, prev_price: float, curr_price: float) -> bool:
        """Return ``True`` if the price has gapped beyond the configured threshold.

        Args:
            prev_price: Price in the previous bar or snapshot.
            curr_price: Current price.

        Returns:
            ``True`` when the breaker should be tripped.
        """
        if prev_price <= 0:
            return False
        change_pct = abs(curr_price - prev_price) / prev_price * 100.0
        return change_pct > self._settings.cb_price_gap_pct

    # ── State transitions ─────────────────────────────────────────────────────

    def trip(self, reason: str) -> None:
        """Trip the circuit breaker, setting state to OPEN.

        Args:
            reason: Human-readable description of why the breaker was tripped.
        """
        self._state = CircuitState.OPEN
        self._tripped_at = time.monotonic()
        self._trip_reason = reason

    def attempt_reset(self) -> bool:
        """Attempt to transition from OPEN → HALF_OPEN or HALF_OPEN → CLOSED.

        Transition rules:
        - OPEN for > 15 min → HALF_OPEN.
        - HALF_OPEN and the last trade was successful → CLOSED.

        Returns:
            ``True`` if a state transition occurred.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._tripped_at
            if elapsed > _RESET_DELAY_S:
                self._state = CircuitState.HALF_OPEN
                return True

        if self._state == CircuitState.HALF_OPEN and self._last_trade_success:
            self._state = CircuitState.CLOSED
            self._trip_reason = ""
            return True

        return False

    def record_trade_result(self, success: bool) -> None:
        """Record whether the last trade was a success or failure.

        Used by :meth:`attempt_reset` to decide HALF_OPEN → CLOSED transitions.

        Args:
            success: ``True`` if the trade closed profitably.
        """
        self._last_trade_success = success

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        """``True`` when the circuit breaker is in the OPEN state."""
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        """``True`` when the circuit breaker is in the CLOSED state."""
        return self._state == CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Current :class:`CircuitState`."""
        return self._state

    @property
    def trip_reason(self) -> str:
        """Human-readable reason for the last trip, or empty string."""
        return self._trip_reason
