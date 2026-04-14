"""Unit tests for :mod:`features.meta_labeler.metrics`."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import brier_score_loss, roc_auc_score

from features.meta_labeler.metrics import calibration_bins, fold_auc, fold_brier


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


def test_fold_auc_matches_sklearn(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=200)
    p = rng.uniform(0.0, 1.0, size=200)
    got = fold_auc(y, p)
    expected = float(roc_auc_score(y, p))
    assert got == pytest.approx(expected, rel=0, abs=1e-12)


def test_fold_auc_propagates_sample_weight(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=150)
    p = rng.uniform(0.0, 1.0, size=150)
    w = rng.uniform(0.1, 2.0, size=150)
    got = fold_auc(y, p, sample_weight=w)
    expected = float(roc_auc_score(y, p, sample_weight=w))
    assert got == pytest.approx(expected, rel=0, abs=1e-12)


def test_fold_auc_rejects_out_of_range_probabilities(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=20)
    p = rng.uniform(0.0, 1.0, size=20)
    p[3] = 1.5  # illegal
    with pytest.raises(ValueError, match=r"y_prob must lie in \[0\.0, 1\.0\]"):
        fold_auc(y, p)


def test_fold_auc_rejects_negative_weight(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=10)
    p = rng.uniform(0.0, 1.0, size=10)
    w = np.ones(10)
    w[2] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        fold_auc(y, p, sample_weight=w)


def test_fold_auc_rejects_nan_probability(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=5)
    p = np.array([0.1, 0.2, np.nan, 0.4, 0.5])
    with pytest.raises(ValueError, match="non-finite"):
        fold_auc(y, p)


def test_fold_auc_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        fold_auc(np.array([], dtype=int), np.array([], dtype=float))


def test_fold_auc_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length"):
        fold_auc(np.array([0, 1]), np.array([0.1]))


def test_fold_brier_matches_sklearn(rng: np.random.Generator) -> None:
    y = rng.integers(0, 2, size=100)
    p = rng.uniform(0.0, 1.0, size=100)
    got = fold_brier(y, p)
    expected = float(brier_score_loss(y, p, pos_label=1))
    assert got == pytest.approx(expected, rel=0, abs=1e-12)


def test_fold_brier_is_zero_on_perfect_predictions() -> None:
    y = np.array([0, 1, 0, 1, 1])
    p = y.astype(float)
    assert fold_brier(y, p) == pytest.approx(0.0, abs=1e-12)


def test_calibration_bins_returns_monotonic_tuples(rng: np.random.Generator) -> None:
    # Well-calibrated: probabilities match the Bernoulli draw directly.
    p = rng.uniform(0.0, 1.0, size=5000)
    y = (rng.uniform(size=5000) < p).astype(int)
    bins = calibration_bins(y, p, n_bins=10)
    assert 2 <= len(bins) <= 10
    for mp, fp in bins:
        assert 0.0 <= mp <= 1.0
        assert 0.0 <= fp <= 1.0
    mean_preds = [b[0] for b in bins]
    assert mean_preds == sorted(mean_preds), "mean_predicted must be non-decreasing across bins"


def test_calibration_bins_rejects_one_bin() -> None:
    with pytest.raises(ValueError, match="n_bins must be >= 2"):
        calibration_bins(np.array([0, 1]), np.array([0.2, 0.8]), n_bins=1)


def test_calibration_bins_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        calibration_bins(np.array([], dtype=int), np.array([], dtype=float))
