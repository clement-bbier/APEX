"""Regime computation engine for APEX Trading System - S03 Regime Detector.

Translates raw macro indicators (VIX, DXY, yield spread) and price history
into typed :class:`~core.models.regime.VolRegime`,
:class:`~core.models.regime.TrendRegime`, and
:class:`~core.models.regime.RiskMode` values.
"""

from __future__ import annotations

from core.models.regime import RiskMode, TrendRegime, VolRegime


class RegimeEngine:
    """Stateless engine for computing market regime signals.

    All methods are pure functions over their inputs.
    """

    def __init__(self) -> None:
        """Initialize the regime engine (stateless; no config needed)."""

    # ── Volatility regime ─────────────────────────────────────────────────────

    def compute_vol_regime(self, vix: float | None) -> VolRegime:
        """Classify the current volatility regime from a VIX reading.

        Thresholds:
        - VIX < 15  → LOW
        - 15 ≤ VIX < 25 → NORMAL
        - 25 ≤ VIX < 35 → HIGH
        - VIX ≥ 35  → CRISIS

        Args:
            vix: Current VIX level.  If ``None``, returns NORMAL.

        Returns:
            A :class:`VolRegime` enum value.
        """
        if vix is None:
            return VolRegime.NORMAL
        if vix < 15.0:
            return VolRegime.LOW
        if vix < 25.0:
            return VolRegime.NORMAL
        if vix < 35.0:
            return VolRegime.HIGH
        return VolRegime.CRISIS

    # ── Macro multiplier ──────────────────────────────────────────────────────

    def compute_macro_mult(
        self,
        vix: float | None,
        dxy: float | None,
        yield_spread: float | None,
    ) -> float:
        """Compute the macro sizing multiplier from macro indicators.

        Rules applied sequentially (multiplicative):
        - VIX > 30 : × 0.6
        - VIX > 20 : × 0.8  (else-if; lower threshold checked second)
        - Yield curve inverted (spread < 0) : × 0.9
        - Result is clamped to [0.0, 1.0].

        Args:
            vix:          Current VIX level or ``None``.
            dxy:          US Dollar Index (reserved, not yet used).
            yield_spread: 10Y-2Y yield spread; negative means inversion.

        Returns:
            Macro multiplier in ``[0.0, 1.0]``.
        """
        mult = 1.0

        if vix is not None:
            if vix > 30.0:
                mult *= 0.6
            elif vix > 20.0:
                mult *= 0.8

        if yield_spread is not None and yield_spread < 0.0:
            mult *= 0.9

        return max(0.0, min(1.0, mult))

    # ── Trend regime ──────────────────────────────────────────────────────────

    def compute_trend_regime(self, price_history: list[float]) -> TrendRegime:
        """Determine the trend regime by comparing 20- vs 50-period EMA direction.

        Requires at least 50 data points.  If insufficient data is provided,
        ``RANGING`` is returned as a conservative default.

        Args:
            price_history: List of close prices in chronological order
                           (oldest first, newest last).

        Returns:
            :class:`TrendRegime` based on EMA direction.
        """
        if len(price_history) < 50:
            return TrendRegime.RANGING

        ema20 = self._ema(price_history, 20)
        ema50 = self._ema(price_history, 50)

        if ema20 > ema50 * 1.001:
            return TrendRegime.TRENDING_UP
        if ema20 < ema50 * 0.999:
            return TrendRegime.TRENDING_DOWN
        return TrendRegime.RANGING

    # ── Risk mode ─────────────────────────────────────────────────────────────

    def compute_risk_mode(
        self,
        vol_regime: VolRegime,
        event_active: bool,
        circuit_open: bool,
    ) -> RiskMode:
        """Derive the system-wide risk mode.

        Priority order (highest to lowest):
        1. CRISIS vol regime → RiskMode.CRISIS
        2. CB event active   → RiskMode.REDUCED
        3. Circuit breaker open → RiskMode.BLOCKED
        4. HIGH vol regime   → RiskMode.REDUCED
        5. Otherwise         → RiskMode.NORMAL

        Args:
            vol_regime:    Current volatility regime.
            event_active:  ``True`` if a CB pre-event block is active.
            circuit_open:  ``True`` if the circuit breaker is tripped.

        Returns:
            The appropriate :class:`RiskMode`.
        """
        if vol_regime == VolRegime.CRISIS:
            return RiskMode.CRISIS
        if event_active:
            return RiskMode.REDUCED
        if circuit_open:
            return RiskMode.BLOCKED
        if vol_regime == VolRegime.HIGH:
            return RiskMode.REDUCED
        return RiskMode.NORMAL

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        """Compute the exponential moving average of *prices* over *period*.

        Uses the standard smoothing factor k = 2 / (period + 1).

        Args:
            prices: Price series (oldest first).
            period: EMA period.

        Returns:
            EMA value computed on the full series.
        """
        k = 2.0 / (period + 1)
        # Seed with the simple average of the first ``period`` prices.
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = price * k + ema * (1.0 - k)
        return ema
