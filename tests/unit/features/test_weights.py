"""Tests for features.weights — SampleWeighter.

Includes Hypothesis property-based tests (1000 examples) as required
by PHASE_3_SPEC Section 2.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from features.weights import SampleWeighter

# ── Deterministic unit tests ────────────────────────────��─────────────


class TestUniquenessWeights:
    """SampleWeighter.uniqueness_weights edge cases."""

    def test_empty_inputs(self) -> None:
        w = SampleWeighter()
        result = w.uniqueness_weights([], [])
        assert len(result) == 0

    def test_single_sample(self) -> None:
        w = SampleWeighter()
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = t0 + timedelta(hours=1)
        result = w.uniqueness_weights([t0], [t1])
        assert len(result) == 1
        assert result[0] == 1.0

    def test_non_overlapping_samples(self) -> None:
        w = SampleWeighter()
        t = [datetime(2024, 1, 1, hour=h, tzinfo=UTC) for h in range(0, 6)]
        entries = [t[0], t[2], t[4]]
        exits = [t[1], t[3], t[5]]
        result = w.uniqueness_weights(entries, exits)
        np.testing.assert_array_equal(result, [1.0, 1.0, 1.0])

    def test_fully_overlapping_samples(self) -> None:
        w = SampleWeighter()
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = t0 + timedelta(hours=1)
        entries = [t0, t0, t0]
        exits = [t1, t1, t1]
        result = w.uniqueness_weights(entries, exits)
        # All 3 samples perfectly overlap => each has uniqueness 1/3
        expected = 1.0 / 3.0
        np.testing.assert_allclose(result, [expected, expected, expected])

    def test_mismatched_lengths_raises(self) -> None:
        w = SampleWeighter()
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="same length"):
            w.uniqueness_weights([t0], [])

    def test_return_attribution_raises(self) -> None:
        w = SampleWeighter()
        with pytest.raises(NotImplementedError, match="deferred"):
            w.return_attribution_weights([], [], np.array([]))


# ── Hypothesis property-based tests ──────────────────────────────────


def _make_datetimes(n: int, base: datetime | None = None) -> list[datetime]:
    """Generate n sequential datetimes."""
    base = base or datetime(2024, 1, 1, tzinfo=UTC)
    return [base + timedelta(hours=i) for i in range(n)]


@given(n=st.integers(min_value=1, max_value=50))
@settings(max_examples=1000)
def test_weights_non_negative(n: int) -> None:
    """All uniqueness weights must be >= 0."""
    w = SampleWeighter()
    times = _make_datetimes(n * 2)
    entries = times[:n]
    exits = times[n : n * 2]
    # Ensure exit >= entry
    exits_fixed = [max(entries[i], exits[i]) for i in range(n)]
    result = w.uniqueness_weights(entries, exits_fixed)
    assert np.all(result >= 0)


@given(n=st.integers(min_value=1, max_value=50))
@settings(max_examples=1000)
def test_weights_sum_positive(n: int) -> None:
    """Sum of weights must be > 0 for non-empty inputs."""
    w = SampleWeighter()
    times = _make_datetimes(n * 2)
    entries = times[:n]
    exits = [entries[i] + timedelta(hours=1) for i in range(n)]
    result = w.uniqueness_weights(entries, exits)
    assert np.sum(result) > 0


@given(n=st.integers(min_value=2, max_value=20))
@settings(max_examples=1000)
def test_identical_labels_same_weight(n: int) -> None:
    """Identical (fully overlapping) labels get identical weights."""
    w = SampleWeighter()
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    entries = [t0] * n
    exits = [t1] * n
    result = w.uniqueness_weights(entries, exits)
    # All weights should be equal
    assert np.allclose(result, result[0])
