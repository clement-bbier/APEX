"""Unit tests for S09 SignalQuality.

Tests: compute_by_type, compute_by_regime, empty list, best_configurations.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.feedback_loop.signal_quality import SignalQuality


def _trade(
    trade_id: str,
    net_pnl: str,
    signal_type: str = "ofi",
    regime: str = "trending_up",
    session: str = "us_normal",
) -> TradeRecord:
    net = Decimal(net_pnl)
    gross = net + Decimal("1")
    return TradeRecord(
        trade_id=trade_id,
        symbol="BTCUSDT",
        direction=Direction.LONG,
        entry_timestamp_ms=1_000_000,
        exit_timestamp_ms=2_000_000,
        entry_price=Decimal("45000"),
        exit_price=Decimal("46000"),
        size=Decimal("0.01"),
        gross_pnl=gross,
        net_pnl=net,
        commission=Decimal("1"),
        slippage_cost=Decimal("0"),
        signal_type=signal_type,
        regime_at_entry=regime,
        session_at_entry=session,
    )


class TestSignalQuality:
    quality = SignalQuality()

    def test_compute_by_type(self) -> None:
        trades = [
            _trade("t1", "10", signal_type="ofi"),
            _trade("t2", "-5", signal_type="ofi"),
            _trade("t3", "20", signal_type="rsi_divergence"),
        ]
        result = self.quality.compute_by_type(trades)
        assert "ofi" in result
        assert "rsi_divergence" in result
        assert result["ofi"]["win_rate"] == pytest.approx(0.5)
        assert result["rsi_divergence"]["win_rate"] == pytest.approx(1.0)

    def test_compute_by_regime(self) -> None:
        trades = [
            _trade("t1", "10", regime="trending_up"),
            _trade("t2", "15", regime="trending_up"),
            _trade("t3", "-5", regime="ranging"),
        ]
        result = self.quality.compute_by_regime(trades)
        assert result["trending_up"]["win_rate"] == pytest.approx(1.0)
        assert result["trending_up"]["avg_pnl"] == pytest.approx(12.5)
        assert result["ranging"]["win_rate"] == pytest.approx(0.0)

    def test_empty_trades(self) -> None:
        assert self.quality.compute_by_type([]) == {}
        assert self.quality.compute_by_regime([]) == {}

    def test_best_configurations_returns_top_3(self) -> None:
        trades = [
            _trade("t1", "100", signal_type="ofi", regime="trending_up", session="us_prime"),
            _trade("t2", "100", signal_type="ofi", regime="trending_up", session="us_prime"),
            _trade("t3", "50", signal_type="cvd", regime="ranging", session="us_normal"),
            _trade("t4", "-10", signal_type="bb_bounce", regime="ranging", session="asian"),
            _trade("t5", "5", signal_type="ema_cross", regime="trending_up", session="london"),
        ]
        best = self.quality.best_configurations(trades)
        assert len(best) <= 3
        sharpes = [entry["sharpe"] for entry in best]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_best_configurations_single_trade_group(self) -> None:
        # Groups with only one trade should have sharpe=0 (std=0)
        trades = [_trade("t1", "50")]
        best = self.quality.best_configurations(trades)
        assert len(best) == 1
        assert best[0]["sharpe"] == 0.0
