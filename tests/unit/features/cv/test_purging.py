"""Tests for features.cv.purging -- purge_train_indices().

Reference: Lopez de Prado (2018) S7.4.1.
"""

from __future__ import annotations

import numpy as np

from features.cv.purging import purge_train_indices


def _make_t1_ns(values: list[int]) -> np.ndarray:
    """Create int64 nanosecond timestamps from simple ints."""
    return np.array(values, dtype=np.int64)


class TestPurgeTrainIndices:
    """Core purging logic."""

    def test_no_overlap_keeps_all(self) -> None:
        """Train samples with t1 strictly before test start are kept."""
        train = np.array([0, 1, 2], dtype=np.intp)
        t1 = _make_t1_ns([10, 20, 30, 100, 110, 120])
        # Test interval is [100, 120]
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(120))])
        np.testing.assert_array_equal(result, [0, 1, 2])

    def test_overlap_purges_sample(self) -> None:
        """Train sample whose t1 falls inside test interval is purged."""
        train = np.array([0, 1, 2], dtype=np.intp)
        # t1[1] = 105 falls inside test interval [100, 110]
        t1 = _make_t1_ns([10, 105, 200, 100, 110])
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(110))])
        np.testing.assert_array_equal(result, [0, 2])

    def test_t1_exactly_at_test_start_is_purged(self) -> None:
        """t1[i] == test_start is inside [start, end] inclusive."""
        train = np.array([0], dtype=np.intp)
        t1 = _make_t1_ns([100, 200])
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(200))])
        np.testing.assert_array_equal(result, np.array([], dtype=np.intp))

    def test_t1_exactly_at_test_end_is_purged(self) -> None:
        """t1[i] == test_end is inside [start, end] inclusive."""
        train = np.array([0], dtype=np.intp)
        t1 = _make_t1_ns([200, 300])
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(200))])
        np.testing.assert_array_equal(result, np.array([], dtype=np.intp))

    def test_t1_strictly_after_test_end_kept(self) -> None:
        """t1[i] > test_end is not in interval -- kept (subject to embargo)."""
        train = np.array([0], dtype=np.intp)
        t1 = _make_t1_ns([201, 300])
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(200))])
        np.testing.assert_array_equal(result, [0])

    def test_multiple_disjoint_test_intervals(self) -> None:
        """Non-contiguous test intervals each purge independently."""
        train = np.array([1, 3, 5], dtype=np.intp)
        #                   idx: 0   1    2   3    4   5    6
        t1 = _make_t1_ns([10, 105, 200, 305, 400, 500, 600])
        # Two disjoint test intervals: [100, 110] and [300, 310]
        intervals = [(np.int64(100), np.int64(110)), (np.int64(300), np.int64(310))]
        result = purge_train_indices(train, t1, intervals)
        # idx 1: t1=105 in [100,110] -> purged
        # idx 3: t1=305 in [300,310] -> purged
        # idx 5: t1=500 -> kept
        np.testing.assert_array_equal(result, [5])

    def test_empty_train_returns_empty(self) -> None:
        train = np.array([], dtype=np.intp)
        t1 = _make_t1_ns([100, 200])
        result = purge_train_indices(train, t1, [(np.int64(100), np.int64(200))])
        assert len(result) == 0

    def test_empty_intervals_keeps_all(self) -> None:
        train = np.array([0, 1], dtype=np.intp)
        t1 = _make_t1_ns([100, 200])
        result = purge_train_indices(train, t1, [])
        np.testing.assert_array_equal(result, [0, 1])

    def test_all_purged(self) -> None:
        """All train samples have t1 inside test interval."""
        train = np.array([0, 1, 2], dtype=np.intp)
        t1 = _make_t1_ns([100, 105, 110])
        result = purge_train_indices(train, t1, [(np.int64(99), np.int64(111))])
        assert len(result) == 0

    def test_purge_is_read_only_on_t1(self) -> None:
        """t1 array must not be mutated."""
        train = np.array([0, 1], dtype=np.intp)
        t1 = _make_t1_ns([100, 200])
        t1_copy = t1.copy()
        purge_train_indices(train, t1, [(np.int64(100), np.int64(150))])
        np.testing.assert_array_equal(t1, t1_copy)
