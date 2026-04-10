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
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import stats as scipy_stats

from core.models.order import TradeRecord

if TYPE_CHECKING:
    from backtesting.walk_forward import CombinatorialPurgedCV

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


def _regime_stats(
    regime_trades: list[TradeRecord],
    initial_capital: float,
    risk_free_rate: float = 0.05,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> dict[str, Any]:
    """Compute rich per-regime performance statistics.

    Builds a regime-local daily equity curve seeded at ``initial_capital``
    (use ``1.0`` for scale-invariant returns) and derives Sharpe, max
    drawdown, and Ulcer Index on that isolated curve. Sharpe requires at
    least 2 daily returns (for variance); DD and Ulcer require at least
    2 equity-curve points.

    Args:
        regime_trades: Trades belonging to a single regime.
        initial_capital: Nominal starting capital for the regime-local
            equity curve.
        risk_free_rate: Annualised risk-free rate forwarded to
            ``sharpe_ratio``.
        annual_factor: Annualisation factor forwarded to
            ``sharpe_ratio``.

    Returns:
        Dict with keys: trade_count, win_rate, hit_rate, total_pnl,
        avg_pnl, sharpe, max_drawdown, ulcer_index.

    Reference:
        Lopez de Prado (2018). AFML Ch. 14.
        ADR-0002 Section A item 10.
    """
    n = len(regime_trades)
    if n == 0:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "hit_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "ulcer_index": 0.0,
        }

    pnls = [_to_float(t.net_pnl) for t in regime_trades]
    total_pnl = sum(pnls)
    wr = win_rate(regime_trades)

    # Build regime-local daily equity curve for risk metrics.
    regime_curve = daily_equity_curve_from_trades(initial_capital, regime_trades)
    regime_returns = daily_returns_from_equity(regime_curve)

    n_returns = len(regime_returns)
    n_curve = len(regime_curve)

    regime_sharpe = (
        sharpe_ratio(regime_returns, risk_free_rate, annual_factor) if n_returns >= 2 else 0.0
    )
    regime_dd, _ = max_drawdown(regime_curve) if n_curve >= 2 else (0.0, 0)
    regime_ulcer = (
        float(_ulcer_index(np.asarray(regime_curve, dtype=float))) if n_curve >= 2 else 0.0
    )

    return {
        "trade_count": n,
        "win_rate": wr,
        "hit_rate": wr,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / n,
        "sharpe": regime_sharpe,
        "max_drawdown": regime_dd,
        "ulcer_index": regime_ulcer,
    }


def _regime_concentration_hhi(
    by_regime: dict[str, dict[str, Any]],
) -> float:
    """Herfindahl-Hirschman concentration index over |total_pnl| per regime.

    HHI = sum( w_i^2 ) where w_i = |pnl_i| / sum(|pnl|).

    - HHI = 1.0 means all PnL comes from one regime (concentrated)
    - HHI = 1/N means equal contribution across N regimes (diversified)
    - HHI = 0.0 means no PnL anywhere (empty or flat strategy)

    A strategy with HHI > 0.8 across 3+ regimes is a red flag per
    ADR-0002 item 10 — the edge is likely regime-dependent.

    Reference:
        Hirschman, A. O. (1964). The Paternity of an Index.
        American Economic Review, 54(5), 761-762.
    """
    if not by_regime:
        return 0.0
    pnls = np.array(
        [abs(float(stats.get("total_pnl", 0.0))) for stats in by_regime.values()],
        dtype=float,
    )
    total = float(np.sum(pnls))
    if total <= 0.0:
        return 0.0
    weights = pnls / total
    return float(np.sum(weights**2))


def by_regime_breakdown(
    trades: list[TradeRecord],
    initial_capital: float = 1.0,
    risk_free_rate: float = 0.05,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> dict[str, dict[str, Any]]:
    """Group trades by regime label and compute rich per-regime stats.

    Per ADR-0002 Section A item 10, every regime gets its own Sharpe,
    max drawdown, Ulcer Index, and hit rate. A strategy whose edge
    lives in a single regime must declare it — use the top-level
    ``regime_concentration`` field from full_report() to quantify.

    Args:
        trades: List of completed trade records.
        initial_capital: Nominal capital to seed per-regime equity curves.
            Default 1.0 for scale-invariant returns. Using the real
            portfolio capital would dilute per-regime drawdowns when
            regime PnL is small relative to the total.
        risk_free_rate: Annualised risk-free rate forwarded to
            ``sharpe_ratio`` via ``_regime_stats``.
        annual_factor: Annualisation factor forwarded to
            ``sharpe_ratio`` via ``_regime_stats``.

    Returns:
        Dict of {regime_label: _regime_stats output}. Regimes with
        fewer than 2 trades get zero-filled Sharpe / DD / Ulcer.

    Reference:
        Lopez de Prado (2018). AFML Ch. 14.
        ADR-0002 Section A item 10.
    """
    groups: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        groups[t.regime_at_entry or "unknown"].append(t)
    return {
        label: _regime_stats(group_trades, initial_capital, risk_free_rate, annual_factor)
        for label, group_trades in groups.items()
    }


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


def probability_of_backtest_overfitting_cpcv(
    strategy_returns: np.ndarray[Any, np.dtype[np.float64]],
    cv: CombinatorialPurgedCV,
    risk_free_rate: float = 0.0,
    annual_factor: float = _ANNUAL_FACTOR_DAILY,
) -> float:
    """Compute the rank-based Probability of Backtest Overfitting via CPCV.

    Non-parametric rank-PBO from Bailey, Borwein, Lopez de Prado, Zhu
    (2014), Eq. 11 (logit) and Eq. 12 (PBO definition). For each of the
    ``C(n_splits, n_test_splits)`` combinatorial CPCV paths:

    1. Compute the in-sample Sharpe of every candidate strategy on the
       concatenated training folds.
    2. Identify the IS-best strategy (highest Sharpe).
    3. Compute the out-of-sample Sharpe of every strategy on the test
       folds and rank that IS-best strategy among the OOS distribution
       (``scipy.stats.rankdata`` with ``method="average"``).
    4. Map the rank to the relative position
       ``omega = (rank + 0.5) / (n_strategies + 1)``. The ``+0.5``
       numerator and ``N+1`` denominator keep ``omega`` strictly inside
       ``(0, 1)`` so the logit ``lambda = log(omega / (1 - omega))`` is
       always finite (no boundary singularities).
    5. PBO is the fraction of combinations whose logit is ``<= 0``,
       i.e. where the IS-best strategy lands at or below the OOS median.

    Interpretation: ``PBO`` close to 0 means IS-best strategies
    systematically remain top performers OOS (genuine edge); ``PBO``
    close to 0.5 means selection is indistinguishable from noise; ``PBO``
    close to 1 means the in-sample winners are systematically the OOS
    losers (severe overfitting).

    Args:
        strategy_returns: 2D array of shape ``(n_observations, n_strategies)``
            of periodic returns (e.g. daily fractions) for each candidate.
        cv: A :class:`~backtesting.walk_forward.CombinatorialPurgedCV`
            instance whose ``split(n_observations)`` yields the
            ``(train_idx, test_idx)`` pairs.
        risk_free_rate: Annualised risk-free rate forwarded to
            :func:`sharpe_ratio` for both IS and OOS Sharpe computations.
        annual_factor: Annualisation factor (``sqrt(252)`` for daily).

    Returns:
        PBO in ``[0, 1]``. Values ``< 0.1`` suggest a genuine edge,
        values near ``0.5`` suggest the backtest is statistically
        indistinguishable from noise selection.

    Raises:
        ValueError: if ``strategy_returns`` is not 2D, if
            ``n_strategies < 2``, or if the CPCV produces no splits.

    Reference:
        Bailey, D. H., Borwein, J. M., Lopez de Prado, M., & Zhu, Q. J.
        (2014). The Probability of Backtest Overfitting. Journal of
        Computational Finance. Equation 11 (logit) and Equation 12
        (PBO definition).
    """
    arr = np.asarray(strategy_returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"strategy_returns must be 2D (n_obs, n_strategies); got shape {arr.shape}"
        )
    n_obs, n_strats = arr.shape
    if n_strats < 2:
        raise ValueError(f"PBO requires at least 2 strategies; got {n_strats}")

    splits = cv.split(n_obs)
    if not splits:
        raise ValueError("CPCV produced no splits — check n_obs vs n_splits")

    n_logits_le_zero = 0
    for train_idx, test_idx in splits:
        train_mat = arr[np.asarray(train_idx, dtype=np.int64), :]
        test_mat = arr[np.asarray(test_idx, dtype=np.int64), :]
        is_sharpes = np.array(
            [
                sharpe_ratio([float(x) for x in train_mat[:, j]], risk_free_rate, annual_factor)
                for j in range(n_strats)
            ],
            dtype=float,
        )
        oos_sharpes = np.array(
            [
                sharpe_ratio([float(x) for x in test_mat[:, j]], risk_free_rate, annual_factor)
                for j in range(n_strats)
            ],
            dtype=float,
        )
        best_is = int(np.argmax(is_sharpes))
        ranks = scipy_stats.rankdata(oos_sharpes, method="average")
        rank_best = float(ranks[best_is])
        omega = (rank_best + 0.5) / (n_strats + 1)
        lambda_c = math.log(omega / (1.0 - omega))
        if lambda_c <= 0.0:
            n_logits_le_zero += 1

    return n_logits_le_zero / len(splits)


def backtest_overfitting_probability(
    in_sample_sharpe: float,
    out_of_sample_sharpe: float,
    n_trials: int,
) -> float:
    """DEPRECATED: use :func:`probability_of_backtest_overfitting_cpcv`.

    PBO — Estimated probability that the backtest is overfit.

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
    import warnings

    warnings.warn(
        "backtest_overfitting_probability() is deprecated. Use "
        "probability_of_backtest_overfitting_cpcv() which implements "
        "Bailey et al. 2014 Eq. 11 canonically via CPCV.",
        DeprecationWarning,
        stacklevel=2,
    )
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


# ---------------------------------------------------------------------------
# Drawdown and tail-risk metrics (ADR-0002 Section A item 6)
# ---------------------------------------------------------------------------


def _max_drawdown_absolute(
    equity_values: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    """Peak-to-trough absolute loss in monetary units.

    Returns the peak-to-trough loss as a **non-negative magnitude** in
    monetary units (e.g. ``1250.00`` means a $1250 drawdown). Returns
    ``0.0`` for monotonically non-decreasing series and for series
    shorter than 2 points.
    """
    if equity_values.size < 2:
        return 0.0
    running_peak = np.maximum.accumulate(equity_values)
    return float(-np.min(equity_values - running_peak))


def _ulcer_index(
    equity_values: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    """Ulcer Index: RMS of percentage drawdowns from running peak.

    Formula: ``UI = sqrt( mean( DD_i^2 ) )`` with
    ``DD_i = (equity_i - peak_i) / peak_i``.

    The classical Martin & McCann definition uses percentage points
    (``× 100``); we deliberately keep ``DD_i`` as a fraction so that
    the Ulcer Index lives in the same unit system as ``CAGR`` and
    ``risk_free_rate`` (both fractions) and the Martin ratio
    ``(CAGR - rf) / UI`` is dimensionally consistent across the
    report. Captures BOTH the depth and the duration of drawdowns,
    unlike max-drawdown which only sees the worst single point. A
    strictly monotonic equity curve yields ``UI = 0`` exactly.

    Reference:
        Martin, P. G., & McCann, B. B. (1989). The Investor's Guide
        to Fidelity Funds. Wiley.
    """
    if equity_values.size < 2:
        return 0.0
    running_peak = np.maximum.accumulate(equity_values)
    safe_peak = np.where(running_peak > 0, running_peak, 1.0)
    drawdowns = np.where(
        running_peak > 0,
        (equity_values - running_peak) / safe_peak,
        0.0,
    )
    return float(math.sqrt(float(np.mean(drawdowns**2))))


def _martin_ratio(
    cagr: float,
    risk_free_rate: float,
    ulcer_index: float,
) -> float:
    """Martin ratio = ``(CAGR - rf) / Ulcer Index``.

    Drawdown-pain analogue of the Sharpe ratio. Preferred by
    practitioners who care about the duration (not just depth) of
    drawdowns. Returns ``0.0`` when ``ulcer_index <= 0`` to avoid
    division by zero on monotonic equity curves.

    Reference:
        Martin, P. G., & McCann, B. B. (1989). The Investor's Guide
        to Fidelity Funds. Wiley.
    """
    if ulcer_index <= 0.0:
        return 0.0
    return (cagr - risk_free_rate) / ulcer_index


def _calmar_ratio(cagr: float, max_drawdown_pct: float) -> float:
    """Calmar ratio = ``CAGR / |max drawdown percentage|``.

    Returns ``0.0`` when ``max_drawdown_pct == 0`` to avoid division
    by zero.

    Reference:
        Young, T. W. (1991). Calmar Ratio: A Smoother Tool. Futures
        Magazine.
    """
    if max_drawdown_pct == 0.0:
        return 0.0
    return cagr / abs(max_drawdown_pct)


def _sortino_ratio(
    returns: np.ndarray[Any, np.dtype[np.float64]],
    risk_free_rate: float,
    annual_factor: float,
    target_return: float = 0.0,
) -> float:
    """Sortino ratio: excess return over downside semi-deviation.

    Formula: ``Sortino = mean(excess) / downside_dev * annual_factor``
    with ``downside_dev = sqrt( mean( min(excess - target, 0)^2 ) )``.

    Uses the semi-deviation below ``target_return`` (default 0), not
    the full standard deviation. A right-skewed strategy (more upside
    than downside) has Sortino > Sharpe.

    Reference:
        Sortino, F. A., & Price, L. N. (1994). Performance Measurement
        in a Downside Risk Framework. Journal of Investing, 3(3),
        59-64.
    """
    if returns.size < 2:
        return 0.0
    rf_per_period = risk_free_rate / (annual_factor**2)
    excess = returns - rf_per_period
    downside = np.minimum(excess - target_return, 0.0)
    dd_var = float(np.mean(downside**2))
    if dd_var <= 0.0:
        # Aligned with the public ``sortino_ratio()``: sign-aware
        # infinity for zero-downside series so callers can still order
        # strategies (consistent gains -> +inf, losses -> -inf).
        mean_excess = float(np.mean(excess))
        if mean_excess > 0:
            return float("inf")
        if mean_excess < 0:
            return float("-inf")
        return 0.0
    dd_dev = math.sqrt(dd_var)
    return float(np.mean(excess)) / dd_dev * annual_factor


def _return_distribution_stats(
    returns: np.ndarray[Any, np.dtype[np.float64]],
) -> dict[str, float]:
    """Skewness, excess kurtosis, and tail ratio of a return series.

    - ``skewness``: ``scipy.stats.skew(returns, bias=False)``.
    - ``excess_kurtosis``: ``scipy.stats.kurtosis(returns, fisher=True,
      bias=False)`` — Fisher's definition where a normal distribution
      has excess kurtosis 0.
    - ``tail_ratio``: ``|P95(returns)| / |P5(returns)|``. Values > 1
      indicate right-tail dominance. Returns ``inf`` when ``|P5|`` is
      below numerical noise.

    Returns a dict with zeros (and ``tail_ratio = 0.0``) for series
    too short or with vanishing variance — see PSR/DSR for the same
    catastrophic-cancellation guard.
    """
    if returns.size < 4:
        return {"skewness": 0.0, "excess_kurtosis": 0.0, "tail_ratio": 0.0}
    if float(np.std(returns, ddof=1)) < 1e-12:
        return {"skewness": 0.0, "excess_kurtosis": 0.0, "tail_ratio": 0.0}
    skew = float(scipy_stats.skew(returns, bias=False))
    kurt = float(scipy_stats.kurtosis(returns, fisher=True, bias=False))
    p95 = float(np.percentile(returns, 95))
    p5 = float(np.percentile(returns, 5))
    if abs(p5) < 1e-12:
        tail = float("inf")
    else:
        tail = abs(p95) / abs(p5)
    return {"skewness": skew, "excess_kurtosis": kurt, "tail_ratio": tail}


# ---------------------------------------------------------------------------
# Turnover, alpha decay, capacity (ADR-0002 Section A item 9)
# ---------------------------------------------------------------------------


def _annualized_turnover(
    trades: list[TradeRecord],
    years: float,
    avg_capital: float,
) -> float:
    """Annualized portfolio turnover ratio.

    Turnover = total_notional_traded / years / avg_capital.

    A turnover of 50 means the portfolio is fully rotated 50x per
    year. High turnover strategies are more sensitive to transaction
    costs and market impact.

    Args:
        trades: Completed trade records.
        years: Holding period in calendar years (same basis as CAGR).
        avg_capital: Average capital deployed (e.g. mean of initial
            and final equity).

    Returns:
        Annualized turnover ratio, 0.0 if years or avg_capital is zero.

    Reference:
        Grinold, R. C., & Kahn, R. N. (1999). Active Portfolio
        Management, Chapter 14.
    """
    if years <= 0 or avg_capital <= 0:
        return 0.0
    total_notional = sum(abs(float(t.entry_price * t.size)) for t in trades)
    return total_notional / years / avg_capital


def _alpha_decay_half_life(
    trades: list[TradeRecord],
    min_trades: int = 10,
) -> float | None:
    """Estimate the half-life of the strategy's per-trade edge decay.

    Fits an exponential decay model to the rolling mean of per-trade
    returns (net_pnl / notional) ordered chronologically:
        edge(i) = edge_0 * exp(-lambda * i)

    The half-life is ln(2) / lambda. Returns None if:
    - Fewer than min_trades trades
    - The fit is poor (R^2 < 0.3)
    - lambda <= 0 (no decay or growing edge — suspicious)

    This metric answers: "how quickly does my strategy's edge erode
    as more trades are placed?" A half-life of 30 days means the
    edge halves every month — the strategy needs constant renewal.

    Reference:
        Lopez de Prado (2018). AFML Chapter 14 (backtest statistics).
        Grinold (1989). Fundamental Law of Active Management.
    """
    if len(trades) < min_trades:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)
    returns = np.array(
        [
            float(t.net_pnl) / abs(float(t.entry_price * t.size))
            if abs(float(t.entry_price * t.size)) > 0
            else 0.0
            for t in sorted_trades
        ],
        dtype=float,
    )

    # Use rolling mean of per-trade returns as a proxy for edge decay
    window = max(3, len(returns) // 10)
    rolling_edge = np.convolve(returns, np.ones(window) / window, mode="valid")

    if len(rolling_edge) < 3:
        return None

    # Fit exponential decay: log(rolling_edge) = log(edge_0) - lambda * t
    # Only fit on positive values (can't log negative edge)
    positive_mask = rolling_edge > 0
    if np.sum(positive_mask) < 3:
        return None

    t_vals = np.arange(len(rolling_edge), dtype=float)[positive_mask]
    y_vals = np.log(rolling_edge[positive_mask])

    # Linear regression on log-transformed data
    if len(t_vals) < 3:
        return None

    coeffs = np.polyfit(t_vals, y_vals, 1)
    lam = -coeffs[0]  # slope = -lambda

    if lam <= 0:
        return None  # no decay or growing — suspicious

    # R^2 check
    y_pred = np.polyval(coeffs, t_vals)
    ss_res = float(np.sum((y_vals - y_pred) ** 2))
    ss_tot = float(np.sum((y_vals - np.mean(y_vals)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    if r_squared < 0.3:
        return None

    # Convert from trade-index to days
    span_ms = sorted_trades[-1].exit_timestamp_ms - sorted_trades[0].exit_timestamp_ms
    if span_ms <= 0:
        return None  # all trades on same timestamp, cannot estimate time decay
    days_per_trade = (span_ms / 1000 / 86400) / max(1, len(sorted_trades) - 1)
    half_life_trades = math.log(2) / lam
    half_life_days = half_life_trades * days_per_trade

    return float(half_life_days) if math.isfinite(half_life_days) else None


def _capacity_estimate_usd(
    trades: list[TradeRecord],
    gross_edge_bps: float,
    impact_k_bps: float = 10.0,
    adv_usd: float = 1_000_000.0,
) -> float | None:
    """Estimate the AUM at which market impact consumes 25% of edge.

    Uses a simplified square-root impact model:
        impact_bps = k * sqrt(order_size / ADV)

    Capacity is the AUM where impact >= 0.25 * gross_edge:
        AUM_max = ADV * (0.25 * gross_edge_bps / k)^2

    Returns None if gross_edge_bps <= 0 (no edge to consume) or
    if fewer than 2 trades.

    Args:
        trades: Trade records (used only for validation).
        gross_edge_bps: Strategy's gross edge in basis points,
            computed as total_pnl / total_notional * 10000
            (notional-weighted average across all trades).
        impact_k_bps: Market impact constant (10 bps typical for
            crypto, 5 bps for liquid equities).
        adv_usd: Average daily volume in USD for the traded asset.

    Returns:
        Capacity in USD, or None if not estimable.

    Reference:
        Almgren, R., & Chriss, N. (2001). Optimal execution of
        portfolio transactions. Journal of Risk, 3(2), 5-40.
        Perold, A. F. (1988). The Implementation Shortfall. JPM.
    """
    if len(trades) < 2 or gross_edge_bps <= 0 or impact_k_bps <= 0 or adv_usd <= 0:
        return None

    # AUM where impact = 25% of edge:
    # k * sqrt(AUM / ADV) = 0.25 * edge
    # sqrt(AUM / ADV) = 0.25 * edge / k
    # AUM = ADV * (0.25 * edge / k)^2
    ratio = (0.25 * gross_edge_bps) / impact_k_bps
    capacity = adv_usd * ratio**2

    return float(capacity) if math.isfinite(capacity) else None


# ---------------------------------------------------------------------------
# Almgren-Chriss market impact model (ADR-0002 Section A item 8)
# ---------------------------------------------------------------------------


def almgren_chriss_impact(
    order_size_usd: float,
    adv_usd: float,
    daily_volatility: float,
    eta: float = 0.01,
    gamma: float = 0.1,
) -> dict[str, float] | None:
    """Estimate market impact using the Almgren-Chriss square-root model.

    Decomposes total execution cost into temporary and permanent
    components:

        temporary_impact = eta * sigma * sqrt(Q / V)
        permanent_impact = gamma * sigma * sqrt(Q / V)
        total_impact = temporary + permanent

    where Q is the order size in USD, V is the average daily volume
    in USD, sigma is the daily volatility (as a fraction, e.g. 0.02
    for 2%), and eta/gamma are calibration constants.

    The temporary component represents the immediate price
    displacement that recovers after execution. The permanent
    component represents the information content of the trade that
    shifts the equilibrium price.

    Typical calibration values from Almgren et al. (2005):
    - eta ~ 0.01 for temporary impact
    - gamma ~ 0.1 for permanent impact
    These values are for US large-cap equities; crypto markets
    typically have 2-5x higher impact.

    Args:
        order_size_usd: Trade notional in USD.
        adv_usd: Average daily volume of the asset in USD.
        daily_volatility: Daily return volatility as a fraction.
        eta: Temporary impact coefficient (default 0.01).
        gamma: Permanent impact coefficient (default 0.1).

    Returns:
        Dict with temporary_impact_bps, permanent_impact_bps,
        total_impact_bps. Returns None if adv_usd <= 0.
        Returns all zeros if order_size_usd <= 0 or
        daily_volatility <= 0.

    Reference:
        Almgren, R., & Chriss, N. (2001). Optimal execution of
        portfolio transactions. Journal of Risk, 3(2), 5-40.
        Almgren, R., Thum, C., Hauptmann, E., & Li, H. (2005).
        Equity market impact. Risk, July, 57-62.
    """
    if adv_usd <= 0:
        return None
    if order_size_usd <= 0 or daily_volatility <= 0:
        return {
            "temporary_impact_bps": 0.0,
            "permanent_impact_bps": 0.0,
            "total_impact_bps": 0.0,
        }

    participation = math.sqrt(abs(order_size_usd) / adv_usd)
    temp = eta * daily_volatility * participation * 10_000  # convert to bps
    perm = gamma * daily_volatility * participation * 10_000
    return {
        "temporary_impact_bps": float(temp),
        "permanent_impact_bps": float(perm),
        "total_impact_bps": float(temp + perm),
    }


# ---------------------------------------------------------------------------
# OOS walk-forward split (ADR-0002 Section A item 2)
# ---------------------------------------------------------------------------


def _split_trades_is_oos(
    trades: list[TradeRecord],
    oos_fraction: float,
    embargo_days: int,
) -> tuple[list[TradeRecord], list[TradeRecord]]:
    """Split trades into in-sample and out-of-sample sets with embargo.

    Trades are sorted by ``exit_timestamp_ms``. The last
    ``oos_fraction`` of trades become OOS. An embargo gap of
    ``embargo_days`` calendar days is removed from the IS tail
    to prevent information leakage across the boundary.

    Args:
        trades: All trades (any order, will be sorted internally).
        oos_fraction: Fraction of trades reserved for OOS (e.g. 0.3).
        embargo_days: Calendar days to remove from IS tail.

    Returns:
        Tuple ``(is_trades, oos_trades)``. Embargo trades are excluded
        from both sets.

    Raises:
        ValueError: If ``oos_fraction`` is not in the open interval (0, 1).

    Reference:
        Lopez de Prado (2018). AFML Chapter 7.
        Pardo (2008). Chapter 5.
    """
    if embargo_days < 0:
        raise ValueError(f"embargo_days must be non-negative, got {embargo_days}")
    if oos_fraction <= 0.0 or oos_fraction >= 1.0:
        msg = f"oos_fraction must be in (0, 1), got {oos_fraction}"
        raise ValueError(msg)

    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)
    split_idx = int(len(sorted_trades) * (1.0 - oos_fraction))
    oos_trades = sorted_trades[split_idx:]

    if not oos_trades:
        return sorted_trades[:split_idx], []

    oos_start_ms = oos_trades[0].exit_timestamp_ms
    embargo_ms = embargo_days * 24 * 3600 * 1000
    is_trades = [
        t for t in sorted_trades[:split_idx] if t.exit_timestamp_ms < oos_start_ms - embargo_ms
    ]
    return is_trades, oos_trades


def full_report(
    trades: list[TradeRecord],
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.05,
    *,
    n_trials: int = 1,
    oos_fraction: float = 0.0,
    embargo_days: int = 5,
    impact_k_bps: float = 10.0,
    adv_usd: float = 1_000_000.0,
    daily_volatility: float = 0.02,
    strategy_returns_matrix: np.ndarray[Any, np.dtype[np.float64]] | None = None,
    n_cv_splits: int = 10,
    n_cv_test_splits: int = 2,
) -> dict[str, Any]:
    """Generate a complete performance report from trade records.

    Adds three ADR-0002 mandatory fields on top of the headline metrics:
    Probabilistic Sharpe Ratio (Bailey and López de Prado, 2012), Deflated
    Sharpe Ratio (Bailey and López de Prado, 2014) computed against the
    caller-provided ``n_trials`` count, and a 95% stationary-bootstrap
    confidence interval on the Sharpe ratio (Politis and Romano, 1994).

    Also computes turnover, alpha decay, and capacity metrics per
    ADR-0002 Section A item 9.

    Args:
        trades: All completed trade records.
        initial_capital: Starting portfolio capital.
        risk_free_rate: Annualised risk-free rate for Sharpe/Sortino.
        n_trials: Number of independent strategy variants tested. Used by
            the Deflated Sharpe Ratio to correct for selection bias.
            Defaults to 1 for backward compatibility.
        oos_fraction: Fraction of trades reserved for out-of-sample
            evaluation (e.g. 0.3). When > 0, the report includes
            ``is_report``, ``oos_report``, and ``oos_sharpe_degradation``.
            Default 0.0 disables the split (backward compatible).
        embargo_days: Calendar days to remove from the IS tail to
            prevent information leakage across the IS/OOS boundary.
            Per Lopez de Prado (2018, Ch. 7). Default 5.
        impact_k_bps: Market impact constant in basis points for the
            capacity estimate. 10 bps typical for crypto, 5 bps for
            liquid equities. Per Almgren & Chriss (2001).
        adv_usd: Average daily volume in USD for the traded asset.
            Used by the capacity estimate and Almgren-Chriss slippage
            model. Default 1M USD.
        daily_volatility: Daily return volatility as a fraction
            (e.g. 0.02 = 2%). Used by the Almgren-Chriss slippage
            model (ADR-0002 Section A item 8). Default 0.02.

    Returns:
        Dict with all metrics: sharpe, sortino, calmar, max_dd, win_rate,
        profit_factor, avg_win, avg_loss, psr, dsr, sharpe_ci_95_low,
        sharpe_ci_95_high, annualized_turnover, alpha_decay_half_life_days,
        capacity_estimate_usd, avg_slippage_bps, by_session, by_regime,
        by_signal, equity_curve.
    """
    if oos_fraction != 0.0:
        if not math.isfinite(oos_fraction) or oos_fraction < 0.0 or oos_fraction >= 1.0:
            raise ValueError(f"oos_fraction must be finite and in [0, 1), got {oos_fraction!r}")

    if not trades:
        return {"error": "no trades"}

    curve = equity_curve_from_trades(initial_capital, trades)
    # Sharpe is computed on daily-resampled equity curve returns (not
    # per-trade returns), per Lopez de Prado (2018) Ch. 14. Per-trade
    # returns of magnitude ~1e-5 (HFT) are dominated by the annualised
    # risk-free rate term and produce arbitrarily negative Sharpe even
    # for highly profitable strategies — see issue #8.
    daily_curve = daily_equity_curve_from_trades(initial_capital, trades)
    daily_returns = daily_returns_from_equity(daily_curve)
    final_equity = curve[-1]

    # Drawdown metrics are computed on the daily-resampled equity
    # curve so they share the same time basis as the Sharpe / PSR /
    # DSR / bootstrap CI block (which already uses daily returns).
    # Mixing per-trade and daily curves silently desynchronises
    # max_drawdown from ulcer_index — see PR #24 review.
    dd, dd_dur = max_drawdown(daily_curve)
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

    # Drawdown / tail-risk metrics (ADR-0002 Section A item 6).
    equity_values = np.asarray(daily_curve, dtype=float)
    daily_returns_arr = np.asarray(daily_returns, dtype=float)
    # CAGR must be annualised on calendar time, not on the count of
    # active trading days. A strategy that fires once per week over a
    # year would otherwise report ~52 "days" -> 0.14 years -> wildly
    # inflated CAGR. Use first/last trade timestamps for the span.
    sorted_trades = sorted(trades, key=lambda t: t.exit_timestamp_ms)
    if len(sorted_trades) >= 2:
        span_ms = max(
            sorted_trades[-1].exit_timestamp_ms - sorted_trades[0].entry_timestamp_ms,
            1,
        )
        years = span_ms / (365.25 * 24.0 * 3600.0 * 1000.0)
    else:
        years = 1.0 / 365.25
    years = max(years, 1.0 / 365.25)  # one-day floor to avoid div-by-near-zero
    total_return = final_equity / initial_capital - 1.0
    if years > 0 and (1.0 + total_return) > 0:
        cagr = (1.0 + total_return) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0
    ulcer = _ulcer_index(equity_values)
    max_dd_abs = _max_drawdown_absolute(equity_values)
    martin = _martin_ratio(cagr, risk_free_rate, ulcer)
    calmar_new = _calmar_ratio(cagr, abs(dd))
    sortino_new = _sortino_ratio(
        daily_excess_returns_arr,
        risk_free_rate=0.0,  # already excess
        annual_factor=_ANNUAL_FACTOR_DAILY,
    )
    dist_stats = _return_distribution_stats(daily_returns_arr)

    pbo: float | None = None
    if strategy_returns_matrix is not None:
        from backtesting.walk_forward import CombinatorialPurgedCV

        cv = CombinatorialPurgedCV(
            n_splits=n_cv_splits,
            n_test_splits=n_cv_test_splits,
        )
        pbo = probability_of_backtest_overfitting_cpcv(
            strategy_returns_matrix,
            cv,
            risk_free_rate=risk_free_rate,
            annual_factor=_ANNUAL_FACTOR_DAILY,
        )

    by_regime_enriched = by_regime_breakdown(
        trades,
        initial_capital=1.0,
        risk_free_rate=risk_free_rate,
    )

    report: dict[str, Any] = {
        "sharpe": sharpe_ratio(
            daily_returns,
            risk_free_rate=risk_free_rate,
            annual_factor=_ANNUAL_FACTOR_DAILY,
        ),
        "psr": float(psr),
        "dsr": float(dsr),
        "sharpe_ci_95_low": float(ci_low),
        "sharpe_ci_95_high": float(ci_high),
        "sortino": float(sortino_new),
        "calmar": float(calmar_new),
        "cagr": float(cagr),
        "max_drawdown": dd,
        "max_drawdown_absolute": float(max_dd_abs),
        "max_drawdown_duration_days": dd_dur,
        "ulcer_index": float(ulcer),
        "martin_ratio": float(martin),
        "return_skewness": float(dist_stats["skewness"]),
        "return_excess_kurtosis": float(dist_stats["excess_kurtosis"]),
        "tail_ratio": float(dist_stats["tail_ratio"]),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "trade_count": len(trades),
        "final_equity": final_equity,
        "total_pnl": final_equity - initial_capital,
        "by_session": by_session_breakdown(trades),
        "by_regime": by_regime_enriched,
        "regime_concentration": float(_regime_concentration_hhi(by_regime_enriched)),
        "by_signal": by_signal_breakdown(trades),
        "equity_curve": curve,
    }
    if pbo is not None:
        report["pbo"] = float(pbo)

    # Turnover, alpha decay, capacity (ADR-0002 Section A item 9)
    avg_capital = (initial_capital + final_equity) / 2.0
    turnover = _annualized_turnover(trades, years, avg_capital)
    decay = _alpha_decay_half_life(trades)

    # Gross edge in bps for capacity estimation
    total_notional = sum(abs(float(t.entry_price * t.size)) for t in trades)
    if total_notional > 0:
        gross_edge_bps = (final_equity - initial_capital) / total_notional * 10000
    else:
        gross_edge_bps = 0.0

    capacity = _capacity_estimate_usd(trades, gross_edge_bps, impact_k_bps, adv_usd)

    report["annualized_turnover"] = float(turnover)
    report["alpha_decay_half_life_days"] = float(decay) if decay is not None else None
    report["capacity_estimate_usd"] = float(capacity) if capacity is not None else None

    # Almgren-Chriss slippage estimation (ADR-0002 Section A item 8)
    slippage_estimates: list[float] = []
    for trade in trades:
        notional = abs(float(trade.entry_price * trade.size))
        if notional <= 0:
            notional = abs(float(trade.net_pnl))
        impact = almgren_chriss_impact(
            order_size_usd=notional,
            adv_usd=adv_usd,
            daily_volatility=daily_volatility,
        )
        if impact is not None:
            slippage_estimates.append(impact["total_impact_bps"])

    avg_slippage = float(np.mean(slippage_estimates)) if slippage_estimates else 0.0
    report["avg_slippage_bps"] = avg_slippage

    # OOS walk-forward split (ADR-0002 Section A item 2).
    if oos_fraction > 0.0:
        is_trades, oos_trades = _split_trades_is_oos(trades, oos_fraction, embargo_days)
        is_sub: dict[str, Any] = (
            full_report(
                trades=is_trades,
                initial_capital=initial_capital,
                risk_free_rate=risk_free_rate,
                n_trials=n_trials,
                impact_k_bps=impact_k_bps,
                adv_usd=adv_usd,
                daily_volatility=daily_volatility,
            )
            if is_trades
            else {"error": "no IS trades after embargo"}
        )
        oos_sub: dict[str, Any] = (
            full_report(
                trades=oos_trades,
                initial_capital=initial_capital,
                risk_free_rate=risk_free_rate,
                n_trials=n_trials,
                impact_k_bps=impact_k_bps,
                adv_usd=adv_usd,
                daily_volatility=daily_volatility,
            )
            if oos_trades
            else {"error": "no OOS trades"}
        )

        # Sharpe degradation IS → OOS.
        if isinstance(is_sub.get("sharpe"), (int, float)) and isinstance(
            oos_sub.get("sharpe"), (int, float)
        ):
            s_is = float(is_sub["sharpe"])
            s_oos = float(oos_sub["sharpe"])
            if s_is != 0.0 and math.isfinite(s_is) and math.isfinite(s_oos):
                oos_deg = (s_is - s_oos) / abs(s_is) * 100.0
            else:
                oos_deg = 0.0
        else:
            oos_deg = 0.0

        report["is_report"] = is_sub
        report["oos_report"] = oos_sub
        report["oos_sharpe_degradation"] = oos_deg
        report["oos_fraction"] = oos_fraction
        report["embargo_days"] = embargo_days

    return report


# ---------------------------------------------------------------------------
# Cost sensitivity analysis (ADR-0002 Section A item 7)
# ---------------------------------------------------------------------------


def _apply_cost_to_trades(
    trades: list[TradeRecord],
    total_bps: float,
) -> list[TradeRecord]:
    """Return a new trade list with round-trip costs applied to net PnL.

    Cost model: ``cost_per_trade = 2 * notional * (total_bps / 1e4)``
    where ``notional = abs(entry_price * size)``. Falls back to
    ``abs(net_pnl)`` as a notional proxy when entry_price or size are
    zero (synthetic fixture trades sometimes use zero-price PnL-only
    records).

    Does **not** mutate the input list or any of its frozen
    ``TradeRecord`` instances; new records are produced via
    ``model_copy(update=...)``. Returning a verbatim copy when
    ``total_bps <= 0`` keeps the no-mutation contract uniform.

    Reference:
        Pardo, R. (2008). The Evaluation and Optimization of Trading
        Strategies. Chapter 7 (transaction costs).
    """
    if total_bps <= 0.0:
        return list(trades)

    cost_fraction = Decimal(str(total_bps)) * Decimal("2") / Decimal("10000")
    adjusted: list[TradeRecord] = []
    for trade in trades:
        notional = abs(trade.entry_price * trade.size)
        if notional == 0:
            notional = abs(trade.net_pnl)
        cost = notional * cost_fraction
        new_net = trade.net_pnl - cost
        adjusted.append(trade.model_copy(update={"net_pnl": new_net}))
    return adjusted


def cost_sensitivity_report(
    trades: list[TradeRecord],
    initial_capital: float,
    realistic_cost_bps: float,
    *,
    risk_free_rate: float = 0.05,
    n_trials: int = 1,
) -> dict[str, Any]:
    """Evaluate a strategy under 3 cost regimes per ADR-0002 item 7.

    Runs :func:`full_report` three times with zero, realistic, and
    stress (``2x`` realistic) round-trip transaction costs and returns
    a comparison dict with Sharpe-degradation percentages and binary
    profitability flags.

    Per ADR-0002 Section A item 7, a strategy that is profitable under
    zero cost but fails under the realistic regime must be rejected.
    The realistic ``bps`` value is split evenly into commission /
    spread / impact components for the metadata field; this split is
    informational only — the cost is applied as a single scalar to
    ``net_pnl``.

    Args:
        trades: List of :class:`~core.models.order.TradeRecord` to
            evaluate. The list is not mutated.
        initial_capital: Starting capital in monetary units.
        realistic_cost_bps: Realistic round-trip cost in basis points
            (``10.0`` = ``0.10%`` per round trip).
        risk_free_rate: Annualised risk-free rate forwarded to
            :func:`full_report`.
        n_trials: Number of strategy variants tested (forwarded to
            DSR via :func:`full_report`).

    Returns:
        Dict with keys ``zero``, ``realistic``, ``stress`` (each a
        full ``full_report`` dict), the input cost bps,
        ``cost_split_metadata``, the two
        ``sharpe_degradation_zero_to_*`` percentages, and the
        ``profitable_under_*`` flags.

    Reference:
        Pardo, R. (2008). The Evaluation and Optimization of Trading
        Strategies. Chapter 7.
        Lopez de Prado, M. (2018). Advances in Financial Machine
        Learning. Chapter 14.
        ADR-0002 Quant Methodology Charter, Section A item 7.
    """
    if not math.isfinite(realistic_cost_bps) or realistic_cost_bps < 0.0:
        raise ValueError(
            f"realistic_cost_bps must be finite and non-negative, got {realistic_cost_bps!r}"
        )

    stress_bps = 2.0 * realistic_cost_bps

    if not trades:
        return {
            "error": "no trades",
            "zero": {"error": "no trades"},
            "realistic": {"error": "no trades"},
            "stress": {"error": "no trades"},
            "realistic_cost_bps": float(realistic_cost_bps),
            "stress_cost_bps": float(stress_bps),
            "sharpe_degradation_zero_to_realistic": 0.0,
            "sharpe_degradation_zero_to_stress": 0.0,
            "profitable_under_realistic": False,
            "profitable_under_stress": False,
        }

    trades_zero = _apply_cost_to_trades(trades, 0.0)
    trades_realistic = _apply_cost_to_trades(trades, realistic_cost_bps)
    trades_stress = _apply_cost_to_trades(trades, stress_bps)

    report_zero = full_report(
        trades=trades_zero,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        n_trials=n_trials,
    )
    report_realistic = full_report(
        trades=trades_realistic,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        n_trials=n_trials,
    )
    report_stress = full_report(
        trades=trades_stress,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        n_trials=n_trials,
    )

    sharpe_z = float(report_zero["sharpe"])
    sharpe_r = float(report_realistic["sharpe"])
    sharpe_s = float(report_stress["sharpe"])

    def _degradation(a: float, b: float) -> float:
        if a == 0.0 or not math.isfinite(a) or not math.isfinite(b):
            return 0.0
        return (a - b) / abs(a) * 100.0

    cost_split = {
        "commission_bps": realistic_cost_bps / 3.0,
        "spread_bps": realistic_cost_bps / 3.0,
        "impact_bps": realistic_cost_bps / 3.0,
    }

    return {
        "zero": report_zero,
        "realistic": report_realistic,
        "stress": report_stress,
        "realistic_cost_bps": float(realistic_cost_bps),
        "stress_cost_bps": float(stress_bps),
        "cost_split_metadata": cost_split,
        "sharpe_degradation_zero_to_realistic": _degradation(sharpe_z, sharpe_r),
        "sharpe_degradation_zero_to_stress": _degradation(sharpe_z, sharpe_s),
        "profitable_under_realistic": (
            sharpe_r > 0.0 and float(report_realistic["total_pnl"]) > 0.0
        ),
        "profitable_under_stress": (sharpe_s > 0.0 and float(report_stress["total_pnl"]) > 0.0),
    }
