# PHASE 4 — Fusion Engine + Meta-Labeler — Specification

**Status**: Design-gate proposed — 2026-04-14
**Related ADRs**: ADR-0002 (Quant Methodology Charter), ADR-0004
(Feature Validation), **ADR-0005** (Meta-Labeling and Fusion
Methodology — this spec operationalizes that ADR).
**Branch**: `design-gate/phase-4`
**Predecessor**: Phase 3 (closed via PR #124).
**Successor**: Phase 5 (streaming integration + production wiring).

---

## 1. Objective

Phase 4 builds the **decision layer** that sits above the Phase 3
signal calculators:

1. A supervised binary classifier (the "Meta-Labeler") that learns
   `p(profitable trade after costs | features)` and emits a
   calibrated probability used as a Kelly bet-size multiplier.
2. A fusion computation that combines the N activated Phase 3
   signals into a single scalar per `(symbol, timestamp)`.

Phase 4 is **offline** (batch training + batch evaluation). Wiring
into the live S02 → S04 pipeline is Phase 5 work.

**Hard dependency chain (three-times-repeated rule):**

```
4.1 Triple Barrier
      ↓
4.2 Sample Weights
      ↓
4.3 Baseline Meta-Labeler
      ↓
4.4 Nested Tuning
      ↓
4.5 Statistical Validation
      ↓
4.6 Persistence + Model Card
      ↓
4.7 Fusion Engine (independent of 4.3-4.6 in principle, but
    benefits from having model card schema from 4.6)
      ↓
4.8 End-to-end Pipeline Test
      ↓
4.9 Phase 4 Closure
```

Triple Barrier (4.1) MUST land before sample weights (4.2), which
MUST land before the classifier (4.3). This is a **hard dependency**,
not a sequencing preference. Meta-Labeler training without
`BarrierLabel` data does not exist. This is restated: **Triple
Barrier before Meta-Labeler. Sample Weights before training. No
exceptions.**

---

## 2. Existing Infrastructure Assessment (audit 2026-04-14)

Phase 4 is emphatically **not** greenfield. A pre-merge audit found
substantial existing infrastructure. The sub-phase specs below are
written against this reality — each module calls out whether it
extends existing code or creates new code, and why.

### 2.1 Reusable as-is (direct import, no modification)

| Component | Path | Used by |
|---|---|---|
| `CombinatoriallyPurgedKFold` | `features/cv/cpcv.py` | 4.3, 4.4 |
| `DeflatedSharpeCalculator` | `features/hypothesis/dsr.py` | 4.5 |
| `PBOCalculator` | `features/hypothesis/pbo.py` | 4.5 |
| `holm_bonferroni`, `benjamini_hochberg` | `features/hypothesis/mht.py` | 4.5 |
| `build_report` | `features/hypothesis/report.py` | 4.5 |
| `FeatureActivationConfig` | `features/integration/config.py` | 4.3 |
| `ICReport`, `ICResult` | `features/ic/` | 4.7 |
| `MulticollinearityReport` | `features/multicollinearity.py` | 4.7 (optional guard) |
| Transaction cost model (3 scenarios) | `backtesting/metrics.py` | 4.5, 4.8 |
| `BacktestingEngine` | `backtesting/engine.py` | 4.8 (optional) |

### 2.2 To extend (existing code, additive changes only)

| Component | Path | Extension in sub-phase |
|---|---|---|
| `TripleBarrierLabeler`, `BarrierLabel` | `core/math/labeling.py` | 4.1 adds binary-target projection + explicit `t0`/`t1` accessors. Ternary labels stay. |
| `TripleBarrierLabelerAdapter` | `features/labels.py` | 4.1 adds batch labeling from an `events` DataFrame + optional direction column. |
| `CombinatoriallyPurgedKFold.split(X, t1)` | `features/cv/cpcv.py` | 4.2 may add an optional `t0` argument backward-compatibly (non-breaking default). Decision deferred to 4.2 implementation; only taken if required. |

### 2.3 To create (no pre-existing equivalent)

| Module | Sub-phase | Reason |
|---|---|---|
| `features/labeling/sample_weights.py` | 4.2 | Uniqueness + return-attribution weights do not exist anywhere in the repo. |
| `features/meta_labeler/baseline.py` | 4.3 | Existing `services/fusion_engine/meta_labeler.py` is a deterministic rules scorer, not a trained classifier. Phase 4 introduces the trained-classifier path as a sibling module that will eventually replace the deterministic scorer in Phase 5 wiring. |
| `features/meta_labeler/feature_builder.py` | 4.3 | Assembles the 8-feature Meta-Labeler input from Phase 3 signals + regime state + time-of-day features. No pre-existing builder. |
| `features/meta_labeler/tuning.py` | 4.4 | Nested CPCV hyperparameter search; new. |
| `features/meta_labeler/validation.py` | 4.5 | Thin wrapper over `features/hypothesis/` for the ML P&L path. New. |
| `features/meta_labeler/persistence.py` | 4.6 | joblib serialization + ModelCard schema v1. New. |
| `features/fusion/ic_weighted.py` | 4.7 | The existing `services/fusion_engine/` computes a different fusion (confluence × regime × mtf); Phase 4 adds the IC-weighted library computation as a distinct module. |
| `tests/integration/test_phase_4_pipeline.py` | 4.8 | New E2E test mirroring `tests/integration/test_phase_3_pipeline.py`. |
| `docs/phase_4_closure_report.md` | 4.9 | Mirrors `docs/phase_3_closure_report.md`. |

### 2.4 Deliberately NOT modified by Phase 4

| Path | Reason |
|---|---|
| `services/signal_engine/` | S02 is frozen; Phase 3.13 adapter is the integration seam. |
| `services/regime_detector/` | Read-only consumer; no modifications. |
| `services/fusion_engine/` | The existing deterministic `MetaLabeler` stays in place until Phase 5 wiring replaces `.score()` with trained-classifier inference. Two paths co-exist during the 4.x window, which is an explicit audit-trail note in ADR-0005 §3. |
| `services/risk_manager/` | `MetaLabelGate` interface is frozen; Phase 4 persists to the Redis key `meta_label:latest:{symbol}` that S05 reads. No code changes to S05 in Phase 4. |

### 2.5 Informal terminology notes

- ADR-0002 does **not** define `OBJ-0`/`OBJ-5` objectives. Existing
  docstrings in `core/math/labeling.py` and
  `services/risk_manager/circuit_breaker.py` reference those
  strings informally; they are not a canonical ADR-0002 contract.
  Phase 4 references ADR-0005 decision numbers (`D1`, `D2`, …)
  exclusively.

---

## 3. Sub-phase specifications

Each sub-phase below uses the same template: Objective, Scope,
Module structure, Public API, Inputs, Outputs, Algorithm notes,
Tests specification, Anti-leakage checks, DoD, Dependencies,
Estimated scope, References.

---

## 3.1 Sub-phase 4.1 — Triple Barrier Labeling

### Objective
Emit a canonical binary-target label per entry event in a
Polars-native batch pipeline that extends the existing
`TripleBarrierLabeler`. Produce a reproducible label-set for
Meta-Labeler training.

### Scope
- **IN**: binary projection `{0, 1}`; batch labeling from an events
  DataFrame; explicit `t0` (entry time) and `t1` (exit time)
  accessors on every label; labels-diagnostics report.
- **OUT**: short-side labeling (deferred to Phase 4.X); online /
  streaming labeling (Phase 5).

### Module structure
```
features/labeling/
├── __init__.py
├── triple_barrier.py          # re-exports core/math/labeling + binary projection
├── events.py                  # event-time construction helpers
└── diagnostics.py             # label distribution + barrier-hit stats

tests/unit/features/labeling/
├── __init__.py
├── test_triple_barrier_binary.py        (~12 tests)
├── test_events_construction.py          (~6 tests)
├── test_diagnostics.py                  (~5 tests)
└── test_integration_with_bar_data.py    (~3 tests synthetic)
```

### Public API
```python
# features/labeling/triple_barrier.py
from core.math.labeling import (
    BarrierLabel, BarrierResult, TripleBarrierConfig,
    TripleBarrierLabeler,
)

def to_binary_target(label: BarrierLabel) -> int:
    """Binary Meta-Labeler target: 1 iff upper-barrier hit, else 0.

    Per ADR-0005 D1, vertical and lower hits both map to 0.
    """
    ...

def label_events_binary(
    events: pl.DataFrame,           # columns: timestamp, symbol, direction, price
    bars: pl.DataFrame,             # columns: timestamp, symbol, close, high, low
    config: TripleBarrierConfig,
) -> pl.DataFrame:
    """Batch labeler. Returns columns:
        symbol, t0, t1, entry_price, exit_price,
        ternary_label, binary_target, barrier_hit, holding_periods
    """
    ...
```

### Inputs
- `events`: `pl.DataFrame` with columns
  `[timestamp: Datetime[UTC], symbol: Utf8, direction: Int8, price: Decimal]`.
  `direction ∈ {+1}` for Phase 4 MVP (long-only per ADR-0005 D1).
- `bars`: `pl.DataFrame` with `[timestamp: Datetime[UTC], symbol: Utf8, high, low, close: Decimal]`
  sorted by symbol then timestamp.
- `config`: `TripleBarrierConfig(pt_multiplier=2.0, sl_multiplier=1.0,
  max_holding_periods=60, vol_lookback=20)`.

### Outputs
- `pl.DataFrame` with one row per event, columns above.
- Optional write: `reports/phase_4_1/labels_{run_id}.parquet` + sidecar
  `labels_diagnostics.md` with:
  - Label distribution (% binary 0 vs 1).
  - Barrier-hit distribution (upper / lower / vertical).
  - Median holding periods; P5 / P95.
  - Per-symbol breakdown.

### Algorithm notes
- Volatility σ_t uses EWMA of squared log returns with `span =
  vol_lookback`. The window must end strictly **before** `t` (no
  peek into the labeled bar). A property-based test verifies this
  by injecting a synthetic shock exactly at `t` and confirming the
  label is unchanged.
- The labeler processes events one at a time internally (existing
  `TripleBarrierLabeler.label_event` loop) but wraps them in a
  vectorized Polars `group_by(symbol)` outer iteration. O(n_events)
  for Phase 4 MVP; streaming optimization is Phase 5.
- UTC-only timestamps; naive datetime raises `ValueError` with the
  fail-loud pattern established in Phase 3.

### Tests specification
Minimum 26 tests total across the submodule. Selected cases:
- `test_binary_target_upper_hit_is_1`
- `test_binary_target_lower_hit_is_0`
- `test_binary_target_vertical_hit_is_0`
- `test_label_events_binary_returns_expected_schema`
- `test_vol_window_strictly_before_t` (property-based)
- `test_naive_datetime_raises_valueerror`
- `test_unsorted_events_raises_valueerror`
- `test_empty_events_returns_empty_frame_no_error`
- `test_single_event_no_future_bars_timeout_label_0`
- `test_config_pt_multiplier_zero_raises`
- `test_config_vol_lookback_less_than_2_raises`
- `test_reproducible_same_seed_same_labels`
- `test_diagnostics_class_balance_reported`
- `test_diagnostics_barrier_hit_reported`
- `test_integration_realistic_bar_data_100_events`
- `test_short_direction_raises_not_implemented` (long-only MVP, ADR-0005 D1)
- (+ 10 additional parametrized / edge cases)

### Anti-leakage checks specific to this sub-phase
- Property test: injecting a shock at bar `t` must not change the
  label for an event at `t` (because σ_t is computed strictly
  from bars `< t`).
- Property test: swapping a future bar's close with NaN must not
  change an already-emitted label if the vertical barrier has
  already been reached.

### DoD
1. All tests passing, coverage ≥ 90 % on `features/labeling/`.
2. `mypy --strict features/labeling/` clean.
3. `ruff check features/labeling/` clean.
4. `reports/phase_4_1/labels_diagnostics.md` generated with
   reproducible numbers from a fixed synthetic scenario
   (APEX_SEED=42).
5. No modifications to `services/`, `core/` (except possibly
   adding a single `to_binary_target()` helper to
   `core/math/labeling.py` if deemed cleaner in review — the spec
   allows either location), or other `features/` submodules.
6. `BarrierLabel` public API is unchanged; additions are additive.

### Dependencies
None (first sub-phase).

### Estimated scope
- LOC: ~200–350 (the existing labeler does the heavy lifting).
- Tests: ~26.
- Complexity: **low** (wrapping existing well-tested code).
- Expected Copilot review cycles: **1**.

### References
- López de Prado (2018) §3.4 pp. 45–49.
- ADR-0005 D1.
- Existing code: `core/math/labeling.py`, `features/labels.py`.

---

## 3.2 Sub-phase 4.2 — Sample Weights (uniqueness × return attribution)

### Objective
Compute per-sample training weights that correct for the
effective-sample-size inflation caused by overlapping label spans
(uniqueness) and for the P&L magnitude attributable to each
span (return attribution).

### Scope
- **IN**: uniqueness weights (López de Prado §4.4), return
  attribution weights (§4.5), combined weight `w = u × r`
  normalized so `sum(w) = n`.
- **OUT**: time-decay weights (§4.10; deferred), class-balance
  resampling (handled by `class_weight="balanced"` per ADR-0005 D3).

### Module structure
```
features/labeling/
├── sample_weights.py          (NEW)

tests/unit/features/labeling/
├── test_sample_weights_uniqueness.py    (~10 tests)
├── test_sample_weights_attribution.py   (~8 tests)
└── test_sample_weights_combined.py      (~6 tests)
```

### Public API
```python
# features/labeling/sample_weights.py

def compute_concurrency(
    t0: pl.Series,       # label start times
    t1: pl.Series,       # label end times
    bars: pl.Series,     # bar index timestamps
) -> pl.Series:
    """Concurrency count c_t: number of active labels at each bar t."""
    ...

def uniqueness_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
) -> pl.Series:
    """u_i = mean(1 / c_t for t in [t0_i, t1_i])"""
    ...

def return_attribution_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
    log_returns: pl.Series,  # per-bar log returns
) -> pl.Series:
    """r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|"""
    ...

def combined_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
    log_returns: pl.Series,
) -> pl.Series:
    """w_i = u_i * r_i, normalized so sum(w) == n_samples."""
    ...
```

### Inputs
- `t0`, `t1`: UTC timestamps per sample (from sub-phase 4.1).
- `bars`: UTC bar timestamps covering the full label range.
- `log_returns`: per-bar log returns aligned with `bars`.

### Outputs
- `pl.Series[Float64]` of length `n_samples`, sum-normalized to `n`.
- Optional diagnostic: `reports/phase_4_2/weights_distribution.md`
  with histogram percentiles (P5 / P50 / P95) of `u`, `r`, and `w`.

### Algorithm notes
- Concurrency: vectorized interval intersection via Polars
  `group_by_dynamic` or bitmap construction, not Python loops.
  Target: O(n_bars + n_samples log n_samples) at most.
- Numerical stability: guard against `c_t = 0` (should not occur if
  bars cover label range, but emit `ValueError` fail-loud if it
  does; never silently skip).
- Normalization: after computing `w`, set `w := w × n / sum(w)`
  using Decimal-equivalent float precision. Accept `sum(w) == n`
  within `1e-9` tolerance.

### Tests specification
Minimum 24 tests. Selected cases:
- `test_concurrency_single_event_is_one`
- `test_concurrency_two_disjoint_events_is_one`
- `test_concurrency_two_overlapping_events_is_two`
- `test_uniqueness_disjoint_events_weight_is_one` (canonical reference)
- `test_uniqueness_overlapping_events_lower_weight`
- `test_uniqueness_matches_reference_table_LdP_4_4` (manual compute from the Table 4.1 scenario in López de Prado §4.4)
- `test_return_attribution_positive_by_construction` (|·|)
- `test_return_attribution_zero_returns_zero_weight`
- `test_combined_weights_sum_to_n_samples` (normalization invariant)
- `test_zero_concurrency_raises_valueerror` (fail-loud)
- `test_misaligned_bars_raises_valueerror`
- `test_naive_datetime_inputs_raise_valueerror`
- `test_reproducibility_deterministic`
- `test_empty_input_returns_empty_series_no_error`
- (+ 10 edge / parametrized cases)

### Anti-leakage checks specific to this sub-phase
- Weights depend only on `t0`, `t1`, bar range, and log returns
  **within** the label span. No future information is used to
  weight past samples. Test: shuffling future returns (post-t1)
  must not change any sample's weight.

### DoD
1. All tests passing, coverage ≥ 92 % on
   `features/labeling/sample_weights.py`.
2. `mypy --strict` clean.
3. `ruff` clean.
4. `reports/phase_4_2/weights_distribution.md` generated from a
   fixed synthetic overlap scenario and a fixed seed.
5. Performance: 10,000 samples × 100,000 bars in ≤ 30 s on a
   single CPU core (offline target).
6. Reference-table test against López de Prado §4.4 Table 4.1
   passes to within numerical tolerance.

### Dependencies
- Sub-phase 4.1 merged (weights require `t0`, `t1` from `BarrierLabel`).

### Estimated scope
- LOC: ~250–400.
- Tests: ~24.
- Complexity: **medium** (vectorization).
- Expected Copilot review cycles: **1–2**.

### References
- López de Prado (2018) §4.4 pp. 59–62, §4.5 pp. 62–65, Table 4.1.
- ADR-0005 D2.

---

## 3.3 Sub-phase 4.3 — Baseline Meta-Labeler (Random Forest)

### Objective
Train a Random Forest Meta-Labeler on the activated Phase 3
features + regime / time contextual features, using Triple Barrier
binary labels and sample weights. No hyperparameter tuning at this
stage — just a working end-to-end training pipeline with default
hyperparameters and mandatory LogisticRegression baseline per
ADR-0005 D3.

### Scope
- **IN**: feature assembly from Phase 3 signals + S03 regime state
  + realized volatility + time-of-day; RF training with
  `class_weight="balanced"`; LogReg baseline side-by-side; single
  CPCV run (no tuning); AUC / precision / recall / F1 / calibration
  curve metrics.
- **OUT**: hyperparameter tuning (→ 4.4); DSR/PBO validation
  (→ 4.5); persistence (→ 4.6); production wiring (Phase 5).

### Module structure
```
features/meta_labeler/
├── __init__.py
├── feature_builder.py         # assembles the 8-feature matrix
├── baseline.py                # RF + LogReg training
└── metrics.py                 # AUC, Brier, calibration curve helpers

tests/unit/features/meta_labeler/
├── __init__.py
├── test_feature_builder.py    (~14 tests)
├── test_baseline_training.py  (~10 tests)
└── test_baseline_metrics.py   (~6 tests)
```

### Public API
```python
# features/meta_labeler/feature_builder.py

@dataclass(frozen=True)
class MetaLabelerFeatureSet:
    X: np.ndarray        # shape (n_samples, 8)
    feature_names: tuple[str, ...]
    t0: np.ndarray       # label starts (for CPCV purging)
    t1: np.ndarray       # label ends

class MetaLabelerFeatureBuilder:
    def __init__(
        self,
        activation_config: FeatureActivationConfig,
        regime_history: pl.DataFrame,       # from S03, historical
        realized_vol_window: int = 28,
    ) -> None: ...

    def build(
        self,
        labels: pl.DataFrame,               # from 4.1
        signals: pl.DataFrame,              # from features/calculators
        bars: pl.DataFrame,
    ) -> MetaLabelerFeatureSet: ...


# features/meta_labeler/baseline.py

@dataclass(frozen=True)
class BaselineTrainingResult:
    rf_model: RandomForestClassifier
    logreg_model: LogisticRegression
    rf_auc_per_fold: tuple[float, ...]
    logreg_auc_per_fold: tuple[float, ...]
    rf_brier_per_fold: tuple[float, ...]
    rf_calibration_bins: tuple[tuple[float, float], ...]
    feature_importances: dict[str, float]

class BaselineMetaLabeler:
    def __init__(
        self,
        cpcv: CombinatoriallyPurgedKFold,
        rf_hyperparameters: dict[str, Any] | None = None,
        seed: int = 42,
    ) -> None: ...

    def train(
        self,
        features: MetaLabelerFeatureSet,
        y: np.ndarray,          # binary target
        sample_weights: np.ndarray,
    ) -> BaselineTrainingResult: ...
```

### Inputs
- Labels DataFrame from 4.1 (binary target, t0, t1).
- Sample weights from 4.2.
- Activated Phase 3 signals (loaded via `FeatureActivationConfig`).
- S03 regime history (timestamp, vol_regime, trend_regime,
  session_mult, macro_mult).
- Bar close prices for realized-volatility computation.

### Feature set (ADR-0005 feature schema, 8 features)
1. `gex_signal` (activated Phase 3)
2. `har_rv_signal` (activated Phase 3)
3. `ofi_signal` (activated Phase 3)
4. `regime_vol_code` (ordinal: LOW=0, NORMAL=1, HIGH=2, CRISIS=3)
5. `regime_trend_code` (ordinal: TRENDING_DOWN=-1, RANGING=0, TRENDING_UP=+1)
6. `realized_vol_28d` (rolling std of 28-day log returns, standardized)
7. `hour_of_day` (0–23, cyclical encoding: `sin(2π·h/24)` only,
   `cos` companion added if ablation shows benefit in 4.4)
8. `day_of_week` (0–6, one-hot is 7 dummies → exceeds 8-feature
   budget; for MVP encoded as `sin(2π·d/7)` cyclical)

Note: the cyclical encoding choice is driven by the 8-feature
budget in ADR-0005 D6 `features_used` list; alternative encodings
are a 4.4 ablation concern.

### Outputs
- `BaselineTrainingResult` with OOS AUC / Brier / calibration per
  fold for both RF and LogReg.
- `reports/phase_4_3/baseline_report.md` with:
  - Per-fold metrics table.
  - RF vs LogReg comparison.
  - Feature importances (RF `feature_importances_`).
  - Calibration curve (10-bin reliability plot data in JSON).

### Algorithm notes
- Every contextual feature MUST respect
  `feature_compute_window_end < label_t0`. Regime state at bar `t0`
  is read from the S03 history **as of** `t0` (not after).
  Realized-volatility at `t0` uses only bars strictly before `t0`.
  `hour_of_day` / `day_of_week` are derived from `t0` itself
  (no lookahead).
- RF default hyperparameters for MVP (per ADR-0005 D3 intent):
  `n_estimators=200`, `max_depth=10`, `min_samples_leaf=20`,
  `class_weight="balanced"`, `n_jobs=-1`, `random_state=APEX_SEED`.
- LogReg baseline: `class_weight="balanced"`, `max_iter=500`,
  `random_state=APEX_SEED`. Features are standardized per-fold.
- CPCV outer setup: `n_splits=6`, `n_test_splits=2`,
  `embargo_pct=0.02`. Inner tuning is out of 4.3 scope.
- Sample weights from 4.2 are passed via
  `fit(X, y, sample_weight=w)`.

### Tests specification
Minimum 30 tests total. Selected cases:
- `test_feature_builder_rejects_non_activated_feature`
- `test_feature_builder_regime_read_as_of_t0_not_after`
- `test_feature_builder_realized_vol_window_end_strict_lt_t0`
- `test_feature_builder_cyclical_encoding_wraps_correctly`
- `test_feature_builder_output_shape_matches_labels`
- `test_feature_builder_missing_regime_at_t0_raises_fail_loud`
- `test_baseline_rf_training_deterministic_same_seed`
- `test_baseline_logreg_baseline_always_trained` (per ADR-0005 D3)
- `test_baseline_auc_per_fold_returned`
- `test_baseline_feature_importances_sum_to_1_approx`
- `test_baseline_sample_weights_propagated_to_fit`
- `test_baseline_class_weight_balanced_applied`
- `test_baseline_calibration_bins_monotone_on_synthetic_alpha`
- `test_baseline_auc_gt_0p55_on_synthetic_alpha` (smoke gate, see DoD)
- `test_baseline_rf_minus_logreg_reported` (diagnostic, not hard gate at 4.3)
- (+ 15 edge cases)

### Anti-leakage checks specific to this sub-phase
- The "leakage audit checkpoint" (cross-cutting issue, see §5.1)
  runs **after** 4.3 and **before** 4.4 to verify every context
  feature respects `feature_window_end < t0`.
- Test: shuffling all bars **strictly after** `t1_max` across the
  dataset must not change any training-feature value.

### DoD
1. All tests passing, coverage ≥ 90 % on `features/meta_labeler/`.
2. `mypy --strict` clean.
3. `ruff` clean.
4. `reports/phase_4_3/baseline_report.md` generated from a fixed
   synthetic-alpha scenario with `APEX_SEED=42`, reproducible.
5. On the synthetic-alpha scenario: mean OOS AUC (RF) ≥ 0.55.
   This is a **smoke gate** confirming the pipeline works; the
   hard ADR-0005 D5 gates run at 4.5, not 4.3.
6. LogReg baseline is always trained alongside RF (per ADR-0005
   D3) — enforced by a test that fails if the `BaselineTrainingResult`
   has no `logreg_auc_per_fold`.

### Dependencies
- Sub-phase 4.2 merged.

### Estimated scope
- LOC: ~500–700.
- Tests: ~30.
- Complexity: **medium** (feature assembly + training loop).
- Expected Copilot review cycles: **2**.

### References
- López de Prado (2018) §3.6 pp. 50–55 (Meta-Labeling).
- Breiman (2001) Random Forests.
- ADR-0005 D3, D4, D6.

---

## 3.4 Sub-phase 4.4 — Nested Hyperparameter Tuning

### Objective
Run nested CPCV hyperparameter search for the Random Forest
Meta-Labeler, producing aggregate best hyperparameters per outer
fold and a stability report. Deterministic outputs under
`APEX_SEED=42`.

### Scope
- **IN**: `GridSearchCV` over a defined search space inside each
  outer CPCV training fold; aggregation of best hyperparameters
  across outer folds; stability diagnostics.
- **OUT**: Bayesian / evolutionary search (deferred); multi-classifier
  tuning (deferred); LogReg tuning (not needed — baseline stays
  untuned to prevent overfit-by-search on the baseline).

### Module structure
```
features/meta_labeler/
├── tuning.py                  (NEW)

tests/unit/features/meta_labeler/
├── test_tuning.py             (~14 tests)
```

### Public API
```python
# features/meta_labeler/tuning.py

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
        # (hyperparams, mean_inner_cv_auc, oos_auc) per trial per fold
    stability_index: float
        # Fraction of outer folds where best hyperparameters agree
        # with the modal choice. 1.0 = perfect stability.
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

### Inputs
- `MetaLabelerFeatureSet` from 4.3.
- Binary labels, sample weights.
- Search space (default as above).

### Outputs
- `TuningResult` dataclass.
- `reports/phase_4_4/tuning_report.md`:
  - Best hyperparams per outer fold (table).
  - `stability_index` value.
  - Trial count (documented: 18 inner × 4 inner folds × 15 outer
    folds = 1,080 fits).
  - Wall-clock timing.
- `reports/phase_4_4/tuning_trials.json` (machine-readable,
  consumed by 4.5 for PBO computation on tuning trials).

### Algorithm notes
- **Budget**: 3 × 3 × 2 = 18 inner search points × 4 inner CPCV
  folds × 15 outer CPCV folds ≈ 1,080 RF fits. Each fit ≤ 2 s
  with `n_jobs=-1` → wall-clock ≈ 35 min on 8-core hardware.
  Documented in the sub-phase PR.
- Inner CPCV: `n_splits=4`, `n_test_splits=1` → C(4, 1) = 4 folds.
- Inner objective: weighted mean AUC across inner folds
  (`sample_weight=w_val` per inner test fold).
- Stability index formula: fraction of outer folds whose best
  hyperparameters match the most frequent (mode) choice across
  outer folds.
- Seed discipline: every RF instantiated with
  `random_state=APEX_SEED + fold_index × 7`. A test must confirm
  same-seed-same-output across two runs.

### Tests specification
Minimum 14 tests. Selected cases:
- `test_search_space_cardinality_18_trials`
- `test_inner_cpcv_produces_4_folds`
- `test_nested_run_deterministic_same_seed`
- `test_sample_weights_propagated_to_inner_fit`
- `test_stability_index_1_on_constant_best_hparam_scenario`
- `test_stability_index_lt_1_on_heterogeneous_scenario`
- `test_tuning_result_all_trials_flat_list_correct_length`
- `test_wall_clock_recorded`
- `test_empty_features_raises_valueerror`
- `test_class_weight_balanced_preserved_through_tuning`
- (+ edge cases)

### Anti-leakage checks specific to this sub-phase
- Inner CPCV on the outer training set only; a property test
  injects a synthetic feature with a perfect correlation to the
  outer test set's `y` and confirms that the tuner does **not**
  select it as best (because inner AUC on the inner-to-outer-train
  subsets remains unaffected).

### DoD
1. All tests passing, coverage ≥ 88 % on
   `features/meta_labeler/tuning.py`.
2. `mypy --strict` clean.
3. `ruff` clean.
4. Wall-clock budget documented in PR body.
5. `reports/phase_4_4/tuning_report.md` +
   `tuning_trials.json` generated with `APEX_SEED=42`,
   reproducible bit-exact.
6. Determinism test passes (two identical runs → identical
   best-hyperparams-per-fold).

### Dependencies
- Sub-phase 4.3 merged.

### Estimated scope
- LOC: ~300–450.
- Tests: ~14.
- Complexity: **medium–high** (nested loop, determinism).
- Expected Copilot review cycles: **2**.

### References
- López de Prado (2018) §7.4 (nested CV).
- ADR-0005 D4.

---

## 3.5 Sub-phase 4.5 — Meta-Labeler Statistical Validation

### Objective
Apply ADR-0005 D5 deployment gates (G1–G7) to the tuned
Meta-Labeler candidate, using existing Phase 3 hypothesis-testing
infrastructure. Emit a pass/fail verdict with numerical evidence.

### Scope
- **IN**: G1–G7 gate measurements; DSR/PBO computation on
  bet-sized P&L under ADR-0002 D7 cost scenarios; aggregate
  verdict; structured failure report if any gate fails.
- **OUT**: New statistical methods (all tests reuse
  `features/hypothesis/`); cross-strategy MHT corrections (deferred,
  this is a single Meta-Labeler).

### Module structure
```
features/meta_labeler/
├── validation.py              (NEW — thin wrapper)
├── pnl_simulation.py          (NEW — bet-size → P&L)

tests/unit/features/meta_labeler/
├── test_validation_gates.py   (~18 tests)
├── test_pnl_simulation.py     (~10 tests)
```

### Public API
```python
# features/meta_labeler/validation.py

@dataclass(frozen=True)
class GateResult:
    name: str
    value: float
    threshold: float
    passed: bool

@dataclass(frozen=True)
class MetaLabelerValidationReport:
    gates: tuple[GateResult, ...]
    all_passed: bool
    failing_gate_names: tuple[str, ...]
    pnl_realistic_sharpe: float
    pnl_realistic_sharpe_ci: tuple[float, float]
    dsr: float
    pbo: float

class MetaLabelerValidator:
    def __init__(self, cost_scenario: CostScenario = CostScenario.REALISTIC) -> None: ...

    def validate(
        self,
        training_result: BaselineTrainingResult,     # 4.3
        tuning_result: TuningResult,                 # 4.4
        features: MetaLabelerFeatureSet,
        y: np.ndarray,
        sample_weights: np.ndarray,
        bars_for_pnl: pl.DataFrame,
    ) -> MetaLabelerValidationReport: ...
```

### Inputs
- Outputs of 4.3 (baseline training result with per-fold AUCs)
  and 4.4 (tuning result with per-trial AUCs).
- Labels, sample weights, bars for P&L simulation.

### Outputs
- `MetaLabelerValidationReport` with per-gate pass/fail + the
  three aggregate numbers `pnl_realistic_sharpe`, `dsr`, `pbo`.
- `reports/phase_4_5/validation_report.md`:
  - Gate-by-gate verdict table.
  - If any gate fails: the observed value, the gap to threshold,
    and a suggested mitigation path (feature engineering vs
    escalation to Phase 3).
- `reports/phase_4_5/validation_report.json` for machine consumption.

### Algorithm notes
- G1/G2 computed directly from CPCV OOS AUC per fold (mean, min).
- G3: simulated bet-sized P&L per OOS fold using
  `pnl_simulation.py` (bet size ∝ predicted probability, position
  held over `[t0, t1]`, transaction costs applied per ADR-0002 D7
  realistic scenario). DSR from `features/hypothesis/dsr.py`.
- G4: PBO on tuning trial AUCs (IS = inner CV AUC, OOS = outer
  CV AUC per trial). Uses `features/hypothesis/pbo.py`.
- G5: Brier score averaged across OOS folds, `sample_weight=w_val`.
- G6: minority class frequency in training data (computed once,
  no CV).
- G7: mean RF OOS AUC − mean LogReg OOS AUC, using per-fold
  values from 4.3's BaselineTrainingResult.
- The report is **deterministic fail-loud**: if any evidence is
  missing (e.g., LogReg baseline not run), the validator raises
  `ValueError` rather than silently passing G7.

### Tests specification
Minimum 28 tests. Selected cases:
- `test_g1_pass_when_mean_auc_ge_0p55`
- `test_g1_fail_when_mean_auc_lt_0p55`
- `test_g2_pass_when_min_auc_ge_0p52`
- `test_g2_fail_when_any_fold_below_0p52`
- `test_g3_dsr_computed_under_realistic_costs`
- `test_g3_pass_when_dsr_ge_0p95`
- `test_g4_pbo_computed_on_tuning_trials`
- `test_g4_fail_when_pbo_ge_0p10`
- `test_g5_brier_le_0p25_pass`
- `test_g6_warns_between_5_and_10_pct_minority`
- `test_g6_rejects_below_5_pct_minority`
- `test_g7_fails_when_logreg_missing` (fail-loud, not silent pass)
- `test_g7_pass_when_rf_beats_logreg_by_0p03`
- `test_all_passed_requires_all_seven`
- `test_report_json_schema_validates`
- `test_report_markdown_rendering_deterministic`
- (+ 12 edge cases)

### Anti-leakage checks specific to this sub-phase
- P&L simulation at bar `t` uses only predicted probability at
  `t0 ≤ t` and realized price path `[t0, t1]`. Test: perturbing
  prices after `t1` must not affect the simulated P&L.

### DoD
1. All tests passing, coverage ≥ 92 % on the new files.
2. `mypy --strict` clean.
3. `ruff` clean.
4. On the synthetic-alpha scenario: **all seven gates pass**
   under `APEX_SEED=42`. Any gate failing on the canonical
   synthetic scenario indicates a pipeline bug and blocks merge.
5. `reports/phase_4_5/validation_report.{md,json}` generated,
   reproducible.

### Dependencies
- Sub-phases 4.3 and 4.4 merged.

### Estimated scope
- LOC: ~400–600.
- Tests: ~28.
- Complexity: **medium** (mostly wiring).
- Expected Copilot review cycles: **2–3**.

### References
- ADR-0005 D5, D8.
- ADR-0002 D7.
- `features/hypothesis/` existing implementations.

---

## 3.6 Sub-phase 4.6 — Model Serialization + Model Card

### Objective
Serialize a validated Meta-Labeler (from 4.5 pass verdict) to
disk with a schema-versioned JSON model card, and provide a
deterministic load-and-predict round-trip test.

### Scope
- **IN**: joblib serialization of sklearn models; JSON model card
  per ADR-0005 D6 schema v1; schema validation on write and load;
  bit-exact round-trip test.
- **OUT**: ONNX export (allowed per ADR-0005 D6 but deferred
  unless a consumer requires it); model registry / versioning
  infrastructure (Phase 5+).

### Module structure
```
features/meta_labeler/
├── persistence.py             (NEW)
├── model_card.py              (NEW — schema + validator)

models/meta_labeler/            (NEW directory, gitignored)
.gitignore                     (update: add models/meta_labeler/*.joblib)

tests/unit/features/meta_labeler/
├── test_persistence.py        (~14 tests)
├── test_model_card.py         (~10 tests)
```

### Public API
```python
# features/meta_labeler/model_card.py

class ModelCardV1(TypedDict):
    schema_version: Literal[1]
    model_type: str
    hyperparameters: dict[str, Any]
    training_date_utc: str             # ISO-8601 Z-suffixed
    training_commit_sha: str           # 40-char git SHA
    training_dataset_hash: str         # "sha256:" + 64-char hex digest
    cpcv_splits_used: list[list[list[int]]]
    features_used: list[str]
    sample_weight_scheme: str
    gates_measured: dict[str, float]
    gates_passed: dict[str, bool]
    baseline_auc_logreg: float
    notes: str

def validate_model_card(card: dict[str, Any]) -> ModelCardV1:
    """Raises ValueError on any schema violation. No silent-pass."""
    ...

# features/meta_labeler/persistence.py

def save_model(
    model: RandomForestClassifier | LogisticRegression,
    card: ModelCardV1,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Writes {training_date}_{commit_sha8}.joblib + .json side-by-side.
    Returns (model_path, card_path)."""
    ...

def load_model(
    model_path: Path,
    card_path: Path,
) -> tuple[RandomForestClassifier | LogisticRegression, ModelCardV1]:
    """Loads and validates both. Raises ValueError on any mismatch
    between card.model_type and the actually loaded object."""
    ...
```

### Inputs
- A trained model (from 4.4 or post-4.5 final refit on the full
  dataset, depending on operational policy).
- A fully populated `ModelCardV1` dict constructed from 4.5's
  validation report.
- An output directory (default `models/meta_labeler/`).

### Outputs
- Two files: `.joblib` and `.json`, named
  `{training_date_iso_no_colons}_{commit_sha8}.{joblib,json}`.
- Schema-validated on both write and read.

### Algorithm notes
- Deterministic round-trip: save → load → predict on 1,000 fixed
  test rows must yield **bit-exact** predicted probabilities
  (tolerance 0.0). Non-determinism is a deployment blocker per
  ADR-0005 D6.
- `training_dataset_hash` is computed at save time as a
  library-agnostic SHA-256 digest over a deterministic byte
  serialization of the training data plus schema metadata. The
  hasher consumes, in this exact order:

  1. UTF-8 encoding of `json.dumps(feature_names, sort_keys=True,
     separators=(",", ":"))` where `feature_names` is the ordered
     list of column names used during training.
  2. UTF-8 encoding of `json.dumps({"shape": list(X.shape),
     "dtype": str(X.dtype)}, sort_keys=True, separators=(",", ":"))`.
  3. `X.tobytes(order="C")` — raw bytes of the `X` numpy array in
     C-contiguous order.
  4. UTF-8 encoding of `json.dumps({"shape": list(y.shape),
     "dtype": str(y.dtype)}, sort_keys=True, separators=(",", ":"))`.
  5. `y.tobytes(order="C")` — raw bytes of the `y` numpy array in
     C-contiguous order.

  The final value stored in the model card is
  `"sha256:" + hashlib.sha256(...).hexdigest()`. This scheme is
  deterministic, library-agnostic (no pandas or pyarrow dependency),
  and stable across numpy versions. A reference test in
  `tests/unit/features/meta_labeler/test_persistence.py` validates
  the hash against a fixed `X`/`y` pair to detect unintended
  regressions.
- `training_commit_sha` is read via
  `subprocess.check_output(["git", "rev-parse", "HEAD"])`. The
  saver raises `ValueError` if the working tree is dirty, to
  guarantee reproducible training provenance.
- Card JSON writes use `json.dumps(..., sort_keys=True,
  ensure_ascii=False)` for deterministic byte-level output.

### Tests specification
Minimum 24 tests. Selected cases:
- `test_save_produces_both_files`
- `test_load_roundtrip_bit_exact_predictions`
- `test_load_raises_on_model_type_mismatch`
- `test_load_raises_on_schema_violation`
- `test_save_raises_on_dirty_working_tree`
- `test_card_json_is_deterministic_bytewise`
- `test_card_required_fields_all_present`
- `test_card_gates_passed_all_true_when_aggregate_true`
- `test_card_feature_names_preserved_order`
- `test_card_schema_version_1_rejects_2`
- `test_card_iso8601_z_suffix_enforced`
- `test_card_commit_sha_40_chars_required`
- (+ 12 edge cases)

### Anti-leakage checks specific to this sub-phase
Not directly applicable (persistence is post-training). Indirect
check: the model card includes the `cpcv_splits_used` field, so
any downstream auditor can reconstruct the CPCV partitioning and
verify purging was applied.

### DoD
1. All tests passing, coverage ≥ 94 % on the new files.
2. `mypy --strict` clean.
3. `ruff` clean.
4. Round-trip test passes bit-exact.
5. `.gitignore` updated to exclude `models/meta_labeler/*.joblib`
   (training artifacts, not source).
6. Example model card JSON committed at
   `docs/examples/model_card_v1_example.json` for reference.

### Dependencies
- Sub-phase 4.5 merged (needs `MetaLabelerValidationReport` to
  populate `gates_measured` / `gates_passed`).

### Estimated scope
- LOC: ~350–500.
- Tests: ~24.
- Complexity: **low–medium**.
- Expected Copilot review cycles: **1–2**.

### References
- ADR-0005 D6.

---

## 3.7 Sub-phase 4.7 — Fusion Engine (IC-weighted baseline)

### Objective
Ship a library-level IC-weighted fusion computation per ADR-0005
D7. Input: activated Phase 3 signals + their IC reports. Output:
a scalar `fusion_score` per `(symbol, timestamp)`. Does NOT
modify `services/fusion_engine/`.

### Scope
- **IN**: fixed IC-IR weights from Phase 3 ICReport; scalar
  fusion score; unit tests; diagnostic report.
- **OUT (explicitly)**: regime-conditional weights; adaptive
  rolling-window re-calibration; HRP; shrinkage; wiring into
  `services/fusion_engine/`.

### Module structure
```
features/fusion/
├── __init__.py
├── ic_weighted.py             (NEW)

tests/unit/features/fusion/
├── __init__.py
├── test_ic_weighted.py        (~16 tests)
```

### Public API
```python
# features/fusion/ic_weighted.py

@dataclass(frozen=True)
class ICWeightedFusionConfig:
    feature_names: tuple[str, ...]       # must match activated set
    weights: tuple[float, ...]           # sum to 1.0

    @classmethod
    def from_ic_report(
        cls,
        ic_report: ICReport,
        activation_config: FeatureActivationConfig,
    ) -> "ICWeightedFusionConfig":
        """w_i = |IC_IR_i| / sum_j |IC_IR_j|, filtered to activated features."""
        ...

class ICWeightedFusion:
    def __init__(self, config: ICWeightedFusionConfig) -> None: ...

    def compute(self, signals: pl.DataFrame) -> pl.DataFrame:
        """Returns DataFrame with columns [timestamp, symbol, fusion_score].
        fusion_score = sum_i (w_i * signal_i)."""
        ...
```

### Inputs
- `ICReport` from Phase 3.3 (loaded from the Phase 3 artifact
  location).
- `FeatureActivationConfig` from Phase 3.12.
- Signals DataFrame: columns
  `[timestamp, symbol, gex_signal, har_rv_signal, ofi_signal]`.

### Outputs
- DataFrame with `fusion_score` scalar per row.
- `reports/phase_4_7/fusion_diagnostics.md`:
  - Computed weights vector.
  - Distribution of `fusion_score` (percentiles).
  - Correlation of `fusion_score` with each input signal
    (sanity check).
  - Sharpe ratio comparison: fusion_score vs best individual
    signal, on the canonical synthetic scenario.

### Algorithm notes
- Weights are **frozen at construction time** from a reference
  IC measurement window. They are NOT re-calibrated per call
  (would introduce look-ahead).
- If `ic_report` contains features not in `activation_config`,
  they are silently dropped (they're already rejected by Phase 3
  gates).
- If `activation_config` contains features not in `ic_report`,
  the constructor raises `ValueError` (incompatible artifacts).
  This is fail-loud.
- If all `IC_IR_i` are zero (degenerate), the constructor raises
  `ValueError`. Fail-loud; no silent uniform fallback.

### Tests specification
Minimum 16 tests. Selected cases:
- `test_weights_sum_to_1`
- `test_weights_proportional_to_abs_ic_ir`
- `test_fusion_score_linear_combination`
- `test_fusion_single_feature_equals_that_feature`
- `test_fusion_two_features_equal_weight_when_ic_ir_equal`
- `test_fusion_sharpe_exceeds_best_individual_on_synthetic`
- `test_constructor_raises_on_feature_mismatch`
- `test_constructor_raises_on_all_zero_ic_ir`
- `test_signals_missing_column_raises`
- `test_timestamp_preserved`
- `test_symbol_preserved`
- `test_deterministic_reproducible`
- `test_output_schema_matches_contract`
- `test_reads_ic_report_as_of_frozen_window` (no lookahead)
- (+ edge cases)

### Anti-leakage checks specific to this sub-phase
- Weights are explicitly frozen. Test: changing future signal
  values after weight-construction time must not change any
  already-computed fusion score.

### DoD
1. All tests passing, coverage ≥ 92 % on `features/fusion/`.
2. `mypy --strict` clean.
3. `ruff` clean.
4. On synthetic scenario (1 alpha + 2 noise signals, known
   IC_IRs): fusion_score Sharpe strictly exceeds max individual
   signal Sharpe.
5. `reports/phase_4_7/fusion_diagnostics.md` generated,
   reproducible with `APEX_SEED=42`.
6. **No modifications** to `services/fusion_engine/` (verified
   by a scope test in the PR).

### Dependencies
- Independent of 4.1–4.6 in principle; can run in parallel. In
  practice, Phase 4 execution order places 4.7 **after** 4.6 for
  cognitive simplicity (one PR per sub-phase sequentially).

### Estimated scope
- LOC: ~250–350.
- Tests: ~16.
- Complexity: **low**.
- Expected Copilot review cycles: **1**.

### References
- Grinold & Kahn (1999) Active Portfolio Management, §4 — the
  IC-IR framework.
- ADR-0005 D7.

---

## 3.8 Sub-phase 4.8 — End-to-end Pipeline Test

### Objective
Integration test exercising the full Phase 4 pipeline end-to-end
on a synthetic scenario: Phase 3 signals → Triple Barrier labels
→ sample weights → Meta-Labeler training → Fusion → bet-sized
P&L. Verify ordering invariance of the performance contracts.

### Scope
- **IN**: one integration test module; one synthetic-alpha
  scenario (reproducible); assertions on relative performance.
- **OUT**: real data integration (Phase 5); multi-scenario
  parameter sweeps (Phase 4.X).

### Module structure
```
tests/integration/
├── test_phase_4_pipeline.py   (NEW)
├── fixtures/
│   └── phase_4_synthetic.py   (NEW — scenario generator, shared)
```

### Scenario specification
- 4 symbols (2 equities, 2 crypto).
- 2 years of daily bars (≈ 500 bars per symbol).
- 1 true alpha channel: a 3-feature linear combination with known
  coefficients drives returns; the other features are i.i.d.
  noise.
- Triple-barrier labeler applied with default config.
- Sample weights computed.
- Meta-Labeler trained with full nested CPCV tuning
  (`APEX_SEED=42`).
- Fusion module run on the same signals.
- P&L simulated under ADR-0002 D7 realistic cost scenario.

### Assertions
The test must assert all of the following:
1. `BetSized_PnL_Sharpe > Fusion_PnL_Sharpe > Random_PnL_Sharpe`,
   with each gap ≥ 1.0 Sharpe unit (synthetic scenario is
   designed to make this robust).
2. Meta-Labeler validation report (4.5) reports
   `all_passed = True`.
3. Fusion Sharpe > max individual Phase 3 signal Sharpe.
4. Model card on the trained classifier is schema-valid and
   round-trip-loads bit-exact.
5. No file outside `reports/phase_4_*/`, `models/meta_labeler/*`,
   and test fixtures is written during the test run.

### Algorithm notes
- Runtime target: ≤ 5 min on a single CI runner. Nested tuning
  grid may be reduced (e.g., `n_estimators ∈ {100, 300}` only)
  for the integration test; the reduction is documented in the
  scenario fixture.
- Deterministic: two identical runs produce identical verdicts.
- Uses `pytest.mark.integration` marker (consistent with Phase 3
  precedent).

### Tests specification
The integration test file contains **one top-level
`test_phase_4_pipeline_end_to_end`** that orchestrates the full
flow, plus ~4 micro-tests inside the fixture file for scenario
generator correctness.

### Anti-leakage checks specific to this sub-phase
- Asserting that P&L simulation does not use any feature
  computed with a window ending after the label start.
- Asserting that CPCV purging is active (a synthetic shock
  placed at a fold boundary must be purged from the training set
  of the adjacent test fold; fusion score at the shock bar
  must be unaffected for training samples).

### DoD
1. Test passes deterministically.
2. Runtime ≤ 5 min on CI.
3. All five assertions above pass.
4. No regressions in `tests/integration/test_phase_3_pipeline.py`.

### Dependencies
- All of 4.1–4.7 merged.

### Estimated scope
- LOC: ~400–550 (fixture generator + test).
- Tests: 1 top-level + ~4 fixture unit tests.
- Complexity: **medium–high** (orchestration).
- Expected Copilot review cycles: **2**.

### References
- Mirror of `tests/integration/test_phase_3_pipeline.py`.
- ADR-0005 (full ADR applies).

---

## 3.9 Sub-phase 4.9 — Phase 4 Closure Report

### Objective
Mirror of PR #124 (Phase 3 closure) but for Phase 4.

### Scope
- **IN**: closure report document; updated memory files;
  Phase 5 prerequisites list; final ADR-0005 gate summary.
- **OUT**: new implementation code (closure is docs-only except
  memory files).

### Module structure
```
docs/
├── phase_4_closure_report.md  (NEW — mirrors docs/phase_3_closure_report.md)

docs/claude_memory/
├── CONTEXT.md                 (UPDATED — "current state = Phase 4 closed")
├── SESSIONS.md                (UPDATED — closure session entry)
├── PHASE_4_NOTES.md           (NEW — accumulated notes during 4.1–4.8)
```

### Content (closure report)
- Sub-phase inventory: 4.1 through 4.8 with PR numbers, LOC
  stats, test counts.
- Gate summary: final ADR-0005 D5 G1–G7 values achieved on the
  canonical scenario.
- Model card excerpt of the final deployed model.
- Technical debt log (explicit): streaming inference wiring,
  Phase 5 drift monitoring, short-side Meta-Labeler,
  regime-conditional fusion.
- Phase 5 prerequisites: what must be true before Phase 5 can
  start (passing E2E test, merged ADR-0005, model card schema
  stable).

### DoD
1. `docs/phase_4_closure_report.md` committed with all sections
   populated.
2. `docs/claude_memory/CONTEXT.md` reflects Phase 4 closed.
3. `docs/claude_memory/SESSIONS.md` has a closure entry.
4. The integration test from 4.8 passes on the closure branch.
5. PR link convention: same as PR #124 precedent.

### Dependencies
- Sub-phase 4.8 merged.

### Estimated scope
- LOC: N/A (docs only).
- Complexity: **low** (pattern-matching to PR #124).
- Expected Copilot review cycles: **1**.

### References
- PR #124 (Phase 3 closure) — template precedent.

---

## 4. Sub-phase tracking table

Populated after issues are created (§5 below). Issue numbers
filled in at issue-creation time.

| Sub-phase | Issue | Branch | Status |
|---|---|---|---|
| 4.1 Triple Barrier Labeling | #125 | `phase-4/triple-barrier` | not started |
| 4.2 Sample Weights | #126 | `phase-4/sample-weights` | not started |
| 4.3 Baseline Meta-Labeler | #127 | `phase-4/meta-labeler-baseline` | not started |
| 4.4 Nested Tuning | #128 | `phase-4/meta-labeler-tuning` | not started |
| 4.5 Statistical Validation | #129 | `phase-4/meta-labeler-validation` | not started |
| 4.6 Persistence + Model Card | #130 | `phase-4/meta-labeler-persistence` | not started |
| 4.7 Fusion Engine (IC-weighted) | #131 | `phase-4/fusion-ic-weighted` | not started |
| 4.8 E2E Pipeline Test | #132 | `phase-4/e2e-test` | not started |
| 4.9 Closure Report | #133 | `chore/phase-4-closure` | not started |

| Transverse | Issue | Status |
|---|---|---|
| Mid-Phase-4 leakage audit checkpoint | #134 | not started |
| Phase 4 closure tracking | #135 | not started |

---

## 5. Transverse concerns

### 5.1 Data leakage audit checkpoint (after 4.3, before 4.4)

A formal mid-Phase-4 audit is mandatory between 4.3 and 4.4. Its
purpose is to confirm that every Meta-Labeler input feature
respects `feature_compute_window_end < label_t0`. This is
**non-negotiable** because a single lookahead violation here
silently invalidates all subsequent training runs and makes the
D5 gates meaningless.

Details in the corresponding GitHub issue (§6 below).

### 5.2 Fail-loud heritage from Phase 3

All Phase 4 code MUST preserve the fail-loud pattern inherited
from Phase 3:
- Missing evidence → explicit `raise ValueError(...)`, never
  silent pass.
- Misaligned schemas → explicit `raise ValueError(...)`.
- Degenerate numerical cases (zero variance, zero concurrency) →
  explicit raise or documented sentinel with test coverage.

Every sub-phase test suite must include at least one "missing
evidence" fail-loud test (examples above in each sub-phase).

### 5.3 mypy strict, ruff, coverage

All sub-phases inherit the Phase 3 CI contract:
- `mypy --strict` zero errors on new modules.
- `ruff check` clean.
- Coverage ≥ 90 % on new modules (some sub-phases specify a
  higher bar).

### 5.4 UTC timestamps, Decimal prices

Inherited from `CLAUDE.md` §2/§10. No bare `datetime.now()`. Prices
and sizes as `Decimal`. Failure to honor these raises in tests.

---

## 6. GitHub issues backlog

Eleven issues total: nine per sub-phase (4.1–4.9) plus two
transverse (leakage audit, closure tracking). Issue bodies are
generated per the template in §6.1; the issue creation commands
are in the companion sub-phase commit instructions.

### 6.1 Per-sub-phase issue template

Each sub-phase issue follows this exact structure:
```markdown
# [phase-4.X] <Name>

## Reference
- `docs/phases/PHASE_4_SPEC.md` §3.X
- `docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D<N>
- López de Prado (2018) §<section>

## Objective
<one sentence, mirror of §3.X Objective>

## Deliverables
<bullet list, mirror of §3.X Module structure>

## Definition of Done
<copy-paste the §3.X DoD block>

## Dependencies
<sub-phase N-1 merged, branch + PR>

## Out of scope
<copy-paste the §3.X Scope "OUT" bullets>

## Anti-leakage checks
<copy-paste the §3.X anti-leakage bullets>

## Estimated scope
- LOC: ~<range>
- Tests: ~<count>
- Complexity: <low|medium|high>
- Copilot review cycles: <1-3>

## References
<per §3.X References>
```

### 6.2 Transverse issue — mid-Phase-4 leakage audit

Triggered after 4.3 merges, before 4.4 starts. Verifies every
Meta-Labeler feature respects temporal ordering. Produces
`reports/phase_4_leakage_audit.md`. See §5.1 for rationale.

### 6.3 Transverse issue — Phase 4 closure tracking

Mirror of PR #124 pattern. Triggered after 4.8 merges. Coordinates
the closure report (4.9), memory updates, and ready-for-Phase-5
verification.

---

## 7. Risks (explicit, non-speculative)

| Risk | Impact | Mitigation |
|---|---|---|
| Label leakage from contextual features | Invalidates D5 gates silently | Transverse §5.1 audit issue |
| Class imbalance < 5 % on real data | Training useless | D2 weights + G6 gate; escalate to Phase 3 if persists |
| Hyperparameter snooping | Inflates reported AUC | D4 nested CPCV; G4 PBO gate |
| RF under-fits on 3-feature basis | G1 AUC < 0.55 | ADR-0005 D3 GB escalation path; escalate to Phase 3 for more features |
| Non-reproducibility | Model card audit trail broken | D6 round-trip test + dirty-tree raise |
| Calibration drift in deployed model | Bet-sizes mis-allocated | D10 drift monitoring (Phase 5) |
| Compute cost of nested tuning | CI timeout | 4.4 reduces grid for CI; full grid for production training runs only |
| Existing `s04_fusion_engine.MetaLabeler` drift | Dual-implementation audit confusion | ADR-0005 §3 documents this explicitly |

---

## 8. Ready-for-Phase-5 checklist (tracked in 4.9 closure)

- [ ] All 9 sub-phase PRs merged to `main`.
- [ ] E2E integration test (4.8) green on CI.
- [ ] `models/meta_labeler/` contains a validated model with
      passing gates G1–G7 on canonical synthetic scenario.
- [ ] Model card schema v1 frozen (no further edits without a
      v2 migration ADR).
- [ ] `docs/phase_4_closure_report.md` committed.
- [ ] Technical debt log enumerates Phase 5 prerequisites
      (streaming inference, drift monitoring, short-side).

---

## 9. References (aggregate)

Full reference list inherited from ADR-0005 §5 plus Phase 3
references from ADR-0004 §6. The only additional Phase 4-specific
reference beyond ADR-0005 is the existing Phase 3 closure report
`docs/phase_3_closure_report.md` as a precedent pattern.
