"""Trade attribution analyzer for APEX Trading System."""

from __future__ import annotations
from typing import Any

from core.models.order import TradeRecord


class TradeAnalyzer:
    """Analyzes individual and batch trade records for attribution."""

    def analyze(self, trade: TradeRecord) -> dict[str, Any]:
        """Return a full attribution dict[str, Any] for a single trade.

        Args:
            trade: TradeRecord instance to analyze.

        Returns:
            Dict with keys: signal_type, regime_at_entry, session,
            mtf_score, expected_slippage_bps, actual_outcome, r_multiple.
        """
        entry = getattr(trade, "entry_price", 0.0) or 0.0
        getattr(trade, "exit_price", 0.0) or 0.0
        stop = getattr(trade, "stop_loss", 0.0) or 0.0
        risk = abs(entry - stop) if entry and stop else 1.0
        pnl = getattr(trade, "net_pnl", 0.0) or 0.0
        r_multiple = float(pnl / risk) if risk != 0.0 else 0.0

        return {
            "signal_type": getattr(trade, "signal_type", "unknown"),
            "regime_at_entry": getattr(trade, "regime_at_entry", "unknown"),
            "session": getattr(trade, "session_at_entry", "unknown"),
            "mtf_score": getattr(trade, "mtf_score", 0.0),
            "expected_slippage_bps": getattr(trade, "expected_slippage_bps", 0.0),
            "actual_outcome": float(pnl),
            "r_multiple": r_multiple,
        }

    def batch_analyze(self, trades: list[TradeRecord]) -> list[dict[str, Any]]:
        """Analyze a list of trade records.

        Args:
            trades: List of TradeRecord instances.

        Returns:
            List of attribution dicts, one per trade.
        """
        return [self.analyze(trade) for trade in trades]
