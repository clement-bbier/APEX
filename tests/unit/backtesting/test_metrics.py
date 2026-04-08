"""Property tests for backtesting.metrics.full_report().

Regression coverage for issue #8: Sharpe must be computed on the
daily-resampled equity curve, not on per-trade returns. A strategy with
WR > 80% and PF > 2 must yield a strictly positive Sharpe.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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


# ---------------------------------------------------------------------------
# Property tests for PSR / DSR / stationary-bootstrap CI wiring (issue #19).
# References:
#   Bailey & López de Prado (2012) — PSR
#   Bailey & López de Prado (2014) — DSR
#   Politis & Romano (1994)         — stationary bootstrap
#   ADR-0002 Quant Methodology Charter
# ---------------------------------------------------------------------------


def _seeded_equity_curve(
    n_days: int = 60,
    win_rate: float = 0.6,
    mean_return: float = 0.003,
    loss_size: float = 0.003,
    seed: int = 42,
) -> tuple[list[TradeRecord], float]:
    """Build a synthetic seeded daily equity curve and matching trades."""
    rng = np.random.default_rng(seed)
    coin = rng.random(n_days)
    daily_returns = np.where(coin < win_rate, mean_return, -loss_size)
    base_ts_s = 1_704_067_200  # 2024-01-01 UTC
    initial = 100_000.0
    equity = initial * np.cumprod(1.0 + daily_returns)
    trades: list[TradeRecord] = []
    prev = initial
    for i in range(n_days):
        day_pnl = float(equity[i]) - prev
        prev = float(equity[i])
        ts_ms = (base_ts_s + i * 86_400) * 1000
        trades.append(_make_trade(day_pnl, ts_ms))
    return trades, initial


def _full_report_from_seeded_strategy(
    n_days: int = 60,
    win_rate: float = 0.6,
    mean_return: float = 0.003,
    loss_size: float = 0.003,
    seed: int = 42,
    n_trials: int = 1,
    risk_free_rate: float = 0.05,
) -> dict[str, Any]:
    trades, initial = _seeded_equity_curve(
        n_days=n_days,
        win_rate=win_rate,
        mean_return=mean_return,
        loss_size=loss_size,
        seed=seed,
    )
    return full_report(
        trades=trades,
        initial_capital=initial,
        risk_free_rate=risk_free_rate,
        n_trials=n_trials,
    )


def test_psr_in_unit_interval() -> None:
    """PSR is a probability so it must live in [0, 1]."""
    report = _full_report_from_seeded_strategy(win_rate=0.6, seed=42)
    psr = float(report["psr"])
    assert 0.0 <= psr <= 1.0


def test_psr_monotonic_in_sharpe() -> None:
    """Higher Sharpe ⇒ higher PSR, ceteris paribus."""
    weak = _full_report_from_seeded_strategy(mean_return=0.001, seed=42)
    strong = _full_report_from_seeded_strategy(mean_return=0.005, seed=42)
    assert float(strong["sharpe"]) > float(weak["sharpe"])
    assert float(strong["psr"]) >= float(weak["psr"])


def test_dsr_strictly_less_than_psr_under_multiple_trials() -> None:
    """DSR deflates PSR when multiple trials are tested."""
    single = _full_report_from_seeded_strategy(seed=42, n_trials=1)
    multi = _full_report_from_seeded_strategy(seed=42, n_trials=50)
    assert float(multi["dsr"]) < float(single["psr"])


def test_bootstrap_ci_contains_point_sharpe() -> None:
    """The 95% bootstrap CI must straddle the point estimate."""
    report = _full_report_from_seeded_strategy(seed=42)
    lo = float(report["sharpe_ci_95_low"])
    hi = float(report["sharpe_ci_95_high"])
    sharpe = float(report["sharpe"])
    assert lo <= sharpe <= hi


def test_bootstrap_ci_width_shrinks_with_sample_size() -> None:
    """Law of large numbers: larger samples yield tighter CIs."""
    short = _full_report_from_seeded_strategy(n_days=30, seed=42)
    long = _full_report_from_seeded_strategy(n_days=300, seed=42)
    short_w = float(short["sharpe_ci_95_high"]) - float(short["sharpe_ci_95_low"])
    long_w = float(long["sharpe_ci_95_high"]) - float(long["sharpe_ci_95_low"])
    assert long_w < short_w


def test_profitable_strategy_has_high_psr() -> None:
    """An 85% winrate strategy with mean daily return 0.5% must get PSR > 0.90."""
    report = _full_report_from_seeded_strategy(
        n_days=120,
        win_rate=0.85,
        mean_return=0.005,
        loss_size=0.003,
        seed=42,
    )
    psr = float(report["psr"])
    assert psr > 0.90, f"got PSR={psr}"


def test_psr_and_sharpe_are_mutually_consistent_at_nonzero_rf() -> None:
    """PSR and Sharpe must both see the same excess-return series.

    Regression test for a bug discovered in PR #20 Copilot review: PSR
    was computed on raw daily returns while Sharpe was computed on
    excess returns, making them silently inconsistent whenever
    risk_free_rate > 0.
    """
    report_rf0 = _full_report_from_seeded_strategy(
        win_rate=0.70, mean_return=0.004, seed=42, risk_free_rate=0.0
    )
    report_rf5 = _full_report_from_seeded_strategy(
        win_rate=0.70, mean_return=0.004, seed=42, risk_free_rate=0.05
    )
    # Sharpe must drop when rf increases.
    assert report_rf5["sharpe"] < report_rf0["sharpe"]
    # PSR must also drop (not stay constant — that was the bug).
    assert report_rf5["psr"] < report_rf0["psr"]
