# Phase 4.7 — Fusion Engine (IC-weighted) — Pre-implementation Audit

**Status**: DRAFT — locked by commit on branch
`phase-4.7-fusion-ic-weighted`.
**Scope source**: PHASE_4_SPEC §3.7, ADR-0005 D7.
**Issue**: #131.
**Branch**: `phase-4.7-fusion-ic-weighted`.

---

## 1. Objective

Ship a library-level **IC-weighted fusion** computation that combines
activated Phase 3 signals into a scalar `fusion_score`:

```
fusion_score(symbol, t) = Σ_i  (w_i · signal_i(symbol, t))
    where  w_i = |IC_IR_i| / Σ_j |IC_IR_j|
```

Weights are **frozen at construction time** from a reference IC
measurement window; they are NOT re-calibrated per call. This is the
ADR-0005 D7 MVP — no regime-conditional weights, no rolling
re-calibration, no HRP, no shrinkage.

Scope is **library code + unit tests + diagnostic report** only.
`services/s04_fusion_engine/` must be untouched (wiring is Phase 5
work, tracked separately).

## 2. Deliverables

| Artifact | Purpose |
| --- | --- |
| `features/fusion/__init__.py` | Public re-exports (`ICWeightedFusion`, `ICWeightedFusionConfig`). |
| `features/fusion/ic_weighted.py` | Module implementing both classes. |
| `tests/unit/features/fusion/__init__.py` | Test package marker. |
| `tests/unit/features/fusion/test_ic_weighted.py` | ≥16 unit tests per spec §3.7. |
| `scripts/generate_phase_4_7_report.py` | Env-var-driven diagnostic report generator. |
| `reports/phase_4_7/fusion_diagnostics.{md,json}` | Generated diagnostic (weights vector, score distribution, per-signal correlations, Sharpe vs best individual signal). |
| `reports/phase_4_7/audit.md` | This document. |
| `docs/pr_bodies/phase_4_7_pr_body.md` | PR body. |
| `docs/claude_memory/CONTEXT.md` + `SESSIONS.md` | Session 036 + state snapshot update. |

## 3. Reuse inventory

| Component | Reused from | Role |
| --- | --- | --- |
| `ICResult` | `features/ic/base.py` | Source of `ic_ir` per activated feature (+ `feature_name`, `horizon_bars`). |
| `ICReport` | `features/ic/report.py` | Container accessed via `.results` property. |
| `FeatureActivationConfig` | `features/integration/config.py` | `activated_features: frozenset[str]` — source of truth for which columns survive the Phase 3.12 gate. |
| `polars` | repo-wide dep (>=1.15.0) | DataFrame substrate for `compute(signals)`. |
| Reporting contract | `scripts/generate_phase_4_{3,4,5,6}_report.py` | `APEX_SEED` / `APEX_REPORT_NOW` / `APEX_REPORT_WALLCLOCK_MODE` env-var grammar reused verbatim for byte-deterministic reports. |

No Phase 3 / 4 module is modified. No service is modified.

## 4. Public API (frozen contract)

```python
# features/fusion/ic_weighted.py

@dataclass(frozen=True)
class ICWeightedFusionConfig:
    feature_names: tuple[str, ...]      # activated + in ic_report, deterministic order
    weights: tuple[float, ...]          # same length; Σ == 1.0 (abs tol 1e-9)

    @classmethod
    def from_ic_report(
        cls,
        ic_report: ICReport,
        activation_config: FeatureActivationConfig,
    ) -> "ICWeightedFusionConfig": ...

class ICWeightedFusion:
    def __init__(self, config: ICWeightedFusionConfig) -> None: ...
    def compute(self, signals: pl.DataFrame) -> pl.DataFrame: ...
    # returns DataFrame[timestamp, symbol, fusion_score]
```

## 5. Construction semantics

`ICWeightedFusionConfig.from_ic_report`:

1. Walk `ic_report.results`; for each `ICResult` with `feature_name` in
   `activation_config.activated_features`, keep `(feature_name, abs(ic_ir))`.
2. If a `feature_name` appears in `ic_report` more than once (e.g.
   multiple horizons), it is a **hard error** — `ValueError`. The
   report must be pre-filtered to a single horizon before fusion.
3. If any `activated_features` entry is **not** present in
   `ic_report.results`, raise `ValueError` (incompatible artifacts;
   fail-loud per spec §3.7).
4. Entries in `ic_report.results` that are NOT in
   `activated_features` are **silently dropped** (Phase 3 already
   rejected them).
5. If Σ |IC_IR_i| == 0 over the kept set, raise `ValueError`
   (degenerate; no uniform fallback).
6. Normalise: `w_i = |IC_IR_i| / Σ_j |IC_IR_j|`. Re-normalise once
   after float summation so Σ == 1.0 strictly.
7. Freeze the feature order by sorted ascending `feature_name` —
   deterministic, independent of `ic_report` insertion order.

`ICWeightedFusionConfig` `__post_init__`:

- `len(feature_names) == len(weights) >= 1`
- `all(w >= 0 for w in weights)` (weights live on the simplex)
- `abs(sum(weights) - 1.0) < 1e-9`
- `len(set(feature_names)) == len(feature_names)`
- All names are non-empty strings.

## 6. Compute semantics

`ICWeightedFusion.compute(signals)`:

- Input is a **polars DataFrame** with a `timestamp` column, a
  `symbol` column, and one Float64 column per configured
  `feature_names`.
- Missing any required column → `ValueError` naming the column.
- Extra columns in `signals` are tolerated (they're simply not read).
- Null / NaN in any feature column → `ValueError` (the Phase 3
  pipeline is supposed to have materialised; no silent zero-fill).
- Timestamps / symbols are preserved unchanged.
- Output columns: `["timestamp", "symbol", "fusion_score"]` in that
  exact order. `fusion_score` is Float64.
- Implementation: a polars expression
  `sum_expr = sum(w_i * pl.col(f_i))`. No Python loop over rows.

## 7. Anti-leakage contract

Weights are baked into the frozen `ICWeightedFusionConfig` at
construction. They cannot shift between `compute` calls. Property
test: constructing a config, then later permuting future rows of
`signals`, must not change any already-computed `fusion_score` for
earlier rows.

## 8. Test plan (≥16 tests, per spec §3.7)

Every bullet below is a distinct test function in
`tests/unit/features/fusion/test_ic_weighted.py`:

1. `test_weights_sum_to_one`
2. `test_weights_proportional_to_abs_ic_ir`
3. `test_weights_use_absolute_value_on_negative_ic_ir`
4. `test_single_feature_equals_that_feature`
5. `test_two_features_equal_weight_when_ic_ir_equal`
6. `test_fusion_score_linear_combination`
7. `test_ic_report_extra_features_silently_dropped`
8. `test_activated_feature_missing_from_ic_report_raises`
9. `test_duplicate_feature_in_ic_report_raises`
10. `test_all_zero_ic_ir_raises`
11. `test_feature_names_sorted_alphabetically_for_determinism`
12. `test_compute_missing_column_raises`
13. `test_compute_null_value_raises`
14. `test_timestamp_preserved`
15. `test_symbol_preserved`
16. `test_output_schema_matches_contract`
17. `test_compute_deterministic_reproducible`
18. `test_fusion_sharpe_exceeds_best_individual_on_synthetic` (DoD)
19. `test_weights_frozen_permuting_future_signals_does_not_change_past_score`
   (anti-leakage property test)
20. `test_config_rejects_negative_weight` (direct construction)
21. `test_config_rejects_weights_not_summing_to_one`
22. `test_config_rejects_length_mismatch`
23. `test_fusion_services_s04_fusion_engine_untouched` (scope guard —
    verifies no file under `services/s04_fusion_engine/` was modified
    by this PR's diff; implemented via git plumbing in the test
    fixture).

## 9. Synthetic scenario for DoD Sharpe assertion

- `n = 1000` bars, single symbol `"TEST"`, `APEX_SEED=42`.
- True alpha `α_t ~ N(0, 1)`.
- 3 signals: `alpha_signal = α_t + N(0, σ_α)`,
  `noise_signal_1 = N(0, 1)`, `noise_signal_2 = N(0, 1)`.
- Returns `r_{t+1} = 0.1 · α_t + N(0, 1)` (alpha is thin but real).
- IC_IRs are computed from the realised returns so weights are
  self-consistent.
- Fusion Sharpe must strictly exceed `max(Sharpe(alpha_signal),
  Sharpe(noise_signal_1), Sharpe(noise_signal_2))`.

## 10. Report contract

`scripts/generate_phase_4_7_report.py` follows the 4.3/4.4/4.5/4.6
env-var contract (`APEX_SEED`, `APEX_REPORT_NOW`,
`APEX_REPORT_WALLCLOCK_MODE`). Writes two artefacts:

- `reports/phase_4_7/fusion_diagnostics.json` —
  - `generated_at`, optional `wall_clock_seconds`,
  - `config` (`feature_names`, `weights`),
  - `score_distribution` (percentiles P05/P25/P50/P75/P95),
  - `per_signal_correlation` (Pearson between `fusion_score` and
    each input signal on the synthetic scenario — sanity check),
  - `sharpe` table (`fusion_score`, each input signal), annual-
    izer-agnostic (Sharpe on centred mean / std).
- `reports/phase_4_7/fusion_diagnostics.md` — Markdown mirror.

## 11. Fail-loud inventory

| Condition | Exception |
| --- | --- |
| `ic_report` missing an activated feature | `ValueError` |
| `ic_report` has duplicate entry for an activated feature | `ValueError` |
| Σ \|IC_IR\| == 0 over kept set | `ValueError` |
| Direct `ICWeightedFusionConfig` with negative weight | `ValueError` |
| Direct construction with Σw ≠ 1 | `ValueError` |
| `len(feature_names) != len(weights)` | `ValueError` |
| Duplicate or empty feature name | `ValueError` |
| `compute(signals)` missing required column | `ValueError` |
| `compute(signals)` has NaN / null in required column | `ValueError` |
| `compute(signals)` with 0 rows | `ValueError` (preserves "no silent empty output" rule) |

## 12. Out of scope (deferred to Phase 5 or sub-phase 4.X)

- Regime-conditional weights.
- Rolling re-calibration.
- Hierarchical Risk Parity (HRP).
- Shrinkage / robust IC_IR estimators.
- Wiring into `services/s04_fusion_engine/_compute_fusion_score()`
  (Phase 5, already tracked).
- Streaming single-row `compute` API (Phase 5, issue #123).

## 13. References

- ADR-0005 D7 — Fusion Engine IC-weighted baseline.
- PHASE_4_SPEC §3.7 — Sub-phase 4.7 spec.
- Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
  Management* (2nd ed.), McGraw-Hill, §4 — IC-IR framework.
