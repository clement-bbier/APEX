"""Tests for TradeAnalyzer attribution and Kelly stats update."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.order import TradeRecord
from services.s09_feedback_loop.trade_analyzer import TradeAnalyzer


def make_trade(net_pnl: float = 100.0, pnl_pct: float = 0.05) -> MagicMock:
    t = MagicMock(spec=TradeRecord)
    t.net_pnl = Decimal(str(net_pnl))
    t.pnl_pct = pnl_pct
    t.entry_price = Decimal("100")
    t.exit_price = Decimal("105")
    t.stop_loss = Decimal("95")
    t.signal_type = "COMPOSITE"
    t.regime_at_entry = "normal"
    t.session_at_entry = "us_prime"
    t.mtf_score = 0.8
    t.expected_slippage_bps = 5.0
    return t


class TestTradeAnalyzer:
    def test_analyze_returns_required_keys(self) -> None:
        analyzer = TradeAnalyzer()
        trade = make_trade()
        result = analyzer.analyze(trade)
        assert "signal_type" in result
        assert "regime_at_entry" in result
        assert "session" in result
        assert "r_multiple" in result

    def test_batch_analyze_length(self) -> None:
        analyzer = TradeAnalyzer()
        trades = [make_trade() for _ in range(5)]
        results = analyzer.batch_analyze(trades)
        assert len(results) == 5

    def test_r_multiple_positive_trade(self) -> None:
        analyzer = TradeAnalyzer()
        trade = make_trade(net_pnl=50.0)
        result = analyzer.analyze(trade)
        assert result["actual_outcome"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_update_kelly_stats_skips_below_5_trades(self) -> None:
        state = AsyncMock()
        analyzer = TradeAnalyzer(state=state)
        await analyzer._update_kelly_stats([make_trade() for _ in range(3)])
        state.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_kelly_stats_writes_to_redis(self) -> None:
        state = AsyncMock()
        analyzer = TradeAnalyzer(state=state)
        trades = [make_trade(net_pnl=100.0, pnl_pct=0.05) for _ in range(10)]
        trades += [make_trade(net_pnl=-50.0, pnl_pct=-0.025) for _ in range(5)]
        await analyzer._update_kelly_stats(trades)
        state.set.assert_called_once()
        call_args = state.set.call_args
        assert call_args[0][0] == "feedback:kelly_stats:default"
        payload = call_args[0][1]
        assert "win_rate" in payload
        assert "avg_rr" in payload
        assert "n_trades" in payload

    @pytest.mark.asyncio
    async def test_update_kelly_stats_no_state_is_noop(self) -> None:
        analyzer = TradeAnalyzer(state=None)
        # Should not raise even without state
        await analyzer._update_kelly_stats([make_trade() for _ in range(10)])
