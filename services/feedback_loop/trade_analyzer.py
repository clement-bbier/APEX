"""Trade attribution analyzer for APEX Trading System."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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

        All input arithmetic is Decimal per CLAUDE.md §2; r_multiple and
        actual_outcome are cast to float at the JSON-serialization
        boundary only.

        Note (post-#258): this method previously used a defensive
        ``getattr(trade, "...", 0.0) or 0.0`` pattern that mixed Decimal
        TradeRecord fields with float defaults, raising TypeError on
        ``Decimal / float``. TradeRecord is a frozen Pydantic v2 model
        (``core/models/order.py:339``), so direct attribute access is
        correct and Decimal-throughout is enforced. TradeRecord does not
        carry a ``stop_loss`` field, so the risk denominator uses
        ``|entry_price - exit_price|`` (consistent with
        :pyattr:`TradeRecord.r_multiple`), falling back to
        ``Decimal("1")`` when entry == exit to avoid division-by-zero.

        Note (post-#258 semantic deviation): r_multiple is computed here
        as ``net_pnl / |entry - exit|`` without the size factor. This
        differs from :pyattr:`TradeRecord.r_multiple`
        (``core/models/order.py:415``) which uses
        ``|entry - exit| * size`` as denominator. The TradeRecord
        property is the canonical position-aware risk multiple. The
        value computed here is a per-unit-price r-multiple used
        internally by feedback_loop attribution. Both are mathematically
        valid but report different magnitudes; unifying them would be a
        follow-up.

        Args:
            trade: TradeRecord instance to analyze.

        Returns:
            Dict with keys: signal_type, regime_at_entry, session,
            mtf_score, expected_slippage_bps, actual_outcome, r_multiple.
        """
        entry = trade.entry_price
        exit_price = trade.exit_price
        pnl = trade.net_pnl

        risk = abs(entry - exit_price)
        if risk == Decimal("0"):
            risk = Decimal("1")
        r_multiple = float(pnl / risk)

        return {
            "signal_type": trade.signal_type if trade.signal_type else "unknown",
            "regime_at_entry": (trade.regime_at_entry if trade.regime_at_entry else "unknown"),
            "session": trade.session_at_entry if trade.session_at_entry else "unknown",
            "mtf_score": trade.mtf_alignment_score,
            # expected_slippage_bps is not modeled on TradeRecord; the dict
            # key is preserved for downstream consumers (vestigial).
            "expected_slippage_bps": 0.0,
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
