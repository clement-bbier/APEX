"""Backtesting metrics for APEX Trading System.

Computes a comprehensive suite of performance statistics from a list of
:class:`~core.models.order.TradeRecord` objects and an equity curve.

References:
    - Sharpe (1966) — "Mutual Fund Performance"
    - Sortino & van der Meer (1991) — "Downside Risk"
    - Calmar ratio — Young (1991)
    - Lopez de Prado (2018) — "Advances in Financial Machine Learning"
"""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal

import numpy as np

from core.models.order import TradeRecord

# Annualisation factor for 1-minute bars (252 trading days × 390 min/day)
_ANNUAL_FACTOR_1M: float = math.sqrt(252 * 390)
_ANNUAL_FACTOR_DAILY: float = math.sqrt(252)


def _to_float(d: Decimal) -> float:
    """Safe Decimal → float conversion."""
    return float(d)


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.05,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> float:
    """Compute the annualised Sharpe ratio.

    Formula: ``S = (μ_p − r_f) / σ_p × √N``

    where N is the annualisation factor (√252 for daily, √(252×390) for 1m).

    Args:
        returns: Period returns as fractions (e.g. 0.01 = +1%).
        risk_free_rate: Annualised risk-free rate (default 5%).
        annual_factor: Square-root of annualisation periods per year.

    Returns:
        Annualised Sharpe ratio, 0.0 if std is zero.
    """
    if len(returns) < 2:
        return 0.0
    arr = np.asarray(returns)
    rf_per_period = risk_free_rate / (annual_factor**2)
    excess = arr - rf_per_period
    std = float(np.std(excess, ddof=1))
    if std == 0:
        return 0.0
    return float(np.mean(excess)) / std * annual_factor


def sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.05,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> float:
    """Compute the annualised Sortino ratio (downside deviation denominator).

    Formula: ``Sort = (μ_p − r_f) / σ_downside × √N``

    Args:
        returns: Period returns.
        risk_free_rate: Annualised risk-free rate.
        annual_factor: Square-root of annualisation factor.

    Returns:
        Annualised Sortino ratio, 0.0 if downside std is zero.
    """
    if len(returns) < 2:
        return 0.0
    arr = np.asarray(returns)
    rf_per_period = risk_free_rate / (annual_factor**2)
    excess = arr - rf_per_period
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    dd_std = float(np.std(downside, ddof=1))
    if dd_std == 0:
        return 0.0
    return float(np.mean(excess)) / dd_std * annual_factor


def calmar_ratio(annual_return: float, max_dd: float) -> float:
    """Compute the Calmar ratio.

    Formula: ``Calmar = annual_return / |max_drawdown|``

    Args:
        annual_return: Annualised portfolio return (e.g. 0.30 = 30%).
        max_dd: Maximum drawdown as a positive fraction (e.g. 0.10 = 10%).

    Returns:
        Calmar ratio, 0.0 if max_dd is zero.
    """
    if max_dd == 0:
        return 0.0
    return annual_return / abs(max_dd)


def max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
    """Compute maximum peak-to-trough drawdown and its duration.

    Args:
        equity_curve: Equity values over time.

    Returns:
        Tuple of (max_drawdown_fraction, duration_in_periods).
        Drawdown is a positive fraction (0.10 = 10% loss from peak).
    """
    if len(equity_curve) < 2:
        return 0.0, 0
    peak = equity_curve[0]
    max_dd = 0.0
    max_duration = 0
    dd_start = 0
    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            dd_start = i
        if peak > 0:
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
                max_duration = i - dd_start
    return max_dd, max_duration


def win_rate(trades: list[TradeRecord]) -> float:
    """Fraction of trades with positive net PnL.

    Args:
        trades: List of completed trade records.

    Returns:
        Win rate in [0, 1].
    """
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.is_winner) / len(trades)


def profit_factor(trades: list[TradeRecord]) -> float:
    """Ratio of gross profit to gross loss.

    Formula: ``PF = Σ(wins) / Σ(|losses|)``

    Args:
        trades: List of completed trade records.

    Returns:
        Profit factor (> 1.0 = profitable overall), 0.0 if no losses.
    """
    gross_win = sum(_to_float(t.net_pnl) for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(_to_float(t.net_pnl) for t in trades if t.net_pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def avg_win_loss(trades: list[TradeRecord]) -> tuple[float, float]:
    """Compute average winning and losing trade PnL.

    Args:
        trades: List of completed trade records.

    Returns:
        Tuple of (avg_win, avg_loss) in quote currency.
    """
    wins = [_to_float(t.net_pnl) for t in trades if t.net_pnl > 0]
    losses = [_to_float(t.net_pnl) for t in trades if t.net_pnl < 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.0
    return avg_w, avg_l


def equity_curve_from_trades(initial_capital: float, trades: list[TradeRecord]) -> list[float]:
    """Build an equity curve from sorted trade records.

    Args:
        initial_capital: Starting capital.
        trades: Trade records sorted by exit_timestamp_ms ascending.

    Returns:
        List of equity values after each trade.
    """
    equity = initial_capital
    curve = [equity]
    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)
    for trade in sorted_trades:
        equity += _to_float(trade.net_pnl)
        curve.append(equity)
    return curve


def by_session_breakdown(trades: list[TradeRecord]) -> dict[str, dict]:
    """Group trades by session and compute stats per group.

    Args:
        trades: List of completed trade records.

    Returns:
        Dict of {session_label: {trade_count, win_rate, avg_pnl, total_pnl}}.
    """
    groups: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        groups[t.session_at_entry or "unknown"].append(t)
    return _group_stats(groups)


def by_regime_breakdown(trades: list[TradeRecord]) -> dict[str, dict]:
    """Group trades by regime label and compute stats per group.

    Args:
        trades: List of completed trade records.

    Returns:
        Dict of {regime_label: {trade_count, win_rate, avg_pnl, total_pnl}}.
    """
    groups: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        groups[t.regime_at_entry or "unknown"].append(t)
    return _group_stats(groups)


def by_signal_breakdown(trades: list[TradeRecord]) -> dict[str, dict]:
    """Group trades by signal trigger type and compute stats per group.

    Args:
        trades: List of completed trade records.

    Returns:
        Dict of {signal_type: {trade_count, win_rate, avg_pnl, total_pnl}}.
    """
    groups: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        groups[t.signal_type or "unknown"].append(t)
    return _group_stats(groups)


def _group_stats(groups: dict[str, list[TradeRecord]]) -> dict[str, dict]:
    """Compute aggregate stats for each group of trades."""
    result: dict[str, dict] = {}
    for label, group_trades in groups.items():
        pnls = [_to_float(t.net_pnl) for t in group_trades]
        result[label] = {
            "trade_count": len(group_trades),
            "win_rate": win_rate(group_trades),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "total_pnl": sum(pnls),
        }
    return result


def full_report(
    trades: list[TradeRecord],
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.05,
) -> dict:
    """Generate a complete performance report from trade records.

    Args:
        trades: All completed trade records.
        initial_capital: Starting portfolio capital.
        risk_free_rate: Annualised risk-free rate for Sharpe/Sortino.

    Returns:
        Dict with all metrics: sharpe, sortino, calmar, max_dd, win_rate,
        profit_factor, avg_win, avg_loss, by_session, by_regime, by_signal,
        equity_curve.
    """
    if not trades:
        return {"error": "no trades"}

    curve = equity_curve_from_trades(initial_capital, trades)
    period_returns = [
        (curve[i] - curve[i - 1]) / curve[i - 1] for i in range(1, len(curve)) if curve[i - 1] > 0
    ]
    final_equity = curve[-1]
    annual_return = final_equity / initial_capital - 1  # simplified single-period

    dd, dd_dur = max_drawdown(curve)
    avg_w, avg_l = avg_win_loss(trades)

    return {
        "sharpe": sharpe_ratio(period_returns, risk_free_rate),
        "sortino": sortino_ratio(period_returns, risk_free_rate),
        "calmar": calmar_ratio(annual_return, dd),
        "max_drawdown": dd,
        "max_drawdown_duration_bars": dd_dur,
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "trade_count": len(trades),
        "final_equity": final_equity,
        "total_pnl": final_equity - initial_capital,
        "by_session": by_session_breakdown(trades),
        "by_regime": by_regime_breakdown(trades),
        "by_signal": by_signal_breakdown(trades),
        "equity_curve": curve,
    }
