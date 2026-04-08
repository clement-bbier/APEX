"""Property tests for backtesting.metrics.full_report().

Regression coverage for issue #8: Sharpe must be computed on the
daily-resampled equity curve, not on per-trade returns. A strategy with
WR > 80% and PF > 2 must yield a strictly positive Sharpe.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from backtesting.metrics import full_report
from core.models.order import TradeRecord
from core.models.signal import Direction


def _make_trade(net_pnl: float, exit_ts_ms: int) -> TradeRecord:
    pnl = Decimal(str(round(net_pnl, 2)))
    entry = Decimal("50000")
    size = Decimal("0.01")
    exit_p = entry + pnl / size
    return TradeRecord(
        trade_id=f"t-{exit_ts_ms}",
        symbol="BTC/USDT",
        direction=Direction.LONG,
        entry_timestamp_ms=exit_ts_ms - 1000,
        exit_timestamp_ms=exit_ts_ms,
        entry_price=entry,
        exit_price=exit_p,
        size=size,
        gross_pnl=pnl,
        net_pnl=pnl,
        commission=Decimal("0"),
        slippage_cost=Decimal("0"),
        signal_type="OFI",
        regime_at_entry="TRENDING",
        session_at_entry="us_normal",
    )


def test_profitable_strategy_has_positive_sharpe() -> None:
    """A strategy with WR>80% and PF>2 must yield positive Sharpe.

    Regression test for issue #8. The previous implementation computed
    Sharpe on per-trade returns minus an annualised 5% risk-free rate,
    yielding catastrophically negative Sharpe (down to -3709) for HFT
    strategies with WR=93% and PF=15. The fix routes Sharpe through the
    daily-resampled equity curve.
    """
    rng = np.random.default_rng(42)
    n_days = 30
    # Mostly winners (~85%) with bounded losers (~ -0.3%) and winners
    # of ~ +1.0%. PF = (0.85*30*1.0) / (0.15*30*0.3) ≈ 5.7, well above 2.
    coin = rng.random(n_days)
    daily_returns = np.where(coin < 0.15, -0.003, 0.010)
    equity = 100_000.0 * np.cumprod(1.0 + daily_returns)

    # One trade per day at UTC midnight, PnL = day's equity delta.
    base_ts_s = 1_704_067_200  # 2024-01-01 00:00:00 UTC
    trades: list[TradeRecord] = []
    prev_equity = 100_000.0
    for i in range(n_days):
        day_pnl = float(equity[i]) - prev_equity
        prev_equity = float(equity[i])
        # Skew towards winners to satisfy WR>80% and PF>2: shift sign
        # so that ~85% of days are wins. The synthetic returns above
        # are already mostly positive (mean 0.5%, std 1%).
        ts_ms = (base_ts_s + i * 86_400) * 1000
        trades.append(_make_trade(day_pnl, ts_ms))

    wins = sum(1 for t in trades if t.net_pnl > 0)
    win_rate_obs = wins / len(trades)
    gross_win = sum(float(t.net_pnl) for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(float(t.net_pnl) for t in trades if t.net_pnl < 0))
    pf_obs = gross_win / gross_loss if gross_loss > 0 else float("inf")

    assert win_rate_obs > 0.80, f"fixture WR={win_rate_obs:.2f} should be >0.80"
    assert pf_obs > 2.0, f"fixture PF={pf_obs:.2f} should be >2.0"

    report = full_report(trades=trades, initial_capital=100_000.0)

    assert report["sharpe"] > 0.0, (
        f"Profitable strategy (WR={win_rate_obs:.2f}, PF={pf_obs:.2f}) "
        f"should have positive Sharpe, got {report['sharpe']}"
    )
