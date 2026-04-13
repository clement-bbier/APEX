"""Purging helper — removes training samples with label leakage.

Purging eliminates training observations whose label end time ``t1[i]``
falls within any test interval.  This prevents the model from learning
on samples whose outcomes were determined using test-period data.

Reference:
    López de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, §7.4.1 — "Purging".
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def purge_train_indices(
    train_candidates: npt.NDArray[np.intp],
    t1: npt.NDArray[np.int64],
    test_intervals: list[tuple[np.int64, np.int64]],
) -> npt.NDArray[np.intp]:
    """Remove train indices whose label end time overlaps any test interval.

    For each candidate training index ``i``, if ``t1[i]`` falls within
    **any** ``[start, end]`` test interval (inclusive), index ``i`` is
    purged from the training set.

    Parameters
    ----------
    train_candidates:
        Array of candidate training indices (int).
    t1:
        Array of shape ``(n_total,)`` with **int64 nanosecond timestamps**
        representing the label end time for each observation.
        ``t1[i]`` is the time at which the label for observation ``i``
        becomes known (e.g. Triple Barrier hit time).
    test_intervals:
        List of ``(start_ns, end_ns)`` int64 timestamp pairs defining
        the temporal extent of each test group.  Intervals may be
        non-contiguous (combinatorial splits can select groups 0 and 4).

    Returns
    -------
    npt.NDArray[np.intp]
        Subset of ``train_candidates`` with leaked indices removed.

    Reference
    ---------
    López de Prado (2018) §7.4.1.
    """
    if len(train_candidates) == 0 or len(test_intervals) == 0:
        return train_candidates

    # Gather t1 values for all train candidates
    t1_train = t1[train_candidates]

    # Build a boolean mask: True = keep (not purged)
    keep = np.ones(len(train_candidates), dtype=np.bool_)

    for start_ns, end_ns in test_intervals:
        # Purge if t1[i] falls inside [start, end] inclusive
        overlaps = (t1_train >= start_ns) & (t1_train <= end_ns)
        keep &= ~overlaps

    return train_candidates[keep]
