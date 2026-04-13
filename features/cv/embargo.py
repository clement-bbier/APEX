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

    # Vectorized embargo zone construction
    test_end_arr = np.asarray(test_end_indices, dtype=np.intp)
    embargo_starts = test_end_arr + 1
    embargo_ends = np.minimum(test_end_arr + embargo_size, n_total - 1)
    valid_windows = embargo_starts <= embargo_ends

    if not np.any(valid_windows):
        return train_candidates

    embargoed_idx = np.unique(
        np.concatenate(
            [
                np.arange(start, end + 1, dtype=np.intp)
                for start, end in zip(
                    embargo_starts[valid_windows],
                    embargo_ends[valid_windows],
                    strict=True,
                )
            ]
        )
    )
    keep = np.isin(train_candidates, embargoed_idx, invert=True)
    return train_candidates[keep]
