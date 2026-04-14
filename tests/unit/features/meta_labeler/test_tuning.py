"""Unit tests for :mod:`features.meta_labeler.tuning`."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.tuning import (
    NestedCPCVTuner,
    TuningResult,
    TuningSearchSpace,
    _stability_index,
)

# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------


def _make_synthetic_dataset(
    n: int = 400, seed: int = 42
) -> tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, size=(n, len(FEATURE_NAMES))).astype(np.float64)
    x[:, 3] = rng.integers(0, 4, size=n).astype(np.float64)
    x[:, 4] = rng.integers(-1, 2, size=n).astype(np.float64)
    x[:, 5] = np.abs(rng.normal(0.01, 0.002, size=n))
    logit = 1.5 * x[:, 2]
    probs = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(0, 1, size=n) < probs).astype(np.int_)
    t0 = np.array(
        [np.datetime64("2025-01-01") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[us]",
    )
    t1 = (t0 + np.timedelta64(5, "h")).astype("datetime64[us]")
    fs = MetaLabelerFeatureSet(X=x, feature_names=FEATURE_NAMES, t0=t0, t1=t1)
    w = np.ones(n, dtype=np.float64)
    return fs, y, w


@pytest.fixture
def tiny_space() -> TuningSearchSpace:
    # 2 * 2 * 2 = 8 trials - fast to evaluate in tests.
    return TuningSearchSpace(
        n_estimators=(30, 60),
        max_depth=(3, 5),
        min_samples_leaf=(5, 10),
    )


@pytest.fixture
def outer_cpcv() -> CombinatoriallyPurgedKFold:
    # C(4, 2) = 6 outer folds.
    return CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.0)


@pytest.fixture
def inner_cpcv() -> CombinatoriallyPurgedKFold:
    # C(3, 1) = 3 inner folds.
    return CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)


@pytest.fixture
def dataset() -> tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray]:
    return _make_synthetic_dataset(n=400, seed=42)


# --------------------------------------------------------------------
# Micro fixtures for the determinism tests
# --------------------------------------------------------------------
# The determinism tests (``test_nested_run_deterministic_same_seed`` and
# ``test_different_seeds_change_per_fold_seed_deterministically``) call
# ``tune()`` twice per test and therefore need a very small search space
# to fit in the 30s per-test CI timeout. A 2x1x1 search space on Outer
# C(3, 1)=3 / Inner C(2, 1)=2 with n=120 runs about 2x(3*(2+1))=18 RF
# fits per ``tune()`` call — comfortably sub-second on GH Actions.


@pytest.fixture
def micro_space() -> TuningSearchSpace:
    return TuningSearchSpace(
        n_estimators=(20, 30),
        max_depth=(3,),
        min_samples_leaf=(5,),
    )


@pytest.fixture
def micro_outer_cpcv() -> CombinatoriallyPurgedKFold:
    return CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)


@pytest.fixture
def micro_inner_cpcv() -> CombinatoriallyPurgedKFold:
    return CombinatoriallyPurgedKFold(n_splits=2, n_test_splits=1, embargo_pct=0.0)


@pytest.fixture
def micro_dataset() -> tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray]:
    return _make_synthetic_dataset(n=120, seed=42)


# --------------------------------------------------------------------
# A. Search-space primitives
# --------------------------------------------------------------------


def test_search_space_cardinality_18_trials() -> None:
    space = TuningSearchSpace()
    assert space.cardinality == 18
    assert len(space.grid()) == 18


def test_search_space_grid_returns_all_combinations_once() -> None:
    space = TuningSearchSpace()
    grid = space.grid()
    unique_keys = {tuple(sorted(hp.items())) for hp in grid}
    assert len(unique_keys) == 18


def test_search_space_reject_empty_n_estimators_tuple() -> None:
    with pytest.raises(ValueError, match="n_estimators must contain"):
        TuningSearchSpace(n_estimators=())


def test_search_space_reject_non_positive_n_estimators() -> None:
    with pytest.raises(ValueError, match="n_estimators values must be positive"):
        TuningSearchSpace(n_estimators=(0,))


def test_search_space_reject_empty_max_depth() -> None:
    with pytest.raises(ValueError, match="max_depth must contain"):
        TuningSearchSpace(max_depth=())


def test_search_space_reject_bad_max_depth_value() -> None:
    with pytest.raises(ValueError, match="max_depth values must be None or positive"):
        TuningSearchSpace(max_depth=(-1,))


def test_search_space_reject_empty_min_samples_leaf() -> None:
    with pytest.raises(ValueError, match="min_samples_leaf must contain"):
        TuningSearchSpace(min_samples_leaf=())


# --------------------------------------------------------------------
# B. Happy path and shapes
# --------------------------------------------------------------------


def test_tune_returns_tuning_result_with_expected_shapes(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    assert isinstance(result, TuningResult)
    n_outer = outer_cpcv.get_n_splits()
    assert len(result.best_hyperparameters_per_fold) == n_outer
    assert len(result.best_oos_auc_per_fold) == n_outer
    assert len(result.all_trials) == n_outer * tiny_space.cardinality


def test_best_hparams_per_fold_length_equals_outer_n_splits(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    # Every fold's winner must be a dict with the three RF knobs.
    for hp in result.best_hyperparameters_per_fold:
        assert set(hp.keys()) == {"n_estimators", "max_depth", "min_samples_leaf"}


def test_all_trials_length_equals_n_outer_x_search_cardinality(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    assert len(result.all_trials) == outer_cpcv.get_n_splits() * tiny_space.cardinality
    # Every trial is (hparams_dict, mean_inner_auc, oos_auc).
    for hp, inner_auc, oos_auc in result.all_trials:
        assert isinstance(hp, dict)
        assert 0.0 <= inner_auc <= 1.0
        assert 0.0 <= oos_auc <= 1.0


def test_best_oos_auc_matches_trials_ledger_entry(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    """For each outer fold, best_oos_auc equals the OOS AUC of the
    winning hparams in ``all_trials``."""
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    card = tiny_space.cardinality
    for fold_idx, (best_hp, best_oos) in enumerate(
        zip(result.best_hyperparameters_per_fold, result.best_oos_auc_per_fold, strict=True)
    ):
        fold_slice = result.all_trials[fold_idx * card : (fold_idx + 1) * card]
        matched = [oos for (hp, _, oos) in fold_slice if hp == best_hp]
        assert best_oos in matched


# --------------------------------------------------------------------
# C. Determinism
# --------------------------------------------------------------------


def test_nested_run_deterministic_same_seed(
    micro_space: TuningSearchSpace,
    micro_outer_cpcv: CombinatoriallyPurgedKFold,
    micro_inner_cpcv: CombinatoriallyPurgedKFold,
    micro_dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = micro_dataset
    a = NestedCPCVTuner(micro_space, micro_outer_cpcv, micro_inner_cpcv, seed=42).tune(fs, y, w)
    b = NestedCPCVTuner(micro_space, micro_outer_cpcv, micro_inner_cpcv, seed=42).tune(fs, y, w)
    assert a.best_hyperparameters_per_fold == b.best_hyperparameters_per_fold
    for oa, ob in zip(a.best_oos_auc_per_fold, b.best_oos_auc_per_fold, strict=True):
        assert oa == pytest.approx(ob, abs=1e-12)
    assert len(a.all_trials) == len(b.all_trials)
    for (hp_a, ia_a, oa_a), (hp_b, ia_b, oa_b) in zip(a.all_trials, b.all_trials, strict=True):
        assert hp_a == hp_b
        assert ia_a == pytest.approx(ia_b, abs=1e-12)
        assert oa_a == pytest.approx(oa_b, abs=1e-12)


def test_different_seeds_change_per_fold_seed_deterministically(
    micro_space: TuningSearchSpace,
    micro_outer_cpcv: CombinatoriallyPurgedKFold,
    micro_inner_cpcv: CombinatoriallyPurgedKFold,
    micro_dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    """Changing the tuner seed must change every RF's ``random_state``
    by exactly the expected offset, which guarantees the RF population
    is a different one.

    This replaces an earlier probabilistic test that compared OOS AUC
    floats across seeds — that check was flaky on pathological grids
    where different RF populations can still tie on AUC. Seeds are the
    causal root cause of determinism, so we pin them directly.
    """
    fs, y, w = micro_dataset
    seed_a, seed_b = 42, 1337
    seen_a: list[int] = []
    seen_b: list[int] = []
    orig_fit = RandomForestClassifier.fit

    def spy_a(self, x_arr, y_arr, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen_a.append(int(self.get_params()["random_state"]))
        return orig_fit(self, x_arr, y_arr, *args, **kwargs)

    def spy_b(self, x_arr, y_arr, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen_b.append(int(self.get_params()["random_state"]))
        return orig_fit(self, x_arr, y_arr, *args, **kwargs)

    RandomForestClassifier.fit = spy_a  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(micro_space, micro_outer_cpcv, micro_inner_cpcv, seed=seed_a).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    RandomForestClassifier.fit = spy_b  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(micro_space, micro_outer_cpcv, micro_inner_cpcv, seed=seed_b).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    n_outer = micro_outer_cpcv.get_n_splits()
    expected_a = {seed_a + i * 7 for i in range(n_outer)}
    expected_b = {seed_b + i * 7 for i in range(n_outer)}
    assert set(seen_a) == expected_a
    assert set(seen_b) == expected_b
    assert set(seen_a).isdisjoint(set(seen_b)), (
        "seed-derived random_states must not collide across different tuner seeds"
    )


# --------------------------------------------------------------------
# D. Stability index
# --------------------------------------------------------------------


def test_stability_index_equals_one_when_all_folds_agree() -> None:
    hp = {"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 5}
    assert _stability_index([dict(hp) for _ in range(15)]) == pytest.approx(1.0)


def test_stability_index_two_thirds_when_two_of_three_folds_agree() -> None:
    a = {"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 5}
    b = {"n_estimators": 300, "max_depth": None, "min_samples_leaf": 20}
    folds = [dict(a), dict(a), dict(b)]
    assert _stability_index(folds) == pytest.approx(2.0 / 3.0)


def test_stability_index_reports_valid_float_on_tuner_output(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    assert 0.0 < result.stability_index <= 1.0


def test_stability_index_raises_on_empty_list() -> None:
    with pytest.raises(ValueError, match="zero folds"):
        _stability_index([])


# --------------------------------------------------------------------
# E. Input validation
# --------------------------------------------------------------------


def test_empty_feature_matrix_raises(
    tiny_space: TuningSearchSpace,
    inner_cpcv: CombinatoriallyPurgedKFold,
) -> None:
    empty_x = np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    empty_ts = np.array([], dtype="datetime64[us]")
    fs = MetaLabelerFeatureSet(X=empty_x, feature_names=FEATURE_NAMES, t0=empty_ts, t1=empty_ts)
    outer = CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0)
    tuner = NestedCPCVTuner(tiny_space, outer, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="empty"):
        tuner.tune(fs, np.array([], dtype=np.int_), np.array([], dtype=np.float64))


def test_non_binary_y_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    y = y.copy()
    y[0] = 2
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="binary"):
        tuner.tune(fs, y, w)


def test_negative_sample_weight_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[0] = -1.0
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="non-negative"):
        tuner.tune(fs, y, w)


def test_non_finite_sample_weight_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[0] = np.nan
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="non-finite"):
        tuner.tune(fs, y, w)


def test_sample_weight_length_mismatch_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="sample_weights length"):
        tuner.tune(fs, y, w[:-1])


def test_y_length_mismatch_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="y length"):
        tuner.tune(fs, y[:-1], w)


def test_degenerate_single_class_y_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="only one class"):
        tuner.tune(fs, np.ones_like(y), w)


def test_outer_cpcv_empty_split_raises(
    tiny_space: TuningSearchSpace,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    fake = MagicMock(spec=CombinatoriallyPurgedKFold)
    fake.get_n_splits.return_value = 1
    fake.split.return_value = iter([(np.array([], dtype=np.intp), np.arange(5, dtype=np.intp))])
    tuner = NestedCPCVTuner(tiny_space, fake, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match="outer CPCV produced an empty split"):
        tuner.tune(fs, y, w)


def test_non_finite_feature_raises(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    fs.X[0, 0] = np.inf
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    with pytest.raises(ValueError, match=r"features\.X contains non-finite"):
        tuner.tune(fs, y, w)


# --------------------------------------------------------------------
# F. Anti-leakage property test
# --------------------------------------------------------------------


def test_inner_search_never_touches_outer_test_indices(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    """Spy on every ``RandomForestClassifier.fit`` call made inside the
    tuner and prove that no outer-test row ever enters an *inner* fit.

    This is the strict form of the nested-CV invariant from Lopez de
    Prado (2018) section 7.4: the inner search must run on a strict
    subset of the outer training slice. A naive "permute the outer-test
    slice and check inner AUC" probe would fail because in CPCV every
    row is test in some outer folds and train in others, so a global
    permutation also perturbs inner-train data for other folds. The fit
    spy avoids that confound by checking the actual rows passed to
    :meth:`RandomForestClassifier.fit` per-call.
    """
    fs, y, w = dataset
    outer_splits = list(outer_cpcv.split(fs.X, fs.t1, fs.t0))
    n_outer = len(outer_splits)
    n_inner = inner_cpcv.get_n_splits()
    card = tiny_space.cardinality

    captured: list[np.ndarray] = []
    orig_fit = RandomForestClassifier.fit

    def spy_fit(self, x_arr, y_arr, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(np.asarray(x_arr).copy())
        return orig_fit(self, x_arr, y_arr, *args, **kwargs)

    RandomForestClassifier.fit = spy_fit  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    # Per outer fold: for each grid point we do n_inner inner fits then
    # 1 outer re-fit, hence ``card * (n_inner + 1)`` fits per outer fold.
    per_fold = card * (n_inner + 1)
    assert len(captured) == n_outer * per_fold, (
        f"expected {n_outer * per_fold} RF fits, got {len(captured)}"
    )

    # Hash each row via bytes for exact-match lookup.
    def _row_hash(row: np.ndarray) -> bytes:
        return bytes(np.ascontiguousarray(row, dtype=np.float64).tobytes())

    for outer_idx, (_train_idx, test_idx) in enumerate(outer_splits):
        test_row_hashes = {_row_hash(fs.X[i]) for i in test_idx}
        base = outer_idx * per_fold
        for trial in range(card):
            # Inner fits come first, followed by the outer re-fit.
            for inner_k in range(n_inner):
                fit_x = captured[base + trial * (n_inner + 1) + inner_k]
                for row in fit_x:
                    assert _row_hash(row) not in test_row_hashes, (
                        f"outer-test row leaked into inner fit "
                        f"(outer_idx={outer_idx}, trial={trial}, inner={inner_k})"
                    )


# --------------------------------------------------------------------
# G. Wall-clock
# --------------------------------------------------------------------


def test_wall_clock_seconds_is_positive_and_finite(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    tuner = NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42)
    result = tuner.tune(fs, y, w)
    assert result.wall_clock_seconds > 0.0
    assert np.isfinite(result.wall_clock_seconds)


# --------------------------------------------------------------------
# H. Side-effect invariants
# --------------------------------------------------------------------


def test_class_weight_balanced_propagated_to_every_rf_fit(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    seen_params: list[dict[str, Any]] = []
    orig_fit = RandomForestClassifier.fit

    def spy_fit(self, x_arr, y_arr, *args, **kwargs):  # type: ignore[no-untyped-def]
        # ``get_params`` inspects the instance's __init__ signature;
        # capture it here so we see the RF configuration that Phase 4.4
        # actually built.
        seen_params.append(self.get_params())
        return orig_fit(self, x_arr, y_arr, *args, **kwargs)

    RandomForestClassifier.fit = spy_fit  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    assert seen_params, "no RF instantiations recorded"
    for kw in seen_params:
        assert kw["class_weight"] == "balanced"
        assert kw["n_jobs"] == 1


def test_sample_weights_propagated_to_rf_fit(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    fs, y, w = dataset
    w = w.copy()
    w[::2] = 2.5
    w[1::2] = 0.3

    calls: list[np.ndarray] = []
    orig_fit = RandomForestClassifier.fit

    def spy_fit(self, x_arr, y_arr, *args, sample_weight=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(np.asarray(sample_weight))
        return orig_fit(self, x_arr, y_arr, *args, sample_weight=sample_weight, **kwargs)

    RandomForestClassifier.fit = spy_fit  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=42).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    assert calls, "no RF fits recorded"
    for arr in calls:
        assert np.any(np.isclose(arr, 2.5)) or np.any(np.isclose(arr, 0.3))


def test_per_fold_seed_derivation_uses_multiplier_seven(
    tiny_space: TuningSearchSpace,
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
    dataset: tuple[MetaLabelerFeatureSet, np.ndarray, np.ndarray],
) -> None:
    """Every RF fit in fold i receives ``random_state = seed + i*7``."""
    fs, y, w = dataset
    seen_params: list[dict[str, Any]] = []
    orig_fit = RandomForestClassifier.fit

    def spy_fit(self, x_arr, y_arr, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen_params.append(self.get_params())
        return orig_fit(self, x_arr, y_arr, *args, **kwargs)

    seed = 42
    RandomForestClassifier.fit = spy_fit  # type: ignore[method-assign]
    try:
        NestedCPCVTuner(tiny_space, outer_cpcv, inner_cpcv, seed=seed).tune(fs, y, w)
    finally:
        RandomForestClassifier.fit = orig_fit  # type: ignore[method-assign]

    n_outer = outer_cpcv.get_n_splits()
    expected_seeds = {seed + i * 7 for i in range(n_outer)}
    observed_seeds = {kw["random_state"] for kw in seen_params}
    # Every expected seed must appear; the set equality also confirms no
    # stray seeds leaked through.
    assert expected_seeds == observed_seeds


# --------------------------------------------------------------------
# Reserved-key guard at tuner construction
# --------------------------------------------------------------------


def test_search_space_reserved_key_is_blocked_at_tuner_ctor(
    outer_cpcv: CombinatoriallyPurgedKFold,
    inner_cpcv: CombinatoriallyPurgedKFold,
) -> None:
    """A crafted search-space subclass injecting a reserved key must
    be rejected by the tuner constructor."""

    class BadSpace(TuningSearchSpace):
        def grid(self) -> tuple[dict[str, Any], ...]:  # type: ignore[override]
            return ({"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 5, "n_jobs": -1},)

    with pytest.raises(ValueError, match="reserved keys"):
        NestedCPCVTuner(BadSpace(), outer_cpcv, inner_cpcv, seed=42)
