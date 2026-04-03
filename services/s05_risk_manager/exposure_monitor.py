"""Portfolio exposure monitor for APEX Trading System - S05 Risk Manager.

Reads live position data from Redis and validates whether a new
:class:`~core.models.order.OrderCandidate` would breach total-exposure
or simultaneous-position limits.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import Settings
from core.models.order import OrderCandidate
from core.state import StateStore


class ExposureMonitor:
    """Track and validate portfolio-level exposure limits.

    Open positions are stored in Redis under keys of the form
    ``positions:{symbol}``.  Each key contains a JSON object with at
    least ``size`` and ``entry`` numeric fields.
    """

    def __init__(self) -> None:
        """Initialize the exposure monitor."""
        self._position_cache: dict[str, dict] = {}

    # ── Exposure queries ──────────────────────────────────────────────────────

    async def get_total_exposure(
        self,
        state: StateStore,
        capital: Decimal,
    ) -> float:
        """Compute total open exposure as a percentage of capital.

        Scans all ``positions:*`` keys in Redis and sums
        ``size × entry`` for each position.

        Args:
            state:   Connected :class:`~core.state.StateStore` instance.
            capital: Portfolio capital in quote currency.

        Returns:
            Total exposure as a percentage of capital (e.g. ``15.0`` = 15 %).
        """
        if capital <= Decimal("0"):
            return 0.0

        r = state._ensure_connected()
        keys = await r.keys("positions:*")
        total_value = Decimal("0")
        for key in keys:
            raw = await state.get(key if isinstance(key, str) else key.decode())
            if isinstance(raw, dict):
                try:
                    pos_size = Decimal(str(raw.get("size", 0)))
                    pos_entry = Decimal(str(raw.get("entry", 0)))
                    total_value += pos_size * pos_entry
                except Exception:
                    continue

        return float(total_value / capital * Decimal("100"))

    async def get_position_count(self, state: StateStore) -> int:
        """Return the number of currently open positions.

        Args:
            state: Connected :class:`~core.state.StateStore` instance.

        Returns:
            Count of ``positions:*`` keys in Redis.
        """
        r = state._ensure_connected()
        keys = await r.keys("positions:*")
        return len(keys)

    # ── Validation ─────────────────────────────────────────────────────────────

    async def check_exposure(
        self,
        candidate: OrderCandidate,
        state: StateStore,
        capital: Decimal,
        settings: Settings,
    ) -> tuple[bool, str]:
        """Check whether adding the candidate would breach exposure limits.

        Checks:

        1. ``total_exposure + new_value / capital ≤ max_total_exposure_pct / 100``.
        2. ``current_position_count < max_simultaneous_positions``.

        Args:
            candidate: Proposed order candidate.
            state:     Connected :class:`~core.state.StateStore` instance.
            capital:   Portfolio capital in quote currency.
            settings:  Application settings containing threshold values.

        Returns:
            ``(True, "")`` if both checks pass;
            ``(False, reason)`` on failure.
        """
        new_value = candidate.size * candidate.entry
        new_exposure_pct = (
            float(new_value / capital * Decimal("100")) if capital > Decimal("0") else 0.0
        )

        current_exposure_pct = await self.get_total_exposure(state, capital)
        combined = current_exposure_pct + new_exposure_pct

        if combined > settings.max_total_exposure_pct:
            return (
                False,
                f"total exposure {combined:.1f}% would exceed max "
                f"{settings.max_total_exposure_pct}%",
            )

        position_count = await self.get_position_count(state)
        if position_count >= settings.max_simultaneous_positions:
            return (
                False,
                f"open positions {position_count} at max {settings.max_simultaneous_positions}",
            )

        return True, ""
