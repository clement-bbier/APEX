"""Walk-forward validation for APEX Trading System.

Implements Lopez de Prado's purged cross-validation methodology:
  [==TRAIN==][--PURGE--][==TEST==][EMBARGO]

  train:   data used to estimate parameters
  purge:   train samples too close to test window removed (prevents leakage)
  test:    out-of-sample evaluation
  embargo: N minutes after test removed from next train (prevents contamination)

Reference:
    Lopez de Prado (2018), *Advances in Financial Machine Learning*,
    Chapter 7: "Cross-Validation in Finance".
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations as _combinations
from typing import Any

import numpy as np
import pandas as pd

from core.models.tick import NormalizedTick

# ---------------------------------------------------------------------------
# Datetime-based purged walk-forward API (Lopez de Prado, Chapter 7)
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardWindow:
    """One train/test window with purge and embargo metadata.

    Attributes:
        window_id:   0-based index of this window.
        train_start: Start of the training period.
        train_end:   End of training (purge applied - stops before test).
        test_start:  Start of out-of-sample evaluation.
        test_end:    End of out-of-sample evaluation.
        embargo_end: End of the embargo period after test.
    """

    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    embargo_end: datetime


@dataclass
class WalkForwardResult:
    """Per-window out-of-sample result.

    Attributes:
        window_id:          Window index.
        sharpe:             Out-of-sample Sharpe ratio.
        max_drawdown:       Maximum drawdown fraction (0.0-1.0).
        win_rate:           Fraction of winning trades.
        n_trades:           Number of trades in this window.
        out_of_sample_return: Total return over the test period.
    """

    window_id: int
    sharpe: float
    max_drawdown: float
    win_rate: float
    n_trades: int
    out_of_sample_return: float


class WalkForwardValidator:
    """Purged walk-forward cross-validator for financial time series.

    Prevents the following leakage sources:
    1. Lookahead bias: train data before test only.
    2. Overlap leakage: train samples spanning test period removed.
    3. Embargo: N minutes after test period purged from next train.

    Usage::

        v = WalkForwardValidator(n_windows=6, train_months=6, test_months=1)
        windows = v.build_windows(data_start, data_end)
        results = [run_backtest(w) for w in windows]
        summary = v.aggregate_results(results)
    """

    def __init__(
        self,
        n_windows: int = 6,
        train_months: int = 6,
        test_months: int = 1,
        embargo_minutes: int = 60,
    ) -> None:
        """Initialize the walk-forward validator.

        Args:
            n_windows:        Number of train/test windows to generate.
            train_months:     Months of data in each training window.
            test_months:      Months of data in each test window.
            embargo_minutes:  Minutes to embargo after each test window.
        """
        if n_windows < 1:
            raise ValueError("n_windows must be >= 1")
        self.n_windows = n_windows
        self.train_months = train_months
        self.test_months = test_months
        self.embargo_minutes = embargo_minutes

    def build_windows(
        self,
        data_start: datetime,
        data_end: datetime,
    ) -> list[WalkForwardWindow]:
        """Build N train/test windows with purging and embargo.

        Args:
            data_start: Start of the full dataset.
            data_end:   End of the full dataset.

        Returns:
            List of :class:`WalkForwardWindow` with no train/test overlap.
        """
        windows: list[WalkForwardWindow] = []
        test_duration = timedelta(days=self.test_months * 30)
        train_duration = timedelta(days=self.train_months * 30)
        embargo = timedelta(minutes=self.embargo_minutes)

        for i in range(self.n_windows):
            test_start = data_start + train_duration + i * test_duration
            test_end = test_start + test_duration

            if test_end > data_end:
                break

            windows.append(
                WalkForwardWindow(
                    window_id=i,
                    train_start=data_start,
                    train_end=test_start - embargo,  # purge buffer before test
                    test_start=test_start,
                    test_end=test_end,
                    embargo_end=test_end + embargo,
                )
            )

        return windows

    def run_validation(
        self,
        data: pd.DataFrame,
        backtest_fn: Callable[..., WalkForwardResult],
    ) -> list[WalkForwardResult]:
        """Run walk-forward validation across all windows.

        Args:
            data:        Full historical dataset with a 'timestamp' column.
            backtest_fn: Callable(train_df, test_df, window_id) -> WalkForwardResult.

        Returns:
            List of :class:`WalkForwardResult` per window (out-of-sample).
        """
        data_start = pd.Timestamp(data["timestamp"].min()).to_pydatetime()
        data_end = pd.Timestamp(data["timestamp"].max()).to_pydatetime()
        windows = self.build_windows(data_start, data_end)

        results: list[WalkForwardResult] = []
        for window in windows:
            train_df = data[
                (data["timestamp"] >= window.train_start)
                & (data["timestamp"] < window.train_end)
            ]
            test_df = data[
                (data["timestamp"] >= window.test_start)
                & (data["timestamp"] < window.test_end)
            ]

            if len(test_df) < 100:
                continue

            result: WalkForwardResult = backtest_fn(train_df, test_df, window.window_id)
            results.append(result)

        return results

    def aggregate_results(self, results: list[WalkForwardResult]) -> dict[str, Any]:
        """Aggregate out-of-sample performance across all windows.

        This is the TRUE performance estimate - no in-sample bias.

        Args:
            results: List of per-window results from :meth:`run_validation`.

        Returns:
            Dict with aggregated metrics and consistency flag.
        """
        if not results:
            return {"error": "no results"}

        sharpes = [r.sharpe for r in results]
        dds = [r.max_drawdown for r in results]
        win_rates = [r.win_rate for r in results]
        n_trades = sum(r.n_trades for r in results)

        return {
            "oos_sharpe_mean": float(np.mean(sharpes)),
            "oos_sharpe_min": float(np.min(sharpes)),
            "oos_sharpe_std": float(np.std(sharpes)),
            "oos_max_dd_mean": float(np.mean(dds)),
            "oos_win_rate_mean": float(np.mean(win_rates)),
            "n_windows": len(results),
            "n_total_trades": n_trades,
            "is_consistent": bool(float(np.std(sharpes)) < 0.5),
        }


# ---------------------------------------------------------------------------
# Tick-based walk-forward (used by BacktestEngine.validate())
# ---------------------------------------------------------------------------

_DEFAULT_TRAIN_RATIO = 0.8
_DEFAULT_N_SPLITS = 5
_DEFAULT_EMBARGO_BARS = 50


@dataclass
class _TickWalkForwardWindow:
    """Internal: NormalizedTick-based train/test split."""

    split_index: int
    train_ticks: list[NormalizedTick]
    test_ticks: list[NormalizedTick]
    test_start_ms: int
    test_end_ms: int


@dataclass
class _TickWalkForwardResult:
    """Internal: aggregated results from tick-based windows."""

    window_sharpes: list[float]
    oos_trades: list[Any]
    aggregate_report: dict[str, Any]
    mean_sharpe: float = 0.0
    std_sharpe: float = 0.0


class TickBasedWalkForwardValidator:
    """Purged walk-forward cross-validator operating on NormalizedTick lists.

    Used by :class:`~backtesting.engine.BacktestEngine` for replay validation.
    """

    def __init__(
        self,
        n_splits: int = _DEFAULT_N_SPLITS,
        embargo_bars: int = _DEFAULT_EMBARGO_BARS,
        train_ratio: float = _DEFAULT_TRAIN_RATIO,
    ) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self._n_splits = n_splits
        self._embargo_bars = embargo_bars
        self._train_ratio = train_ratio

    def build_windows_fast(
        self, ticks: list[NormalizedTick]
    ) -> list[_TickWalkForwardWindow]:
        """Fast O(n) window builder without list.index() calls."""
        n = len(ticks)
        if n < self._n_splits * 2:
            raise ValueError(f"Not enough ticks ({n}) for {self._n_splits} splits")

        window_size = n // self._n_splits
        windows: list[_TickWalkForwardWindow] = []

        for i in range(self._n_splits):
            test_start = i * window_size
            test_end = test_start + window_size if i < self._n_splits - 1 else n
            embargo_end = min(test_end + self._embargo_bars, n)
            purge_start = max(0, test_start - window_size // 4)

            train_ticks = ticks[:purge_start] + ticks[embargo_end:]
            test_ticks_window = ticks[test_start:test_end]

            if not test_ticks_window:
                continue

            windows.append(
                _TickWalkForwardWindow(
                    split_index=i,
                    train_ticks=train_ticks,
                    test_ticks=test_ticks_window,
                    test_start_ms=test_ticks_window[0].timestamp_ms,
                    test_end_ms=test_ticks_window[-1].timestamp_ms,
                )
            )
        return windows

    async def validate(
        self,
        ticks: list[NormalizedTick],
        engine_factory: Callable[[Decimal], Any],
        initial_capital: Decimal = Decimal("100000"),
    ) -> _TickWalkForwardResult:
        """Run the engine on each OOS window and aggregate results."""
        from backtesting.metrics import full_report as _full_report

        windows = self.build_windows_fast(ticks)
        all_trades: list[Any] = []
        window_sharpes: list[float] = []

        for win in windows:
            engine = engine_factory(initial_capital)
            trades = await engine.run(win.test_ticks)
            all_trades.extend(trades)
            report = _full_report(trades, float(initial_capital))
            window_sharpes.append(report.get("sharpe", 0.0))

        aggregate = _full_report(all_trades, float(initial_capital))
        mean_s = sum(window_sharpes) / len(window_sharpes) if window_sharpes else 0.0
        variance = (
            sum((s - mean_s) ** 2 for s in window_sharpes) / len(window_sharpes)
            if len(window_sharpes) > 1
            else 0.0
        )

        return _TickWalkForwardResult(
            window_sharpes=window_sharpes,
            oos_trades=all_trades,
            aggregate_report=aggregate,
            mean_sharpe=mean_s,
            std_sharpe=math.sqrt(variance),
        )


# ---------------------------------------------------------------------------
# CPCV — Combinatorial Purged Cross-Validation
# ---------------------------------------------------------------------------


@dataclass
class CPCVResult:
    """Results from Combinatorial Purged Cross-Validation.

    Contains the full distribution of OOS Sharpe ratios (one per C(N,k)
    combination) and the Probability of Backtest Overfitting (PBO).

    Attributes:
        oos_sharpes:       OOS Sharpe for each combination path.
        is_sharpes:        IS Sharpe for each combination's training set.
        is_sharpe_median:  Median IS Sharpe (the comparison baseline for PBO).
        oos_sharpe_mean:   Mean of the OOS Sharpe distribution.
        oos_sharpe_std:    Std of the OOS Sharpe distribution.
        oos_sharpe_median: Median OOS Sharpe (used for DEPLOY gate).
        pbo:               P(OOS Sharpe < IS median) ∈ [0, 1].
        n_combinations:    Number of C(N, k) paths evaluated.
        recommendation:    "DEPLOY" | "INVESTIGATE" | "DISCARD".
    """

    oos_sharpes: list[float]
    is_sharpes: list[float]
    is_sharpe_median: float
    oos_sharpe_mean: float
    oos_sharpe_std: float
    oos_sharpe_median: float
    pbo: float
    n_combinations: int
    recommendation: str = field(default="INVESTIGATE")


class CombinatorialPurgedCV:
    """Combinatorial Purged Cross-Validation (CPCV).

    Generates C(n_splits, n_test_splits) train/test paths to build a
    DISTRIBUTION of OOS Sharpe ratios rather than a single point estimate.

    Key difference from standard walk-forward:
    - Walk-forward → one sequential OOS estimate (high variance)
    - CPCV → C(N,k) independent OOS paths → PBO estimate (distribution)

    PBO (Probability of Backtest Overfitting) = fraction of OOS paths with
    Sharpe below the median IS Sharpe. Bailey et al. (2015), Eq.11.

    Deployment gates:
        DEPLOY:      pbo < 0.25  AND  oos_sharpe_median > 0.5
        INVESTIGATE: pbo < 0.50  (possible edge, more data needed)
        DISCARD:     pbo >= 0.50 (overfit signal — do not deploy)

    References:
        Bailey, Borwein, López de Prado & Zhu (2015).
            The Probability of Backtest Overfitting.
            Journal of Computational Finance 20(4). UC Davis + AHL Man Group.
        López de Prado, M. (2018). Advances in Financial Machine Learning.
            Wiley. Chapter 12: Cross-Validation in Finance.

    Args:
        n_splits:      Total number of equal-size data groups.
        n_test_splits: Groups used as test in each combination (k).
        embargo_pct:   Post-test embargo as fraction of total samples.
    """

    def __init__(
        self,
        n_splits: int = 6,
        n_test_splits: int = 2,
        embargo_pct: float = 0.01,
    ) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if n_test_splits < 1 or n_test_splits >= n_splits:
            raise ValueError("n_test_splits must be in [1, n_splits-1]")
        if not (0.0 <= embargo_pct < 0.5):
            raise ValueError("embargo_pct must be in [0, 0.5)")
        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.embargo_pct = embargo_pct

    def split(self, n_samples: int) -> list[tuple[list[int], list[int]]]:
        """Generate purged (train, test) index pairs for each C(N,k) path.

        Purging removes train samples inside the test window.
        Embargo removes train samples within embargo_pct of total length
        immediately after each test window.

        Args:
            n_samples: Total number of samples in the dataset.

        Returns:
            List of (train_indices, test_indices) pairs — one per combination.
        """
        if n_samples < self.n_splits * 2:
            raise ValueError(
                f"n_samples ({n_samples}) too small for {self.n_splits} splits"
            )
        group_size = n_samples // self.n_splits
        embargo_size = int(n_samples * self.embargo_pct)

        group_bounds: list[tuple[int, int]] = []
        for g in range(self.n_splits):
            start = g * group_size
            end = start + group_size if g < self.n_splits - 1 else n_samples
            group_bounds.append((start, end))

        splits: list[tuple[list[int], list[int]]] = []

        for test_groups in _combinations(range(self.n_splits), self.n_test_splits):
            test_set = set(test_groups)
            train_groups = [g for g in range(self.n_splits) if g not in test_set]

            # Collect test indices.
            test_idx: list[int] = []
            for g in sorted(test_groups):
                s, e = group_bounds[g]
                test_idx.extend(range(s, e))

            # Embargo zones: samples immediately after each test group boundary.
            # Applied per-group (not global min-max) to avoid incorrectly
            # excluding train groups that sit between non-contiguous test groups.
            embargo_zones: set[int] = set()
            if embargo_size > 0:
                for g in sorted(test_groups):
                    _, e = group_bounds[g]
                    for j in range(e, min(n_samples, e + embargo_size)):
                        embargo_zones.add(j)

            # Collect train indices: by construction train groups are disjoint
            # from test groups. We only need to skip embargo-zone samples.
            train_idx: list[int] = []
            for g in train_groups:
                s, e = group_bounds[g]
                for i in range(s, e):
                    if i not in embargo_zones:
                        train_idx.append(i)

            if train_idx and test_idx:
                splits.append((train_idx, test_idx))

        return splits

    def run(
        self,
        returns: list[float],
        sharpe_fn: Callable[[list[float]], float],
    ) -> CPCVResult:
        """Evaluate sharpe_fn on every C(N,k) combination and compute PBO.

        Args:
            returns:   Full return series (e.g. daily or per-trade returns).
            sharpe_fn: Callable(returns) → annualised Sharpe ratio.
                       Called on both training and test sets independently.

        Returns:
            :class:`CPCVResult` with PBO and deployment recommendation.
        """
        n = len(returns)
        splits = self.split(n)

        oos_sharpes: list[float] = []
        is_sharpes: list[float] = []

        for train_idx, test_idx in splits:
            train_r = [returns[i] for i in sorted(train_idx)]
            test_r = [returns[i] for i in sorted(test_idx)]
            is_sharpes.append(sharpe_fn(train_r))
            oos_sharpes.append(sharpe_fn(test_r))

        is_median = float(np.median(is_sharpes)) if is_sharpes else 0.0
        oos_arr = np.asarray(oos_sharpes, dtype=float) if oos_sharpes else np.array([0.0])

        pbo = (
            float(np.sum(oos_arr < is_median)) / len(oos_sharpes)
            if oos_sharpes
            else 1.0
        )
        oos_median = float(np.median(oos_arr))

        if pbo < 0.25 and oos_median > 0.5:
            rec = "DEPLOY"
        elif pbo < 0.50:
            rec = "INVESTIGATE"
        else:
            rec = "DISCARD"

        return CPCVResult(
            oos_sharpes=oos_sharpes,
            is_sharpes=is_sharpes,
            is_sharpe_median=is_median,
            oos_sharpe_mean=float(np.mean(oos_arr)),
            oos_sharpe_std=float(np.std(oos_arr)),
            oos_sharpe_median=oos_median,
            pbo=pbo,
            n_combinations=len(splits),
            recommendation=rec,
        )
