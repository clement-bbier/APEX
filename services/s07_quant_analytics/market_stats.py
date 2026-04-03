"""Market statistics and econometric tests for APEX Trading System."""

from __future__ import annotations

import numpy as np
from typing import Optional


class MarketStats:
    """Provides econometric and statistical tests for market data analysis."""

    def ljung_box(self, returns: list[float], lags: int = 10) -> dict:
        """Compute the Ljung-Box Q-statistic test for autocorrelation.

        Q = n(n+2) × Σ(ρ_k²/(n-k)) for k=1..lags.

        Args:
            returns: List of return values.
            lags: Number of lags to include in the test.

        Returns:
            dict with keys "q_stat" (float) and "significant" (bool).
            Significant is True if Q > chi-squared critical value (approx lags * 1.5).
        """
        n = len(returns)
        if n < lags + 1:
            return {"q_stat": 0.0, "significant": False}

        arr = np.array(returns, dtype=float)
        mean = np.mean(arr)
        variance = np.var(arr)
        if variance == 0.0:
            return {"q_stat": 0.0, "significant": False}

        autocorrs = []
        for k in range(1, lags + 1):
            cov = np.mean((arr[k:] - mean) * (arr[:-k] - mean))
            autocorrs.append(cov / variance)

        q_stat = n * (n + 2) * sum(
            (rho ** 2) / (n - k) for k, rho in enumerate(autocorrs, start=1)
        )
        # Approximate 5% critical value for chi-squared with `lags` degrees of freedom
        critical_value = lags * 1.5
        return {"q_stat": float(q_stat), "significant": bool(q_stat > critical_value)}

    def hurst_exponent(self, prices: list[float]) -> float:
        """Estimate the Hurst exponent using the R/S method.

        H = log(R/S) / log(n).
        Values near 0.5 indicate a random walk, > 0.5 trending, < 0.5 mean-reverting.

        Args:
            prices: List of price values.

        Returns:
            Hurst exponent as a float, or 0.5 if insufficient data (< 20 points).
        """
        if len(prices) < 20:
            return 0.5

        arr = np.array(prices, dtype=float)
        n = len(arr)
        mean = np.mean(arr)
        deviations = arr - mean
        cumulative = np.cumsum(deviations)
        r = np.max(cumulative) - np.min(cumulative)
        s = np.std(arr, ddof=1)
        if s == 0.0:
            return 0.5
        rs = r / s
        if rs <= 0.0:
            return 0.5
        return float(np.log(rs) / np.log(n))

    def garch_volatility(
        self,
        returns: list[float],
        omega: float = 0.0001,
        alpha: float = 0.1,
        beta: float = 0.85,
    ) -> float:
        """Compute GARCH(1,1) volatility estimate.

        σ²_t = ω + α×ε²_(t-1) + β×σ²_(t-1)

        Args:
            returns: List of return values.
            omega: Long-run variance weight (ω).
            alpha: ARCH coefficient (α).
            beta: GARCH coefficient (β).

        Returns:
            Current conditional volatility (σ) as a float.
        """
        if not returns:
            return float(np.sqrt(omega))

        arr = np.array(returns, dtype=float)
        sigma2 = np.var(arr) if len(arr) > 1 else omega
        for r in arr:
            sigma2 = omega + alpha * (r ** 2) + beta * sigma2
        return float(np.sqrt(max(sigma2, 0.0)))

    def realized_vs_implied_ratio(
        self, realized_vol: float, implied_vol: float
    ) -> Optional[float]:
        """Compute the ratio of realized to implied volatility.

        Args:
            realized_vol: Realized (historical) volatility.
            implied_vol: Implied volatility from options market.

        Returns:
            realized_vol / implied_vol, or None if implied_vol is zero.
        """
        if implied_vol == 0.0:
            return None
        return realized_vol / implied_vol
