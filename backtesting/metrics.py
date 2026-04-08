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
from datetime import UTC, datetime
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
    if std < 1e-9:
        # Zero-variance series: Sharpe is undefined in the strict sense.
        # Return sign-aware infinity so callers can still order strategies
        # (consistent gains -> +inf, consistent losses -> -inf, flat -> 0).
        mean_excess = float(np.mean(excess))
        if abs(mean_excess) < 1e-9:
            return 0.0
        return float("inf") if mean_excess > 0 else float("-inf")
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


def daily_equity_curve_from_trades(
    initial_capital: float,
    trades: list[TradeRecord],
) -> list[float]:
    """Build a daily-resampled equity curve from trade records.

    Trades are bucketed by UTC calendar day on their ``exit_timestamp_ms``.
    The returned series contains one equity value per active day, equal to
    the running portfolio equity after applying every trade closed on that
    day. The initial capital is prepended so that ``pct_change`` over the
    series captures the first day's PnL.

    This is the standard input for an annualised (√252) Sharpe ratio
    (Lopez de Prado, 2018, Ch. 14): per-trade returns are not iid in time
    and produce arbitrarily biased Sharpe values for HFT-style strategies.

    Args:
        initial_capital: Starting capital.
        trades: Trade records (any order).

    Returns:
        List of daily equity values, length = 1 + number of active days.
    """
    if not trades:
        return [initial_capital]
    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)
    daily_pnl: dict[str, float] = defaultdict(float)
    day_order: list[str] = []
    for trade in sorted_trades:
        day = datetime.fromtimestamp(trade.exit_timestamp_ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")
        if day not in daily_pnl:
            day_order.append(day)
        daily_pnl[day] += _to_float(trade.net_pnl)
    equity = initial_capital
    curve = [equity]
    for day in day_order:
        equity += daily_pnl[day]
        curve.append(equity)
    return curve


def daily_returns_from_equity(curve: list[float]) -> list[float]:
    """Compute daily pct_change returns from a daily equity curve.

    Args:
        curve: Daily equity values (output of
            :func:`daily_equity_curve_from_trades`).

    Returns:
        List of daily fractional returns; empty if fewer than 2 points.
    """
    if len(curve) < 2:
        return []
    return [
        (curve[i] - curve[i - 1]) / curve[i - 1] for i in range(1, len(curve)) if curve[i - 1] > 0
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


def _stationary_bootstrap_sharpe_ci(
    returns: np.ndarray[Any, np.dtype[np.float64]],
    risk_free_rate: float,
    annual_factor: float,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Compute a bootstrap confidence interval on the Sharpe ratio.

    Uses the stationary bootstrap of Politis and Romano (1994), which
    preserves the weak dependence structure of the returns series by
    sampling blocks of geometrically-distributed length and concatenating
    them with wrap-around. Unlike the moving-block bootstrap, the resulting
    resampled series is itself stationary, which is the right null model
    for evaluating Sharpe under serial correlation.

    Args:
        returns: 1D array of period returns (e.g. daily fractions).
        risk_free_rate: Annualised risk-free rate.
        annual_factor: Annualisation factor (√252 for daily).
        n_resamples: Number of bootstrap replications.
        confidence: Two-sided confidence level (default 0.95).
        seed: RNG seed for reproducibility.

    Returns:
        Tuple ``(ci_low, ci_high)`` at the requested confidence level.
        Returns ``(0.0, 0.0)`` for fewer than 2 observations and
        ``(point, point)`` when the series has zero variance.

    Reference:
        Politis, D. N., and Romano, J. P. (1994). "The Stationary
        Bootstrap." Journal of the American Statistical Association,
        89(428), 1303-1313.
    """
    n = int(returns.size)
    if n < 2:
        return 0.0, 0.0
    returns_list: list[float] = [float(x) for x in returns]
    point = sharpe_ratio(returns_list, risk_free_rate, annual_factor)
    if float(np.std(returns, ddof=1)) < 1e-12:
        return point, point

    rng = np.random.default_rng(seed)
    block_len = max(1, round(n ** (1.0 / 3.0)))
    p = 1.0 / block_len
    alpha = 1.0 - confidence
    lo_pct = 100.0 * (alpha / 2.0)
    hi_pct = 100.0 * (1.0 - alpha / 2.0)

    sharpe_values = np.empty(n_resamples, dtype=float)
    for b in range(n_resamples):
        idx = np.empty(n, dtype=np.int64)
        i = 0
        while i < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(p))
            length = min(length, n - i)
            for k in range(length):
                idx[i + k] = (start + k) % n
            i += length
        resample = returns[idx]
        sharpe_values[b] = sharpe_ratio([float(x) for x in resample], risk_free_rate, annual_factor)

    finite = sharpe_values[np.isfinite(sharpe_values)]
    if finite.size == 0:
        return point, point
    return float(np.percentile(finite, lo_pct)), float(np.percentile(finite, hi_pct))


def full_report(
    trades: list[TradeRecord],
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.05,
    *,
    n_trials: int = 1,
) -> dict[str, Any]:
    """Generate a complete performance report from trade records.

    Adds three ADR-0002 mandatory fields on top of the headline metrics:
    Probabilistic Sharpe Ratio (Bailey and López de Prado, 2012), Deflated
    Sharpe Ratio (Bailey and López de Prado, 2014) computed against the
    caller-provided ``n_trials`` count, and a 95% stationary-bootstrap
    confidence interval on the Sharpe ratio (Politis and Romano, 1994).

    Args:
        trades: All completed trade records.
        initial_capital: Starting portfolio capital.
        risk_free_rate: Annualised risk-free rate for Sharpe/Sortino.
        n_trials: Number of independent strategy variants tested. Used by
            the Deflated Sharpe Ratio to correct for selection bias.
            Defaults to 1 for backward compatibility.

    Returns:
        Dict with all metrics: sharpe, sortino, calmar, max_dd, win_rate,
        profit_factor, avg_win, avg_loss, psr, dsr, sharpe_ci_95_low,
        sharpe_ci_95_high, by_session, by_regime, by_signal, equity_curve.
    """
    if not trades:
        return {"error": "no trades"}

    curve = equity_curve_from_trades(initial_capital, trades)
    period_returns = [
        (curve[i] - curve[i - 1]) / curve[i - 1] for i in range(1, len(curve)) if curve[i - 1] > 0
    ]
    # Sharpe is computed on daily-resampled equity curve returns (not
    # per-trade returns), per Lopez de Prado (2018) Ch. 14. Per-trade
    # returns of magnitude ~1e-5 (HFT) are dominated by the annualised
    # risk-free rate term and produce arbitrarily negative Sharpe even
    # for highly profitable strategies — see issue #8.
    daily_curve = daily_equity_curve_from_trades(initial_capital, trades)
    daily_returns = daily_returns_from_equity(daily_curve)
    final_equity = curve[-1]
    annual_return = final_equity / initial_capital - 1  # simplified single-period

    dd, dd_dur = max_drawdown(curve)
    avg_w, avg_l = avg_win_loss(trades)

    # Per Bailey & Lopez de Prado (2012, 2014), PSR and DSR must be computed
    # on the same excess-return series that the headline Sharpe is built from
    # — otherwise PSR/DSR would be silently inconsistent with Sharpe whenever
    # risk_free_rate != 0. sharpe_ratio() subtracts ``rf / annual_factor**2``
    # internally; we mirror that here exactly.
    rf_per_period = risk_free_rate / (_ANNUAL_FACTOR_DAILY**2)
    daily_excess_returns = [r - rf_per_period for r in daily_returns]
    daily_excess_returns_arr = np.asarray(daily_excess_returns, dtype=float)
    psr = probabilistic_sharpe_ratio(
        daily_excess_returns,
        benchmark_sharpe=0.0,
        annual_factor=_ANNUAL_FACTOR_DAILY,
    )
    dsr = deflated_sharpe_ratio(
        daily_excess_returns,
        n_trials=n_trials,
        annual_factor=_ANNUAL_FACTOR_DAILY,
        benchmark_sharpe=0.0,
    )
    # Excess returns are already net of rf, so pass rf=0 to avoid double
    # subtraction inside sharpe_ratio() within the bootstrap.
    ci_low, ci_high = _stationary_bootstrap_sharpe_ci(
        daily_excess_returns_arr,
        risk_free_rate=0.0,
        annual_factor=_ANNUAL_FACTOR_DAILY,
    )

    return {
        "sharpe": sharpe_ratio(
            daily_returns,
            risk_free_rate=risk_free_rate,
            annual_factor=_ANNUAL_FACTOR_DAILY,
        ),
        "psr": float(psr),
        "dsr": float(dsr),
        "sharpe_ci_95_low": float(ci_low),
        "sharpe_ci_95_high": float(ci_high),
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
