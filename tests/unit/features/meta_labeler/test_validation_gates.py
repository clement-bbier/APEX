"""Unit tests for :mod:`features.meta_labeler.validation`.

Coverage target: ≥ 92 % on ``validation.py``.

The bulk of the suite is gate-by-gate (G1..G7) pass/fail logic plus the
fail-loud contract on missing evidence. End-to-end tests run the full
4.3 → 4.4 → 4.5 pipeline on a small synthetic dataset so the wiring
between the validator and the existing DSR / PBO calculators is
exercised under realistic shapes (≤ 60 s on a single core).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import polars as pl
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.baseline import (
    BaselineMetaLabeler,
    BaselineTrainingResult,
)
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.pnl_simulation import CostScenario
from features.meta_labeler.tuning import (
    NestedCPCVTuner,
    TuningResult,
    TuningSearchSpace,
)
from features.meta_labeler.validation import (
    GateResult,
    MetaLabelerValidationReport,
    MetaLabelerValidator,
)

# --------------------------------------------------------------------
# Helpers / fixtures
# --------------------------------------------------------------------


def _baseline_result(
    *,
    rf_aucs: tuple[float, ...] = (0.60, 0.62, 0.58, 0.61, 0.59, 0.63),
    logreg_aucs: tuple[float, ...] | None = (0.55, 0.56, 0.54, 0.55, 0.55, 0.56),
    rf_briers: tuple[float, ...] | None = None,
) -> BaselineTrainingResult:
    """Construct a synthetic BaselineTrainingResult for gate tests.

    The dummy RF / LogReg models are unfitted; gate logic only reads
    ``*_per_fold`` so the actual estimators are irrelevant.
    """
    if rf_briers is None:
        rf_briers = tuple([0.20] * len(rf_aucs))
    if logreg_aucs is None:
        logreg_aucs = ()
    return BaselineTrainingResult(
        rf_model=RandomForestClassifier(),
        logreg_model=LogisticRegression(),
        rf_auc_per_fold=rf_aucs,
        logreg_auc_per_fold=logreg_aucs,
        rf_brier_per_fold=rf_briers,
        rf_calibration_bins=((0.5, 0.5),),
        feature_importances={name: 1.0 / len(FEATURE_NAMES) for name in FEATURE_NAMES},
    )


def _trial_grid(n_outer: int, oos_lift: float = 0.05) -> TuningResult:
    """Trial ledger with a clear winner across folds.

    Two distinct hparam dicts (``A`` and ``B``) - the minimum
    cardinality for PBO. ``B`` always beats ``A`` by ``oos_lift`` so
    PBO is 0.0 (no overfitting).
    """
    grid = [
        {"n_estimators": 30, "max_depth": 3, "min_samples_leaf": 5},
        {"n_estimators": 60, "max_depth": 5, "min_samples_leaf": 5},
    ]
    trials: list[tuple[dict[str, Any], float, float]] = []
    for outer in range(n_outer):
        for k, hp in enumerate(grid):
            inner = 0.55 + 0.01 * outer + 0.005 * k
            oos = 0.55 + 0.01 * outer + oos_lift * k
            trials.append((dict(hp), float(inner), float(oos)))
    best = tuple(grid[1] for _ in range(n_outer))
    return TuningResult(
        best_hyperparameters_per_fold=best,
        best_oos_auc_per_fold=tuple(0.55 + 0.01 * o + oos_lift for o in range(n_outer)),
        all_trials=tuple(trials),
        stability_index=1.0,
        wall_clock_seconds=0.1,
    )


def _synthetic_dataset(
    n: int = 200, seed: int = 42
) -> tuple[
    MetaLabelerFeatureSet,
    np.ndarray,
    np.ndarray,
    pl.DataFrame,
]:
    """Synthetic features + bars covering [min(t0), max(t1)]."""
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

    span = int(((t1.max() - t0.min())).astype("timedelta64[h]").astype(np.int64)) + 1
    timestamps = np.array(
        [t0.min() + np.timedelta64(i, "h") for i in range(span)],
        dtype="datetime64[us]",
    )
    drift = np.zeros(span, dtype=np.float64)
    bar_idx = np.searchsorted(timestamps, t0, side="left")
    drift[bar_idx] = 0.001 * x[:, 2]
    noise = rng.normal(0.0, 0.0015, size=span)
    log_returns = drift + noise
    log_returns[0] = 0.0
    close = 100.0 * np.exp(np.cumsum(log_returns))
    bars = pl.DataFrame(
        {
            "timestamp": pl.Series(
                "timestamp", timestamps, dtype=pl.Datetime("us", "UTC")
            ),
            "close": pl.Series("close", close.astype(np.float64), dtype=pl.Float64),
        }
    )
    return fs, y, w, bars


@pytest.fixture
def cpcv() -> CombinatoriallyPurgedKFold:
    # C(4, 2) = 6 outer folds - small for fast tests.
    return CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.0)


# --------------------------------------------------------------------
# G1 - mean OOS AUC ≥ 0.55
# --------------------------------------------------------------------


def test_g1_pass_when_mean_auc_above_0p55(cpcv: CombinatoriallyPurgedKFold) -> None:
    g1 = MetaLabelerValidator._gate_g1(np.array([0.60, 0.61, 0.59]))
    assert g1.name == "G1_mean_auc"
    assert g1.threshold == pytest.approx(0.55)
    assert g1.passed is True


def test_g1_fail_when_mean_auc_below_0p55() -> None:
    g1 = MetaLabelerValidator._gate_g1(np.array([0.50, 0.51, 0.52]))
    assert g1.passed is False


def test_g1_boundary_at_exactly_0p55_passes() -> None:
    g1 = MetaLabelerValidator._gate_g1(np.array([0.55, 0.55, 0.55]))
    assert g1.passed is True


# --------------------------------------------------------------------
# G2 - min OOS AUC ≥ 0.52
# --------------------------------------------------------------------


def test_g2_pass_when_min_auc_above_0p52() -> None:
    g2 = MetaLabelerValidator._gate_g2(np.array([0.60, 0.55, 0.53]))
    assert g2.name == "G2_min_auc"
    assert g2.value == pytest.approx(0.53)
    assert g2.passed is True


def test_g2_fail_when_any_fold_below_0p52() -> None:
    g2 = MetaLabelerValidator._gate_g2(np.array([0.60, 0.51, 0.55]))
    assert g2.passed is False


# --------------------------------------------------------------------
# G4 - PBO < 0.10
# --------------------------------------------------------------------


def test_g4_pass_when_oos_winner_matches_inner_winner() -> None:
    tuning = _trial_grid(n_outer=4, oos_lift=0.05)
    g4, pbo = MetaLabelerValidator._gate_g4(tuning)
    assert g4.name == "G4_pbo"
    assert g4.threshold == pytest.approx(0.10)
    assert g4.passed is True
    assert pbo < 0.10


def test_g4_fail_when_trial_ledger_is_empty() -> None:
    empty = TuningResult(
        best_hyperparameters_per_fold=(),
        best_oos_auc_per_fold=(),
        all_trials=(),
        stability_index=0.0,
        wall_clock_seconds=0.0,
    )
    with pytest.raises(ValueError, match="all_trials is empty"):
        MetaLabelerValidator._gate_g4(empty)


def test_g4_fail_when_only_one_distinct_trial_id() -> None:
    hp = {"n_estimators": 30, "max_depth": 3, "min_samples_leaf": 5}
    trials = tuple(
        (dict(hp), 0.55 + 0.01 * o, 0.55 + 0.01 * o) for o in range(4)
    )
    tuning = TuningResult(
        best_hyperparameters_per_fold=tuple(dict(hp) for _ in range(4)),
        best_oos_auc_per_fold=tuple(0.55 + 0.01 * o for o in range(4)),
        all_trials=trials,
        stability_index=1.0,
        wall_clock_seconds=0.0,
    )
    with pytest.raises(ValueError, match="at least 2 distinct"):
        MetaLabelerValidator._gate_g4(tuning)


# --------------------------------------------------------------------
# G5 - Brier ≤ 0.25
# --------------------------------------------------------------------


def test_g5_pass_when_mean_brier_at_or_below_0p25() -> None:
    g5 = MetaLabelerValidator._gate_g5(np.array([0.20, 0.22, 0.18]))
    assert g5.name == "G5_brier"
    assert g5.passed is True


def test_g5_fail_when_mean_brier_above_0p25() -> None:
    g5 = MetaLabelerValidator._gate_g5(np.array([0.30, 0.28, 0.27]))
    assert g5.passed is False


def test_g5_boundary_at_exactly_0p25_passes() -> None:
    g5 = MetaLabelerValidator._gate_g5(np.array([0.25, 0.25, 0.25]))
    assert g5.passed is True


# --------------------------------------------------------------------
# G6 - minority frequency three-state
# --------------------------------------------------------------------


def test_g6_pass_when_minority_above_0p10() -> None:
    y = np.array([0] * 70 + [1] * 30, dtype=np.int_)  # 30% minority
    g6 = MetaLabelerValidator._gate_g6(y)
    assert g6.name == "G6_minority_freq"
    assert g6.value == pytest.approx(0.30)
    assert g6.passed is True


def test_g6_warn_state_still_passes() -> None:
    """5 % ≤ freq < 10 % is a warn but still passes."""
    y = np.array([0] * 92 + [1] * 8, dtype=np.int_)  # 8% minority
    g6 = MetaLabelerValidator._gate_g6(y)
    assert g6.passed is True
    assert g6.value == pytest.approx(0.08)


def test_g6_reject_state_fails() -> None:
    y = np.array([0] * 97 + [1] * 3, dtype=np.int_)  # 3% minority
    g6 = MetaLabelerValidator._gate_g6(y)
    assert g6.passed is False


# --------------------------------------------------------------------
# G7 - RF − LogReg mean AUC ≥ 0.03
# --------------------------------------------------------------------


def test_g7_pass_when_rf_beats_logreg_by_at_least_0p03() -> None:
    g7 = MetaLabelerValidator._gate_g7(
        np.array([0.60, 0.62, 0.61]),
        np.array([0.55, 0.56, 0.55]),
    )
    assert g7.name == "G7_rf_minus_logreg"
    assert g7.value == pytest.approx(0.61 - 0.5533333, rel=1e-3)
    assert g7.passed is True


def test_g7_fail_when_rf_only_marginally_better() -> None:
    g7 = MetaLabelerValidator._gate_g7(
        np.array([0.60, 0.61, 0.60]),
        np.array([0.59, 0.60, 0.59]),
    )
    assert g7.passed is False


def test_g7_fails_when_logreg_baseline_missing(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    """ADR-0005 D5 G7 footnote forbids silent pass on missing baseline."""
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result(logreg_aucs=())
    tuning = _trial_grid(n_outer=cpcv.get_n_splits())
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    with pytest.raises(ValueError, match="logreg_auc_per_fold"):
        validator.validate(training, tuning, fs, y, w, bars)


# --------------------------------------------------------------------
# Validator.__init__ + input validation
# --------------------------------------------------------------------


def test_validator_default_scenario_is_realistic(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    v = MetaLabelerValidator(cpcv=cpcv)
    # Use dataclasses.asdict / attribute access; private but stable.
    assert v._scenario == CostScenario.REALISTIC


def test_validate_rejects_empty_rf_auc_per_fold(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result(rf_aucs=(), logreg_aucs=(), rf_briers=())
    tuning = _trial_grid(n_outer=cpcv.get_n_splits())
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    with pytest.raises(ValueError, match="rf_auc_per_fold is empty"):
        validator.validate(training, tuning, fs, y, w, bars)


def test_validate_rejects_length_mismatch_rf_logreg(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result(
        rf_aucs=(0.6, 0.6, 0.6),
        logreg_aucs=(0.55, 0.55),
        rf_briers=(0.2, 0.2, 0.2),
    )
    tuning = _trial_grid(n_outer=cpcv.get_n_splits())
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    with pytest.raises(ValueError, match="must have the same"):
        validator.validate(training, tuning, fs, y, w, bars)


def test_validate_rejects_y_length_mismatch(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result()
    tuning = _trial_grid(n_outer=cpcv.get_n_splits())
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    bad_y = y[:-1]
    with pytest.raises(ValueError, match="y has"):
        validator.validate(training, tuning, fs, bad_y, w, bars)


def test_validate_rejects_sample_weight_length_mismatch(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result()
    tuning = _trial_grid(n_outer=cpcv.get_n_splits())
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    bad_w = w[:-1]
    with pytest.raises(ValueError, match="sample_weights has"):
        validator.validate(training, tuning, fs, y, bad_w, bars)


def test_validate_rejects_empty_best_hyperparameters(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=80, seed=0)
    training = _baseline_result()
    tuning = TuningResult(
        best_hyperparameters_per_fold=(),
        best_oos_auc_per_fold=(),
        all_trials=(({"n_estimators": 30, "max_depth": 3, "min_samples_leaf": 5}, 0.6, 0.6),) * 2,
        stability_index=0.0,
        wall_clock_seconds=0.0,
    )
    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    with pytest.raises(ValueError, match="best_hyperparameters_per_fold is empty"):
        validator.validate(training, tuning, fs, y, w, bars)


# --------------------------------------------------------------------
# End-to-end happy path: small 4.3 → 4.4 → 4.5 pipeline
# --------------------------------------------------------------------


def test_end_to_end_validation_returns_report_with_seven_gates(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    fs, y, w, bars = _synthetic_dataset(n=160, seed=42)

    baseline = BaselineMetaLabeler(cpcv=cpcv, seed=42)
    training_result = baseline.train(fs, y, w)

    tuner = NestedCPCVTuner(
        search_space=TuningSearchSpace(
            n_estimators=(30, 60),
            max_depth=(3, 5),
            min_samples_leaf=(5, 10),
        ),
        outer_cpcv=cpcv,
        inner_cpcv=CombinatoriallyPurgedKFold(
            n_splits=3, n_test_splits=1, embargo_pct=0.0
        ),
        seed=42,
    )
    tuning_result = tuner.tune(fs, y, w)

    validator = MetaLabelerValidator(
        cpcv=cpcv, cost_scenario=CostScenario.REALISTIC, seed=42
    )
    report = validator.validate(training_result, tuning_result, fs, y, w, bars)

    assert isinstance(report, MetaLabelerValidationReport)
    assert len(report.gates) == 7
    names = [g.name for g in report.gates]
    assert names == [
        "G1_mean_auc",
        "G2_min_auc",
        "G3_dsr",
        "G4_pbo",
        "G5_brier",
        "G6_minority_freq",
        "G7_rf_minus_logreg",
    ]
    # ``all_passed`` and ``failing_gate_names`` must be self-consistent.
    expected_failing = tuple(g.name for g in report.gates if not g.passed)
    assert report.failing_gate_names == expected_failing
    assert report.all_passed == (len(expected_failing) == 0)
    assert report.scenario_realistic_round_trip_bps == pytest.approx(10.0)


def test_end_to_end_failing_gates_listed_in_canonical_order(
    cpcv: CombinatoriallyPurgedKFold,
) -> None:
    """Manufacture failures in G1, G5, G7 - failing_gate_names must keep G1→G7 order."""
    fs, y, w, bars = _synthetic_dataset(n=160, seed=42)

    baseline = BaselineMetaLabeler(cpcv=cpcv, seed=42)
    training_result = baseline.train(fs, y, w)
    # Force G1 fail (mean < 0.55), G5 fail (Brier > 0.25), G7 fail
    # (RF − LogReg < 0.03) by overriding the per-fold tuples.
    tampered = dataclasses.replace(
        training_result,
        rf_auc_per_fold=tuple([0.51] * len(training_result.rf_auc_per_fold)),
        logreg_auc_per_fold=tuple(
            [0.50] * len(training_result.logreg_auc_per_fold)
        ),
        rf_brier_per_fold=tuple([0.30] * len(training_result.rf_brier_per_fold)),
    )

    tuner = NestedCPCVTuner(
        search_space=TuningSearchSpace(
            n_estimators=(30, 60),
            max_depth=(3, 5),
            min_samples_leaf=(5, 10),
        ),
        outer_cpcv=cpcv,
        inner_cpcv=CombinatoriallyPurgedKFold(
            n_splits=3, n_test_splits=1, embargo_pct=0.0
        ),
        seed=42,
    )
    tuning_result = tuner.tune(fs, y, w)

    validator = MetaLabelerValidator(cpcv=cpcv, seed=42)
    report = validator.validate(tampered, tuning_result, fs, y, w, bars)

    failing = list(report.failing_gate_names)
    # Canonical G1→G7 ordering must be preserved.
    canonical = ["G1_mean_auc", "G5_brier", "G7_rf_minus_logreg"]
    assert all(name in failing for name in canonical)
    found_indices = [failing.index(n) for n in canonical]
    assert found_indices == sorted(found_indices)


# --------------------------------------------------------------------
# GateResult shape contract
# --------------------------------------------------------------------


def test_gate_result_is_frozen_dataclass() -> None:
    g = GateResult(name="G1_mean_auc", value=0.6, threshold=0.55, passed=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.value = 0.0  # type: ignore[misc]
