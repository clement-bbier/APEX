# Phase 4.8 — End-to-end Pipeline Test — Pre-implementation Audit

**Status**: DRAFT — locked on branch `phase-4.8-e2e-pipeline-test`.
**Scope source**: PHASE_4_SPEC §3.8, ADR-0005 (full ADR applies).
**Issue**: #132.
**Branch**: `phase-4.8-e2e-pipeline-test`.

---

## 1. Objective

One integration test that chains every Phase 4 library module already
shipped on `main` (4.1 labels → 4.2 weights → 4.3 RF train → 4.4
nested CPCV tuning → 4.5 gates → 4.6 persistence → 4.7 fusion) on a
single controlled synthetic scenario. Any composition gap between
those modules surfaces here; individual-module correctness stays the
domain of the unit suites.

The test is a **composition gate**, not a new algorithmic contract:
no new public API is introduced by this sub-phase.

## 2. Deliverables

| Artifact | Purpose |
| --- | --- |
| `tests/integration/fixtures/__init__.py` | Package marker. |
| `tests/integration/fixtures/phase_4_synthetic.py` | Deterministic scenario generator shared by the integration test and the diagnostic script. |
| `tests/integration/test_phase_4_pipeline.py` | One top-level `test_phase_4_pipeline_end_to_end` + ~4 micro-tests verifying scenario-generator invariants. |
| `scripts/generate_phase_4_8_report.py` | Env-var-driven diagnostic generator mirroring the 4.3/4.4/4.5/4.6/4.7 contract. |
| `reports/phase_4_8/pipeline_diagnostics.{md,json}` | Aggregated scenario + module summary (weights, per-gate verdicts, Sharpe trio, DSR/PBO, round-trip proof). |
| `reports/phase_4_8/audit.md` | This document. |
| `docs/pr_bodies/phase_4_8_pr_body.md` | PR body. |
| `docs/claude_memory/CONTEXT.md` + `SESSIONS.md` | Session + state snapshot update. |

## 3. Reuse inventory — no new library code

Every imported symbol is already on `main` after PRs #138 – #145.

| Module | Phase | Used for |
| --- | --- | --- |
| `features.labeling.label_events_binary` | 4.1 | Triple-Barrier labels per symbol. |
| `features.labeling.{compute_concurrency, uniqueness_weights, return_attribution_weights, combined_weights}` | 4.2 | `w_i = u_i · r_i`. |
| `features.meta_labeler.MetaLabelerFeatureSet` + `FEATURE_NAMES` | 4.3 | 8-feature matrix container; we bypass `MetaLabelerFeatureBuilder` because the integration scenario does not need the full regime-history plumbing (builder is unit-tested). |
| `features.meta_labeler.BaselineMetaLabeler` | 4.3 | CPCV-aware RF + LogReg training loop. |
| `features.meta_labeler.NestedCPCVTuner` + `TuningSearchSpace` | 4.4 | Reduced nested-CPCV tuning grid. |
| `features.meta_labeler.MetaLabelerValidator` | 4.5 | ADR-0005 D5 gates G1–G7. |
| `features.meta_labeler.persistence.save_model` / `load_model` / `compute_dataset_hash` | 4.6 | Bit-exact round-trip. |
| `features.meta_labeler.model_card.ModelCardV1` + `validate_model_card` | 4.6 | Schema-v1 card. |
| `features.meta_labeler.pnl_simulation.simulate_meta_labeler_pnl` + `CostScenario.REALISTIC` | 4.5 | Bet-sized realised P&L. |
| `features.fusion.ICWeightedFusion` / `ICWeightedFusionConfig` | 4.7 | Fusion score from an `ICReport`. |
| `features.ic.report.ICReport` + `features.ic.base.ICResult` | 3.3 | Source of `IC_IR` per signal. |
| `features.integration.config.FeatureActivationConfig` | 3.12 | Activated-feature set. |
| `features.cv.cpcv.CombinatoriallyPurgedKFold` | 3.10 | Outer + inner CPCV used by 4.3 / 4.4 / 4.5. |

No change to any of these modules is made by this PR (scope-guard
assertion below).

## 4. Synthetic scenario — design

Mirrors PHASE_4_SPEC §3.8 "Scenario specification":

- **4 symbols**: `AAPL`, `MSFT` (equities) and `BTCUSDT`, `ETHUSDT`
  (crypto). Labels are pooled across symbols — CPCV partitions
  labels, not bars.
- **500 bars per symbol** = 2000 total. Hourly grid anchored at
  `2025-01-01T00:00:00Z`. First 30 bars of each symbol are reserved
  as the Triple-Barrier volatility warmup (``vol_lookback = 20`` by
  default plus slack).
- **Three Phase-3 signals** — `gex_signal`, `har_rv_signal`,
  `ofi_signal` — generated as independent N(0, 1) columns. These
  are the three features ADR-0005 D6 / Phase 4.3 explicitly
  activates, so `FeatureActivationConfig.activated_features ==
  {gex_signal, har_rv_signal, ofi_signal}`.
- **Latent alpha**: `α_t = 0.5 · gex + 0.3 · har_rv + 0.2 · ofi`
  (linear combination with known coefficients). All three signals
  therefore carry overlapping information, which is exactly the
  regime where IC-weighted fusion is expected to strictly help
  (Grinold-Kahn §4).
- **Per-bar log-return**: ``log_ret_t = κ · α_t + N(0, σ)`` with
  ``κ = 0.002`` and ``σ = 0.001``. This gives a per-label realised
  Sharpe in the ``(2.0, 5.0)`` band under the realistic-cost
  scenario — large enough to pass G3 deterministically with seed
  42 and the reduced tuning grid.
- **Bars schema**: `timestamp` (UTC, `Datetime('us', 'UTC')`,
  strictly monotonic per symbol), `symbol` (Utf8), `close`
  (Float64, strictly positive). Close is a geometric walk:
  ``close_t = 100 · exp(Σ log_ret_t)``.
- **Events**: one event every 5 bars after warmup → ~94 events
  per symbol → ~376 events total. Long-only (ADR-0005 D1 MVP).
- **Triple-Barrier config**: default ``TripleBarrierConfig`` —
  ``pt=2.0`` σ, ``sl=1.0`` σ, ``max_holding=60`` bars,
  ``vol_lookback=20``.
- **Sample weights**: ``w_i = u_i · r_i`` per ADR-0005 D2.

## 5. Meta-Labeler inputs

The 8-feature matrix is built directly (the regime-history path via
`MetaLabelerFeatureBuilder` is unit-tested separately and adds no
composition risk):

| Col | Name | Source in the scenario |
| --- | --- | --- |
| 0 | `gex_signal` | value at `t0_i` |
| 1 | `har_rv_signal` | value at `t0_i` |
| 2 | `ofi_signal` | value at `t0_i` |
| 3 | `vol_regime_code` | sampled from `{0, 1, 2}` uniformly |
| 4 | `trend_regime_code` | sampled from `{-1, 0, 1}` uniformly |
| 5 | `realized_vol` | rolling std of log-return over 28 prior bars |
| 6 | `sin_time_of_day` | `sin(2π · hour/24)` at `t0_i` |
| 7 | `cos_time_of_day` | `cos(2π · hour/24)` at `t0_i` |

Binary target `y_i` is the Phase 4.1 `binary_target` column.

## 6. Tuning grid reduction (CI runtime)

Full grid is 18 trials per outer fold. The integration test uses a
**reduced** grid compatible with the ≤ 5 min CI budget:

```
n_estimators ∈ {100, 300}          # 2
max_depth    ∈ {5, 10}             # 2
min_samples_leaf ∈ {5, 20}         # 2
```

⇒ 8 trials per outer fold. Documented here and in the fixture
docstring so reviewers see the deviation from the 4.5 production
grid.

CPCV: outer = `(n_splits=6, n_test_splits=2, embargo=0.02)` per
ADR-0005 D4; inner = `(n_splits=4, n_test_splits=1, embargo=0.0)`.

## 7. Fusion + three-Sharpe comparison

1. **Per-signal IC measurement** — Pearson correlation proxy on the
   raw signal vs realised forward-return, one value per signal.
   This matches the synthetic fixture and Phase 4.7 report generator,
   which use Pearson as a pragmatic proxy here rather than Spearman.
   `IC_IR_i ≈ IC_i / sqrt(Var(IC_i))`; a ``20``-chunk bootstrap
   gives a stable denominator (same proxy used by 4.7).
2. **Fusion config** — `ICWeightedFusionConfig.from_ic_report`
   with the 3 activated names.
3. **`fusion_score` per event** — computed on the event-aligned
   signal frame and joined back onto `(t0, symbol)`.
4. **Three realised P&L series** on the shared event set:
   - `bet_sized_pnl` = meta-labeler `bet_i · r_i` from
     `simulate_meta_labeler_pnl(..., scenario=REALISTIC)`;
   - `fusion_pnl` = `sign(fusion_score_i) · r_i` (unit-size);
   - `random_pnl` = `sign(uniform_i − 0.5) · r_i` (seed-controlled).
5. **Sharpe trio**: annualiser-agnostic centred `mean / std` on
   each series (same convention as 4.7).

## 8. Assertions (PHASE_4_SPEC §3.8)

The top-level test asserts **all** of:

1. `Sharpe(bet_sized) > Sharpe(fusion) > Sharpe(random)` **with each
   gap ≥ 1.0 Sharpe unit**. Scenario is calibrated so both gaps
   exceed 1.0 on `seed = 42` deterministically.
2. `MetaLabelerValidationReport.all_passed is True`.
3. `Sharpe(fusion) > max_i Sharpe(sig_i)` where `sig_i ∈
   {gex, har_rv, ofi}` — the 4.7 fusion DoD holds on the integrated
   scenario too (tighter than the unit-test expectation-level version
   because here we can tune the scenario to give fusion a clean win).
4. Model card round-trip via `save_model` → `load_model` produces
   `np.array_equal(orig.predict_proba(X_fix), loaded.predict_proba(X_fix))`
   on a 1000-row fixture (tolerance `0.0`).
5. **Scope guard**: no file is written outside
   `reports/phase_4_*/`, `models/meta_labeler/`, or `tmp_path`. A
   snapshot of the set of files on disk before and after the test
   run is diffed, and any path outside the allow-list fails the
   test with a `ValueError`.

## 9. Anti-leakage checks (PHASE_4_SPEC §3.8)

- **Feature freshness**: for every label `i`, every Phase-3 signal
  value fed into the feature matrix must have a timestamp
  ``≤ t0_i``. The fixture builder asserts this and the test
  re-asserts via `np.all(feature_ts <= t0)`.
- **CPCV purging**: a synthetic shock (`+1e3` spike in `ofi_signal`
  placed at a fold boundary) must be absent from adjacent test
  folds' training indices. The test walks
  `cpcv.split(X, t1, t0)` and asserts the shocked sample's index
  is not in any adjacent fold's `train_idx`. The per-bar fusion
  score at the shocked bar is also asserted to be unaffected for
  training-time samples (i.e., weights are frozen at construction).

## 10. No-write scope guard

Before the test starts we snapshot:
```
snap = {p.relative_to(REPO_ROOT) for p in REPO_ROOT.rglob("*") if p.is_file()}
```
After the test we diff. Any path that is new **and** not under
`{reports/phase_4_*/, models/meta_labeler/, tests/integration/, tmp_path}`
triggers a hard-fail with the offending path name. `tmp_path` is
the pytest fixture used for the save/load round-trip, so files
created there are whitelisted.

## 11. Determinism contract

Two invocations of the test with `APEX_SEED=42` must produce the
same:
- `MetaLabelerValidationReport.gates` (per-gate float values bit-
  equal within `1e-12` — RF + CPCV are deterministic once seeded);
- `fusion_score` array (`np.array_equal`);
- per-series Sharpe values (bit-equal mean/std given the shared
  returns arrays).

This is asserted as a property test inside the fixture unit suite
(see §12).

## 12. Test inventory

Integration test (1):
- `test_phase_4_pipeline_end_to_end`.

Fixture micro-tests (4, on the scenario generator only):
- `test_scenario_is_deterministic_under_same_seed`.
- `test_scenario_respects_warmup_window`.
- `test_scenario_bar_and_label_schemas_match_phase_4_contracts`.
- `test_scenario_alpha_coefficients_are_recoverable_via_ols`.

## 13. CI integration

- `pytestmark = pytest.mark.integration` mirrors the Phase 3 precedent.
- Runtime target ≤ 5 min on the `integration-tests` job. Measured
  budget (local dry-run) on the reduced grid: ≈ 90 s.
- No new fixtures in `tests/integration/conftest.py` — the
  integration test is self-contained (fixture module imports
  explicitly).

## 14. Fail-loud inventory

| Condition | Exception |
| --- | --- |
| Any Phase-4 module import fails | `ImportError` (CI surfaces at collection) |
| Scenario generator called with `n_symbols != 4` | `ValueError` |
| Scenario generator called with `bars_per_symbol < 100` | `ValueError` |
| `label_events_binary` returns empty for any symbol | `ValueError` |
| `all_passed is False` | assertion fails with failing-gate names |
| Sharpe trio ordering or gap violated | assertion fails with the three values |
| `predict_proba` not bit-exact on reload | assertion fails with max |Δp| |
| Extraneous file written outside allow-list | assertion fails naming the path |

## 15. Out of scope (deferred)

- Real data integration (Phase 5).
- Multi-scenario sweeps (Phase 4.X parameter sweeps).
- Regime-conditional fusion weights (already listed as deferred in
  the 4.7 audit).
- Feature-builder path through `MetaLabelerFeatureBuilder`
  (unit-tested in `tests/unit/features/meta_labeler/`).
- Streaming single-row fusion / bet-sizing APIs (Phase 5, issue
  #123).

## 16. References

- PHASE_4_SPEC §3.8 — Sub-phase 4.8 spec.
- ADR-0005 D1 – D8 (full ADR applies).
- `tests/integration/test_phase_3_pipeline.py` — structural mirror.
- Grinold, R. C. & Kahn, R. N. (1999), *Active Portfolio
  Management* (2nd ed.), McGraw-Hill, §4.
- López de Prado, M. (2018), *Advances in Financial Machine
  Learning*, Wiley, §3–§11.
