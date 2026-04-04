"""Drift Detector - Model performance degradation detection.

Monitors rolling win rate over last 50 trades.
Alerts if win rate drops > 10% from 3-month baseline.
Triggers daily review cycle.

This service does NOT automatically adjust parameters.
It observes and reports - humans validate all changes.
(per MANIFEST.md Section 9, Service 09)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from core.models.order import TradeRecord


@dataclass
class DriftAlert:
    """Alert fired when win rate drifts significantly from its baseline."""

    timestamp: datetime
    current_win_rate: float
    baseline_win_rate: float
    drop_pct: float
    n_trades_in_window: int
    message: str


class DriftDetector:
    """Detects when system performance has drifted below its baseline.

    Alert threshold: win rate drops > 10% relative to 3-month baseline.
    Minimum sample: 50 trades required before any alert fires.
    """

    DRIFT_THRESHOLD = 0.10  # 10% relative drop triggers alert
    MIN_TRADES = 50

    def check_drift(
        self,
        recent_trades: list[Any],
        baseline_win_rate: float,
    ) -> DriftAlert | None:
        """Check if recent performance has drifted from baseline.

        Args:
            recent_trades:    Last N trade objects with a pnl_net attribute.
            baseline_win_rate: 3-month historical win rate [0.0, 1.0].

        Returns:
            :class:`DriftAlert` if drift detected, None if healthy.
        """
        if len(recent_trades) < self.MIN_TRADES:
            return None  # insufficient data

        wins = sum(1 for t in recent_trades if getattr(t, "pnl_net", 0) > 0)
        current_wr = wins / len(recent_trades)

        drop = baseline_win_rate - current_wr
        drop_pct = drop / baseline_win_rate if baseline_win_rate > 0 else 0.0

        if drop_pct >= self.DRIFT_THRESHOLD:
            return DriftAlert(
                timestamp=datetime.now(UTC),
                current_win_rate=current_wr,
                baseline_win_rate=baseline_win_rate,
                drop_pct=drop_pct,
                n_trades_in_window=len(recent_trades),
                message=(
                    f"WIN RATE DRIFT DETECTED: {current_wr:.1%} vs baseline "
                    f"{baseline_win_rate:.1%} ({drop_pct:.1%} drop over "
                    f"{len(recent_trades)} trades). "
                    f"Review signal quality and current regime."
                ),
            )
        return None

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
            threshold: Maximum acceptable absolute drop in win rate.

        Returns:
            True if current_win_rate has dropped more than threshold below baseline.
        """
        return (baseline_win_rate - current_win_rate) > threshold

    def pnl_garch_vol(self, pnl_series: list[float]) -> float:
        """Estimate current PnL volatility using GARCH(1,1).

        sigma^2_t = omega + alpha * eps^2_(t-1) + beta * sigma^2_(t-1)
        Default params: omega=0.0001, alpha=0.1, beta=0.85.

        Args:
            pnl_series: List of PnL values over time.

        Returns:
            Current conditional volatility (sigma) estimate.
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
