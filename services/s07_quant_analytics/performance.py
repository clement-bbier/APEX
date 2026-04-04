"""Portfolio performance analytics for APEX Trading System."""

from __future__ import annotations

from typing import Any

import numpy as np


class PerformanceAnalyzer:
    """Computes standard and advanced portfolio performance metrics."""

    def sharpe_ratio(self, returns: list[float], risk_free_rate: float = 0.05) -> float:
        """Compute the annualised Sharpe ratio.

        Sharpe = (Rp - Rf) / σp × sqrt(252)

        Args:
            returns: List of daily return values.
            risk_free_rate: Annual risk-free rate (default 5%).

        Returns:
            Annualised Sharpe ratio, or 0.0 if standard deviation is zero.
        """
        if not returns:
            return 0.0
        arr = np.array(returns, dtype=float)
        daily_rf = risk_free_rate / 252.0
        excess = arr - daily_rf
        std = float(np.std(excess, ddof=1))
        if std == 0.0:
            return 0.0
        return float(np.mean(excess) / std * np.sqrt(252))

    def sortino_ratio(self, returns: list[float], risk_free_rate: float = 0.05) -> float:
        """Compute the annualised Sortino ratio using downside deviation.

        Only negative excess returns contribute to the denominator.

        Args:
            returns: List of daily return values.
            risk_free_rate: Annual risk-free rate (default 5%).

        Returns:
            Annualised Sortino ratio, or 0.0 if downside deviation is zero.
        """
        if not returns:
            return 0.0
        arr = np.array(returns, dtype=float)
        daily_rf = risk_free_rate / 252.0
        excess = arr - daily_rf
        downside = excess[excess < 0.0]
        if len(downside) == 0:
            return 0.0
        downside_std = float(np.std(downside, ddof=1))
        if downside_std == 0.0:
            return 0.0
        return float(np.mean(excess) / downside_std * np.sqrt(252))

    def calmar_ratio(self, annual_return: float, max_drawdown: float) -> float:
        """Compute the Calmar ratio.

        Calmar = annual_return / |max_drawdown|

        Args:
            annual_return: Annualised portfolio return.
            max_drawdown: Maximum drawdown value (may be negative or positive).

        Returns:
            Calmar ratio, or 0.0 if max_drawdown is zero.
        """
        if max_drawdown == 0.0:
            return 0.0
        return annual_return / abs(max_drawdown)

    def max_drawdown(self, equity_curve: list[float]) -> tuple[float, int]:
        """Compute maximum drawdown percentage and its duration.

        Args:
            equity_curve: List of equity values over time.

        Returns:
            Tuple of (max_drawdown_pct, duration_in_periods) where duration
            is the number of periods in the longest consecutive drawdown.
        """
        if not equity_curve:
            return 0.0, 0

        arr = np.array(equity_curve, dtype=float)
        peak = arr[0]
        max_dd = 0.0
        max_duration = 0
        current_duration = 0

        for value in arr:
            if value > peak:
                peak = value
                current_duration = 0
            else:
                current_duration += 1
                if peak > 0.0:
                    dd = (peak - value) / peak
                    if dd > max_dd:
                        max_dd = dd
            if current_duration > max_duration:
                max_duration = current_duration

        return float(max_dd), int(max_duration)

    def information_ratio(
        self,
        portfolio_returns: list[float],
        benchmark_returns: list[float],
    ) -> float:
        """Compute the annualised Information Ratio.

        IR = mean(active_returns) / std(active_returns) × sqrt(252)

        Args:
            portfolio_returns: List of portfolio daily returns.
            benchmark_returns: List of benchmark daily returns.

        Returns:
            Annualised Information Ratio, or 0.0 if tracking error is zero.
        """
        n = min(len(portfolio_returns), len(benchmark_returns))
        if n == 0:
            return 0.0
        active = np.array(portfolio_returns[:n]) - np.array(benchmark_returns[:n])
        std = float(np.std(active, ddof=1))
        if std == 0.0:
            return 0.0
        return float(np.mean(active) / std * np.sqrt(252))

    def factor_attribution(self, trade_records: list[dict[str, Any]]) -> dict[str, Any]:
        """Attribute performance across regimes, sessions, and signal types.

        Groups trades by regime, session, and signal_type, then computes
        win_rate and avg_pnl for each group.

        Args:
            trade_records: List of trade dicts with keys such as "regime",
                "session", "signal_type", "pnl", and "won".

        Returns:
            Nested dict[str, Any] keyed by group dimension then group value, each
            containing "win_rate" and "avg_pnl".
        """
        result: dict[str, Any] = {"regime": {}, "session": {}, "signal_type": {}}

        def _group(key: str) -> dict[str, Any]:
            groups: dict[str, list[dict[str, Any]]] = {}
            for trade in trade_records:
                grp = str(trade.get(key, "unknown"))
                groups.setdefault(grp, []).append(trade)
            out = {}
            for grp, trades in groups.items():
                pnls = [float(t.get("pnl", 0.0)) for t in trades]
                wins = [t for t in trades if t.get("won", False)]
                out[grp] = {
                    "win_rate": len(wins) / len(trades) if trades else 0.0,
                    "avg_pnl": float(np.mean(pnls)) if pnls else 0.0,
                }
            return out

        result["regime"] = _group("regime")
        result["session"] = _group("session")
        result["signal_type"] = _group("signal_type")
        return result
