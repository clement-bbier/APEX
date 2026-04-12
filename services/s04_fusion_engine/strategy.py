"""Strategy compatibility and sizing multiplier rules for APEX S04.

Maps strategies to allowable regime conditions and returns per-strategy
sizing multipliers for use by the Fusion Engine service.

Uses a declarative registry (StrategyProfile dataclass) so that adding
a new strategy requires only a registry entry — no code change.

Design pattern: Strategy + Registry (Open/Closed Principle).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.models.regime import Regime, RiskMode, TrendRegime, VolRegime


@dataclass(frozen=True)
class StrategyProfile:
    """Declarative strategy affinity — which regimes activate it.

    Attributes:
        name: Unique strategy identifier.
        active_vol_regimes: Vol regimes where this strategy may run.
        active_trend_regimes: Trend regimes where this strategy may run.
            If empty, trend is not constrained.
        use_or_logic: If True, match trend OR vol (not both).
            Default is AND (both must match).
        size_multiplier: Fixed sizing multiplier for this strategy.
    """

    name: str
    active_vol_regimes: frozenset[VolRegime] = field(default_factory=frozenset)
    active_trend_regimes: frozenset[TrendRegime] = field(default_factory=frozenset)
    use_or_logic: bool = False
    size_multiplier: float = 1.0

    def is_compatible(self, trend: TrendRegime, vol: VolRegime) -> bool:
        """Check if the given regime combination activates this strategy."""
        vol_match = vol in self.active_vol_regimes if self.active_vol_regimes else True
        trend_match = trend in self.active_trend_regimes if self.active_trend_regimes else True
        if self.use_or_logic:
            return vol_match or trend_match
        return vol_match and trend_match


# ── Declarative registry — add a strategy by adding an entry ─────────────────

STRATEGY_REGISTRY: dict[str, StrategyProfile] = {
    "momentum_scalp": StrategyProfile(
        name="momentum_scalp",
        active_vol_regimes=frozenset({VolRegime.NORMAL}),
        active_trend_regimes=frozenset({TrendRegime.TRENDING_UP, TrendRegime.TRENDING_DOWN}),
        size_multiplier=1.0,
    ),
    "mean_reversion": StrategyProfile(
        name="mean_reversion",
        active_vol_regimes=frozenset({VolRegime.LOW, VolRegime.NORMAL}),
        active_trend_regimes=frozenset({TrendRegime.RANGING}),
        size_multiplier=0.8,
    ),
    "spike_scalp": StrategyProfile(
        name="spike_scalp",
        active_vol_regimes=frozenset({VolRegime.HIGH}),
        size_multiplier=0.5,
    ),
    "short_momentum": StrategyProfile(
        name="short_momentum",
        active_vol_regimes=frozenset({VolRegime.HIGH, VolRegime.CRISIS}),
        active_trend_regimes=frozenset({TrendRegime.TRENDING_DOWN}),
        use_or_logic=True,
        size_multiplier=0.6,
    ),
}


class StrategySelector:
    """Check strategy compatibility and retrieve sizing multipliers.

    Uses :data:`STRATEGY_REGISTRY` for declarative lookup — no if/elif chains.
    All strategies are automatically blocked when ``risk_mode`` is
    ``BLOCKED`` or ``CRISIS``.
    """

    def __init__(
        self,
        registry: dict[str, StrategyProfile] | None = None,
    ) -> None:
        self._registry = registry if registry is not None else STRATEGY_REGISTRY

    def is_active(self, strategy: str, regime: Regime) -> bool:
        """Return ``True`` if ``strategy`` is compatible with the current regime.

        Args:
            strategy: Strategy name string.
            regime:   Current market regime snapshot.

        Returns:
            ``True`` if the strategy may be executed.
        """
        if regime.risk_mode in (RiskMode.BLOCKED, RiskMode.CRISIS):
            return False
        profile = self._registry.get(strategy)
        if profile is None:
            return False
        return profile.is_compatible(regime.trend_regime, regime.vol_regime)

    def get_size_multiplier(self, strategy: str, regime: Regime) -> float:
        """Return the size multiplier for a given strategy and regime.

        Args:
            strategy: Strategy name string.
            regime:   Current market regime snapshot.

        Returns:
            Size multiplier (``0.0`` to ``1.0``).
        """
        if regime.risk_mode == RiskMode.CRISIS:
            return 0.0
        profile = self._registry.get(strategy)
        if profile is None:
            return 0.0
        return profile.size_multiplier
