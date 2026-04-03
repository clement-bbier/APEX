"""Walk-forward validation for APEX Trading System.

Implements Lopez de Prado's purged cross-validation methodology:
- Splits data into N sequential train/test windows.
- Purges training samples whose labels overlap with the test period.
- Adds an embargo of K bars after each test window to prevent leakage.

Reference:
    Lopez de Prado (2018), *Advances in Financial Machine Learning*,
    Chapter 7: "Cross-Validation in Finance".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from core.models.tick import NormalizedTick
from backtesting.metrics import full_report, sharpe_ratio

_DEFAULT_TRAIN_RATIO = 0.8
_DEFAULT_N_SPLITS = 5
_DEFAULT_EMBARGO_BARS = 50


@dataclass
class WalkForwardWindow:
    """A single train/test split with purge metadata.

    Attributes:
        split_index: 0-based index of this window.
        train_ticks: Ticks available for strategy calibration.
        test_ticks:  Ticks used for out-of-sample evaluation.
        test_start_ms: Earliest timestamp in the test set.
        test_end_ms:   Latest timestamp in the test set.
    """

    split_index: int
    train_ticks: list[NormalizedTick]
    test_ticks: list[NormalizedTick]
    test_start_ms: int
    test_end_ms: int


@dataclass
class WalkForwardResult:
    """Aggregated results from all out-of-sample windows.

    Attributes:
        window_sharpes: Sharpe ratio for each out-of-sample window.
        oos_trades:     All out-of-sample trade records combined.
        aggregate_report: Full performance report across all OOS trades.
        mean_sharpe: Mean OOS Sharpe across windows.
        std_sharpe:  Standard deviation of window Sharpes.
    """

    window_sharpes: list[float]
    oos_trades: list[Any]  # list[TradeRecord]
    aggregate_report: dict
    mean_sharpe: float = 0.0
    std_sharpe: float = 0.0


class WalkForwardValidator:
    """Purged walk-forward cross-validator.

    Usage::

        wfv = WalkForwardValidator(n_splits=5, embargo_bars=50)
        result = await wfv.validate(ticks, engine_factory)

    Args:
        n_splits:      Number of train/test windows.
        embargo_bars:  Bars to exclude immediately after each test window.
        train_ratio:   Fraction of each window allocated to training.
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

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_windows(self, ticks: list[NormalizedTick]) -> list[WalkForwardWindow]:
        """Build purged train/test windows from an ordered tick list.

        Args:
            ticks: All available ticks sorted by timestamp ascending.

        Returns:
            List of :class:`WalkForwardWindow` ready for backtesting.
        """
        n = len(ticks)
        window_size = n // self._n_splits
        windows: list[WalkForwardWindow] = []

        for i in range(self._n_splits):
            test_start = i * window_size
            test_end = test_start + window_size if i < self._n_splits - 1 else n
            # Embargo: skip bars immediately after test end
            embargo_end = min(test_end + self._embargo_bars, n)

            # Training set: all bars NOT in [test_start, embargo_end)
            train_ticks = (
                [t for t in ticks[:test_start]]
                + [t for t in ticks[embargo_end:]]
            )
            # Purge: remove training bars whose label horizon reaches the test set
            # (simplified: remove bars within 1 window_size before test_start)
            purge_horizon = max(0, test_start - window_size // 4)
            train_ticks = [t for t in train_ticks if ticks.index(t) < purge_horizon or
                           ticks.index(t) >= embargo_end]

            test_ticks_window = ticks[test_start:test_end]
            if not test_ticks_window:
                continue

            windows.append(
                WalkForwardWindow(
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
        engine_factory: Any,
        initial_capital: Decimal = Decimal("100000"),
    ) -> WalkForwardResult:
        """Run the engine on each OOS test window and aggregate results.

        Args:
            ticks:           Full tick history (sorted ascending).
            engine_factory:  Callable that returns a fresh BacktestEngine.
            initial_capital: Capital for each window run.

        Returns:
            :class:`WalkForwardResult` with per-window and aggregate metrics.
        """
        from backtesting.metrics import full_report as _full_report

        windows = self.build_windows_fast(ticks)
        all_trades: list = []
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

        return WalkForwardResult(
            window_sharpes=window_sharpes,
            oos_trades=all_trades,
            aggregate_report=aggregate,
            mean_sharpe=mean_s,
            std_sharpe=math.sqrt(variance),
        )

    def build_windows_fast(self, ticks: list[NormalizedTick]) -> list[WalkForwardWindow]:
        """Fast window builder that avoids O(n²) list.index() calls.

        Args:
            ticks: All available ticks sorted by timestamp ascending.

        Returns:
            List of :class:`WalkForwardWindow`.
        """
        n = len(ticks)
        if n < self._n_splits * 2:
            raise ValueError(f"Not enough ticks ({n}) for {self._n_splits} splits")

        window_size = n // self._n_splits
        windows: list[WalkForwardWindow] = []

        for i in range(self._n_splits):
            test_start = i * window_size
            test_end = test_start + window_size if i < self._n_splits - 1 else n
            embargo_end = min(test_end + self._embargo_bars, n)
            purge_start = max(0, test_start - window_size // 4)

            # Training: before purge_start AND after embargo_end
            train_ticks = ticks[:purge_start] + ticks[embargo_end:]
            test_ticks_window = ticks[test_start:test_end]

            if not test_ticks_window:
                continue

            windows.append(
                WalkForwardWindow(
                    split_index=i,
                    train_ticks=train_ticks,
                    test_ticks=test_ticks_window,
                    test_start_ms=test_ticks_window[0].timestamp_ms,
                    test_end_ms=test_ticks_window[-1].timestamp_ms,
                )
            )
        return windows
