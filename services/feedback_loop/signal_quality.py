"""Signal quality analysis for APEX Trading System."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.models.order import TradeRecord


class SignalQuality:
    """Evaluates signal quality grouped by type, regime, and session."""

    def compute_by_type(self, trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
        """Compute win rate and average PnL grouped by signal type.

        Args:
            trades: List of TradeRecord instances.

        Returns:
            Dict keyed by signal_type with "win_rate" and "avg_pnl".
        """
        return self._group_stats(trades, "signal_type")

    def compute_by_regime(self, trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
        """Compute win rate and average PnL grouped by regime at entry.

        Args:
            trades: List of TradeRecord instances.

        Returns:
            Dict keyed by regime_at_entry with "win_rate" and "avg_pnl".
        """
        return self._group_stats(trades, "regime_at_entry")

    def compute_by_session(self, trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
        """Compute win rate and average PnL grouped by session at entry.

        Args:
            trades: List of TradeRecord instances.

        Returns:
            Dict keyed by session_at_entry with "win_rate" and "avg_pnl".
        """
        return self._group_stats(trades, "session_at_entry")

    def best_configurations(self, trades: list[TradeRecord]) -> list[dict[str, Any]]:
        """Return the top 3 signal_type + regime + session combinations by Sharpe.

        Args:
            trades: List of TradeRecord instances.

        Returns:
            List of up to 3 dicts with keys "signal_type", "regime",
            "session", and "sharpe".
        """
        groups: dict[tuple[str, ...], list[float]] = {}
        for trade in trades:
            key = (
                getattr(trade, "signal_type", "unknown"),
                getattr(trade, "regime_at_entry", "unknown"),
                getattr(trade, "session_at_entry", "unknown"),
            )
            pnl = float(getattr(trade, "net_pnl", 0.0) or 0.0)
            groups.setdefault(key, []).append(pnl)

        scored: list[dict[str, Any]] = []
        for (sig, regime, session), pnls in groups.items():
            arr = np.array(pnls, dtype=float)
            std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
            sharpe = float(np.mean(arr) / std) if std > 0.0 else 0.0
            scored.append(
                {
                    "signal_type": sig,
                    "regime": regime,
                    "session": session,
                    "sharpe": sharpe,
                }
            )

        scored.sort(key=lambda x: x["sharpe"], reverse=True)
        return scored[:3]

    def _group_stats(self, trades: list[TradeRecord], attr: str) -> dict[str, dict[str, Any]]:
        """Generic grouping helper that computes win_rate and avg_pnl.

        Args:
            trades: List of TradeRecord instances.
            attr: Attribute name to group by.

        Returns:
            Dict keyed by attribute value with "win_rate" and "avg_pnl".
        """
        groups: dict[str, list[TradeRecord]] = {}
        for trade in trades:
            key = str(getattr(trade, attr, "unknown"))
            groups.setdefault(key, []).append(trade)

        result: dict[str, dict[str, Any]] = {}
        for key, group in groups.items():
            pnls = [float(getattr(t, "net_pnl", 0.0) or 0.0) for t in group]
            wins = [t for t in group if float(getattr(t, "net_pnl", 0.0) or 0.0) > 0.0]
            result[key] = {
                "win_rate": len(wins) / len(group) if group else 0.0,
                "avg_pnl": float(np.mean(pnls)) if pnls else 0.0,
            }
        return result
