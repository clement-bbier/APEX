"""Tests for features.cv.cpcv -- CombinatoriallyPurgedKFold.

Covers constructor validation, split counts, partition invariants,
purging correctness, embargo correctness, determinism, edge cases,
and the critical leakage-elimination integration test.

References:
    Lopez de Prado (2018) Ch. 7.
    Bailey et al. (2017) for downstream PBO usage.
"""

from __future__ import annotations

from math import comb

import numpy as np
import polars as pl
import pytest

from features.cv.cpcv import CombinatoriallyPurgedKFold

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_timestamps(n: int, start: int = 0) -> np.ndarray:
    """Create monotonically increasing datetime64[ns] timestamps."""
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    offsets = np.arange(start, start + n, dtype="timedelta64[h]").astype("timedelta64[ns]")
    return base + offsets


def _make_t1_with_horizon(timestamps: np.ndarray, horizon: int) -> np.ndarray:
    """Create t1 where t1[i] = timestamps[min(i + horizon, n - 1)].

    Simulates a label that looks ``horizon`` bars into the future.
    """
    n = len(timestamps)
    indices = np.minimum(np.arange(n) + horizon, n - 1)
    return timestamps[indices]


# ---------------------------------------------------------------------------
# Constructor validation (D030)
# ---------------------------------------------------------------------------


class TestCPCVConstructor:
    """Constructor validation per D030."""

    def test_defaults(self) -> None:
        cv = CombinatoriallyPurgedKFold()
        assert cv.n_splits == 6
        assert cv.n_test_splits == 2
        assert cv.embargo_pct == 0.01

    def test_n_splits_below_2_raises(self) -> None:
        with pytest.raises(ValueError, match="n_splits must be >= 2"):
            CombinatoriallyPurgedKFold(n_splits=1)

    def test_n_test_splits_below_1_raises(self) -> None:
        with pytest.raises(ValueError, match="n_test_splits must be >= 1"):
            CombinatoriallyPurgedKFold(n_test_splits=0)

    def test_n_test_splits_ge_n_splits_raises(self) -> None:
        with pytest.raises(ValueError, match="must be < n_splits"):
            CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=4)

    def test_embargo_pct_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="embargo_pct must be in"):
            CombinatoriallyPurgedKFold(embargo_pct=-0.1)

    def test_embargo_pct_ge_1_raises(self) -> None:
        with pytest.raises(ValueError, match="embargo_pct must be in"):
            CombinatoriallyPurgedKFold(embargo_pct=1.0)


# ---------------------------------------------------------------------------
# Split count
# ---------------------------------------------------------------------------


class TestSplitCount:
    """get_n_splits() and actual yield count match C(N, k)."""

    @pytest.mark.parametrize(
        ("n_splits", "n_test_splits", "expected"),
        [
            (6, 2, 15),
            (10, 3, 120),
            (5, 1, 5),
            (4, 3, 4),
        ],
    )
    def test_get_n_splits(self, n_splits: int, n_test_splits: int, expected: int) -> None:
        cv = CombinatoriallyPurgedKFold(
            n_splits=n_splits,
            n_test_splits=n_test_splits,
            embargo_pct=0.0,
        )
        assert cv.get_n_splits() == expected

    def test_actual_yield_count_matches(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.0)
        n = 60
        x = np.zeros(n)
        t1 = _make_timestamps(n)
        splits = list(cv.split(x, t1))
        assert len(splits) == cv.get_n_splits()

    def test_c10_3_yield_count(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=10, n_test_splits=3, embargo_pct=0.0)
        n = 100
        x = np.zeros(n)
        t1 = _make_timestamps(n)
        splits = list(cv.split(x, t1))
        assert len(splits) == comb(10, 3)

    def test_degenerate_k_1_equals_n(self) -> None:
        """C(N, 1) = N -- degenerates to walk-forward-like splits."""
        cv = CombinatoriallyPurgedKFold(n_splits=5, n_test_splits=1, embargo_pct=0.0)
        n = 50
        x = np.zeros(n)
        t1 = _make_timestamps(n)
        splits = list(cv.split(x, t1))
        assert len(splits) == 5


# ---------------------------------------------------------------------------
# Partition invariants
# ---------------------------------------------------------------------------


class TestPartitionInvariants:
    """For every split: train and test are disjoint, valid, unique."""

    @pytest.fixture
    def cv_and_data(self) -> tuple[CombinatoriallyPurgedKFold, np.ndarray, np.ndarray]:
        cv = CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.0)
        n = 60
        x = np.zeros(n)
        t1 = _make_timestamps(n)
        return cv, x, t1

    def test_train_test_disjoint(
        self, cv_and_data: tuple[CombinatoriallyPurgedKFold, np.ndarray, np.ndarray]
    ) -> None:
        cv, x, t1 = cv_and_data
        for train_idx, test_idx in cv.split(x, t1):
            assert len(np.intersect1d(train_idx, test_idx)) == 0

    def test_all_indices_in_valid_range(
        self, cv_and_data: tuple[CombinatoriallyPurgedKFold, np.ndarray, np.ndarray]
    ) -> None:
        cv, x, t1 = cv_and_data
        n = len(x)
        for train_idx, test_idx in cv.split(x, t1):
            assert np.all(train_idx >= 0)
            assert np.all(train_idx < n)
            assert np.all(test_idx >= 0)
            assert np.all(test_idx < n)

    def test_no_duplicate_indices(
        self, cv_and_data: tuple[CombinatoriallyPurgedKFold, np.ndarray, np.ndarray]
    ) -> None:
        cv, x, t1 = cv_and_data
        for train_idx, test_idx in cv.split(x, t1):
            assert len(train_idx) == len(set(train_idx.tolist()))
            assert len(test_idx) == len(set(test_idx.tolist()))


# ---------------------------------------------------------------------------
# Purging correctness
# ---------------------------------------------------------------------------


class TestPurging:
    """Purging removes training samples with label leakage."""

    def test_sample_with_t1_inside_test_is_purged(self) -> None:
        """If t1[i] falls inside a test group, i must not be in train."""
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        n = 20
        timestamps = _make_timestamps(n)
        # Label horizon of 5: t1[i] = timestamps[i + 5]
        t1 = _make_t1_with_horizon(timestamps, horizon=5)
        x = np.zeros(n)

        for train_idx, test_idx in cv.split(x, t1):
            # Purging interval is based on t1 values at group boundaries
            t1_test_start = t1[test_idx[0]]
            t1_test_end = t1[test_idx[-1]]
            for i in train_idx:
                # t1[i] must NOT fall in the t1-based test interval
                assert not (t1_test_start <= t1[i] <= t1_test_end), (
                    f"Train index {i} has t1={t1[i]} inside test [{t1_test_start}, {t1_test_end}]"
                )

    def test_no_purging_when_labels_dont_overlap(self) -> None:
        """With t1[i] = timestamps[i] (no look-ahead), no purging occurs."""
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        n = 20
        timestamps = _make_timestamps(n)
        t1 = timestamps.copy()  # t1[i] = timestamps[i], no forward look
        x = np.zeros(n)

        for train_idx, test_idx in cv.split(x, t1):
            # Without overlap, train + test = all indices
            assert len(train_idx) + len(test_idx) == n

    def test_purging_with_large_horizon(self) -> None:
        """Larger label horizon should purge more training samples."""
        n = 60
        timestamps = _make_timestamps(n)
        x = np.zeros(n)

        purged_counts: list[int] = []
        for horizon in [0, 5, 15]:
            t1 = _make_t1_with_horizon(timestamps, horizon)
            cv = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)
            total_purged = 0
            for train_idx, test_idx in cv.split(x, t1):
                expected_train_size = n - len(test_idx)
                total_purged += expected_train_size - len(train_idx)
            purged_counts.append(total_purged)

        # Monotonically increasing purge count
        assert purged_counts[0] <= purged_counts[1] <= purged_counts[2]
        # With horizon=0, no purging
        assert purged_counts[0] == 0

    def test_non_contiguous_test_groups_purge_correctly(self) -> None:
        """Combinatorial split with groups 0 and 2 (skipping 1).

        For non-contiguous test groups, purging checks each group's
        interval independently.  A train sample in the gap is only
        purged if its t1 overlaps one of the individual group intervals.
        """
        cv = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=2, embargo_pct=0.0)
        n = 30
        timestamps = _make_timestamps(n)
        t1 = _make_t1_with_horizon(timestamps, horizon=3)
        x = np.zeros(n)

        for train_idx, test_idx in cv.split(x, t1):
            # Identify individual contiguous test groups
            test_sorted = np.sort(test_idx)
            group_intervals: list[tuple[np.datetime64, np.datetime64]] = []
            g_start = test_sorted[0]
            for k in range(1, len(test_sorted)):
                if test_sorted[k] != test_sorted[k - 1] + 1:
                    group_intervals.append((t1[g_start], t1[test_sorted[k - 1]]))
                    g_start = test_sorted[k]
            group_intervals.append((t1[g_start], t1[test_sorted[-1]]))

            # Each train sample's t1 must not fall in any group interval
            for i in train_idx:
                for g_min, g_max in group_intervals:
                    assert not (g_min <= t1[i] <= g_max), (
                        f"Train index {i} has t1 inside test group [{g_min}, {g_max}]"
                    )


# ---------------------------------------------------------------------------
# Embargo correctness
# ---------------------------------------------------------------------------


class TestEmbargo:
    """Embargo removes samples after test group boundaries."""

    def test_embargo_excludes_correct_bars(self) -> None:
        """With embargo_pct=0.1 on n=100, embargo=10 bars after each test end."""
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.1)
        n = 100
        timestamps = _make_timestamps(n)
        t1 = timestamps.copy()  # No label overlap
        x = np.zeros(n)

        splits = list(cv.split(x, t1))
        # First split: test=group0=[0,50), train initially=[50,100)
        # Embargo after test end (idx 49): exclude [50, 59]
        train_0, _test_0 = splits[0]
        assert 50 not in train_0
        assert 59 not in train_0
        assert 60 in train_0

    def test_embargo_zero_no_exclusion(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        n = 20
        timestamps = _make_timestamps(n)
        t1 = timestamps.copy()
        x = np.zeros(n)

        for train_idx, test_idx in cv.split(x, t1):
            # No purging, no embargo -> train + test = n
            assert len(train_idx) + len(test_idx) == n

    def test_embargo_at_series_end_no_overflow(self) -> None:
        """When test group is the last group, embargo doesn't overflow."""
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.1)
        n = 100
        timestamps = _make_timestamps(n)
        t1 = timestamps.copy()
        x = np.zeros(n)

        splits = list(cv.split(x, t1))
        # Second split: test=group1=[50,100), no train after test
        train_1, _test_1 = splits[1]
        # All train indices should be valid
        assert np.all(train_1 >= 0)
        assert np.all(train_1 < n)

    def test_embargo_with_multiple_test_groups(self) -> None:
        """Embargo applied after each test group boundary."""
        cv = CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.05)
        n = 100
        timestamps = _make_timestamps(n)
        t1 = timestamps.copy()
        x = np.zeros(n)

        # embargo_size = 0.05 * 100 = 5 bars
        for train_idx, test_idx in cv.split(x, t1):
            train_set = set(train_idx.tolist())
            test_sorted = np.sort(test_idx)

            # Find test group boundaries (discontinuities)
            diffs = np.diff(test_sorted)
            group_ends = [int(test_sorted[0])]
            for k, d in enumerate(diffs):
                if d > 1:
                    group_ends.append(int(test_sorted[k]))
                    group_ends.append(int(test_sorted[k + 1]))
            group_ends.append(int(test_sorted[-1]))

            # Check embargo after each test group end
            for end_idx in group_ends[1::2]:  # Every second is group end
                for offset in range(1, 6):
                    embargo_idx = end_idx + offset
                    if embargo_idx < n and embargo_idx not in set(test_idx.tolist()):
                        assert embargo_idx not in train_set, (
                            f"Index {embargo_idx} should be embargoed "
                            f"(test group ends at {end_idx})"
                        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same inputs produce identical splits in identical order."""

    def test_two_calls_same_result(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.01)
        n = 40
        x = np.zeros(n)
        t1 = _make_timestamps(n)

        splits_a = [(tr.copy(), te.copy()) for tr, te in cv.split(x, t1)]
        splits_b = [(tr.copy(), te.copy()) for tr, te in cv.split(x, t1)]

        assert len(splits_a) == len(splits_b)
        for (tr_a, te_a), (tr_b, te_b) in zip(splits_a, splits_b, strict=True):
            np.testing.assert_array_equal(tr_a, tr_b)
            np.testing.assert_array_equal(te_a, te_b)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_n_splits_gt_n_raises(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=10, n_test_splits=2, embargo_pct=0.0)
        x = np.zeros(5)
        t1 = _make_timestamps(5)
        with pytest.raises(ValueError, match="n_samples=5 is less than n_splits=10"):
            list(cv.split(x, t1))

    def test_t1_length_mismatch_raises(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        x = np.zeros(10)
        t1 = _make_timestamps(8)
        with pytest.raises(ValueError, match="len\\(t1\\)=8 != len\\(X\\)=10"):
            list(cv.split(x, t1))

    def test_t1_not_monotonic_raises(self) -> None:
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        x = np.zeros(4)
        t1 = _make_timestamps(4)
        # Swap two values to break monotonicity
        t1_bad = t1.copy()
        t1_bad[1], t1_bad[2] = t1_bad[2], t1_bad[1]
        with pytest.raises(ValueError, match="monotonically non-decreasing"):
            list(cv.split(x, t1_bad))

    def test_minimum_viable_split(self) -> None:
        """n=2, n_splits=2, n_test_splits=1 produces 2 valid splits."""
        cv = CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)
        x = np.zeros(2)
        t1 = _make_timestamps(2)
        splits = list(cv.split(x, t1))
        assert len(splits) == 2
        for train_idx, test_idx in splits:
            assert len(test_idx) == 1
            assert len(train_idx) >= 1

    def test_polars_dataframe_input(self) -> None:
        """x can be a polars DataFrame."""
        cv = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)
        n = 30
        x = pl.DataFrame({"a": range(n), "b": range(n)})
        t1 = _make_timestamps(n)
        splits = list(cv.split(x, t1))
        assert len(splits) == 3

    def test_polars_series_t1_input(self) -> None:
        """t1 can be a polars Series of datetimes."""
        cv = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)
        n = 30
        x = np.zeros(n)
        ts = _make_timestamps(n)
        t1 = pl.Series("t1", ts)
        splits = list(cv.split(x, t1))
        assert len(splits) == 3


# ---------------------------------------------------------------------------
# Conditioned on D028 (forecast-like classification)
# ---------------------------------------------------------------------------


class TestConditionedOnD028:
    """For forecast-like labels where t1[i] = i + horizon."""

    def test_purging_removes_horizon_leaking_samples(self) -> None:
        """Samples whose label end time crosses into the test set are purged."""
        n = 60
        timestamps = _make_timestamps(n)
        horizon = 10
        t1 = _make_t1_with_horizon(timestamps, horizon)

        cv = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)
        x = np.zeros(n)

        for train_idx, test_idx in cv.split(x, t1):
            # Purge interval uses t1 values at group boundaries
            t1_test_min = t1[test_idx[0]]
            t1_test_max = t1[test_idx[-1]]
            for i in train_idx:
                assert not (t1_test_min <= t1[i] <= t1_test_max)


# ---------------------------------------------------------------------------
# Integration: leakage characterization test
# ---------------------------------------------------------------------------


class TestLeakageCharacterization:
    """THE critical test proving CPCV eliminates label leakage.

    Synthetic dataset with strongly autocorrelated features (random walk)
    and overlapping labels (y[i] depends on data at i + horizon).
    Without CPCV, a classifier exploits temporal leakage from overlapping
    train/test samples.  With CPCV + purging, this leakage is eliminated.
    """

    @staticmethod
    def _build_leaky_dataset(
        n: int, horizon: int, seed: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Build autocorrelated dataset with overlapping label leakage.

        Features are cumulative sums (random walk), making nearby
        observations highly correlated.  The label y[i] is the sign of
        the price move from i to i + horizon.  The features at time i
        contain information about prices at i + horizon through
        autocorrelation, creating exploitable leakage.
        """
        rng = np.random.default_rng(seed)
        # Random walk features -- strongly autocorrelated
        increments = rng.standard_normal((n, 5))
        x = np.cumsum(increments, axis=0)
        timestamps = _make_timestamps(n)

        # Forward return label: 1 if price goes up over horizon, else 0
        # This creates overlapping labels because y[i] uses data at i+horizon
        y = np.zeros(n, dtype=np.int64)
        for i in range(n - horizon):
            y[i] = 1 if x[i + horizon, 0] > x[i, 0] else 0

        t1 = _make_t1_with_horizon(timestamps, horizon)
        return x, y, timestamps, t1

    def test_random_kfold_shows_leakage(self) -> None:
        """Without purging, random shuffled K-fold exploits autocorrelation."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import KFold

        n, horizon, seed = 1000, 20, 42
        x, y, _, _ = self._build_leaky_dataset(n, horizon, seed)

        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        accuracies: list[float] = []
        for train_idx, test_idx in kf.split(x):
            clf = RandomForestClassifier(n_estimators=100, random_state=seed)
            clf.fit(x[train_idx], y[train_idx])
            acc = float(np.mean(clf.predict(x[test_idx]) == y[test_idx]))
            accuracies.append(acc)

        mean_acc = float(np.mean(accuracies))
        # Shuffled K-fold on autocorrelated data should exploit leakage
        assert mean_acc > 0.55, f"Expected leaky K-fold accuracy > 0.55, got {mean_acc:.3f}"

    def test_cpcv_eliminates_leakage(self) -> None:
        """With CPCV + purging + embargo, accuracy drops toward chance."""
        from sklearn.ensemble import RandomForestClassifier

        n, horizon, seed = 1000, 20, 42
        x, y, _timestamps, t1 = self._build_leaky_dataset(n, horizon, seed)

        cv = CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.02)

        accuracies: list[float] = []
        for train_idx, test_idx in cv.split(x, t1):
            if len(train_idx) < 10 or len(test_idx) < 5:
                continue
            clf = RandomForestClassifier(n_estimators=100, random_state=seed)
            clf.fit(x[train_idx], y[train_idx])
            acc = float(np.mean(clf.predict(x[test_idx]) == y[test_idx]))
            accuracies.append(acc)

        mean_acc = float(np.mean(accuracies))
        # CPCV should bring accuracy close to chance (0.5)
        assert mean_acc < 0.62, (
            f"CPCV accuracy should be near chance (<0.62), got {mean_acc:.3f}. "
            f"Purging may not be working correctly."
        )

    def test_cpcv_accuracy_lower_than_kfold(self) -> None:
        """CPCV accuracy must be strictly lower than random K-fold on leaky data."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import KFold

        n, horizon, seed = 1000, 20, 42
        x, y, _timestamps, t1 = self._build_leaky_dataset(n, horizon, seed)

        # Random K-fold accuracy
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        kf_accs: list[float] = []
        for train_idx, test_idx in kf.split(x):
            clf = RandomForestClassifier(n_estimators=100, random_state=seed)
            clf.fit(x[train_idx], y[train_idx])
            kf_accs.append(float(np.mean(clf.predict(x[test_idx]) == y[test_idx])))

        # CPCV accuracy
        cv = CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.02)
        cpcv_accs: list[float] = []
        for train_idx, test_idx in cv.split(x, t1):
            if len(train_idx) < 10 or len(test_idx) < 5:
                continue
            clf = RandomForestClassifier(n_estimators=100, random_state=seed)
            clf.fit(x[train_idx], y[train_idx])
            cpcv_accs.append(float(np.mean(clf.predict(x[test_idx]) == y[test_idx])))

        assert float(np.mean(cpcv_accs)) < float(np.mean(kf_accs)), (
            f"CPCV acc ({np.mean(cpcv_accs):.3f}) should be < K-fold acc ({np.mean(kf_accs):.3f})"
        )
