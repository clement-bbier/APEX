"""Tests for features.labeling.diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from features.labeling.diagnostics import compute_label_diagnostics


def _ts(minute: int) -> datetime:
    return datetime(2024, 6, 1, tzinfo=UTC) + timedelta(minutes=minute)


def _make_labels_df(
    ternary: list[int],
    binary: list[int],
    barriers: list[str],
    holding: list[int],
    entries: list[float],
    exits: list[float],
) -> pl.DataFrame:
    n = len(ternary)
    return pl.DataFrame(
        {
            "symbol": ["X"] * n,
            "t0": [_ts(i) for i in range(n)],
            "t1": [_ts(i + 5) for i in range(n)],
            "entry_price": entries,
            "exit_price": exits,
            "ternary_label": ternary,
            "binary_target": binary,
            "barrier_hit": barriers,
            "holding_periods": holding,
        },
        schema={
            "symbol": pl.Utf8,
            "t0": pl.Datetime("us", "UTC"),
            "t1": pl.Datetime("us", "UTC"),
            "entry_price": pl.Float64,
            "exit_price": pl.Float64,
            "ternary_label": pl.Int8,
            "binary_target": pl.Int8,
            "barrier_hit": pl.Utf8,
            "holding_periods": pl.Int32,
        },
    )


class TestLabelDiagnostics:
    def test_class_balance(self) -> None:
        df = _make_labels_df(
            ternary=[1, 1, 0, -1],
            binary=[1, 1, 0, 0],
            barriers=["upper", "upper", "vertical", "lower"],
            holding=[5, 3, 10, 7],
            entries=[100.0, 100.0, 100.0, 100.0],
            exits=[105.0, 103.0, 100.5, 97.0],
        )
        diag = compute_label_diagnostics(df)
        assert diag.n_events == 4
        assert diag.binary_pct_one == pytest.approx(0.5)
        assert diag.binary_pct_zero == pytest.approx(0.5)
        assert diag.ternary_pct_up == pytest.approx(0.5)
        assert diag.ternary_pct_flat == pytest.approx(0.25)
        assert diag.ternary_pct_down == pytest.approx(0.25)

    def test_barrier_distribution(self) -> None:
        df = _make_labels_df(
            ternary=[1, 0, 0, -1, 1],
            binary=[1, 0, 0, 0, 1],
            barriers=["upper", "vertical", "vertical", "lower", "upper"],
            holding=[3, 10, 10, 4, 2],
            entries=[100.0] * 5,
            exits=[105.0, 100.2, 99.8, 96.0, 107.0],
        )
        diag = compute_label_diagnostics(df)
        assert diag.barrier_pct_upper == pytest.approx(0.4)
        assert diag.barrier_pct_lower == pytest.approx(0.2)
        assert diag.barrier_pct_vertical == pytest.approx(0.4)

    def test_holding_distribution(self) -> None:
        df = _make_labels_df(
            ternary=[1, 1, 1, 1, 1],
            binary=[1, 1, 1, 1, 1],
            barriers=["upper"] * 5,
            holding=[1, 2, 3, 4, 5],
            entries=[100.0] * 5,
            exits=[101.0, 102.0, 103.0, 104.0, 105.0],
        )
        diag = compute_label_diagnostics(df)
        assert diag.holding_min == 1
        assert diag.holding_max == 5
        assert diag.holding_median == pytest.approx(3.0)

    def test_sanity_check_label_one_positive(self) -> None:
        df = _make_labels_df(
            ternary=[1, 1, -1, -1],
            binary=[1, 1, 0, 0],
            barriers=["upper", "upper", "lower", "lower"],
            holding=[5, 5, 5, 5],
            entries=[100.0, 100.0, 100.0, 100.0],
            exits=[105.0, 108.0, 95.0, 93.0],
        )
        diag = compute_label_diagnostics(df)
        assert diag.mean_return_label_one > 0
        assert diag.mean_return_label_zero < 0
        assert diag.sanity_label_one_positive
        assert diag.sanity_label_zero_nonpositive

    def test_empty_raises(self) -> None:
        empty = _make_labels_df([], [], [], [], [], [])
        with pytest.raises(ValueError, match="empty"):
            compute_label_diagnostics(empty)

    def test_missing_column_raises(self) -> None:
        df = pl.DataFrame(
            {
                "ternary_label": [1],
                "binary_target": [1],
                "barrier_hit": ["upper"],
                "holding_periods": [3],
                # missing entry_price, exit_price
            }
        )
        with pytest.raises(ValueError, match="missing columns"):
            compute_label_diagnostics(df)
