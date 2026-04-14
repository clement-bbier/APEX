"""Tests for features.labeling.sample_weights - uniqueness & concurrency.

Groups:

A. compute_concurrency primitives
B. uniqueness_weights core semantics (disjoint -> 1.0, overlap -> < 1.0)
C. Lopez de Prado (2018) section 4.4 Table 4.1 reference scenario
D. Fail-loud validation (naive / non-UTC, orphan timestamps, non-monotonic bars)
E. Edge cases (empty input, single sample, t0 == t1)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from features.labeling.sample_weights import (
    _ensure_utc_scalar,
    _validate_datetime_series,
    compute_concurrency,
    uniqueness_weights,
)

# --------------------------- Helpers ---------------------------------


def _ts(minute: int) -> datetime:
    return datetime(2024, 6, 1, 9, 30, tzinfo=UTC) + timedelta(minutes=minute)


def _bars(n: int) -> pl.Series:
    return pl.Series(
        values=[_ts(i) for i in range(n)],
        dtype=pl.Datetime("us", "UTC"),
    )


def _times(minutes: list[int]) -> pl.Series:
    return pl.Series(
        values=[_ts(m) for m in minutes],
        dtype=pl.Datetime("us", "UTC"),
    )


# --------------------------- A. Concurrency primitives ----------------


class TestComputeConcurrency:
    def test_single_span_covers_three_bars(self) -> None:
        bars = _bars(5)
        t0 = _times([1])
        t1 = _times([3])
        c = compute_concurrency(t0, t1, bars).to_list()
        assert c == [0, 1, 1, 1, 0]

    def test_three_overlapping_spans(self) -> None:
        """Classic overlapping triangle from LdP Figure 4.1-like scenario."""
        bars = _bars(5)
        t0 = _times([0, 1, 2])
        t1 = _times([2, 3, 4])
        c = compute_concurrency(t0, t1, bars).to_list()
        assert c == [1, 2, 3, 2, 1]

    def test_disjoint_spans_each_bar_one(self) -> None:
        bars = _bars(4)
        t0 = _times([0, 2])
        t1 = _times([1, 3])
        c = compute_concurrency(t0, t1, bars).to_list()
        assert c == [1, 1, 1, 1]

    def test_empty_samples_returns_zero_vector(self) -> None:
        bars = _bars(5)
        t0 = _times([])
        t1 = _times([])
        c = compute_concurrency(t0, t1, bars).to_list()
        assert c == [0, 0, 0, 0, 0]

    def test_single_bar_span_t0_equals_t1(self) -> None:
        bars = _bars(3)
        t0 = _times([1])
        t1 = _times([1])
        c = compute_concurrency(t0, t1, bars).to_list()
        assert c == [0, 1, 0]


# --------------------------- B. Uniqueness core -----------------------


class TestUniquenessCore:
    def test_disjoint_spans_all_ones(self) -> None:
        """LdP §4.4 canonical: non-overlapping labels each have u_i == 1.0."""
        bars = _bars(6)
        t0 = _times([0, 2, 4])
        t1 = _times([1, 3, 5])
        u = uniqueness_weights(t0, t1, bars).to_list()
        assert u == pytest.approx([1.0, 1.0, 1.0])

    def test_overlapping_spans_strictly_below_one(self) -> None:
        bars = _bars(5)
        t0 = _times([0, 1, 2])
        t1 = _times([2, 3, 4])
        u = uniqueness_weights(t0, t1, bars).to_list()
        assert all(v < 1.0 for v in u)
        # Middle sample has the heaviest overlap, so it must be the smallest.
        assert u[1] < u[0]
        assert u[1] < u[2]

    def test_single_sample_is_one(self) -> None:
        bars = _bars(5)
        t0 = _times([1])
        t1 = _times([3])
        u = uniqueness_weights(t0, t1, bars).to_list()
        assert u == pytest.approx([1.0])

    def test_identical_spans_each_get_half(self) -> None:
        """Two identical spans share concurrency == 2 at every bar -> u = 0.5."""
        bars = _bars(5)
        t0 = _times([1, 1])
        t1 = _times([3, 3])
        u = uniqueness_weights(t0, t1, bars).to_list()
        assert u == pytest.approx([0.5, 0.5])

    def test_span_length_one_equals_inverse_concurrency(self) -> None:
        """When |T_i| == 1, u_i == 1/c_{t0}."""
        bars = _bars(4)
        t0 = _times([1, 1, 2])
        t1 = _times([1, 1, 2])
        u = uniqueness_weights(t0, t1, bars).to_list()
        # bar 1 has c = 2 (samples 0 and 1); bar 2 has c = 1 (sample 2).
        assert u == pytest.approx([0.5, 0.5, 1.0])


# --------------------------- C. LdP Table 4.1 reference --------------


class TestUniquenessReferenceTable:
    def test_uniqueness_matches_reference_table_lopezdeprado_4_4(self) -> None:
        """Reproduce LdP (2018) §4.4 textbook illustration.

        Setup (see ADR-0005 D2 and audit.md §2.2):
            - 3 samples with spans:
                #0: bars [0, 2]  -> c = [1, 2, 3]         (concurrency at t0, t0+1, t0+2)
                #1: bars [1, 3]  -> c = [2, 3, 2]
                #2: bars [2, 4]  -> c = [3, 2, 1]
            - Overall concurrency across [0..4] = [1, 2, 3, 2, 1]
            - u_0 = mean(1/1, 1/2, 1/3) = 11/18   = 0.6111...
            - u_1 = mean(1/2, 1/3, 1/2) =  4/9    = 0.4444...
            - u_2 = mean(1/3, 1/2, 1/1) = 11/18   = 0.6111...
        """
        bars = _bars(5)
        t0 = _times([0, 1, 2])
        t1 = _times([2, 3, 4])
        u = uniqueness_weights(t0, t1, bars).to_list()
        expected = [11.0 / 18.0, 4.0 / 9.0, 11.0 / 18.0]
        assert u == pytest.approx(expected, abs=1e-12)


# --------------------------- D. Fail-loud validation ------------------


class TestUniquenessValidation:
    def test_naive_t0_raises(self) -> None:
        bars = _bars(3)
        naive = pl.Series(
            values=[datetime(2024, 6, 1, 9, 30)],  # no tzinfo
            dtype=pl.Datetime("us"),  # naive dtype
        )
        with pytest.raises(ValueError, match="UTC"):
            uniqueness_weights(naive, naive, bars)

    def test_non_utc_timezone_raises(self) -> None:
        bars = _bars(3)
        plus_two = timezone(timedelta(hours=2))
        ts = datetime(2024, 6, 1, 11, 30, tzinfo=plus_two)
        series = pl.Series(values=[ts], dtype=pl.Datetime("us", "+02:00"))
        with pytest.raises(ValueError, match="UTC"):
            uniqueness_weights(series, series, bars)

    def test_orphan_t0_not_in_bars_raises(self) -> None:
        bars = _bars(5)
        orphan = datetime(2024, 6, 1, 9, 30, 30, tzinfo=UTC)  # between bars
        t0 = pl.Series(values=[orphan], dtype=pl.Datetime("us", "UTC"))
        t1 = _times([3])
        with pytest.raises(ValueError, match="not present in bars"):
            uniqueness_weights(t0, t1, bars)

    def test_t1_before_t0_raises(self) -> None:
        bars = _bars(5)
        t0 = _times([3])
        t1 = _times([1])
        with pytest.raises(ValueError, match="t1 < t0"):
            uniqueness_weights(t0, t1, bars)

    def test_non_monotonic_bars_raises(self) -> None:
        reordered = pl.Series(
            values=[_ts(2), _ts(0), _ts(1)],
            dtype=pl.Datetime("us", "UTC"),
        )
        t0 = _times([0])
        t1 = _times([1])
        with pytest.raises(ValueError, match="strictly monotonic"):
            uniqueness_weights(t0, t1, reordered)

    def test_t1_past_last_bar_raises(self) -> None:
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([5])  # past last bar
        with pytest.raises(ValueError, match="past the last bar"):
            uniqueness_weights(t0, t1, bars)

    def test_orphan_t1_not_in_bars_raises(self) -> None:
        """t0 aligned on a bar, t1 off-grid -> fail-loud on the t1 branch."""
        bars = _bars(5)
        orphan_t1 = datetime(2024, 6, 1, 9, 30, tzinfo=UTC) + timedelta(minutes=2, seconds=30)
        t0 = _times([0])
        t1 = pl.Series(values=[orphan_t1], dtype=pl.Datetime("us", "UTC"))
        with pytest.raises(ValueError, match=r"t1=.* is not present in bars"):
            uniqueness_weights(t0, t1, bars)

    def test_t0_t1_length_mismatch_raises(self) -> None:
        bars = _bars(5)
        t0 = _times([0, 1])
        t1 = _times([2])
        with pytest.raises(ValueError, match="different lengths"):
            uniqueness_weights(t0, t1, bars)

    def test_bars_dtype_mismatch_raises(self) -> None:
        """t0 carries a different Datetime unit from bars -> fail-loud."""
        # bars in us, t0/t1 in ns -> dtype mismatch in _locate_span_indices.
        bars = _bars(5)
        ns_t0 = pl.Series(
            values=[_ts(0)],
            dtype=pl.Datetime("ns", "UTC"),
        )
        ns_t1 = pl.Series(
            values=[_ts(1)],
            dtype=pl.Datetime("ns", "UTC"),
        )
        # _validate_datetime_series rejects the different dtype first.
        with pytest.raises(ValueError, match=r"pl\.Datetime\('us', 'UTC'\)"):
            uniqueness_weights(ns_t0, ns_t1, bars)


# --------------------------- E. Edge cases ----------------------------


class TestUniquenessEdgeCases:
    def test_empty_events_returns_empty_series(self) -> None:
        bars = _bars(5)
        t0 = _times([])
        t1 = _times([])
        u = uniqueness_weights(t0, t1, bars)
        assert len(u) == 0
        assert u.dtype == pl.Float64

    def test_empty_bars_but_nonempty_events_raises(self) -> None:
        bars = pl.Series(values=[], dtype=pl.Datetime("us", "UTC"))
        t0 = _times([0])
        t1 = _times([0])
        with pytest.raises(ValueError, match="bars is empty"):
            uniqueness_weights(t0, t1, bars)

    def test_compute_concurrency_empty_bars_nonempty_events_raises(self) -> None:
        """Same fail-loud path as uniqueness, surfaced by compute_concurrency."""
        bars = pl.Series(values=[], dtype=pl.Datetime("us", "UTC"))
        t0 = _times([0])
        t1 = _times([0])
        with pytest.raises(ValueError, match="bars is empty"):
            compute_concurrency(t0, t1, bars)

    def test_uniqueness_values_in_unit_interval(self) -> None:
        """u_i in (0, 1] for every well-formed sample."""
        rng = np.random.default_rng(42)
        n_bars = 50
        bars = _bars(n_bars)
        starts = sorted(int(x) for x in rng.integers(0, n_bars - 5, size=10))
        lengths = rng.integers(1, 5, size=10).tolist()
        t0 = _times(list(starts))
        t1 = _times([s + int(ln) for s, ln in zip(starts, lengths, strict=True)])
        u = uniqueness_weights(t0, t1, bars).to_numpy()
        assert np.all(u > 0.0)
        assert np.all(u <= 1.0)

    def test_result_dtype_is_float64(self) -> None:
        bars = _bars(4)
        t0 = _times([0])
        t1 = _times([1])
        u = uniqueness_weights(t0, t1, bars)
        assert u.dtype == pl.Float64


# --------------------------- F. Private helpers (defensive paths) ------


class TestPrivateValidators:
    """Direct coverage of defensive branches inside private helpers.

    These paths cannot be reached via the public API on well-typed Polars
    inputs, but they remain important belt-and-braces checks for callers
    that hand-build a series bypassing dtype coercion.
    """

    def test_ensure_utc_scalar_naive_raises(self) -> None:
        naive = datetime(2024, 6, 1, 9, 30)
        with pytest.raises(ValueError, match="tz-naive"):
            _ensure_utc_scalar(naive, "probe")

    def test_ensure_utc_scalar_non_utc_raises(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        ts = datetime(2024, 6, 1, 11, 30, tzinfo=plus_two)
        with pytest.raises(ValueError, match="not UTC"):
            _ensure_utc_scalar(ts, "probe")

    def test_validate_datetime_series_with_null_head_ok(self) -> None:
        """Null first element should skip the per-scalar UTC check gracefully."""
        series = pl.Series(
            values=[None, _ts(0)],
            dtype=pl.Datetime("us", "UTC"),
        )
        # Must not raise: the `head is None` branch exits cleanly.
        _validate_datetime_series(series, "probe")
