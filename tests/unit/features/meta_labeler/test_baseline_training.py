"""Unit tests for :mod:`features.meta_labeler.baseline`."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.baseline import BaselineMetaLabeler, BaselineTrainingResult
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet

# --------------------------------------------------------------------
# Fixtures: a synthetic dataset with calibrated alpha in feature 3 (ofi).
# --------------------------------------------------------------------


def _make_synthetic_dataset(
    n: int = 400, seed: int = 42
) -> tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray]:
    """Build a synthetic ``(features, y, weights)`` triple with calibrated alpha.

    Features 1-3 are i.i.d. normal with ``ofi_signal`` (column 2) weakly
    correlated with a latent logit - a RandomForest should lift the OOS
    AUC above 0.55 across all 15 CPCV folds.
    """
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, size=(n, len(FEATURE_NAMES))).astype(np.float64)
    # Regime codes only take small integer values
    x[:, 3] = rng.integers(0, 4, size=n).astype(np.float64)
    x[:, 4] = rng.integers(-1, 2, size=n).astype(np.float64)
    x[:, 5] = np.abs(rng.normal(0.01, 0.002, size=n))

    # Latent logit = 1.5 * ofi_signal. Bernoulli outcome.
    logit = 1.5 * x[:, 2]
    probs = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(0, 1, size=n) < probs).astype(np.int_)

    # Monotonic t0, t1 separated by 5 bars.
    t0 = np.array(
        [np.datetime64("2025-01-01") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[us]",
    )
    t1 = t0 + np.timedelta64(5, "h")
    fs = MetaLabelerFeatureSet(X=x, feature_names=FEATURE_NAMES, t0=t0, t1=t1)
    w = np.ones(n, dtype=np.float64)
    return fs, y, w


@pytest.fixture
def cpcv_small() -> CombinatoriallyPurgedKFold:
    # C(4, 2) = 6 folds - small enough to keep tests fast.
    return CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.0)


@pytest.fixture
def dataset() -> tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray]:
    return _make_synthetic_dataset(n=400, seed=42)


# --------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------


def test_train_returns_baseline_training_result_with_expected_shapes(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    result = trainer.train(fs, y, w)
    assert isinstance(result, BaselineTrainingResult)
    assert isinstance(result.rf_model, RandomForestClassifier)
    assert isinstance(result.logreg_model, LogisticRegression)
    n_folds = cpcv_small.get_n_splits()
    assert len(result.rf_auc_per_fold) == n_folds
    assert len(result.logreg_auc_per_fold) == n_folds
    assert len(result.rf_brier_per_fold) == n_folds
    assert 2 <= len(result.rf_calibration_bins) <= 10
    assert set(result.feature_importances) == set(FEATURE_NAMES)


def test_feature_importances_sum_to_approximately_one(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    result = trainer.train(fs, y, w)
    total = sum(result.feature_importances.values())
    assert abs(total - 1.0) < 1e-6


def test_rf_mean_auc_above_smoke_gate_on_calibrated_alpha(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    result = trainer.train(fs, y, w)
    mean_auc_rf = float(np.mean(result.rf_auc_per_fold))
    assert mean_auc_rf >= 0.55, f"RF mean OOS AUC {mean_auc_rf} below smoke gate 0.55"


def test_logreg_is_always_trained_even_when_rf_hp_overridden(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, rf_hyperparameters={"n_estimators": 50}, seed=42)
    result = trainer.train(fs, y, w)
    # LogReg classes_ populated means fit() ran.
    assert result.logreg_model.classes_.tolist() == [0, 1]
    # LogReg AUC vector non-empty.
    assert len(result.logreg_auc_per_fold) == cpcv_small.get_n_splits()


def test_determinism_same_seed_same_importances(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    a = BaselineMetaLabeler(cpcv_small, seed=42).train(fs, y, w)
    b = BaselineMetaLabeler(cpcv_small, seed=42).train(fs, y, w)
    for name in FEATURE_NAMES:
        assert a.feature_importances[name] == pytest.approx(b.feature_importances[name], abs=1e-12)
    for af, bf in zip(a.rf_auc_per_fold, b.rf_auc_per_fold, strict=True):
        assert af == pytest.approx(bf, abs=1e-12)


def test_different_seeds_produce_different_models(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    a = BaselineMetaLabeler(cpcv_small, seed=42).train(fs, y, w)
    b = BaselineMetaLabeler(cpcv_small, seed=7).train(fs, y, w)
    differs = any(a.feature_importances[n] != b.feature_importances[n] for n in FEATURE_NAMES)
    assert differs, "different seeds must yield different RF importances"


def test_sample_weight_is_propagated_to_sklearn_fit(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[::2] = 2.5
    w[1::2] = 0.3
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)

    calls: list[np.ndarray] = []
    orig_rf = RandomForestClassifier.fit

    def spy_fit(self, x_arr, y_arr, *args, sample_weight=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(np.asarray(sample_weight))
        return orig_rf(self, x_arr, y_arr, *args, sample_weight=sample_weight, **kwargs)

    RandomForestClassifier.fit = spy_fit  # type: ignore[method-assign]
    try:
        trainer.train(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_rf  # type: ignore[method-assign]

    assert len(calls) == cpcv_small.get_n_splits() + 1  # per-fold + final
    for arr in calls:
        # At least one 2.5 or 0.3 weight must appear in every fold fit.
        assert np.any(np.isclose(arr, 2.5)) or np.any(np.isclose(arr, 0.3))


def test_class_weight_is_balanced_on_both_models(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    result = trainer.train(fs, y, w)
    assert result.rf_model.class_weight == "balanced"
    assert result.logreg_model.class_weight == "balanced"


# --------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------


def test_reserved_hyperparameters_cannot_be_overridden(
    cpcv_small: CombinatoriallyPurgedKFold,
) -> None:
    with pytest.raises(ValueError, match="reserved keys"):
        BaselineMetaLabeler(cpcv_small, rf_hyperparameters={"random_state": 1}, seed=42)


def test_train_rejects_non_binary_y(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    y = y.copy()
    y[5] = 3
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="binary"):
        trainer.train(fs, y, w)


def test_train_rejects_negative_sample_weight(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[0] = -1.0
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="non-negative"):
        trainer.train(fs, y, w)


def test_train_rejects_length_mismatch(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match=r"y length"):
        trainer.train(fs, y[:-1], w)


def test_train_rejects_empty_feature_matrix() -> None:
    empty_x = np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    empty_ts = np.array([], dtype="datetime64[us]")
    fs = MetaLabelerFeatureSet(X=empty_x, feature_names=FEATURE_NAMES, t0=empty_ts, t1=empty_ts)
    trainer = BaselineMetaLabeler(
        CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0), seed=42
    )
    with pytest.raises(ValueError, match="empty"):
        trainer.train(fs, np.array([], dtype=np.int_), np.array([], dtype=np.float64))


def test_train_rejects_degenerate_single_class_target(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    y_all_ones = np.ones_like(y)
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="only one class"):
        trainer.train(fs, y_all_ones, w)


def test_train_rejects_non_integer_y(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="integer array"):
        trainer.train(fs, y.astype(np.float64), w)


def test_train_rejects_nan_sample_weight(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[3] = np.nan
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="non-finite"):
        trainer.train(fs, y, w)


def test_train_rejects_sample_weight_length_mismatch(
    cpcv_small: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    trainer = BaselineMetaLabeler(cpcv_small, seed=42)
    with pytest.raises(ValueError, match="sample_weights length"):
        trainer.train(fs, y, w[:-1])


def test_cpcv_empty_split_is_detected(
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    # Fake a CPCV that yields an empty train set.
    fake_cpcv = MagicMock(spec=CombinatoriallyPurgedKFold)
    fake_cpcv.get_n_splits.return_value = 1
    fake_cpcv.split.return_value = iter(
        [(np.array([], dtype=np.intp), np.arange(5, dtype=np.intp))]
    )
    trainer = BaselineMetaLabeler(fake_cpcv, seed=42)
    with pytest.raises(ValueError, match="empty split"):
        trainer.train(fs, y, w)
