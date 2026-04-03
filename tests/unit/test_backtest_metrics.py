"""Unit tests for backtesting metrics: Sharpe, Sortino, Calmar, drawdown."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backtesting.metrics import (
    avg_win_loss,
    calmar_ratio,
    equity_curve_from_trades,
    full_report,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)
from core.models.order import TradeRecord
from core.models.signal import Direction


def _make_trade(
    net_pnl: str,
    exit_ts: int = 0,
    signal_type: str = "OFI",
    regime: str = "RANGING",
    session: str = "us_normal",
) -> TradeRecord:
    pnl = Decimal(net_pnl)
    entry = Decimal("50000")
    size = Decimal("0.01")
    exit_p = entry + pnl / size
    return TradeRecord(
        trade_id=f"t-{exit_ts}",
        symbol="BTC/USDT",
        direction=Direction.LONG,
        entry_timestamp_ms=exit_ts - 1000,
        exit_timestamp_ms=exit_ts,
        entry_price=entry,
        exit_price=exit_p,
        size=size,
        gross_pnl=pnl,
        net_pnl=pnl,
        commission=Decimal("0"),
        slippage_cost=Decimal("0"),
        signal_type=signal_type,
        regime_at_entry=regime,
        session_at_entry=session,
    )


class TestSharpeRatio:
    def test_positive_sharpe_for_consistent_gains(self) -> None:
        returns = [0.01] * 100
        s = sharpe_ratio(returns)
        assert s > 0.0

    def test_zero_returns_negative_sharpe(self) -> None:
        # Zero returns with 5% risk-free rate → negative Sharpe
        returns = [0.0] * 50
        s = sharpe_ratio(returns, risk_free_rate=0.05)
        assert s < 0.0

    def test_negative_sharpe_for_losses(self) -> None:
        returns = [-0.01] * 100
        s = sharpe_ratio(returns, risk_free_rate=0.0)
        assert s < 0.0

    def test_empty_returns(self) -> None:
        assert sharpe_ratio([]) == 0.0

    def test_single_return(self) -> None:
        assert sharpe_ratio([0.05]) == 0.0


class TestMaxDrawdown:
    def test_no_drawdown(self) -> None:
        curve = [100.0, 110.0, 120.0, 130.0]
        dd, dur = max_drawdown(curve)
        assert dd == pytest.approx(0.0, abs=1e-9)
        assert dur == 0

    def test_simple_drawdown(self) -> None:
        # Peak=110, trough=90: DD = 20/110 ≈ 18.18%
        curve = [100.0, 110.0, 90.0, 105.0]
        dd, _ = max_drawdown(curve)
        assert dd == pytest.approx(20 / 110, rel=1e-4)

    def test_short_curve(self) -> None:
        dd, dur = max_drawdown([100.0])
        assert dd == 0.0


class TestWinRateProfitFactor:
    def test_all_winners(self) -> None:
        trades = [_make_trade("100", i) for i in range(10)]
        assert win_rate(trades) == pytest.approx(1.0)
        assert profit_factor(trades) == float("inf")

    def test_all_losers(self) -> None:
        trades = [_make_trade("-100", i) for i in range(10)]
        assert win_rate(trades) == 0.0
        assert profit_factor(trades) == 0.0

    def test_mixed(self) -> None:
        trades = [_make_trade("200", i) for i in range(6)]
        trades += [_make_trade("-100", i + 100) for i in range(4)]
        assert win_rate(trades) == pytest.approx(0.6)
        pf = profit_factor(trades)
        # gross_win=1200, gross_loss=400 → PF=3.0
        assert pf == pytest.approx(3.0)


class TestFullReport:
    def test_report_returns_expected_keys(self) -> None:
        trades = [_make_trade("100", i * 1000) for i in range(5)]
        report = full_report(trades, initial_capital=10000.0)
        assert "sharpe" in report
        assert "sortino" in report
        assert "calmar" in report
        assert "max_drawdown" in report
        assert "win_rate" in report
        assert "profit_factor" in report
        assert "by_session" in report
        assert "by_regime" in report
        assert "by_signal" in report
        assert "equity_curve" in report

    def test_no_trades_returns_error(self) -> None:
        report = full_report([])
        assert "error" in report
