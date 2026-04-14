# Phase 4.4 — Pre-Implementation Audit

**Issue**: #128
**Branch**: `phase/4.4-nested-tuning`
**Author**: Clément Barbier (with Claude Code)
**Date**: 2026-04-14
**Status**: PRE-IMPLEMENTATION — no code written yet
**Predecessor**: Phase 4.3 merged (PR #140, commit `d5dc3a0`), mid-phase
leakage audit PASS (issue #134, branch `phase/4-leakage-audit`).

Reference: `docs/phases/PHASE_4_SPEC.md` §3.4;
`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D4.

---

## 1. Objective

Run a nested CPCV hyperparameter search for the Random Forest
Meta-Labeler delivered in Phase 4.3, producing:

- per-outer-fold best hyperparameter dictionary,
- per-outer-fold best OOS AUC (from the inner-selected hparam
  re-evaluated on the outer test slice),
- a full trial ledger (every `(hparams, inner_cv_auc, oos_auc)` tuple)
  for Phase 4.5's PBO computation,
- a scalar stability index describing how often outer folds agree on
  the same best hyperparameters,
- wall-clock timing for the sub-phase PR body.

Deterministic outputs under `APEX_SEED=42`.

## 2. Reuse inventory

Before writing any new code, Phase 4.4 already has access to:

| Component | Location | Phase 4.4 usage |
|---|---|---|
| `CombinatoriallyPurgedKFold` | `features/cv/cpcv.py` | outer + inner splitter |
| `MetaLabelerFeatureSet` | `features/meta_labeler/feature_builder.py` | typed feature container with `t0`, `t1` |
| `FEATURE_NAMES` | same | canonical 8-column order |
| `fold_auc` | `features/meta_labeler/metrics.py` | weighted ROC-AUC per fold |
| `RandomForestClassifier` (sklearn) | `sklearn.ensemble` | classifier under tuning |
| Validation scaffolding | `BaselineMetaLabeler._validate_inputs` pattern (reference) | mirror for `NestedCPCVTuner` |

No modifications to 4.3 code are needed or intended. 4.4 is strictly
additive: a single new module `features/meta_labeler/tuning.py`, a new
test module `tests/unit/features/meta_labeler/test_tuning.py`, and a
report generator `scripts/generate_phase_4_4_report.py`.

## 3. API contract (as specified in §3.4)

Verbatim from `PHASE_4_SPEC.md` §3.4 lines 634–671:

```python
@dataclass(frozen=True)
class TuningSearchSpace:
    n_estimators: tuple[int, ...] = (100, 300, 500)
    max_depth: tuple[int | None, ...] = (5, 10, None)
    min_samples_leaf: tuple[int, ...] = (5, 20)
    # 3 × 3 × 2 = 18 trials per outer fold

@dataclass(frozen=True)
class TuningResult:
    best_hyperparameters_per_fold: tuple[dict[str, Any], ...]
    best_oos_auc_per_fold: tuple[float, ...]
    all_trials: tuple[tuple[dict[str, Any], float, float], ...]
    stability_index: float
    wall_clock_seconds: float

class NestedCPCVTuner:
    def __init__(
        self,
        search_space: TuningSearchSpace,
        outer_cpcv: CombinatoriallyPurgedKFold,
        inner_cpcv: CombinatoriallyPurgedKFold,
        seed: int = 42,
    ) -> None: ...

    def tune(
        self,
        features: MetaLabelerFeatureSet,
        y: np.ndarray,
        sample_weights: np.ndarray,
    ) -> TuningResult: ...
```

The contract is frozen — any deviation must be justified and flagged
in the PR body.

## 4. Algorithm skeleton

```
start_timer
for fold_idx, (train_idx, test_idx) in enumerate(outer_cpcv.split(...)):
    best_score   = -inf
    best_hparams = None
    fold_trials  = []

    for hparams in search_space.grid():          # 18 trials
        inner_aucs = []
        for inner_train_idx, inner_test_idx in inner_cpcv.split(
                x[train_idx], t1[train_idx], t0[train_idx]):
            rf = RandomForestClassifier(
                **hparams,
                class_weight="balanced",
                random_state=seed + fold_idx * 7,
                n_jobs=1,
            )
            rf.fit(
                x[train_idx][inner_train_idx],
                y[train_idx][inner_train_idx],
                sample_weight=w[train_idx][inner_train_idx],
            )
            prob = rf.predict_proba(x[train_idx][inner_test_idx])[:, 1]
            inner_aucs.append(fold_auc(
                y[train_idx][inner_test_idx],
                prob,
                sample_weight=w[train_idx][inner_test_idx],
            ))
        mean_inner_auc = float(np.mean(inner_aucs))

        # Re-fit winner on the full outer train slice and score OOS
        # on the outer test slice for the all_trials ledger.
        rf_refit = RandomForestClassifier(
            **hparams, class_weight="balanced",
            random_state=seed + fold_idx * 7, n_jobs=1)
        rf_refit.fit(x[train_idx], y[train_idx], sample_weight=w[train_idx])
        oos_prob = rf_refit.predict_proba(x[test_idx])[:, 1]
        oos_auc = fold_auc(y[test_idx], oos_prob, sample_weight=w[test_idx])
        fold_trials.append((hparams, mean_inner_auc, oos_auc))

        if mean_inner_auc > best_score:
            best_score   = mean_inner_auc
            best_hparams = hparams

    # Best for this outer fold is the one that maximised mean inner AUC.
    best_oos_auc = next(
        oos for (hp, _, oos) in fold_trials if hp == best_hparams
    )
    record best_hparams, best_oos_auc, fold_trials

stability_index = fraction of outer folds whose best_hparams
                  equal the mode across outer folds
wall_clock      = stop_timer - start_timer
```

Key invariants enforced by the algorithm, not just spec:

- Inner search is strictly inside the outer training slice. No outer
  test index is ever passed to any inner fit. Verified by an
  anti-leakage property test (§7 below).
- Inner-AUC is the selection criterion; OOS-AUC is *observed*, never
  used to pick the winner. Decoupling the two is what makes the nested
  CV honest and makes the 4.5 PBO computation well-defined.
- The winning RF is re-fitted on the outer training slice before OOS
  scoring, so the per-fold OOS AUC reflects the chosen hparams on the
  exact data available at the outer fold's decision time.

## 5. Budget and determinism

- **Trial count**: 3 × 3 × 2 = 18 inner search points.
- **Inner CV**: `n_splits=4, n_test_splits=1` → C(4, 1) = 4 folds.
- **Outer CV**: `n_splits=6, n_test_splits=2, embargo_pct=0.02`
  → C(6, 2) = 15 folds (unchanged from 4.3).
- **Fits per run**: 18 × 4 × 15 = 1,080 inner fits + 18 × 15 = 270
  outer-refits = **1,350 RF fits per full run**.
- **Wall-clock estimate**: ≤ 2 s per fit with `n_jobs=1` and
  `n_estimators ≤ 500` on synthetic n=1,200 → ~45 min on single-core,
  ~5–8 min with `n_jobs=-1`. Tests use n=400 + Inner(4,1) + Outer(4,2)
  to keep the test suite under ~1 minute.
- **Seed discipline**: every RF is instantiated with
  `random_state = seed + fold_index × 7`. Test pins determinism.

## 6. Test plan (minimum 14 tests)

Organised into six groups; every test has a named function below.

**A. Search-space primitives**
1. `test_search_space_cardinality_18_trials`
2. `test_search_space_grid_returns_all_combinations_once`
3. `test_search_space_reject_empty_n_estimators_tuple`

**B. Happy path and shapes**
4. `test_tune_returns_tuning_result_with_expected_shapes`
5. `test_best_hparams_per_fold_length_equals_outer_n_splits`
6. `test_all_trials_length_equals_n_outer_x_search_cardinality`

**C. Determinism**
7. `test_nested_run_deterministic_same_seed`
8. `test_different_seed_produces_different_best_hparams_or_same_with_note`

**D. Stability index**
9. `test_stability_index_equals_one_when_all_folds_select_same_hparams`
10. `test_stability_index_less_than_one_on_heterogeneous_scenario`

**E. Input validation**
11. `test_empty_feature_matrix_raises`
12. `test_non_binary_y_raises`
13. `test_negative_sample_weight_raises`
14. `test_search_space_overriding_random_state_raises`

**F. Anti-leakage property**
15. `test_inner_search_never_touches_outer_test_indices`
    — mutates the outer-test slice of `x` in-place between inner search
    calls (via a monkeypatched fit spy) and asserts the inner-CV AUC
    vector is unchanged, proving the inner loop does not read outer
    test data.

**G. Wall-clock**
16. `test_wall_clock_seconds_is_positive_and_finite`

**H. Side-effect invariants**
17. `test_class_weight_balanced_propagated_to_every_rf_fit`
18. `test_sample_weights_sliced_consistently_between_inner_and_outer`

That is 18 tests — above the §3.4 minimum of 14. Coverage target on
`tuning.py`: ≥ 88%.

## 7. Anti-leakage proof obligations

The sub-phase must prove that no outer-test data reaches any inner
fit. The property test (F.15 above) does this by:

1. Run the tuner once on `(features, y, w)` and record
   `result_baseline.all_trials`.
2. Mutate `features.X[outer_test_idx]` in-place with a random
   permutation for each outer fold *before* calling `.tune()` on a
   shallow-copy pipeline.
3. Record `result_permuted.all_trials`.
4. Assert that the *inner-CV-mean AUC* column of each trial tuple is
   unchanged: only the OOS column (which *does* depend on the outer
   test slice) may differ.

This is a stronger invariant than just "inner uses train_idx only" — it
catches any bug that accidentally routes `test_idx` rows into an inner
fit or scorer.

## 8. Deliverables checklist

- [ ] `features/meta_labeler/tuning.py` (~300–400 LOC, `mypy --strict`
      clean, `ruff` clean)
- [ ] `tests/unit/features/meta_labeler/test_tuning.py` (≥ 18 tests,
      ≥ 88 % coverage on `tuning.py`)
- [ ] `scripts/generate_phase_4_4_report.py` (synthetic data with
      calibrated alpha, writes `reports/phase_4_4/tuning_report.md` +
      `tuning_trials.json`)
- [ ] `reports/phase_4_4/tuning_report.md` generated with
      `APEX_SEED=42` under the reduced-grid test configuration (not the
      production 1,080 fits — the full run is executed in CI on-demand
      behind a `APEX_FULL_TUNING=1` flag)
- [ ] Memory docs updated (`CONTEXT.md`, `SESSIONS.md`,
      `PHASE_4_NOTES.md` if present)
- [ ] PR #(new) opened against `main`, Copilot review cycle

## 9. Out of scope

- Bayesian / evolutionary search (deferred to a future phase — 4.4
  is grid-only per ADR-0005 D4).
- LogReg tuning: the baseline stays untuned by design to prevent
  overfit-by-search on the comparator (ADR-0005 D3 rationale).
- Multi-classifier tuning (deferred).
- DSR / PBO on the tuning trials (that's Phase 4.5 §3.5, gate G4/G5).
- Wiring the tuner into `scripts/generate_phase_4_3_report.py` — the
  4.3 report remains untuned per spec.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| 1,080+ fits × 15 outer folds blow the CI budget. | Default script uses reduced grid/outer for CI (n=400, Outer(4,2)=6, Inner(3,1)=3, grid=8 → 144 fits ≤ 30 s wall-clock). Production grid gated behind `APEX_FULL_TUNING=1`. |
| `GridSearchCV` does not natively support CPCV (it assumes a scikit-learn CV splitter that yields (train, test) indices — CPCV does, but the scoring path needs `sample_weight`, which `GridSearchCV`'s `fit_params` handles asymmetrically across sklearn versions). | Implement the nested loop **explicitly** (no `GridSearchCV`), as sketched in §4. Gives full control over sample_weight routing and per-fold seeding. The §3.4 spec language says "`GridSearchCV` over a defined search space"; the explicit implementation is behaviourally equivalent and correctness-superior for CPCV + weighted AUC. Documented in this audit. |
| Determinism breaks on `max_depth=None` (unbounded trees, noisier). | Seeding is per-fold (`seed + fold_idx × 7`). Test F.7 pins bit-exact determinism across two runs; if `max_depth=None` proves flaky, drop it from the default grid and document. |

## 11. References

- `docs/phases/PHASE_4_SPEC.md` §3.4 (Phase 4.4 specification).
- `docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D4 (nested
  CPCV rationale).
- López de Prado (2018) *Advances in Financial Machine Learning*
  §7.4 (nested CV premise — no leakage allowed between inner and
  outer loops).
- `features/meta_labeler/baseline.py` (Phase 4.3 — trainer reused
  pattern).
- `reports/phase_4_leakage_audit.md` (mid-phase-4 audit — issue
  #134 — verdict PASS).
