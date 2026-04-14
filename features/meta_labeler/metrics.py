"""Phase 4.3 - Classification metric helpers for the Baseline Meta-Labeler.

Thin, test-friendly wrappers around :mod:`sklearn.metrics` that:

- enforce a single numeric contract (``float64``, no NaN, no Inf);
- accept an optional ``sample_weight`` and propagate it unchanged;
- guarantee a deterministic order of probability / label inputs so that
  the CPCV loop downstream can concatenate per-fold outputs without
  hidden reshuffles.

Only three functions are exposed because PHASE_4_SPEC section 3.3 lists
exactly three diagnostic metrics for the baseline: ROC-AUC, Brier score,
and a 10-bin reliability diagram. Anything richer belongs to Phase 4.5
(DSR / PBO).

References:
    PHASE_4_SPEC section 3.3 - diagnostic metrics.
    Niculescu-Mizil & Caruana (2005). *Predicting good probabilities
    with supervised learning.* ICML.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score

__all__ = [
    "calibration_bins",
    "fold_auc",
    "fold_brier",
]


def _validate_pair(
    y_true: npt.NDArray[np.int_] | npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    sample_weight: npt.NDArray[np.float64] | None,
) -> None:
    """Fail-loud shape / finiteness check for a metric input triple."""
    if len(y_true) != len(y_prob):
        raise ValueError(
            f"y_true length ({len(y_true)}) does not match y_prob length ({len(y_prob)})"
        )
    if len(y_true) == 0:
        raise ValueError("y_true / y_prob are empty; cannot compute metric on an empty fold")
    if not np.isfinite(y_prob).all():
        raise ValueError("y_prob contains non-finite values (NaN/Inf)")
    if np.any(y_prob < 0.0) or np.any(y_prob > 1.0):
        raise ValueError("y_prob must lie in [0.0, 1.0]")
    if sample_weight is not None:
        if len(sample_weight) != len(y_true):
            raise ValueError(
                f"sample_weight length ({len(sample_weight)}) "
                f"does not match y_true length ({len(y_true)})"
            )
        if not np.isfinite(sample_weight).all():
            raise ValueError("sample_weight contains non-finite values (NaN/Inf)")
        if np.any(sample_weight < 0.0):
            raise ValueError("sample_weight must be non-negative")


def fold_auc(
    y_true: npt.NDArray[np.int_] | npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    sample_weight: npt.NDArray[np.float64] | None = None,
) -> float:
    """Return the weighted ROC-AUC for one CPCV fold.

    Args:
        y_true: Binary labels in ``{0, 1}``, shape ``(n,)``.
        y_prob: Predicted probability of class 1, shape ``(n,)``.
        sample_weight: Optional non-negative weight vector, shape
            ``(n,)``. Propagated to :func:`sklearn.metrics.roc_auc_score`
            unchanged.

    Returns:
        ROC-AUC score as a Python ``float``.

    Raises:
        ValueError: If inputs fail validation (see
            :func:`_validate_pair`) or if ``y_true`` is constant (AUC is
            undefined and scikit-learn raises - we surface the same
            error rather than hiding it).
    """
    _validate_pair(y_true, y_prob, sample_weight)
    auc = roc_auc_score(y_true, y_prob, sample_weight=sample_weight)
    return float(auc)


def fold_brier(
    y_true: npt.NDArray[np.int_] | npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    sample_weight: npt.NDArray[np.float64] | None = None,
) -> float:
    """Return the weighted Brier score for one CPCV fold.

    The Brier score is the mean squared error between predicted
    probabilities and observed binary outcomes; lower is better, with
    perfect predictions reaching zero. Calibration quality is directly
    proportional to the Brier score at a fixed discrimination level.

    Args:
        y_true: Binary labels in ``{0, 1}``, shape ``(n,)``.
        y_prob: Predicted probability of class 1, shape ``(n,)``.
        sample_weight: Optional non-negative weight vector, shape
            ``(n,)``.

    Returns:
        Brier score as a Python ``float`` in ``[0.0, 1.0]``.
    """
    _validate_pair(y_true, y_prob, sample_weight)
    # ``brier_score_loss`` requires ``pos_label`` to be unambiguous for
    # ``{0, 1}`` integer targets; we pass it explicitly to avoid the
    # sklearn 1.5+ deprecation warning that will become an error in 1.7.
    score = brier_score_loss(y_true, y_prob, sample_weight=sample_weight, pos_label=1)
    return float(score)


def calibration_bins(
    y_true: npt.NDArray[np.int_] | npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    n_bins: int = 10,
) -> list[tuple[float, float]]:
    """Return ``(mean_predicted, observed_positive_rate)`` per bin.

    This is the discrete reliability-diagram input reported in Phase 4.3
    diagnostic output. We use equal-width probability bins
    (``strategy="uniform"``) over ``[0, 1]`` rather than equal-frequency
    so that the returned curve is comparable across folds without
    re-computing quantiles.

    Args:
        y_true: Binary labels, shape ``(n,)``.
        y_prob: Predicted probability of class 1, shape ``(n,)``.
        n_bins: Number of probability bins (default ``10``). Must be
            ``>= 2``; scikit-learn raises if not.

    Returns:
        A list of ``(mean_pred, frac_positives)`` tuples - one per bin
        that contains at least one sample. Empty bins are dropped by
        :func:`sklearn.calibration.calibration_curve`, so the returned
        list has length ``<= n_bins``.

    Raises:
        ValueError: If inputs fail validation.
    """
    _validate_pair(y_true, y_prob, None)
    if n_bins < 2:
        raise ValueError(f"n_bins must be >= 2, got {n_bins}")

    # calibration_curve returns (frac_positives, mean_pred) - note the
    # unexpected order relative to most APIs; see scikit-learn docs.
    frac_positives, mean_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
    return [
        (float(mp), float(fp))
        for mp, fp in zip(
            cast(npt.NDArray[np.float64], mean_pred),
            cast(npt.NDArray[np.float64], frac_positives),
            strict=True,
        )
    ]
