"""Embargo helper — adds temporal buffer after test groups.

After purging removes samples with label overlap, an embargo buffer
removes additional training samples that fall immediately after each
test group boundary.  This guards against information leakage via
autocorrelation of features (e.g. Kyle lambda, OFI multi-window).

Reference:
    López de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, §7.4.2 — "Embargo".
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def apply_embargo(
    train_candidates: npt.NDArray[np.intp],
    test_end_indices: list[int],
    embargo_size: int,
    n_total: int,
) -> npt.NDArray[np.intp]:
    """Remove training indices within the embargo zone after each test group.

    For each test group ending at index ``end_i``, indices in the range
    ``[end_i + 1, end_i + embargo_size]`` (inclusive, clamped to
    ``n_total - 1``) are excluded from the training set.

    Parameters
    ----------
    train_candidates:
        Array of candidate training indices (int).
    test_end_indices:
        List of the last index (inclusive) of each test group.
    embargo_size:
        Number of observations to exclude after each test group end.
        If ``0``, no embargo is applied.
    n_total:
        Total number of observations (used for boundary clamping).

    Returns
    -------
    npt.NDArray[np.intp]
        Subset of ``train_candidates`` with embargoed indices removed.

    Reference
    ---------
    López de Prado (2018) §7.4.2.
    """
    if embargo_size <= 0 or len(test_end_indices) == 0 or len(train_candidates) == 0:
        return train_candidates

    # Collect all embargoed indices into a set for O(1) lookup
    embargoed: set[int] = set()
    for end_i in test_end_indices:
        embargo_start = end_i + 1
        embargo_end = min(end_i + embargo_size, n_total - 1)
        for idx in range(embargo_start, embargo_end + 1):
            embargoed.add(idx)

    if not embargoed:
        return train_candidates

    # Boolean mask: True = keep (not in embargo zone)
    keep = np.array(
        [int(idx) not in embargoed for idx in train_candidates],
        dtype=np.bool_,
    )
    return train_candidates[keep]
