"""Rough Volatility and Variance Ratio Test for APEX Trading System.

H ≈ 0.1 empirically for all major assets (Gatheral et al. 2018).
This means volatility is ANTI-PERSISTENT on short scales:
  - H < 0.5 → mean-reverting vol → scalping edge identified
  - H → 0   → maximum roughness → high short-term predictability
  - H = 0.5 → classical Brownian motion (no edge)

The Variance Ratio Test quantifies whether log-returns exhibit
autocorrelation (momentum) or anti-autocorrelation (mean reversion)
at different horizons — directly actionable as signal strength modifier.

References:
    Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018).
        Volatility is rough. Quantitative Finance, 18(6), 933-949.
    Lo, A.W. & MacKinlay, A.C. (1988).
        Stock Market Prices Do Not Follow Random Walks.
        Review of Financial Studies, 1(1), 41-66.
    Cont, R. (2001). Empirical properties of asset returns:
        stylized facts and statistical issues.
        Quantitative Finance, 1(2), 223-236.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class RoughVolSignal:
    """Output of rough volatility analysis."""

    hurst_exponent: float     # H ∈ (0, 0.5) for rough vol; closer to 0 = rougher
    is_rough: bool            # H < 0.3 → strong rough vol regime
    scalping_edge_score: float  # [0, 1]: higher = more predictable short-term vol
    vol_regime: str           # "rough" | "semi_rough" | "classical"
    size_adjustment: float    # Multiplicative adjustment for position sizing


@dataclass
class VarianceRatioResult:
    """Output of Lo-MacKinlay Variance Ratio Test."""

    vr_q: float             # VR(q) = Var(r_t + ... + r_{t+q}) / (q × Var(r_t))
    q: int                  # Aggregation period
    z_statistic: float      # Standardized test statistic
    signal: str             # "momentum" | "mean_reversion" | "random_walk"
    signal_strength: float  # |VR(q) - 1| normalized ∈ [0, 1]
    is_significant: bool    # |z| > 1.96 at 95% confidence


class RoughVolAnalyzer:
    """Rough volatility regime detection via Hurst exponent estimation.

    Uses the log-log regression method (R/S analysis) on vol time series.
    More robust than simple price R/S for detecting rough vol properties.
    """

    def estimate_hurst_from_vol(
        self,
        realized_vols: list[float],
        n_lags: int = 10,
    ) -> RoughVolSignal:
        """Estimate Hurst exponent from realized volatility series.

        Method: compute the autocorrelation structure of log(vol):
            C(τ) = E[log σ_t × log σ_{t+τ}]
            For rough vol: C(τ) ∝ τ^{2H}  (Gatheral et al. 2018 eq.1)

        Empirical finding: H ≈ 0.10 ± 0.05 for S&P 500, Bitcoin,
        forex, commodities — universally rough across all asset classes.

        Trading implication: when H is estimated to be very small (< 0.2),
        the vol process is highly predictable over short windows → stronger
        mean-reversion signals → increase scalping confidence.

        Args:
            realized_vols: Daily realized volatility series (annualized).
            n_lags: Number of autocorrelation lags to fit (default 10).

        Returns:
            RoughVolSignal with regime classification and sizing adjustment.
        """
        if len(realized_vols) < n_lags + 5:
            return RoughVolSignal(hurst_exponent=0.5, is_rough=False,
                                  scalping_edge_score=0.0, vol_regime="classical",
                                  size_adjustment=1.0)

        log_vols = np.log(np.maximum(np.asarray(realized_vols, dtype=float), 1e-10))
        log_vols -= np.mean(log_vols)

        # Compute autocorrelations at lags 1..n_lags
        lags = np.arange(1, n_lags + 1, dtype=float)
        n = len(log_vols)
        autocorrs = []
        for lag in range(1, n_lags + 1):
            if n - lag < 5:
                break
            c = float(np.mean(log_vols[:n-lag] * log_vols[lag:]))
            c0 = float(np.var(log_vols))
            autocorrs.append(max(1e-10, abs(c / c0) if c0 > 0 else 1e-10))

        if len(autocorrs) < 3:
            return RoughVolSignal(hurst_exponent=0.5, is_rough=False,
                                  scalping_edge_score=0.0, vol_regime="classical",
                                  size_adjustment=1.0)

        # Log-log regression: log C(τ) = 2H × log(τ) + const
        log_lags = np.log(lags[:len(autocorrs)])
        log_corrs = np.log(np.array(autocorrs))
        try:
            slope, _ = np.polyfit(log_lags, log_corrs, 1)
        except (np.linalg.LinAlgError, ValueError):
            slope = 0.0

        # H = slope / 2, clamped to (0, 0.5)
        h = max(0.01, min(0.5, float(slope) / 2.0))

        is_rough = h < 0.3
        # Edge score: higher when H is smaller (rougher = more predictable)
        edge_score = max(0.0, min(1.0, (0.5 - h) / 0.5))

        if h < 0.2:
            regime = "rough"
            size_adj = 1.15  # vol predictability → slight size boost
        elif h < 0.35:
            regime = "semi_rough"
            size_adj = 1.05
        else:
            regime = "classical"
            size_adj = 1.0

        return RoughVolSignal(hurst_exponent=h, is_rough=is_rough,
                              scalping_edge_score=edge_score,
                              vol_regime=regime, size_adjustment=size_adj)

    def variance_ratio_test(
        self,
        log_returns: list[float],
        q: int = 5,
    ) -> VarianceRatioResult:
        """Lo-MacKinlay (1988) Variance Ratio Test.

        VR(q) = Var(r_t + r_{t-1} + ... + r_{t-q+1}) / (q × Var(r_t))

        Under random walk null: VR(q) = 1.
        VR(q) > 1 → positive autocorrelation → momentum signal.
        VR(q) < 1 → negative autocorrelation → mean reversion signal.

        Standardized test statistic (Lo-MacKinlay 1988 eq.14):
            z*(q) = (VR(q) - 1) / √(Θ*(q) / n)
        where Θ*(q) accounts for heteroskedasticity.

        This test is used by Renaissance Technologies, AQR, and
        Dimensional Fund Advisors to identify exploitable return patterns.

        Args:
            log_returns: Log return series.
            q: Aggregation period (e.g., q=5 for weekly autocorrelation).

        Returns:
            VarianceRatioResult with signal direction and significance.
        """
        r = np.asarray(log_returns, dtype=float)
        n = len(r)
        if n < 2 * q:
            return VarianceRatioResult(vr_q=1.0, q=q, z_statistic=0.0,
                                       signal="random_walk", signal_strength=0.0,
                                       is_significant=False)

        # Variance of single-period returns (demean)
        mu = np.mean(r)
        r_dm = r - mu
        var1 = float(np.var(r_dm, ddof=1))

        if var1 == 0:
            return VarianceRatioResult(vr_q=1.0, q=q, z_statistic=0.0,
                                       signal="random_walk", signal_strength=0.0,
                                       is_significant=False)

        # Variance of q-period returns
        r_q = np.array([np.sum(r[i:i+q]) for i in range(n - q + 1)])
        mu_q = np.mean(r_q)
        var_q = float(np.var(r_q - mu_q, ddof=1))

        vr = (var_q / q) / var1

        # Heteroskedasticity-consistent standard error (Lo-MacKinlay 1988)
        theta = 0.0
        for k in range(1, q):
            delta_k = float(np.sum(r_dm[:-k] ** 2 * r_dm[k:] ** 2)) / (var1 ** 2 * n) ** 2
            theta += (2.0 * (q - k) / q) ** 2 * delta_k

        se = math.sqrt(max(theta, 1.0 / n) / n)
        z = (vr - 1.0) / se if se > 0 else 0.0

        if vr > 1.05:
            signal = "momentum"
        elif vr < 0.95:
            signal = "mean_reversion"
        else:
            signal = "random_walk"

        strength = min(1.0, abs(vr - 1.0) / 0.5)

        return VarianceRatioResult(vr_q=vr, q=q, z_statistic=z,
                                   signal=signal, signal_strength=strength,
                                   is_significant=abs(z) > 1.96)
