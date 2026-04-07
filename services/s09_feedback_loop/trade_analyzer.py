"""Trade attribution analyzer for APEX Trading System."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from core.models.order import TradeRecord

if TYPE_CHECKING:
    from core.state import StateStore

logger = structlog.get_logger(__name__)


class TradeAnalyzer:
    """Analyzes individual and batch trade records for attribution."""

    def __init__(self, state: StateStore | None = None) -> None:
        """Initialize analyzer with optional StateStore for Redis updates.

        Args:
            state: Optional StateStore instance. Required for _update_kelly_stats.
        """
        self._state = state

    def analyze(self, trade: TradeRecord) -> dict[str, Any]:
        """Return a full attribution dict for a single trade.

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

    def batch_analyze(self, trades: list[Any]) -> list[dict[str, Any]]:
        """Analyze a list of trade records.

        Args:
            trades: List of TradeRecord instances (or any object with TradeRecord fields).

        Returns:
            List of attribution dicts, one per trade.
        """
        return [self.analyze(trade) for trade in trades]

    async def _update_kelly_stats(self, trades: list[Any]) -> None:
        """Update Kelly statistics in Redis after each closed trade.

        Called by S09 whenever a TradeRecord is finalized.
        Writes rolling win_rate and avg_rr over the last 50 trades.

        Args:
            trades: All closed trades seen so far (any object with pnl_net and pnl_pct).
        """
        if self._state is None:
            return

        if len(trades) < 5:
            return  # need minimum trades

        recent = trades[-50:]  # rolling last 50 trades
        wins = [t for t in recent if getattr(t, "net_pnl", 0.0) > 0]
        losses = [t for t in recent if getattr(t, "net_pnl", 0.0) <= 0]

        win_rate = len(wins) / len(recent)

        avg_win = sum(abs(float(getattr(t, "pnl_pct", 0.0))) for t in wins) / max(len(wins), 1)
        avg_loss = sum(abs(float(getattr(t, "pnl_pct", 0.0))) for t in losses) / max(len(losses), 1)
        avg_rr = avg_win / avg_loss if avg_loss > 0 else 1.5

        await self._state.set(
            "feedback:kelly_stats:default",
            {
                "win_rate": round(win_rate, 4),
                "avg_rr": round(avg_rr, 4),
                "n_trades": len(recent),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "kelly_stats_updated",
            win_rate=win_rate,
            avg_rr=avg_rr,
            n_trades=len(recent),
        )
