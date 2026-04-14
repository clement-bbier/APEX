# APEX Project Context Snapshot

**Last updated**: 2026-04-14
**Updated by**: Session 034 (Phase 4.4 Nested CPCV Tuning)

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

Phase 4.4 Nested CPCV Tuning (`#128`) in progress on branch
`phase/4.4-nested-tuning`. ADR-0005 D4 and PHASE_4_SPEC §3.4. New
module `features/meta_labeler/tuning.py`:
- `TuningSearchSpace` (3x3x2 = 18 default trials),
- `TuningResult` (per-fold winners, full trial ledger, stability
  index, wall-clock),
- `NestedCPCVTuner` with explicit nested loop (not `GridSearchCV`
  — rationale in `reports/phase_4_4/audit.md` §10).
32 unit tests, 100% pass, mypy --strict clean, ruff clean. Fast
config (n=400, 8-trial x 6 outer x 3 inner = 144+48 fits) runs in
~22 s with APEX_SEED=42; full config gated behind
`APEX_FULL_TUNING=1` (18-trial x 15 outer x 4 inner = 1,350 fits).
Report generator: `scripts/generate_phase_4_4_report.py` →
`reports/phase_4_4/{tuning_report.md, tuning_trials.json}`.

Remaining Phase 4 work: #129 (Statistical Validation DSR/PBO),
#130 (Persistence + Model Card), #131 (Fusion Engine IC-weighted),
#132 (E2E Pipeline Test), #133 (Closure Report), #135 (closure
tracking).

Technical debt tracked: `#115` (CVD-Kyle perf, Phase 5), `#123`
(streaming calculators, Phase 5).

| Metric | Value |
|---|---|
| Active Phase | Phase 4.4 (Nested CPCV Tuning — #128 in progress); 4.1-4.3 merged (PRs #138/#139/#140); #134 leakage audit PASS on `phase/4-leakage-audit` |
| Previous Phase | Phase 3 — Feature Validation Harness (DONE, 13/13 sub-phases) |
| Total tests | 1,833 unit (1 xfailed latency) + 1 new Phase 3 integration test + existing integration tests |
| Production LOC | ~35,770 (+ ~8,271 `features/` + ~970 `features/meta_labeler/`) |
| Test LOC | ~22,700 (+ ~10,532 `tests/unit/features/` + ~820 `tests/unit/features/meta_labeler/`) |
| mypy strict | 0 errors |
| Services scaffolded | 10/10 (S01-S10) |
| S01 fully implemented | Yes (78 files, 9,583 LOC) |
| ADRs accepted | 10 (+ ADR-0004 Feature Validation Methodology) |
| features/ coverage | ~93% (557 tests incl. meta-labeler at 94%) |

## On the horizon

Phase 4.5 Statistical Validation (issue #129): compute DSR
(Bailey & Lopez de Prado 2014) and PBO (Bailey, Borwein, Lopez
de Prado, Zhu 2014) on the `tuning_trials.json` ledger produced
by 4.4, plus Harvey & Liu (2015) haircut-Sharpe. Gates G4/G5 from
PHASE_4_SPEC §3.5.

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
| #85 pre-commit hooks | Sprint 6 | PR PENDING |
| #86 stale agent prompts | Sprint 6 | PR PENDING |

## Branch Status

- `main` is clean, all tests passing (Sprint 5 merged via PR #105)
- `sprint6/meta-governance` — PR pending (#81-#86)
- Follow-up issue #102 created for backtest-gate continue-on-error removal
