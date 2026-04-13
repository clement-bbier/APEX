"""Combinatorial Purged Cross-Validation (CPCV) splitter.

Implements the CPCV methodology from López de Prado (2018) Ch. 7:

1. **Combinatorial splits**: partition *n* observations into *N* contiguous
   groups, then iterate over every combination of *k* groups as the test
   set — yielding C(N, k) train/test splits per run.
2. **Purging**: for each split, remove training samples whose label end
   time ``t1[i]`` falls within any test group's temporal range (§7.4.1).
3. **Embargo**: remove training samples within ``embargo_pct × n`` bars
   after each test group boundary (§7.4.2).

This eliminates three types of information leakage that make standard
K-fold invalid on financial time series:

- **Index leakage**: train ∩ test = ∅ by construction.
- **Label leakage**: purging removes samples whose outcome depends on
  test-period data.
- **Autocorrelation leakage**: embargo removes samples whose features
  are correlated with the test set via serial dependence.

API follows the scikit-learn cross-validator pattern:
``split(X, t1) -> Iterator[(train_idx, test_idx)]``.

References:
    López de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 7 S7.4-7.5.
    Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J.
    (2017). "The Probability of Backtest Overfitting." *Journal of
    Computational Finance*, 20(4), 39-69.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from math import comb
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from features.cv.embargo import apply_embargo
from features.cv.purging import purge_train_indices


class CombinatoriallyPurgedKFold:
    """Combinatorial Purged K-Fold cross-validator.

    Splits time-ordered observations into *N* groups, then takes every
    combination of *k* groups as test set (yielding ``C(N, k)`` splits
    per run).  For each split:

    1. Identify the *k* test groups (contiguous index ranges).
    2. **Purge**: remove training samples whose label end time ``t1[i]``
       falls inside any test group's time range.
    3. **Embargo**: remove training samples whose index falls within
       ``embargo_pct × n`` bars after each test group's last index.

    Yields ``(train_idx, test_idx)`` tuples of ``np.intp`` arrays.

    Parameters
    ----------
    n_splits : int
        Total number of groups to partition observations into.
        Default 6.
    n_test_splits : int
        Number of groups per test set.  Default 2 →
        ``C(6, 2) = 15`` splits.
    embargo_pct : float
        Embargo size as fraction of total observations.  Default 0.01
        (1%).  E.g. ``n=1000, embargo_pct=0.01`` → embargo of 10 bars
        after each test group's end.

    Raises
    ------
    ValueError
        If ``n_splits < 2``, ``n_test_splits < 1``,
        ``n_test_splits >= n_splits``, or ``embargo_pct`` not in
        ``[0, 1)``.

    Reference
    ---------
    López de Prado, M. (2018). *Advances in Financial Machine Learning*,
    Ch. 7 S7.4-7.5, Wiley.
    """

    def __init__(
        self,
        n_splits: int = 6,
        n_test_splits: int = 2,
        embargo_pct: float = 0.01,
    ) -> None:
        if n_splits < 2:
            msg = f"n_splits must be >= 2, got {n_splits}"
            raise ValueError(msg)
        if n_test_splits < 1:
            msg = f"n_test_splits must be >= 1, got {n_test_splits}"
            raise ValueError(msg)
        if n_test_splits >= n_splits:
            msg = f"n_test_splits ({n_test_splits}) must be < n_splits ({n_splits})"
            raise ValueError(msg)
        if not 0.0 <= embargo_pct < 1.0:
            msg = f"embargo_pct must be in [0, 1), got {embargo_pct}"
            raise ValueError(msg)

        self._n_splits = n_splits
        self._n_test_splits = n_test_splits
        self._embargo_pct = embargo_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_n_splits(self) -> int:
        """Return total number of ``(train, test)`` splits this will yield.

        Returns ``C(n_splits, n_test_splits)``.
        """
        return comb(self._n_splits, self._n_test_splits)

    def split(
        self,
        X: pl.DataFrame | npt.NDArray[Any],  # noqa: N803
        t1: pl.Series | npt.NDArray[np.datetime64],
        t0: pl.Series | npt.NDArray[np.datetime64] | None = None,
    ) -> Iterator[tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]]:
        """Yield ``(train_idx, test_idx)`` for each combinatorial split.

        Parameters
        ----------
        X:
            Feature matrix or array -- only ``len(X)`` matters; columns
            are ignored.
        t1:
            Array/Series of datetime values.  ``t1[i]`` is the time when
            the label for observation ``i`` is known (e.g. Triple
            Barrier hit time, or ``t_i + horizon``).
            Must be monotonically non-decreasing.
        t0:
            Optional array/Series of label start times.  ``t0[i]`` is
            the time when observation ``i`` enters the market (e.g. the
            bar timestamp).  When provided, the purging interval for
            each test group uses ``[t0[group_start], t1[group_end - 1]]``
            per Lopez de Prado (2018) S7.4.1.

            If omitted, ``t1`` is used as both start and end, which
            assumes labels are point-in-time.  This may **under-purge**
            with horizon-based labels where ``t1[i] > t0[i]``.

        Yields
        ------
        tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]
            ``(train_indices, test_indices)`` for each of the
            ``C(n_splits, n_test_splits)`` combinatorial splits.

        Raises
        ------
        ValueError
            If ``len(X) < n_splits``, ``len(t1) != len(X)``,
            ``t1`` is not monotonically non-decreasing, or
            ``t0`` is provided with mismatched length or ``t0[i] > t1[i]``.
        """
        n = len(X)
        t1_ns = self._validate_and_convert_t1(t1, n)
        t0_ns = self._validate_and_convert_t0(t0, t1_ns, n)

        # Partition [0, n) into n_splits contiguous groups
        groups = self._make_groups(n)

        # Embargo size in number of bars
        embargo_size = int(self._embargo_pct * n)

        # Iterate over all C(n_splits, n_test_splits) combinations
        for test_group_indices in itertools.combinations(
            range(self._n_splits), self._n_test_splits
        ):
            # Collect test indices and compute intervals
            test_idx_parts: list[npt.NDArray[np.intp]] = []
            test_intervals: list[tuple[np.int64, np.int64]] = []
            test_end_indices: list[int] = []

            for gi in test_group_indices:
                group_start, group_end = groups[gi]
                test_idx_parts.append(np.arange(group_start, group_end, dtype=np.intp))

                # Purge interval: [t0 of first test obs, t1 of last test obs]
                # per Lopez de Prado (2018) S7.4.1
                test_intervals.append((t0_ns[group_start], t1_ns[group_end - 1]))
                test_end_indices.append(group_end - 1)

            test_idx = np.concatenate(test_idx_parts)

            # Build train set from non-test groups (vectorized)
            test_group_set = set(test_group_indices)
            train_parts = [
                np.arange(gs, ge, dtype=np.intp)
                for gid, (gs, ge) in enumerate(groups)
                if gid not in test_group_set
            ]
            train_candidates = (
                np.concatenate(train_parts) if train_parts else np.empty(0, dtype=np.intp)
            )

            # Apply purging
            train_idx = purge_train_indices(train_candidates, t1_ns, test_intervals)

            # Apply embargo
            train_idx = apply_embargo(train_idx, test_end_indices, embargo_size, n)

            yield train_idx, test_idx

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def n_splits(self) -> int:
        """Number of groups observations are partitioned into."""
        return self._n_splits

    @property
    def n_test_splits(self) -> int:
        """Number of groups per test set."""
        return self._n_test_splits

    @property
    def embargo_pct(self) -> float:
        """Embargo size as fraction of total observations."""
        return self._embargo_pct

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_and_convert_t1(
        self,
        t1: pl.Series | npt.NDArray[np.datetime64],
        n: int,
    ) -> npt.NDArray[np.int64]:
        """Validate t1 and convert to int64 nanosecond timestamps.

        Raises
        ------
        ValueError
            If length mismatch or not monotonically non-decreasing.
        """
        # Convert to numpy datetime64 if polars Series
        if isinstance(t1, pl.Series):
            t1_arr: npt.NDArray[np.datetime64] = t1.to_numpy().astype("datetime64[ns]")
        else:
            t1_arr = np.asarray(t1, dtype="datetime64[ns]")

        if len(t1_arr) != n:
            msg = f"len(t1)={len(t1_arr)} != len(X)={n}"
            raise ValueError(msg)

        # Convert to int64 nanoseconds for fast comparison
        t1_ns: npt.NDArray[np.int64] = t1_arr.view(np.int64)

        # Check monotonically non-decreasing
        if len(t1_ns) > 1 and np.any(np.diff(t1_ns) < 0):
            msg = (
                "t1 must be monotonically non-decreasing. "
                "Label end times must be sorted chronologically."
            )
            raise ValueError(msg)

        return t1_ns

    def _validate_and_convert_t0(
        self,
        t0: pl.Series | npt.NDArray[np.datetime64] | None,
        t1_ns: npt.NDArray[np.int64],
        n: int,
    ) -> npt.NDArray[np.int64]:
        """Validate optional t0 and convert to int64 nanosecond timestamps.

        If ``t0`` is ``None``, returns ``t1_ns`` (legacy fallback:
        point-in-time label assumption).

        Raises
        ------
        ValueError
            If length mismatch or any ``t0[i] > t1[i]``.
        """
        if t0 is None:
            return t1_ns

        if isinstance(t0, pl.Series):
            t0_arr: npt.NDArray[np.datetime64] = t0.to_numpy().astype("datetime64[ns]")
        else:
            t0_arr = np.asarray(t0, dtype="datetime64[ns]")

        if len(t0_arr) != n:
            msg = f"len(t0)={len(t0_arr)} != len(X)={n}"
            raise ValueError(msg)

        t0_ns: npt.NDArray[np.int64] = t0_arr.view(np.int64)

        if np.any(t0_ns > t1_ns):
            msg = "t0[i] must be <= t1[i] for all i. Label start cannot exceed label end."
            raise ValueError(msg)

        return t0_ns

    def _make_groups(self, n: int) -> list[tuple[int, int]]:
        """Partition ``[0, n)`` into ``n_splits`` contiguous groups.

        Returns list of ``(start, end)`` tuples (end exclusive).
        Groups are as equal as possible; first groups may be 1 larger
        if ``n`` is not evenly divisible.

        Raises
        ------
        ValueError
            If ``n < n_splits``.
        """
        if n < self._n_splits:
            msg = (
                f"n_samples={n} is less than n_splits={self._n_splits}. "
                f"Cannot partition into that many groups."
            )
            raise ValueError(msg)

        base_size, remainder = divmod(n, self._n_splits)
        groups: list[tuple[int, int]] = []
        start = 0
        for i in range(self._n_splits):
            size = base_size + (1 if i < remainder else 0)
            groups.append((start, start + size))
            start += size
        return groups
