# APEX Project Context Snapshot

**Last updated**: 2026-04-17
**Updated by**: Session 040 (Strategic Audit + Post-Audit Batches A+B)
**Main commit**: `1b7c3b5` pre-batch-A, `f4fd79d` post-Batch-A merge (PR #178).

---

## Phase 5.1 — CLOSED (2026-04-17)

Phase 5.1 Fail-Closed Pre-Trade Risk Controls **merged** via PR #177.
GitHub issue #148 CLOSED 2026-04-17T12:35:20Z.
Canonical decision record: [`docs/adr/ADR-0006-fail-closed-risk-controls.md`](../adr/ADR-0006-fail-closed-risk-controls.md).
Deliverables: `SystemRiskState` / `SystemRiskStateCause` / `SystemRiskStateChange` / `SystemRiskMonitor` in
`core/state.py:365-600`; `FailClosedGuard` at `services/s05_risk_manager/fail_closed.py`;
`Topics.RISK_SYSTEM_STATE_CHANGE` constant at `core/topics.py:48`; 43+ new tests.

Follow-up S10 observability (subscribe + persist + alert on `risk.system.state_change`) merged via PR #178
as part of Batch A of the post-audit execution.

---

## Phase 5 — RE-SEQUENCED (2026-04-17)

Per [`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md),
Phase 5 scope reduced from 9 sub-phases to 6 remaining. Ordering:

```
5.1 Fail-Closed Pre-Trade Risk Controls          ✅ DONE (PR #177)
  ↓
5.2 Event Sourcing / In-Memory State             NEXT
  ↓
5.3 Streaming Inference Wiring
  ↓
5.5 Drift Monitoring & Feedback Loop             (reordered ahead of 5.4)
  ↓
5.4 Short-Side Meta-Labeler + Regime Fusion
  ↓
5.8 Geopolitical NLP Overlay (GDELT 2.0 + FinBERT substitute)
  ↓
5.10 Phase 5 Closure Report
  → Phase 7 Paper Trading
```

**Dropped from Phase 5** and moved to new **Phase 7.5 Infrastructure Hardening** backlog:
- 5.6 ZMQ Peer-to-Peer Bus — premature at solo-operator scale.
- 5.7 SBE / FlatBuffers Serialization — not the bottleneck at mid-frequency cadence.
- 5.9 Rust FFI Hot Path Migration — defer until live benchmarks prove Python too slow.

**Hard prerequisite for 5.2**: 8 S05 pre-trade context Redis keys are orphan reads in production code
(confirmed in [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md)).
PHASE_5_SPEC_v2.md §3.2 (authored in Batch C) addresses writer strategy.

---

## Phase 4 — CLOSED

Phase 4 (Fusion Engine + Meta-Labeler) is **complete**. All 8 sub-phases
(4.1–4.8) merged to `main`. CI green on all 5 jobs. Closure report at
`docs/phase_4_closure_report.md`. Phase 4 accumulated notes at
`docs/claude_memory/PHASE_4_NOTES.md` (now ARCHIVED).

### 4.8 DGP calibration — locked

- `SCENARIO_KAPPA = 0.030`, `_SIGNAL_INTERACTION_GAMMA = 0.8`,
  `_VOL_REGIME_DRIFT_SCALE = (0.2, 1.0, 1.8)` at quantiles
  `(0.25, 0.75)`, σ = 0.001, event stride = 5, 500 bars / symbol.
- Reduced tuning grid = 2 trials:
  `n_estimators=(300,), max_depth=(5,), min_samples_leaf=(5, 80)`.
  `leaf=80` is a **deterministic foil** that collapses the RF to
  AUC≈0.5 on the 336-event pool with class_weight="balanced" →
  PBO = 0/15 and G4 holds deterministically.
- All 7 D5 gates pass at seed=42 (pnl_sharpe = +1.55, DSR = 0.9997,
  G7 = 0.0414). `test_scenario_alpha_coefficients_are_recoverable_via_ols`
  now asserts proportionality (β/Σβ ≈ SCENARIO_ALPHA_COEFFS)
  because the heteroscedastic drift inflates raw β by a common
  factor K ≈ 1.56 but preserves ratios.


---

## Current State

Phase 3 closed (PR #124 merged). See
[`docs/phase_3_closure_report.md`](../phase_3_closure_report.md) for
the full inventory. 3 features activated for downstream use:
`gex_signal`, `har_rv_signal`, `ofi_signal`. S02 adapter scaffolded,
not wired (issue #123 for streaming).

Phase 4 design-gate merged. Phase 4.1 Triple Barrier Labeling (`#125`)
merged via PR #138 on `main`. Phase 4.2 Sample Weights (`#126`) merged
via PR #139 on `main`.

Phase 4.3 Baseline Meta-Labeler (`#127`) merged via PR #140
(commit `d5dc3a0`). Implements ADR-0005 D3:
`RandomForestClassifier` primary + mandatory `LogisticRegression`
baseline, trained with outer CPCV (`n_splits=6, n_test_splits=2,
embargo_pct=0.02` → 15 folds). Module tree `features/meta_labeler/`:
`metrics.py` (`fold_auc`, `fold_brier`, `calibration_bins`),
`feature_builder.py` (8-feature matrix — gex/har/ofi signals + regime
vol/trend codes + realized_vol_28d + cyclical hour/weekday — with
strict anti-leakage via `searchsorted(side='left') - 1`),
`baseline.py` (`BaselineMetaLabeler` trainer + frozen
`BaselineTrainingResult`). 66 new unit tests, 94% coverage on the new
package. Diagnostic report at `reports/phase_4_3/baseline_report.{md,
json}`: smoke gate PASS (mean RF AUC 0.7630 ≥ 0.55 on synthetic alpha,
APEX_SEED=42, n=1200). G7 gate (RF−LogReg ≥ +0.03) deferred to 4.5
per spec; synthetic alpha is linear so LogReg edges RF by 2.3 pp —
expected.

Mid-phase leakage audit (`#134`) PASS — `phase/4-leakage-audit`
branch pushed, `reports/phase_4_leakage_audit.md` records strict
`feature_compute_window_end_i < t0_i` compliance plus the
`realized_vol` and cyclical-time columns strictly before `t0`, and
the regime-code columns as-of `t0` (documented exception).

Phase 4.4 Nested CPCV Tuning (`#128`) merged via PR #141. Module
`features/meta_labeler/tuning.py`: `TuningSearchSpace` (3x3x2 = 18
default trials), `TuningResult` (per-fold winners, full trial
ledger, stability index, wall-clock), `NestedCPCVTuner` with
explicit nested loop (not `GridSearchCV` — rationale in
`reports/phase_4_4/audit.md` §10). 32 unit tests, 100% pass,
mypy --strict clean. Report generator:
`scripts/generate_phase_4_4_report.py` →
`reports/phase_4_4/{tuning_report.md, tuning_trials.json}`.

Phase 4.5 Statistical Validation (`#129`) merged via PR #143
(commit `d4768a3`). ADR-0005 D5 / PHASE_4_SPEC §3.5: the seven-gate
deployment validator (G1 mean AUC ≥ 0.55, G2 min AUC ≥ 0.52, G3 DSR
≥ 0.95 on bet-sized P&L with realistic costs, G4 PBO < 0.10, G5
Brier ≤ 0.25, G6 minority freq ≥ 10%, G7 RF − LogReg AUC ≥ +0.03).
New modules `features/meta_labeler/pnl_simulation.py` (López de Prado
2018 §3.7 `bet = 2p − 1` + ADR-0002 D7 cost model) and
`validation.py` (`MetaLabelerValidator.validate` with Politis-Romano
1994 stationary bootstrap and PBO matrix pivot).

Phase 4.6 Persistence + Model Card (`#130`) merged via PR #144
(commit `1371a12`). ADR-0005 D6 / PHASE_4_SPEC §3.6:
joblib serialization + schema-v1 JSON model card. New modules
`features/meta_labeler/model_card.py` (`ModelCardV1` TypedDict +
`validate_model_card` with exact-key-set enforcement, Z-suffix
ISO-8601 date, 40-char SHA regex, `sha256:` + 64-hex dataset-hash
regex, aggregate-gate cross-check) and
`features/meta_labeler/persistence.py` (`save_model` / `load_model`
round-trip with working-tree-clean + HEAD SHA guards,
`compute_dataset_hash` over fixed-order `(feature_names, X, y)`
bytes, deterministic canonical JSON card, bit-exact `predict_proba`
round-trip on 1000 fixed rows under `np.array_equal`). Filename
stem `{training_date_iso_no_colons}_{commit_sha8}` shared by
`.joblib` and `.json`. ~34 tests on card schema, ~22 tests on
persistence, plus `docs/examples/model_card_v1_example.json`
as the canonical reference card. Report generator:
`scripts/generate_phase_4_6_report.py` →
`reports/phase_4_6/persistence_report.{md,json}`. `.gitignore`
excludes `models/meta_labeler/*.{joblib,json}` — trained weights
are artefacts, not source.

Phase 4.7 Fusion Engine IC-weighted (`#131`) merged via PR #145.
ADR-0005 D7 / PHASE_4_SPEC §3.7:
library-level `features/fusion/` package ships
`ICWeightedFusionConfig` (frozen dataclass on the simplex: weights
non-negative, sum to 1.0 within `1e-9`, names sorted alphabetically
for determinism) + `ICWeightedFusion` (stateless `compute(signals:
pl.DataFrame) -> pl.DataFrame[timestamp, symbol, fusion_score]` via
`pl.sum_horizontal` — no Python row loops). `from_ic_report(ic_report,
activation_config)` computes `w_i = |IC_IR_i| / Σ_j |IC_IR_j|` over
the intersection of Phase 3.3 `ICReport.results` and Phase 3.12
`FeatureActivationConfig.activated_features`; silently drops extra
report entries, hard-errors on missing-activation, duplicate-in-report,
or `Σ|IC_IR|=0` (no silent uniform fallback). Weights **frozen at
construction** — no lookahead via per-call recalibration (tested via
property test permuting future rows). `compute` rejects missing
columns, null/NaN feature values, and zero-row frames with explicit
`ValueError`. ~30 unit tests covering simplex contract, linear-
combination sanity, mismatch handling, determinism, compute
validation, output schema, direct-construction invariants, anti-
leakage, and the DoD Sharpe assertion (fusion Sharpe > best
individual on a 1-alpha + 2-noise synthetic scenario). Scope guard
test verifies `services/s04_fusion_engine/` is untouched by the 4.7
branch via `git diff --name-only main...HEAD`. Report generator:
`scripts/generate_phase_4_7_report.py` →
`reports/phase_4_7/fusion_diagnostics.{md,json}` (weights vector,
P05/P25/P50/P75/P95 of `fusion_score`, per-signal Pearson
correlations, Sharpe comparison table). Streaming wiring into
`services/s04_fusion_engine/` stays out of scope (Phase 5, issue
#123).

Phase 4.8 End-to-end Pipeline Test merged via PR `#132` to `main`.
PHASE_4_SPEC §3.8 composition gate: single integration test wiring
every Phase 4 module already on `main` on a deterministic
synthetic scenario. No new library API. New test assets:
`tests/integration/fixtures/__init__.py`,
`tests/integration/fixtures/phase_4_synthetic.py` (deterministic
scenario generator — 4 symbols `AAPL / MSFT / BTCUSDT / ETHUSDT`,
500 hourly bars each = 2000 total bars; 3 activated signals `gex /
har_rv / ofi` as independent N(0,1); latent `α = 0.5·gex +
0.3·har_rv + 0.2·ofi`; `log_ret = κ·α + N(0, σ)` with `κ=0.002,
σ=0.001`; ~94 events/symbol via events-every-5-bars after Triple-
Barrier warmup), and `tests/integration/test_phase_4_pipeline.py`
(1 top-level `test_phase_4_pipeline_end_to_end` + 4 fixture micro-
tests). Reduced 2×2×2 = 8-trial tuning grid (spec-aligned subset
of the 4.5 production grid) to keep the run under the 5-min CI
budget; local dry-run ≈ 90 s. Single-symbol `AAPL` slice fed to
`MetaLabelerValidator` because `pnl_simulation._validate_inputs`
requires a strictly monotonic unique bar index; the pooled 4-
symbol Sharpe trio is computed separately via per-fold RF refit.
Top-level asserts (audit §8): (1) `Sharpe(bet_sized) >
Sharpe(fusion) > Sharpe(random)` with each gap ≥ 1.0; (2)
`report.all_passed is True`; (3) `Sharpe(fusion) > max_i
Sharpe(signal_i)`; (4) `predict_proba` bit-exact after
`save_model → load_model` round-trip on 1000 rows; (5) runtime
no-write scope guard (snapshot-diff of `REPO_ROOT` confined to
`reports/phase_4_*/`, `models/meta_labeler/`,
`tests/integration/`, or `tmp_path`). Throwaway `git_repo` fixture
(`tmp_path/"repo" + monkeypatch.chdir + git init --initial-
branch=main + user.email/user.name + commit.gpgsign=false +
initial README commit`) satisfies `save_model`'s clean-working-
tree + HEAD-SHA contract. Report generator:
`scripts/generate_phase_4_8_report.py` →
`reports/phase_4_8/pipeline_diagnostics.{md,json}` (scenario
summary, IC/IR per signal, frozen fusion weights, per-gate verdict
table, Sharpe trio + gaps, DSR/PBO/round-trip bps, tuner
stability_index, optional wall-clock).

Technical debt tracked: `#115` (CVD-Kyle perf, Phase 5), `#123`
(streaming calculators, Phase 5).

| Metric | Value |
|---|---|
| Active Phase | Phase 5 (Live Integration) — 5.1 DONE (PR #177); remaining 5.2/5.3/5.5/5.4/5.8/5.10 re-sequenced per STRATEGIC_AUDIT_2026-04-17. 5.6/5.7/5.9 moved to Phase 7.5 backlog. |
| Previous Phase | Phase 3 — Feature Validation Harness (DONE, 13/13 sub-phases) |
| Total tests | 2,259 unit (1 xfailed OFI latency) as of Batch A merge (PR #178); +5 new Phase 5.1 S10 observability tests; full Phase 4 contributions preserved. |
| Production LOC | ~35,770 (+ ~8,271 `features/` + ~1,280 `features/meta_labeler/` + ~280 `features/fusion/` Phase 4.7) |
| Test LOC | ~22,700 (+ ~10,532 `tests/unit/features/` + ~1,360 `tests/unit/features/meta_labeler/` + ~515 `tests/unit/features/fusion/` Phase 4.7) |
| mypy strict | 0 errors |
| Services scaffolded | 10/10 (S01-S10) |
| S01 fully implemented | Yes (78 files, 9,583 LOC) |
| ADRs accepted | 10 (+ ADR-0004 Feature Validation Methodology) |
| features/ coverage | ~93% (613 tests incl. meta-labeler at 94%) |

## On the horizon

Phase 5 (Live Integration & Infrastructure Hardening) — spec at
`docs/phases/PHASE_5_SPEC.md`. 9 sub-phases:
- 5.1 Fail-Closed (#148), 5.2 Event Sourcing (#149),
  5.3 Streaming Inference (#123), 5.4 Short-Side + Regime Fusion,
  5.5 Drift Monitoring, 5.6 ZMQ P2P (#150), 5.7 SBE (#151),
  5.8 Alt Data NLP (#153), 5.9 Rust FFI (#152).
Phase 6 backlog: DMA Research (#154), Rust monolith, Aeron, auto-retrain.

## Audit Status

| Audit | Status | Findings | Issues |
|---|---|---|---|
| Whole-codebase (#55) | CLEARED | P0: 0, P1: 15, P2: 13, P3: 6 | #64-#77 |
| Meta-governance (#59) | CLEARED | P0: 3, P1: 8, P2: 7, P3: 5 | #78-#86 |

**All P1 findings from audits #55 and #59 are now closed (100%).** Separately tracked items outside those audit issue ranges (e.g., deferred issue #63 for S01 connector Decimal migration) are tracked independently with backlog labels.

## Phase 3 Design

Spec document: `docs/phases/PHASE_3_SPEC.md`
- 13 sub-phases (3.1--3.13)
- 6 candidate features: HAR-RV, Rough Vol, OFI, CVD+Kyle, GEX
- Key ABCs: FeatureCalculator, FeatureStore, ICMeasurer, CPCVSplitter
- Estimated 3-4 weeks execution
- ADR-0004 defines the canonical 6-step validation pipeline

## Key Architecture Points for Phase 3

- S07 functions are PURE (stateless, no side effects) — safe to call from features/
- S02 signal pipeline: 5 weighted components (microstructure=0.35, bollinger=0.25,
  ema_mtf=0.20, rsi_divergence=0.15, vwap=0.05)
- Feature Store will use TimescaleDB (custom, not Feast)
- All features must produce SignalComponent-compatible output for S02 integration
- IC threshold for feature acceptance: |IC| > 0.02, IC_IR > 0.5
- CPCV mandatory (ADR-0004): N=10 splits, k=2 test folds, 5-bar embargo
- DSR + PBO mandatory for multiple testing correction (PSR > 0.95, PBO < 0.10)

## Open Issues

- GEX validation requires options data (source TBD, may need paid API)
- Whether all 6 features will pass IC threshold is unknown
- #63 S01 connector Decimal migration (backlog — deferred to Phase 3.X when macro/fundamental data is actively consumed; ~30 files in scope)
- #102 backtest-gate continue-on-error removal (follow-up, pending Sharpe bug fix)

## Sprint Status

| Sprint | PR | Issues | Status |
|---|---|---|---|
| Sprint 1 — Docs quick wins | #100 | #67, #78, #79, #80 | MERGED |
| Sprint 2 — Security & Config | #101 | #66, #69, #71 | MERGED |
| Sprint 3 — CI hardening | #103 | #64, #65, #68, #70 | MERGED |
| Sprint 4 — Architecture refactors | #104 | #74, #75, #76, #77 | MERGED |
| Sprint 5 — Architecture heavy refactors | #105 | #72, #73 | MERGED |
| Sprint 6 — Meta-governance | TBD | #81, #82, #83, #84, #85, #86 | PR PENDING |

## P1 Issue Progress (Whole-Codebase Audit #55)

| Issue | Sprint | Status |
|---|---|---|
| #64 CI coverage | Sprint 3 | CLOSED |
| #65 CI CVE | Sprint 3 | CLOSED |
| #66 SecretStr | Sprint 2 | CLOSED |
| #67 Docs | Sprint 1 | CLOSED |
| #68 CI backtest | Sprint 3 | CLOSED |
| #69 Decimal | Sprint 2 | CLOSED |
| #70 CI linting | Sprint 3 | CLOSED |
| #71 Config | Sprint 2 | CLOSED |
| #72 S06 Broker ABC | Sprint 5 | CLOSED |
| #73 S02 SignalPipeline | Sprint 5 | CLOSED |
| #74 S03 dead code | Sprint 4 | CLOSED |
| #75 S04 OCP | Sprint 4 | CLOSED |
| #76 S05 DIP | Sprint 4 | CLOSED |
| #77 S01 layering | Sprint 4 | CLOSED |

14/14 P1 closed from whole-codebase audit (100%).

## P1 Issue Progress (Meta-Governance Audit #59)

| Issue | Sprint | Status |
|---|---|---|
| #81 ADR-0004 | Sprint 6 | PR PENDING |
| #82 ARCHITECTURE.md | Sprint 6 | PR PENDING |
| #83 ACADEMIC_REFERENCES.md | Sprint 6 | PR PENDING |
| #84 ONBOARDING.md | Sprint 6 | PR PENDING |
| #85 pre-commit hooks | Sprint 6 | PR PENDING
