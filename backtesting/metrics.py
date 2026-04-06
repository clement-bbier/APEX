"""Backtesting metrics for APEX Trading System.

Computes a comprehensive suite of performance statistics from a list of
:class:`~core.models.order.TradeRecord` objects and an equity curve.

References:
    - Sharpe (1966) - "Mutual Fund Performance"
    - Sortino & van der Meer (1991) - "Downside Risk"
    - Calmar ratio - Young (1991)
    - Lopez de Prado (2018) - "Advances in Financial Machine Learning"
"""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal
from typing import Any

import numpy as np
from scipy import stats as scipy_stats

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


_MS_PER_DAY: int = 86_400_000


def daily_equity_returns(
    trades: list[TradeRecord],
    initial_capital: float,
) -> list[float]:
    """Compute per-calendar-day fractional equity returns from trade records.

    Trade PnL is bucketed by UTC calendar day using ``exit_timestamp_ms``.
    Days with no trades carry forward the previous day's equity so that the
    series covers every calendar day between the first and last trade.

    Using daily returns (rather than per-trade returns) gives a Sharpe ratio
    that is correctly annualised with √252 and is not sensitive to trade
    frequency — following the same convention as the López de Prado PSR/DSR
    functions above.

    Args:
        trades: Completed trade records.
        initial_capital: Starting portfolio capital.

    Returns:
        List of per-day fractional returns (empty when fewer than 2 days).
    """
    if not trades:
        return []

    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)

    # Aggregate PnL per calendar day
    day_pnl: dict[int, float] = {}
    for trade in sorted_trades:
        day = trade.exit_timestamp_ms // _MS_PER_DAY
        day_pnl[day] = day_pnl.get(day, 0.0) + _to_float(trade.net_pnl)

    min_day = min(day_pnl)
    max_day = max(day_pnl)

    # Build a daily equity series, filling gaps by carrying forward
    daily_equities: list[float] = [initial_capital]
    current_equity = initial_capital
    for day in range(min_day, max_day + 1):
        current_equity += day_pnl.get(day, 0.0)
        daily_equities.append(current_equity)

    from itertools import pairwise

    return [
        (curr - prev) / prev
        for prev, curr in pairwise(daily_equities)
        if prev > 0
    ]


def by_session_breakdown(trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
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


def by_regime_breakdown(trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
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


def by_signal_breakdown(trades: list[TradeRecord]) -> dict[str, dict[str, Any]]:
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


def _group_stats(groups: dict[str, list[TradeRecord]]) -> dict[str, dict[str, Any]]:
    """Compute aggregate stats for each group of trades."""
    result: dict[str, dict[str, Any]] = {}
    for label, group_trades in groups.items():
        pnls = [_to_float(t.net_pnl) for t in group_trades]
        result[label] = {
            "trade_count": len(group_trades),
            "win_rate": win_rate(group_trades),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "total_pnl": sum(pnls),
        }
    return result


# ---------------------------------------------------------------------------
# Institutional-grade validation metrics (López de Prado)
# ---------------------------------------------------------------------------
# PSR, DSR, PBO, MinTRL replace classical Sharpe as the primary performance
# gate.  A Sharpe=2.0 with negative skewness + fat tails can have PSR < 0.5.
# A strategy found after N=1000 parameter tests has DSR << PSR.
#
# References:
#   Bailey & López de Prado (2012). Journal of Risk 15(2).
#   Bailey & López de Prado (2014). Journal of Portfolio Management 40(5).
#   Bailey, Borwein, López de Prado & Zhu (2015). J. Computational Finance 20(4).
#   López de Prado (2018). AFML. Wiley. Chapter 8.
# ---------------------------------------------------------------------------


def probabilistic_sharpe_ratio(
    returns: list[float],
    benchmark_sharpe: float = 0.0,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> float:
    """PSR(SR*) = Φ[(SR̂ - SR*) × √(T-1) / √(1 - γ₃×SR̂ + (γ₄-1)/4×SR̂²)]

    Corrects for non-normality (skewness + kurtosis) so that a strategy with
    fat-tailed losses cannot fake a high Sharpe.

    PSR > 0.95 → deploy.  PSR < 0.50 → do not deploy.

    Reference:
        Bailey & López de Prado (2012). "The Sharpe Ratio Efficient Frontier."
        Journal of Risk 15(2). Propositions 1-2.

    Args:
        returns: Period returns (e.g. daily fractions).
        benchmark_sharpe: Annualised SR* threshold (default 0).
        annual_factor: √(periods per year) — √252 for daily.

    Returns:
        PSR in [0, 1].
    """
    if len(returns) < 4:
        return 0.0
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr, ddof=1))
    # Guard against near-zero std (numpy may return ~1e-19 for constant arrays).
    # scipy.skew/kurtosis on near-constant data raises RuntimeWarning (catastrophic
    # cancellation), which pytest treats as an error via filterwarnings="error".
    if std_r < 1e-10:
        if mean_r > 1e-10:
            return 1.0
        if mean_r < -1e-10:
            return 0.0
        return 0.5  # zero mean, zero vol → truly indeterminate
    sr_raw = mean_r / std_r
    skew = float(scipy_stats.skew(arr, bias=False))
    kurt = float(scipy_stats.kurtosis(arr, bias=False))
    var_sr = (1.0 - skew * sr_raw + (kurt + 2.0) / 4.0 * sr_raw**2) / (n - 1)
    if var_sr <= 0:
        return 0.5
    z = (sr_raw - benchmark_sharpe / annual_factor) / math.sqrt(var_sr)
    return float(scipy_stats.norm.cdf(z))


def deflated_sharpe_ratio(
    returns: list[float],
    n_trials: int,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
    benchmark_sharpe: float = 0.0,
) -> float:
    """DSR — PSR corrected for selection bias across N independent trials.

    Expected maximum Sharpe under the null (no edge, N parameter sets tested):

        SR* = σ(SR̂) × [(1-γ) × Φ⁻¹(1-1/N) + γ × Φ⁻¹(1-1/Ne)]

    where γ = 0.5772156649 (Euler-Mascheroni constant).

    DSR answers: "given that we tried N strategies and kept the best,
    how likely is our observed SR to reflect genuine alpha?"

    Reference:
        Bailey & López de Prado (2014). "The Deflated Sharpe Ratio."
        Journal of Portfolio Management 40(5). Equation 2.

    Args:
        returns: Period returns.
        n_trials: Number of independently tested parameter sets / strategies.
        annual_factor: √(periods per year).
        benchmark_sharpe: Hard-floor SR* (annualised). Final SR* = max(this, DSR SR*).

    Returns:
        DSR in [0, 1]. Always ≤ PSR for the same returns.
    """
    if len(returns) < 4 or n_trials < 1:
        return probabilistic_sharpe_ratio(returns, benchmark_sharpe, annual_factor)
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    std_r = float(np.std(arr, ddof=1))
    mean_r = float(np.mean(arr))
    if std_r < 1e-10:
        if mean_r > 1e-10:
            return 1.0
        if mean_r < -1e-10:
            return 0.0
        return 0.5
    sr_raw = mean_r / std_r
    skew = float(scipy_stats.skew(arr, bias=False))
    kurt = float(scipy_stats.kurtosis(arr, bias=False))
    var_sr = max(
        1e-10,
        (1.0 - skew * sr_raw + (kurt + 2.0) / 4.0 * sr_raw**2) / (n - 1),
    )
    std_sr = math.sqrt(var_sr)
    gamma = 0.5772156649  # Euler-Mascheroni constant
    n_f = float(n_trials)
    if n_f > 1:
        z1 = float(scipy_stats.norm.ppf(1.0 - 1.0 / n_f))
        z2 = float(scipy_stats.norm.ppf(1.0 - 1.0 / (n_f * math.e)))
        sr_max = std_sr * ((1.0 - gamma) * z1 + gamma * z2)
    else:
        sr_max = 0.0
    sr_star = max(benchmark_sharpe / annual_factor, sr_max)
    z = (sr_raw - sr_star) / math.sqrt(var_sr)
    return float(scipy_stats.norm.cdf(z))


def minimum_track_record_length(
    target_sharpe: float,
    benchmark_sharpe: float = 0.0,
    confidence: float = 0.95,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> int:
    """T* = 1 + V[SR̂] × (Φ⁻¹(α) / (SR̂ - SR*))²

    Minimum number of observations for PSR ≥ confidence.

    Interpretation: "how many months of live data do we need before we can
    claim this strategy has SR ≥ benchmark_sharpe with confidence α?"

    Reference:
        Bailey & López de Prado (2012). "The Sharpe Ratio Efficient Frontier."
        Journal of Risk 15(2). Proposition 3.

    Args:
        target_sharpe: Annualised SR the strategy is expected to achieve.
        benchmark_sharpe: Annualised SR* threshold.
        confidence: Required PSR threshold (default 0.95).
        annual_factor: √(periods per year).
        skewness: Return distribution skewness (0 = normal).
        excess_kurtosis: Return distribution excess kurtosis (0 = normal).

    Returns:
        Minimum number of return observations needed. Returns int(1e9) when
        target_sharpe ≤ benchmark_sharpe (impossible to achieve).
    """
    if target_sharpe <= benchmark_sharpe:
        return 1_000_000_000
    sr_raw = target_sharpe / annual_factor
    sr_star = benchmark_sharpe / annual_factor
    z = float(scipy_stats.norm.ppf(confidence))
    var_f = 1.0 - skewness * sr_raw + (excess_kurtosis + 2.0) / 4.0 * sr_raw**2
    return max(1, math.ceil(1.0 + var_f * (z / (sr_raw - sr_star)) ** 2))


def backtest_overfitting_probability(
    in_sample_sharpe: float,
    out_of_sample_sharpe: float,
    n_trials: int,
) -> float:
    """PBO — Estimated probability that the backtest is overfit.

    PBO > 0.5 → overfit → DO NOT DEPLOY.
    PBO < 0.1 → strong evidence of genuine edge.

    Derived from the rank-based PBO estimator (Bailey et al. 2015, Eq. 11):
    when IS Sharpe degrades significantly OOS, and the strategy was selected
    from N candidates, the probability of overfitting rises with both
    the degradation ratio d and log(N).

    Reference:
        Bailey, Borwein, López de Prado & Zhu (2015).
        "The Probability of Backtest Overfitting."
        Journal of Computational Finance 20(4). Equation 11.

    Args:
        in_sample_sharpe: Sharpe ratio measured in-sample.
        out_of_sample_sharpe: Sharpe ratio measured out-of-sample.
        n_trials: Number of strategies / parameter combinations tested.

    Returns:
        PBO in [0, 1].
    """
    if n_trials <= 1:
        return 0.0
    if in_sample_sharpe <= 0:
        return 1.0
    d = (in_sample_sharpe - out_of_sample_sharpe) / abs(in_sample_sharpe)
    d = max(-1.0, min(1.0, d))
    log_f = math.log(max(1, n_trials)) / math.log(100)
    return max(0.0, min(1.0, 0.5 * (1 + d) * (0.5 + 0.5 * log_f)))


def full_report(
    trades: list[TradeRecord],
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.05,
) -> dict[str, Any]:
    """Generate a complete performance report from trade records.

    Sharpe and Sortino are computed on **daily** equity returns (bucketed by
    calendar day) rather than per-trade returns.  Using a consistent daily
    period makes the annualised figures comparable regardless of trade
    frequency and matches the √252 annual factor convention used by the PSR
    and DSR functions.

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

    # Daily returns for Sharpe/Sortino: correct annualisation with √252.
    day_returns = daily_equity_returns(trades, initial_capital)
    # Fall back to per-trade returns if fewer than 2 calendar days of data.
    returns_for_risk = day_returns if len(day_returns) >= 2 else [
        (curve[i] - curve[i - 1]) / curve[i - 1]
        for i in range(1, len(curve))
        if curve[i - 1] > 0
    ]

    final_equity = curve[-1]
    annual_return = final_equity / initial_capital - 1  # simplified single-period

    dd, dd_dur = max_drawdown(curve)
    avg_w, avg_l = avg_win_loss(trades)

    return {
        "sharpe": sharpe_ratio(returns_for_risk, risk_free_rate),
        "sortino": sortino_ratio(returns_for_risk, risk_free_rate),
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
