"""Tests for features.cv.embargo -- apply_embargo().

Reference: Lopez de Prado (2018) S7.4.2.
"""

from __future__ import annotations

import numpy as np

from features.cv.embargo import apply_embargo


class TestApplyEmbargo:
    """Core embargo logic."""

    def test_embargo_removes_indices_after_test_end(self) -> None:
        """Indices immediately after test_end are excluded."""
        # n=10, test ends at index 4, embargo_size=2
        train = np.array([5, 6, 7, 8, 9], dtype=np.intp)
        result = apply_embargo(train, [4], embargo_size=2, n_total=10)
        # indices 5, 6 are in embargo zone [5, 6]
        np.testing.assert_array_equal(result, [7, 8, 9])

    def test_embargo_size_zero_keeps_all(self) -> None:
        train = np.array([5, 6, 7], dtype=np.intp)
        result = apply_embargo(train, [4], embargo_size=0, n_total=10)
        np.testing.assert_array_equal(result, [5, 6, 7])

    def test_embargo_clamps_to_n_total(self) -> None:
        """Embargo zone doesn't overflow past the last index."""
        # n=10, test ends at index 8, embargo_size=5
        train = np.array([9], dtype=np.intp)
        result = apply_embargo(train, [8], embargo_size=5, n_total=10)
        # embargo zone: [9, min(13, 9)] = [9, 9] -> index 9 removed
        np.testing.assert_array_equal(result, np.array([], dtype=np.intp))

    def test_multiple_test_groups_embargo(self) -> None:
        """Embargo applied after each test group independently."""
        # n=20, test ends at 4 and 14, embargo_size=2
        train = np.array([5, 6, 7, 15, 16, 17], dtype=np.intp)
        result = apply_embargo(train, [4, 14], embargo_size=2, n_total=20)
        # embargo after 4: [5, 6]; after 14: [15, 16]
        np.testing.assert_array_equal(result, [7, 17])

    def test_empty_train(self) -> None:
        train = np.array([], dtype=np.intp)
        result = apply_embargo(train, [4], embargo_size=2, n_total=10)
        assert len(result) == 0

    def test_empty_test_end_indices(self) -> None:
        train = np.array([0, 1, 2], dtype=np.intp)
        result = apply_embargo(train, [], embargo_size=2, n_total=10)
        np.testing.assert_array_equal(result, [0, 1, 2])

    def test_embargo_of_one(self) -> None:
        """embargo_size=1 excludes exactly one bar."""
        train = np.array([5, 6, 7], dtype=np.intp)
        result = apply_embargo(train, [4], embargo_size=1, n_total=10)
        np.testing.assert_array_equal(result, [6, 7])
