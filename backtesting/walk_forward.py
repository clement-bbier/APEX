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
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
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
