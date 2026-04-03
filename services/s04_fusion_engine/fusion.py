"""Fusion scoring and strategy selection for APEX Trading System - S04.

Combines multi-timeframe alignment, session context, confluence bonus, and
macro regime into a single numeric score used for final position sizing.
"""

from __future__ import annotations

from core.models.regime import Regime, RiskMode, TrendRegime, VolRegime
from core.models.signal import Signal


class FusionEngine:
    """Compute composite fusion scores and select an execution strategy.

    All methods are stateless transforms over their inputs.
    """

    # ── Confluence ────────────────────────────────────────────────────────────

    def compute_confluence_bonus(self, triggers: list[str]) -> float:
        """Return a bonus multiplier based on the number of active triggers.

        Scoring:
        - 0 triggers → 0.0
        - 1 trigger  → 0.50
        - 2 triggers → 1.00
        - 3+ triggers → 1.35

        Args:
            triggers: List of trigger identifiers that fired for this signal.

        Returns:
            Confluence bonus multiplier.
        """
        n = len(triggers)
        if n >= 3:
            return 1.35
        if n == 2:
            return 1.00
        if n == 1:
            return 0.50
        return 0.0

    # ── Final score ───────────────────────────────────────────────────────────

    def compute_final_score(self, signal: Signal, regime: Regime) -> float:
        """Compute the final fusion score for a signal in the given regime.

        Formula::

            final = |signal.strength|
                    × regime.macro_mult
                    × confluence_bonus
                    × session_mult
                    × mtf_alignment
                    × session_prime_bonus

        The result is capped at ``2.0``.

        Args:
            signal: The trade signal to score.
            regime: Current market regime snapshot.

        Returns:
            Final fusion score in ``[0.0, 2.0]``.
        """
        mtf_alignment = (
            signal.mtf_context.alignment_score if signal.mtf_context is not None else 0.7
        )
        session_mult = signal.mtf_context.session_bonus if signal.mtf_context is not None else 1.0
        confluence_bonus = self.compute_confluence_bonus(signal.triggers)
        session_prime_bonus = 1.10 if regime.session.is_us_prime else 1.0

        final = (
            abs(signal.strength)
            * regime.macro_mult
            * confluence_bonus
            * session_mult
            * mtf_alignment
            * session_prime_bonus
        )
        return min(final, 2.0)

    # ── Strategy selection ────────────────────────────────────────────────────

    def select_strategy(self, regime: Regime) -> str:
        """Choose the most appropriate execution strategy for the current regime.

        Decision table:

        - TRENDING_UP or TRENDING_DOWN → ``"momentum_scalp"``
        - RANGING → ``"mean_reversion"``
        - HIGH volatility → ``"spike_scalp"``
        - CRISIS → ``"blocked"``
        - Default → ``"momentum_scalp"``

        Args:
            regime: Current market regime snapshot.

        Returns:
            Strategy name string.
        """
        if regime.risk_mode == RiskMode.CRISIS:
            return "blocked"

        if regime.trend_regime in (TrendRegime.TRENDING_UP, TrendRegime.TRENDING_DOWN):
            return "momentum_scalp"

        if regime.trend_regime == TrendRegime.RANGING:
            return "mean_reversion"

        if regime.vol_regime == VolRegime.HIGH:
            return "spike_scalp"

        return "momentum_scalp"
