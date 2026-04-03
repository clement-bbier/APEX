"""Drift detection and regime change monitoring for APEX Trading System."""

from __future__ import annotations

import numpy as np

from core.models.order import TradeRecord


class DriftDetector:
    """Detects performance drift and volatility changes in trade outcomes."""

    def rolling_win_rate(self, trades: list[TradeRecord], window: int = 50) -> float:
        """Compute win rate over the most recent `window` trades.

        Args:
            trades: Full list of TradeRecord instances.
            window: Number of most recent trades to include.

        Returns:
            Win rate as a fraction in [0.0, 1.0].
        """
        recent = trades[-window:] if len(trades) >= window else trades
        if not recent:
            return 0.0
        wins = sum(1 for t in recent if float(getattr(t, "net_pnl", 0.0) or 0.0) > 0.0)
        return wins / len(recent)

    def is_drifting(
        self,
        current_win_rate: float,
        baseline_win_rate: float,
        threshold: float = 0.10,
    ) -> bool:
        """Determine whether performance has drifted below acceptable levels.

        Args:
            current_win_rate: Recent rolling win rate.
            baseline_win_rate: Historical baseline win rate.
            threshold: Maximum acceptable drop in win rate.

        Returns:
            True if current_win_rate has dropped more than threshold below baseline.
        """
        return (baseline_win_rate - current_win_rate) > threshold

    def pnl_garch_vol(self, pnl_series: list[float]) -> float:
        """Estimate current volatility of PnL using GARCH(1,1).

        σ²_t = ω + α×ε²_(t-1) + β×σ²_(t-1)
        Uses default params: ω=0.0001, α=0.1, β=0.85.

        Args:
            pnl_series: List of PnL values over time.

        Returns:
            Current conditional volatility (σ) estimate.
        """
        omega, alpha, beta = 0.0001, 0.1, 0.85
        if not pnl_series:
            return float(np.sqrt(omega))

        arr = np.array(pnl_series, dtype=float)
        sigma2 = float(np.var(arr)) if len(arr) > 1 else omega
        for r in arr:
            sigma2 = omega + alpha * (r**2) + beta * sigma2
        return float(np.sqrt(max(sigma2, 0.0)))

    def outcome_correlation(
        self,
        predicted_strengths: list[float],
        actual_pnls: list[float],
    ) -> float:
        """Compute Pearson correlation between predicted signal strength and actual PnL.

        Args:
            predicted_strengths: List of signal strength scores.
            actual_pnls: List of corresponding realised PnL values.

        Returns:
            Pearson correlation coefficient in [-1.0, 1.0], or 0.0 if insufficient data.
        """
        n = min(len(predicted_strengths), len(actual_pnls))
        if n < 2:
            return 0.0
        x = np.array(predicted_strengths[:n], dtype=float)
        y = np.array(actual_pnls[:n], dtype=float)
        corr_matrix = np.corrcoef(x, y)
        return float(corr_matrix[0, 1])
