"""Strategy compatibility and sizing multiplier rules for APEX S04.

Maps strategies to allowable regime conditions and returns per-strategy
sizing multipliers for use by the Fusion Engine service.
"""

from __future__ import annotations

from core.models.regime import Regime, RiskMode, TrendRegime, VolRegime


class StrategySelector:
    """Check strategy compatibility and retrieve sizing multipliers.

    Each strategy is valid only in specific trend-regime / vol-regime
    combinations.  All strategies are automatically blocked when
    ``risk_mode`` is ``BLOCKED`` or ``CRISIS``.
    """

    def is_active(self, strategy: str, regime: Regime) -> bool:
        """Return ``True`` if ``strategy`` is compatible with the current regime.

        Hard-blocked regimes (BLOCKED / CRISIS) disable every strategy.

        Compatibility table:

        - ``"momentum_scalp"`` : TRENDING_UP or TRENDING_DOWN, NORMAL vol.
        - ``"mean_reversion"`` : RANGING trend, LOW or NORMAL vol.
        - ``"spike_scalp"``    : HIGH vol only.
        - ``"short_momentum"`` : TRENDING_DOWN, HIGH vol, or CRISIS vol.

        Args:
            strategy: Strategy name string.
            regime:   Current market regime snapshot.

        Returns:
            ``True`` if the strategy may be executed.
        """
        if regime.risk_mode in (RiskMode.BLOCKED, RiskMode.CRISIS):
            return False

        trend = regime.trend_regime
        vol = regime.vol_regime

        if strategy == "momentum_scalp":
            return (
                trend in (TrendRegime.TRENDING_UP, TrendRegime.TRENDING_DOWN)
                and vol == VolRegime.NORMAL
            )

        if strategy == "mean_reversion":
            return trend == TrendRegime.RANGING and vol in (
                VolRegime.LOW,
                VolRegime.NORMAL,
            )

        if strategy == "spike_scalp":
            return vol == VolRegime.HIGH

        if strategy == "short_momentum":
            return trend == TrendRegime.TRENDING_DOWN or vol in (
                VolRegime.HIGH,
                VolRegime.CRISIS,
            )

        return False

    def get_size_multiplier(self, strategy: str, regime: Regime) -> float:
        """Return the size multiplier for a given strategy and regime.

        If the regime is CRISIS the multiplier is always ``0.0``.

        Multiplier table:

        - ``"momentum_scalp"`` → 1.0
        - ``"mean_reversion"`` → 0.8
        - ``"spike_scalp"``    → 0.5
        - ``"short_momentum"`` → 0.6
        - Unknown strategy     → 0.0

        Args:
            strategy: Strategy name string.
            regime:   Current market regime snapshot.

        Returns:
            Size multiplier (``0.0`` to ``1.0``).
        """
        if regime.risk_mode == RiskMode.CRISIS:
            return 0.0

        _multipliers: dict[str, float] = {
            "momentum_scalp": 1.0,
            "mean_reversion": 0.8,
            "spike_scalp": 0.5,
            "short_momentum": 0.6,
        }
        return _multipliers.get(strategy, 0.0)
