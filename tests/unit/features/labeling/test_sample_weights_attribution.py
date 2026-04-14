"""Tests for features.labeling.sample_weights - return attribution r_i.

Groups:

A. Core semantics (|sum(ret/c)| under overlap vs disjoint)
B. Zero-return corner cases
C. Fail-loud validation (NaN / Inf returns, length mismatch, c_t == 0)
D. Anti-leakage property (shuffling log returns strictly after max(t1) does
   not change any r_i). This is the critical invariant of ADR-0005 D2.
E. Dtype / empty input contract
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from features.labeling.sample_weights import return_attribution_weights

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


# --------------------------- A. Core semantics ------------------------


class TestReturnAttributionCore:
    def test_single_span_equals_sum_of_returns(self) -> None:
        """With c_t == 1 everywhere in the span, r_i == |sum(ret_t)|."""
        bars = _bars(5)
        t0 = _times([1])
        t1 = _times([3])
        ret = _returns([0.0, 0.01, 0.02, 0.03, 0.0])
        r = return_attribution_weights(t0, t1, bars, ret).to_list()
        # Sum over bars 1,2,3 = 0.06
        assert r == pytest.approx([0.06])

    def test_is_absolute_value_of_sum(self) -> None:
        bars = _bars(4)
        t0 = _times([0])
        t1 = _times([3])
        ret = _returns([-0.02, -0.03, -0.01, -0.01])  # all negative
        r = return_attribution_weights(t0, t1, bars, ret).to_list()
        assert r == pytest.approx([0.07])

    def test_concurrency_scales_attribution(self) -> None:
        """Two identical spans cover c == 2; each gets half the return."""
        bars = _bars(4)
        t0 = _times([1, 1])
        t1 = _times([2, 2])
        ret = _returns([0.0, 0.04, 0.06, 0.0])
        # ret/c on [1,2] = [0.02, 0.03]; per-sample sum = 0.05.
        r = return_attribution_weights(t0, t1, bars, ret).to_list()
        assert r == pytest.approx([0.05, 0.05])


# --------------------------- B. Zero-return corner cases --------------


class TestReturnAttributionZero:
    def test_all_zero_returns(self) -> None:
        bars = _bars(4)
        t0 = _times([0, 1])
        t1 = _times([2, 3])
        ret = _returns([0.0, 0.0, 0.0, 0.0])
        r = return_attribution_weights(t0, t1, bars, ret).to_list()
        assert r == pytest.approx([0.0, 0.0])

    def test_positive_and_negative_returns_cancel(self) -> None:
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([2])
        ret = _returns([0.05, -0.03, -0.02])  # sums to 0
        r = return_attribution_weights(t0, t1, bars, ret).to_list()
        assert r == pytest.approx([0.0], abs=1e-12)


# --------------------------- C. Fail-loud validation ------------------


class TestReturnAttributionValidation:
    def test_nan_return_raises(self) -> None:
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([2])
        ret = _returns([0.01, float("nan"), 0.02])
        with pytest.raises(ValueError, match="non-finite"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_inf_return_raises(self) -> None:
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([2])
        ret = _returns([0.01, float("inf"), 0.02])
        with pytest.raises(ValueError, match="non-finite"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_length_mismatch_raises(self) -> None:
        bars = _bars(4)
        t0 = _times([0])
        t1 = _times([1])
        ret = _returns([0.01, 0.02])  # wrong length
        with pytest.raises(ValueError, match="length"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_null_returns_raise(self) -> None:
        bars = _bars(3)
        t0 = _times([0])
        t1 = _times([2])
        ret = pl.Series(values=[0.01, None, 0.02], dtype=pl.Float64)
        with pytest.raises(ValueError, match="null"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_empty_bars_nonempty_events_raises(self) -> None:
        """Fail-loud when we have events but no bar series to anchor them."""
        bars = pl.Series(values=[], dtype=pl.Datetime("us", "UTC"))
        t0 = _times([0])
        t1 = _times([0])
        ret = pl.Series(values=[], dtype=pl.Float64)
        with pytest.raises(ValueError, match="bars is empty"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_fully_empty_inputs_return_empty(self) -> None:
        """Empty bars + empty events + empty returns must return an empty series."""
        bars = pl.Series(values=[], dtype=pl.Datetime("us", "UTC"))
        t0 = _times([])
        t1 = _times([])
        ret = pl.Series(values=[], dtype=pl.Float64)
        r = return_attribution_weights(t0, t1, bars, ret)
        assert len(r) == 0
        assert r.dtype == pl.Float64


# --------------------------- D. Anti-leakage property -----------------


@st.composite
def _event_and_bars(draw: st.DrawFn) -> tuple[pl.Series, pl.Series, pl.Series, pl.Series, int]:
    """Generate (t0, t1, bars, log_returns, tail_start_index) for anti-leakage.

    tail_start_index marks the first bar strictly after max(t1); bars at or
    past this index must have no influence on any r_i.
    """
    n_bars = draw(st.integers(min_value=5, max_value=40))
    n_samples = draw(st.integers(min_value=1, max_value=8))
    starts = draw(
        st.lists(
            st.integers(min_value=0, max_value=n_bars - 2),
            min_size=n_samples,
            max_size=n_samples,
        )
    )
    # Ensure t1_i >= t0_i and t1_i fits inside bars.
    lengths = draw(
        st.lists(
            st.integers(min_value=0, max_value=max(1, n_bars // 3)),
            min_size=n_samples,
            max_size=n_samples,
        )
    )
    t0_idx = sorted(starts)  # sort just for readability; not required
    t1_idx = [min(s + ln, n_bars - 1) for s, ln in zip(t0_idx, lengths, strict=True)]

    bars = _bars(n_bars)
    t0 = _times(t0_idx)
    t1 = _times(t1_idx)

    rets = draw(
        st.lists(
            st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False),
            min_size=n_bars,
            max_size=n_bars,
        )
    )
    log_returns = _returns(rets)
    tail_start = max(t1_idx) + 1
    return t0, t1, bars, log_returns, tail_start


class TestAntiLeakage:
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(payload=_event_and_bars())
    def test_shuffling_returns_after_max_t1_preserves_weights(
        self,
        payload: tuple[pl.Series, pl.Series, pl.Series, pl.Series, int],
    ) -> None:
        """Weights must depend only on returns inside [min(t0), max(t1)].

        ADR-0005 D2 forbids future information leakage. We enforce it by
        permuting the slice of log_returns strictly AFTER max(t1) and
        verifying every r_i is unchanged.
        """
        t0, t1, bars, log_returns, tail_start = payload
        before = return_attribution_weights(t0, t1, bars, log_returns).to_numpy()

        if tail_start >= len(bars):
            # Tail is empty; nothing to shuffle. Any permutation equals identity.
            return

        rng = np.random.default_rng(0)
        arr = log_returns.to_numpy().copy()
        tail = arr[tail_start:].copy()
        rng.shuffle(tail)
        arr[tail_start:] = tail
        shuffled = pl.Series(values=arr, dtype=pl.Float64)

        after = return_attribution_weights(t0, t1, bars, shuffled).to_numpy()
        np.testing.assert_allclose(before, after, atol=1e-12)


# --------------------------- E. Empty / dtype -------------------------


class TestReturnAttributionEdgeCases:
    def test_empty_events_returns_empty_series(self) -> None:
        bars = _bars(3)
        ret = _returns([0.0, 0.0, 0.0])
        t0 = _times([])
        t1 = _times([])
        r = return_attribution_weights(t0, t1, bars, ret)
        assert len(r) == 0
        assert r.dtype == pl.Float64

    def test_result_is_non_negative(self) -> None:
        bars = _bars(5)
        t0 = _times([0, 2])
        t1 = _times([3, 4])
        ret = _returns([-0.02, -0.01, -0.03, -0.04, -0.01])
        r = return_attribution_weights(t0, t1, bars, ret).to_numpy()
        assert np.all(r >= 0.0)

    def test_empty_t0_nonempty_t1_raises(self) -> None:
        """Regression guard for Copilot review on PR #139.

        Mismatched ``t0`` / ``t1`` lengths must fail-loud even when the
        empty-input fast path is otherwise active.
        """
        bars = _bars(3)
        ret = _returns([0.0, 0.0, 0.0])
        t0 = _times([])
        t1 = _times([1])
        with pytest.raises(ValueError, match="different lengths"):
            return_attribution_weights(t0, t1, bars, ret)

    def test_nonempty_t0_empty_t1_raises(self) -> None:
        bars = _bars(3)
        ret = _returns([0.0, 0.0, 0.0])
        t0 = _times([1])
        t1 = _times([])
        with pytest.raises(ValueError, match="different lengths"):
            return_attribution_weights(t0, t1, bars, ret)
