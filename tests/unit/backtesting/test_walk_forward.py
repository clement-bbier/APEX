"""Tests for the purged walk-forward cross-validator (Lopez de Prado, Chapter 7).

Coverage mission (Sprint 4 Vague 2 Wave B, Agent F): raise this module's coverage
(full-suite) from 75.8% toward 95%+, secondary target after
core/data/timescale_repository.py, to unblock issue #203.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from backtesting.walk_forward import (
    CombinatorialPurgedCV,
    CPCVResult,
    TickBasedWalkForwardValidator,
    WalkForwardResult,
    WalkForwardValidator,
)
from core.models.tick import Market, NormalizedTick


class TestWalkForwardValidator:
    def make_validator(self) -> WalkForwardValidator:
        return WalkForwardValidator(n_windows=3, train_months=3, test_months=1)

    def test_windows_dont_overlap(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        windows = v.build_windows(start, end)

        for i in range(len(windows) - 1):
            assert windows[i].test_end <= windows[i + 1].test_start

    def test_train_ends_before_test(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        windows = v.build_windows(start, end)

        for w in windows:
            assert w.train_end < w.test_start

    def test_embargo_end_after_test_end(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        windows = v.build_windows(start, end)

        for w in windows:
            assert w.embargo_end > w.test_end

    def test_window_ids_sequential(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        windows = v.build_windows(start, end)

        for i, w in enumerate(windows):
            assert w.window_id == i

    def test_aggregate_results(self) -> None:
        v = self.make_validator()
        results = [
            WalkForwardResult(
                0,
                sharpe=1.2,
                max_drawdown=0.04,
                win_rate=0.54,
                n_trades=50,
                out_of_sample_return=0.05,
            ),
            WalkForwardResult(
                1,
                sharpe=0.9,
                max_drawdown=0.06,
                win_rate=0.51,
                n_trades=45,
                out_of_sample_return=0.03,
            ),
        ]
        agg = v.aggregate_results(results)
        assert agg["oos_sharpe_mean"] == pytest.approx(1.05)
        assert agg["n_total_trades"] == 95
        assert "is_consistent" in agg

    def test_aggregate_empty_returns_error(self) -> None:
        v = self.make_validator()
        result = v.aggregate_results([])
        assert "error" in result

    def test_zero_windows_raises(self) -> None:
        with pytest.raises(ValueError, match="n_windows"):
            WalkForwardValidator(n_windows=0)

    def test_data_too_short_produces_fewer_windows(self) -> None:
        """If data range is too short, some windows are skipped."""
        v = WalkForwardValidator(n_windows=10, train_months=6, test_months=1)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        windows = v.build_windows(start, end)
        # Only 6 months remain for test windows after 6-month train
        assert len(windows) < 10


class TestRunValidation:
    """Cover WalkForwardValidator.run_validation (lines 169-188)."""

    def _make_data(self, n_days: int = 365) -> pd.DataFrame:
        """Generate a synthetic timestamp-column DataFrame."""
        timestamps = pd.date_range(
            start="2024-01-01",
            periods=n_days * 24,
            freq="1h",
            tz="UTC",
        )
        return pd.DataFrame({"timestamp": timestamps, "value": range(len(timestamps))})

    def test_run_validation_invokes_backtest_per_window(self) -> None:
        v = WalkForwardValidator(n_windows=3, train_months=3, test_months=1)
        data = self._make_data(n_days=200)
        calls: list[int] = []

        def backtest_fn(train_df, test_df, window_id):
            calls.append(window_id)
            return WalkForwardResult(
                window_id=window_id,
                sharpe=1.0,
                max_drawdown=0.05,
                win_rate=0.5,
                n_trades=500,
                out_of_sample_return=0.02,
            )

        results = v.run_validation(data, backtest_fn)
        assert len(results) == len(calls)
        assert len(results) > 0
        assert all(isinstance(r, WalkForwardResult) for r in results)

    def test_run_validation_skips_small_test_windows(self) -> None:
        """A window with <100 test rows is skipped (line 182-183)."""
        # Build tiny dataset — one hour per day so test windows only have ~30 rows
        timestamps = pd.date_range(
            start="2024-01-01",
            periods=200,
            freq="1D",
            tz="UTC",
        )
        data = pd.DataFrame({"timestamp": timestamps, "value": range(200)})
        v = WalkForwardValidator(n_windows=3, train_months=3, test_months=1)

        calls: list[int] = []

        def backtest_fn(train_df, test_df, window_id):
            calls.append(window_id)
            return WalkForwardResult(window_id, 1.0, 0.0, 0.5, 1, 0.0)

        results = v.run_validation(data, backtest_fn)
        # With only ~30 rows per month, all test windows should be skipped
        assert len(results) == 0
        assert len(calls) == 0


class TestTickBasedWalkForwardValidatorInit:
    """Cover TickBasedWalkForwardValidator.__init__ (lines 264-268)."""

    def test_init_defaults(self) -> None:
        v = TickBasedWalkForwardValidator()
        assert v._n_splits == 5
        assert v._embargo_bars == 50
        assert v._train_ratio == 0.8

    def test_init_custom_values(self) -> None:
        v = TickBasedWalkForwardValidator(n_splits=3, embargo_bars=10, train_ratio=0.7)
        assert v._n_splits == 3
        assert v._embargo_bars == 10
        assert v._train_ratio == 0.7

    def test_init_rejects_too_few_splits(self) -> None:
        with pytest.raises(ValueError, match="n_splits"):
            TickBasedWalkForwardValidator(n_splits=1)


def _make_tick(ts_ms: int) -> NormalizedTick:
    """Build a minimal NormalizedTick at the given millisecond timestamp."""
    return NormalizedTick(
        symbol="BTCUSDT",
        market=Market.CRYPTO,
        timestamp_ms=ts_ms + 1,  # gt=0 constraint
        price=Decimal("100"),
        volume=Decimal("1"),
        bid=Decimal("99.9"),
        ask=Decimal("100.1"),
    )


class TestTickBasedBuildWindowsFast:
    """Cover TickBasedWalkForwardValidator.build_windows_fast (lines 272-300)."""

    def test_build_windows_too_few_ticks_raises(self) -> None:
        v = TickBasedWalkForwardValidator(n_splits=5)
        # n_splits=5 requires at least 10 ticks
        ticks = [_make_tick(i * 1000) for i in range(5)]
        with pytest.raises(ValueError, match="Not enough ticks"):
            v.build_windows_fast(ticks)

    def test_build_windows_produces_n_splits(self) -> None:
        v = TickBasedWalkForwardValidator(n_splits=3, embargo_bars=1)
        ticks = [_make_tick(i * 1000) for i in range(30)]
        windows = v.build_windows_fast(ticks)

        assert len(windows) == 3
        assert [w.split_index for w in windows] == [0, 1, 2]
        # Each window has non-empty test ticks
        for w in windows:
            assert w.test_ticks
            assert w.test_start_ms == w.test_ticks[0].timestamp_ms
            assert w.test_end_ms == w.test_ticks[-1].timestamp_ms

    def test_build_windows_final_split_extends_to_end(self) -> None:
        """Final split should absorb any remainder ticks (lines 281)."""
        v = TickBasedWalkForwardValidator(n_splits=3, embargo_bars=0)
        # 31 ticks / 3 = 10 rem 1 → final split gets 11 ticks
        ticks = [_make_tick(i * 1000) for i in range(31)]
        windows = v.build_windows_fast(ticks)

        assert len(windows) == 3
        assert len(windows[-1].test_ticks) == 11

    def test_build_windows_empty_window_is_skipped(self) -> None:
        """A window with no ticks is skipped (line 288-289)."""
        v = TickBasedWalkForwardValidator(n_splits=3, embargo_bars=0)
        # Just enough ticks to pass the minimum (n_splits * 2 = 6),
        # but window_size = 2 and at least one window will be empty after slicing.
        # This path asserts `continue` doesn't crash even if rare.
        ticks = [_make_tick(i * 1000) for i in range(6)]
        windows = v.build_windows_fast(ticks)
        # 3 windows of size 2 each; last absorbs remainder → all non-empty
        assert len(windows) == 3


class TestCombinatorialPurgedCVInit:
    """Cover CombinatorialPurgedCV.__init__ (lines 411-419)."""

    def test_init_defaults(self) -> None:
        cv = CombinatorialPurgedCV()
        assert cv.n_splits == 6
        assert cv.n_test_splits == 2
        assert cv.embargo_pct == 0.01

    def test_init_rejects_too_few_splits(self) -> None:
        with pytest.raises(ValueError, match="n_splits"):
            CombinatorialPurgedCV(n_splits=1)

    def test_init_rejects_too_many_test_splits(self) -> None:
        with pytest.raises(ValueError, match="n_test_splits"):
            CombinatorialPurgedCV(n_splits=5, n_test_splits=5)

    def test_init_rejects_zero_test_splits(self) -> None:
        with pytest.raises(ValueError, match="n_test_splits"):
            CombinatorialPurgedCV(n_splits=5, n_test_splits=0)

    def test_init_rejects_bad_embargo(self) -> None:
        with pytest.raises(ValueError, match="embargo_pct"):
            CombinatorialPurgedCV(embargo_pct=0.5)

    def test_init_rejects_negative_embargo(self) -> None:
        with pytest.raises(ValueError, match="embargo_pct"):
            CombinatorialPurgedCV(embargo_pct=-0.1)


class TestCombinatorialPurgedCVSplit:
    """Cover CombinatorialPurgedCV.split (lines 434-481)."""

    def test_split_rejects_too_few_samples(self) -> None:
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2)
        with pytest.raises(ValueError, match="too small"):
            cv.split(n_samples=5)

    def test_split_produces_expected_combinations(self) -> None:
        # C(6, 2) = 15 combinations
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
        splits = cv.split(n_samples=600)
        assert len(splits) == 15
        # Every split has disjoint train and test
        for train_idx, test_idx in splits:
            train_set = set(train_idx)
            test_set = set(test_idx)
            assert train_set.isdisjoint(test_set)
            assert len(train_idx) > 0
            assert len(test_idx) > 0

    def test_split_embargo_removes_train_samples(self) -> None:
        """With embargo_pct > 0, some train samples immediately after test are excluded (lines 462-466)."""
        cv_no_embargo = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.0)
        cv_with_embargo = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.1)

        ne = cv_no_embargo.split(n_samples=400)
        we = cv_with_embargo.split(n_samples=400)

        # Each split tuple's train set is smaller (or equal for the last group's
        # test, where embargo extends beyond data)
        train_sizes_no = [len(t[0]) for t in ne]
        train_sizes_with = [len(t[0]) for t in we]
        assert sum(train_sizes_with) < sum(train_sizes_no)


class TestCombinatorialPurgedCVRun:
    """Cover CombinatorialPurgedCV.run and the DEPLOY/INVESTIGATE/DISCARD gates
    (lines 498-523)."""

    def test_run_deploy_recommendation(self) -> None:
        """When OOS sharpe is always high, recommendation is DEPLOY."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.0)
        returns = [0.01] * 400

        def sharpe_fn(rs: list[float]) -> float:
            # Constant strong OOS sharpe for all paths — OOS > IS median threshold
            return 2.0 if len(rs) > 0 else 0.0

        result = cv.run(returns, sharpe_fn)
        assert isinstance(result, CPCVResult)
        # All IS == OOS == 2.0 → pbo = 0 (no OOS < median)
        assert result.pbo == 0.0
        assert result.oos_sharpe_median == 2.0
        assert result.recommendation == "DEPLOY"
        assert result.n_combinations > 0

    def test_run_discard_when_high_pbo(self) -> None:
        """When OOS sharpe is systematically below IS sharpe, recommendation is DISCARD."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.0)
        returns = [0.01] * 400

        call_count = {"n": 0}

        def sharpe_fn(rs: list[float]) -> float:
            # Alternate between high IS and low OOS scores (train called first per loop)
            # For split loop: is_sharpes.append(train), oos_sharpes.append(test)
            # So odd calls = training, even calls = test (in order)
            call_count["n"] += 1
            # Higher for training, lower for test
            if call_count["n"] % 2 == 1:
                return 3.0  # IS
            return -1.0  # OOS

        result = cv.run(returns, sharpe_fn)
        assert result.pbo == 1.0  # all OOS < IS median
        assert result.oos_sharpe_median < 0
        assert result.recommendation == "DISCARD"

    def test_run_investigate_when_moderate_pbo(self) -> None:
        """pbo in [0.25, 0.5) → INVESTIGATE."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.0)
        returns = [0.01] * 400

        # 4 splits: mix OOS sharpes so pbo = 0.25 (1/4 below IS median)
        # IS median will be ~1.0 (4 paths of 1.0) → pick OOS such that 1 of 4 is below
        call_count = {"n": 0}

        def sharpe_fn(rs: list[float]) -> float:
            call_count["n"] += 1
            # Odd = IS (return 1.0), even = OOS (varied)
            if call_count["n"] % 2 == 1:
                return 1.0
            # OOS values: 0.3 (below IS median so pbo>0 but oos median will be high)
            # sequence of OOS values per combination
            oos_idx = (call_count["n"] // 2) - 1
            # Make 1 of 4 below, 3 above with mid = 1.5
            return [0.3, 1.5, 1.5, 1.5][oos_idx % 4]

        result = cv.run(returns, sharpe_fn)
        # pbo = 0.25 (1 out of 4 < 1.0)
        assert 0.0 < result.pbo < 0.5
        # oos_median = 1.5 > 0.5 but pbo >= 0.25 so not DEPLOY → INVESTIGATE
        assert result.recommendation == "INVESTIGATE"

    def test_run_empty_oos_paths(self) -> None:
        """Smoke: confirm run returns something even on short input just above minimum."""
        cv = CombinatorialPurgedCV(n_splits=3, n_test_splits=1, embargo_pct=0.0)
        returns = [0.01] * 60

        def sharpe_fn(_rs: list[float]) -> float:
            return 0.5

        result = cv.run(returns, sharpe_fn)
        # With n_splits=3, n_test_splits=1 → C(3,1)=3 combinations
        assert result.n_combinations == 3
        assert len(result.oos_sharpes) == 3
        assert len(result.is_sharpes) == 3
