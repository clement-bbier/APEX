"""Tests for the purged walk-forward cross-validator (Lopez de Prado, Chapter 7)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backtesting.walk_forward import WalkForwardResult, WalkForwardValidator


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
