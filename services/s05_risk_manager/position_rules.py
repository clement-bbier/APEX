"""Position-level risk rules for APEX Trading System - S05 Risk Manager.

Validates a single :class:`~core.models.order.OrderCandidate` against
portfolio-level thresholds defined in application settings.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import Settings
from core.models.order import OrderCandidate


class PositionRules:
    """Validate an order candidate against risk-management constraints.

    All checks are applied sequentially.  The first failing check short-circuits
    and returns ``(False, <reason>)``.
    """

    def validate(
        self,
        candidate: OrderCandidate,
        capital: Decimal,
        settings: Settings,
    ) -> tuple[bool, str]:
        """Run all position-level risk checks.

        Checks performed (in order):

        1. **Capital at risk** – ``capital_at_risk ≤ capital × max_position_risk_pct / 100``.
        2. **Stop loss exists** – ``candidate.stop_loss > 0``.
        3. **Minimum R:R** – if a source signal is attached,
           ``signal.risk_reward ≥ min_risk_reward``.
        4. **Maximum position size** – ``size × entry ≤ capital × max_position_size_pct / 100``.

        Args:
            candidate: Order candidate to validate.
            capital:   Total portfolio capital in quote currency.
            settings:  Application settings containing threshold values.

        Returns:
            ``(True, "")`` if all checks pass;
            ``(False, reason_string)`` on the first failure.
        """
        # 1. Capital at risk
        max_risk = capital * Decimal(str(settings.max_position_risk_pct)) / Decimal("100")
        if candidate.capital_at_risk > max_risk:
            return (
                False,
                f"capital_at_risk {candidate.capital_at_risk} exceeds max "
                f"{max_risk} ({settings.max_position_risk_pct}% of {capital})",
            )

        # 2. Stop loss must be positive
        if candidate.stop_loss <= Decimal("0"):
            return False, "stop_loss must be greater than zero"

        # 3. Minimum risk/reward ratio
        if candidate.source_signal is not None:
            rr = candidate.source_signal.risk_reward
            if rr is not None and rr < settings.min_risk_reward:
                return (
                    False,
                    f"risk_reward {rr:.2f} below minimum {settings.min_risk_reward}",
                )

        # 4. Maximum position size
        position_value = candidate.size * candidate.entry
        max_size_value = capital * Decimal(str(settings.max_position_size_pct)) / Decimal("100")
        if position_value > max_size_value:
            return (
                False,
                f"position_value {position_value} exceeds max "
                f"{max_size_value} ({settings.max_position_size_pct}% of {capital})",
            )

        return True, ""
