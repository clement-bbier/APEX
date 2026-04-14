"""Tests for features.labeling.sample_weights.combined_weights.

Groups:

A. Normalization invariant sum(w) == n_samples
B. Componentwise identity w == u * r (up to normalization factor)
C. All-zero pathological case (no silent remap to uniform)
D. Reproducibility across calls
E. Empty input / dtype
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from features.labeling.sample_weights import (
    combined_weights,
    return_attribution_weights,
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


def _returns(values: list[float]) -> pl.Series:
    return pl.Series(values=values, dtype=pl.Float64)


# --------------------------- A. Normalization -------------------------


class TestCombinedNormalization:
    def test_sum_equals_n_samples_disjoint(self) -> None:
        bars = _bars(6)
        t0 = _times([0, 2, 4])
        t1 = _times([1, 3, 5])
        ret = _returns([0.01, 0.02, -0.01, 0.03, -0.02, 0.01])
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert float(np.sum(w)) == pytest.approx(3.0, abs=1e-9)

    def test_sum_equals_n_samples_overlapping(self) -> None:
        bars = _bars(5)
        t0 = _times([0, 1, 2])
        t1 = _times([2, 3, 4])
        ret = _returns([0.01, 0.02, 0.03, 0.04, 0.05])
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert float(np.sum(w)) == pytest.approx(3.0, abs=1e-9)

    def test_sum_equals_n_samples_single_sample(self) -> None:
        bars = _bars(4)
        t0 = _times([0])
        t1 = _times([3])
        ret = _returns([0.02, 0.03, -0.01, 0.04])
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert float(np.sum(w)) == pytest.approx(1.0, abs=1e-9)
        # Single sample normalized => exactly 1.0 regardless of magnitude
        assert w.tolist() == pytest.approx([1.0])


# --------------------------- B. Componentwise identity ----------------


class TestCombinedIdentity:
    def test_raw_product_matches_u_times_r_up_to_scale(self) -> None:
        """Combined must be proportional to u*r with a single global factor."""
        bars = _bars(6)
        t0 = _times([0, 1, 3])
        t1 = _times([2, 4, 5])
        ret = _returns([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])

        u = uniqueness_weights(t0, t1, bars).to_numpy()
        r = return_attribution_weights(t0, t1, bars, ret).to_numpy()
        raw = u * r

        w = combined_weights(t0, t1, bars, ret).to_numpy()

        scale = float(np.sum(raw))
        expected = raw * (len(t0) / scale)
        np.testing.assert_allclose(w, expected, atol=1e-12)


# --------------------------- C. All-zero pathological -----------------


class TestCombinedZero:
    def test_all_zero_returns_returns_zero_vector(self) -> None:
        """ADR-0005 D2: no silent remap to uniform when r == 0 everywhere."""
        bars = _bars(4)
        t0 = _times([0, 2])
        t1 = _times([1, 3])
        ret = _returns([0.0, 0.0, 0.0, 0.0])
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert w.tolist() == [0.0, 0.0]

    def test_all_uniqueness_zero_would_return_zero(self) -> None:
        # uniqueness can never be 0 in a well-formed input, but u*r being
        # all zero (via returns) should yield all-zero combined.
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([2])
        ret = _returns([0.02, -0.01, -0.01])  # sum == 0
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert w.tolist() == pytest.approx([0.0], abs=1e-12)


# --------------------------- D. Reproducibility -----------------------


class TestCombinedReproducibility:
    def test_two_calls_return_identical_values(self) -> None:
        bars = _bars(6)
        t0 = _times([0, 2, 3])
        t1 = _times([2, 4, 5])
        ret = _returns([0.01, -0.02, 0.03, 0.01, -0.01, 0.02])
        w1 = combined_weights(t0, t1, bars, ret).to_numpy()
        w2 = combined_weights(t0, t1, bars, ret).to_numpy()
        np.testing.assert_array_equal(w1, w2)


# --------------------------- E. Empty / dtype -------------------------


class TestCombinedEdgeCases:
    def test_empty_events_returns_empty(self) -> None:
        bars = _bars(3)
        ret = _returns([0.0, 0.0, 0.0])
        t0 = _times([])
        t1 = _times([])
        w = combined_weights(t0, t1, bars, ret)
        assert len(w) == 0
        assert w.dtype == pl.Float64

    def test_result_dtype_is_float64(self) -> None:
        bars = _bars(4)
        t0 = _times([0])
        t1 = _times([2])
        ret = _returns([0.01, 0.02, 0.03, 0.04])
        w = combined_weights(t0, t1, bars, ret)
        assert w.dtype == pl.Float64

    def test_all_weights_non_negative(self) -> None:
        bars = _bars(5)
        t0 = _times([0, 1])
        t1 = _times([2, 4])
        ret = _returns([-0.01, 0.02, -0.03, 0.01, -0.02])
        w = combined_weights(t0, t1, bars, ret).to_numpy()
        assert np.all(w >= 0.0)
