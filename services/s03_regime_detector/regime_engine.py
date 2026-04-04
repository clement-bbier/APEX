"""Regime computation engine for APEX Trading System - S03 Regime Detector.

Translates raw macro indicators (VIX, DXY, yield spread) and price history
into typed regime values.

Two APIs are provided:

* Legacy API (compute_vol_regime / compute_macro_mult / compute_trend_regime /
  compute_risk_mode) — used by RegimeDetectorService._tick().
* Phase-2 API (compute) — returns a RegimeState with richer VIX thresholds,
  DXY risk-off detection, and yield curve inversion handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from core.models.regime import (
    RiskMode as CoreRiskMode,
)
from core.models.regime import (
    TrendRegime,
)
from core.models.regime import (
    VolRegime as CoreVolRegime,
)

# ── Phase-2 local enums ────────────────────────────────────────────────────────


class VolRegime(StrEnum):
    """Volatility regime with Phase-2 granularity."""

    CRISIS = "crisis"
    HIGH_VOL = "high_vol"
    NORMAL = "normal"
    LOW_VOL = "low_vol"
    TRENDING = "trending"


class RiskMode(StrEnum):
    """System risk mode derived from macro indicators."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"


@dataclass
class RegimeState:
    """Full regime state returned by the Phase-2 compute() method."""

    vol_regime: VolRegime
    risk_mode: RiskMode
    macro_mult: float
    vix: float
    dxy_1h_change_pct: float
    yield_curve_inverted: bool
    reasoning: list[str]


# ── Engine ─────────────────────────────────────────────────────────────────────


class RegimeEngine:
    """Stateless engine for computing market regime signals.

    Provides both the legacy per-indicator methods (used by RegimeDetectorService)
    and the Phase-2 compute() method that returns a RegimeState.
    """

    def __init__(self) -> None:
        """Initialize the regime engine (stateless; no config needed)."""

    # ── Phase-2 API ───────────────────────────────────────────────────────────

    VIX_THRESHOLDS: ClassVar[dict[str, float]] = {
        "crisis": 35.0,
        "high_vol": 25.0,
        "normal": 15.0,
    }

    BASE_MULT: ClassVar[dict[VolRegime, float]] = {
        VolRegime.CRISIS: 0.0,
        VolRegime.HIGH_VOL: 0.3,
        VolRegime.NORMAL: 1.0,
        VolRegime.LOW_VOL: 1.2,
        VolRegime.TRENDING: 1.5,
    }

    def compute(
        self,
        vix: float,
        dxy_1h_change_pct: float,
        yield_10y: float,
        yield_2y: float,
        btc_funding_rate: float = 0.0,
    ) -> RegimeState:
        """Compute current regime from macro inputs.

        Args:
            vix: CBOE VIX index current value.
            dxy_1h_change_pct: DXY % change over last 1 hour.
            yield_10y: US 10-year treasury yield.
            yield_2y: US 2-year treasury yield.
            btc_funding_rate: Binance perpetual funding rate (crypto only).

        Returns:
            RegimeState with vol_regime, risk_mode, macro_mult, and reasoning.
        """
        reasoning: list[str] = []

        # Step 1: VIX-based vol regime
        if vix >= self.VIX_THRESHOLDS["crisis"]:
            vol_regime = VolRegime.CRISIS
            reasoning.append(f"VIX={vix:.1f} → CRISIS (> 35)")
        elif vix >= self.VIX_THRESHOLDS["high_vol"]:
            vol_regime = VolRegime.HIGH_VOL
            reasoning.append(f"VIX={vix:.1f} → HIGH_VOL (25-35)")
        elif vix >= self.VIX_THRESHOLDS["normal"]:
            vol_regime = VolRegime.NORMAL
            reasoning.append(f"VIX={vix:.1f} → NORMAL (15-25)")
        else:
            vol_regime = VolRegime.LOW_VOL
            reasoning.append(f"VIX={vix:.1f} → LOW_VOL (< 15)")

        # Step 2: Base multiplier
        macro_mult = self.BASE_MULT[vol_regime]

        # Step 3: Risk-off adjustments
        yield_inverted = yield_2y > yield_10y

        if dxy_1h_change_pct > 0.5:
            macro_mult *= 0.7
            reasoning.append(f"DXY +{dxy_1h_change_pct:.2f}% in 1h → risk_off x0.7")

        if yield_inverted:
            macro_mult *= 0.8
            reasoning.append(
                f"Yield curve inverted (2Y={yield_2y:.2f}% > 10Y={yield_10y:.2f}%) → x0.8"
            )

        if abs(btc_funding_rate) > 0.03:  # > 3% 8h funding = extreme sentiment
            macro_mult *= 0.9
            reasoning.append(f"Extreme funding rate {btc_funding_rate:.3f} → x0.9")

        # Step 4: Risk mode classification
        risk_mode = RiskMode.RISK_OFF if (
            dxy_1h_change_pct > 0.3
            or yield_inverted
            or vol_regime in (VolRegime.CRISIS, VolRegime.HIGH_VOL)
        ) else RiskMode.RISK_ON

        return RegimeState(
            vol_regime=vol_regime,
            risk_mode=risk_mode,
            macro_mult=round(macro_mult, 3),
            vix=vix,
            dxy_1h_change_pct=dxy_1h_change_pct,
            yield_curve_inverted=yield_inverted,
            reasoning=reasoning,
        )

    # ── Legacy API (used by RegimeDetectorService._tick) ─────────────────────

    def compute_vol_regime(self, vix: float | None) -> CoreVolRegime:
        """Classify the current volatility regime from a VIX reading.

        Thresholds:
        - VIX < 15  → LOW
        - 15 ≤ VIX < 25 → NORMAL
        - 25 ≤ VIX < 35 → HIGH
        - VIX ≥ 35  → CRISIS

        Args:
            vix: Current VIX level.  If ``None``, returns NORMAL.

        Returns:
            A :class:`CoreVolRegime` enum value.
        """
        if vix is None:
            return CoreVolRegime.NORMAL
        if vix < 15.0:
            return CoreVolRegime.LOW
        if vix < 25.0:
            return CoreVolRegime.NORMAL
        if vix < 35.0:
            return CoreVolRegime.HIGH
        return CoreVolRegime.CRISIS

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

    def compute_risk_mode(
        self,
        vol_regime: CoreVolRegime,
        event_active: bool,
        circuit_open: bool,
    ) -> CoreRiskMode:
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
            The appropriate :class:`CoreRiskMode`.
        """
        if vol_regime == CoreVolRegime.CRISIS:
            return CoreRiskMode.CRISIS
        if event_active:
            return CoreRiskMode.REDUCED
        if circuit_open:
            return CoreRiskMode.BLOCKED
        if vol_regime == CoreVolRegime.HIGH:
            return CoreRiskMode.REDUCED
        return CoreRiskMode.NORMAL

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        """Compute the exponential moving average of *prices* over *period*.

        Args:
            prices: Price series (oldest first).
            period: EMA period.

        Returns:
            EMA value computed on the full series.
        """
        k = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = price * k + ema * (1.0 - k)
        return ema
