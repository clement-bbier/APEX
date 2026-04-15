# Phase 4.5 — Implementation Audit

**Issue**: #129
**Branch**: `phase/4.5-statistical-validation`
**Author**: Clément Barbier (with Claude Code)
**Date**: 2026-04-15
**Status**: POST-IMPLEMENTATION — written before code, retained as the
design contract that the shipped code (`features/meta_labeler/{pnl_simulation,validation}.py`,
`scripts/generate_phase_4_5_report.py`, plus tests) implements.
**Predecessors**: Phase 4.3 (PR #140, `d5dc3a0`), Phase 4.4 (PR #141,
`e477c96`), mid-phase leakage audit (PR #142, `acbbe07`).

References: `docs/phases/PHASE_4_SPEC.md` §3.5;
`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D5, D8;
`docs/adr/0002-quant-methodology-charter.md` Section A item 7.

---

## 1. Objective

Apply the seven ADR-0005 D5 deployment gates (G1–G7) to the tuned
Meta-Labeler candidate, emit a pass/fail verdict per gate plus an
aggregate verdict, and produce a reproducible
`MetaLabelerValidationReport` with the three aggregate numbers
required by the §3.5 spec (`pnl_realistic_sharpe`, `dsr`, `pbo`).

Failure on the canonical synthetic-alpha scenario (`APEX_SEED=42`)
under realistic costs blocks merge per §3.5 DoD item 4.

## 2. Gate inventory and measurement source

| # | Gate | Threshold | Source (existing or new) |
|---|---|---|---|
| G1 | Mean OOS AUC | ≥ 0.55 | `BaselineTrainingResult.rf_auc_per_fold` (4.3) |
| G2 | Min per-fold OOS AUC | ≥ 0.52 | same |
| G3 | DSR on bet-sized P&L (realistic costs) | ≥ 0.95 | NEW `pnl_simulation.py` → `features/hypothesis/dsr.py` |
| G4 | PBO on tuning trials (IS = inner-CV AUC, OOS = outer-test AUC) | < 0.10 | `TuningResult.all_trials` (4.4) → `features/hypothesis/pbo.py` |
| G5 | Brier score (calibration) | ≤ 0.25 | `BaselineTrainingResult.rf_brier_per_fold` (4.3) |
| G6 | Minority class frequency | ≥ 10 % (warn 5–10 %, reject < 5 %) | computed from `y` once, no CV |
| G7 | RF − LogReg mean OOS AUC | ≥ 0.03 | both `*_auc_per_fold` from 4.3 |

DSR threshold and PBO threshold are inherited from ADR-0004 §6 and
re-asserted by ADR-0005 D5.

## 3. Reuse inventory

Phase 4.5 is **wiring + 1 new P&L simulator**. Every statistical
calculation reuses an existing, peer-reviewed implementation:

| Component | Path | Phase 4.5 usage |
|---|---|---|
| `DeflatedSharpeCalculator`, `DSRResult` | `features/hypothesis/dsr.py` | G3 |
| `PBOCalculator`, `PBOResult` | `features/hypothesis/pbo.py` | G4 |
| `sharpe_ratio` (annualised) | `backtesting/metrics.py` | per-fold realised SR |
| `cost_sensitivity_report` (zero/realistic/stress) | `backtesting/metrics.py` | informational scenarios in the report |
| `BaselineTrainingResult` (RF + LogReg per-fold AUC, Brier) | `features/meta_labeler/baseline.py` | G1, G2, G5, G7 |
| `TuningResult.all_trials` (per-trial inner-AUC + OOS-AUC) | `features/meta_labeler/tuning.py` | G4 |
| `MetaLabelerFeatureSet` (`X`, `t0`, `t1`) | `features/meta_labeler/feature_builder.py` | OOS prediction time grid |

No modification of `features/hypothesis/` or `backtesting/metrics.py`.
The gate logic lives entirely in the new `features/meta_labeler/
validation.py`.

## 4. New code surface

Two new modules under `features/meta_labeler/`:

```
features/meta_labeler/
├── pnl_simulation.py    NEW — bet-sized P&L per OOS fold, costs applied
└── validation.py        NEW — G1–G7 wiring + MetaLabelerValidationReport
```

Two new test modules under `tests/unit/features/meta_labeler/`:

```
tests/unit/features/meta_labeler/
├── test_pnl_simulation.py     ~12 tests, ≥ 92 % cov on pnl_simulation.py
└── test_validation_gates.py   ~22 tests, ≥ 92 % cov on validation.py
```

One report generator script:

```
scripts/generate_phase_4_5_report.py
```

Scope estimate: ~600 LOC production + ~900 LOC tests.

## 5. P&L simulation contract (`pnl_simulation.py`)

Per ADR-0005 D8 + PHASE_4_SPEC §3.5 algorithm note for G3:

- For each outer CPCV fold, hold out `(test_idx, predicted_proba)` from
  the trained RF.
- Convert proba `p ∈ [0, 1]` to a signed bet via
  `bet = 2 * p - 1 ∈ [-1, +1]` (calibrated long/short notional; per
  López de Prado 2018 §3.7 "betting on probabilities").
- Position is opened at `t0_i` close and closed at `t1_i` close, both
  drawn from the bar series. Holding period return is
  `r_i = log(C(t1_i) / C(t0_i)) * sign(bet_i) * |bet_i|`.
- Apply realistic round-trip cost per ADR-0002 D7: 5 bps per side =
  10 bps round-trip, encoded as a flat additive deduction
  `r_net_i = r_gross_i - cost_round_trip * |bet_i|`. The cost scales
  with bet magnitude — a half-conviction position pays half cost.
- The per-fold realised Sharpe is `sharpe_ratio(r_net_per_label,
  risk_free_rate=0.0, annual_factor=√bars_per_year)`. `bars_per_year`
  is derived from the median spacing of `t0` (no hardcoded 252).

### Anti-leakage invariants (P&L simulator)

1. The proba feeding bar `t0_i` is the model's prediction at `t0_i`,
   which only consumed features built strictly before `t0_i` (4.3
   audit, PR #142). No proba is reused across labels.
2. Permuting any close price strictly after `max(t1)` MUST NOT change
   any per-label P&L. Property test
   `test_pnl_unchanged_when_prices_after_max_t1_permuted`.
3. Permuting any close price strictly between `t1_i` and `t0_{i+1}`
   that does not belong to `{t0_i, t1_i}` for any label MUST NOT
   change `r_i` either. Verified by a second property test.

## 6. PBO wiring (G4)

Per `PBOCalculator` API (`features/hypothesis/pbo.py`):
- `is_metrics`: dict keyed by trial-id (deterministic name like
  `"n=300_d=10_min=5"`) → list of `mean_inner_cv_auc` per outer fold.
- `oos_metrics`: same shape with `oos_auc` per outer fold.

`TuningResult.all_trials` is a flat sequence of length
`n_outer_folds × cardinality`; we reshape it into the two dicts above
preserving outer-fold ordering. Minimum cardinality 2 is already
enforced by `PBOCalculator._validate`; the production search space
(3 × 3 × 2 = 18) satisfies this trivially.

## 7. DSR wiring (G3)

Per `DeflatedSharpeCalculator.compute(...)` API:
- `feature_sharpes`: `{"meta_labeler_realistic": realised_sharpe}` —
  single-strategy DSR. `n_trials = 1` is acceptable for the gate
  (see ADR-0005 D5 G3 footnote: "single-strategy DSR uses
  `n_trials=1`; multiple-strategy correction is Phase 4.7+ for the
  fusion engine"). The DSR formula still corrects for skewness,
  kurtosis, and sample size via the existing `deflated_sharpe_ratio`.
- `returns_data`: `{"meta_labeler_realistic": pl.Series(r_net)}`.
- DSR significance threshold passed into the calculator constructor:
  `0.95` per ADR-0005 D5 G3 (= ADR-0004 §6 default).

For the `sharpe_ratio_ci` reported alongside G3, we use the
non-parametric stationary-bootstrap helper
`bootstrap_sharpe_ci_stationary` already shipped in
`backtesting/metrics.py` (Politis-Romano 1994). 95 % CI computed on
`r_net` of the realistic scenario.

## 8. Aggregate verdict

```
all_passed = G1 AND G2 AND G3 AND G4 AND G5 AND G6 AND G7
```

`G6` returns three states `{ok, warn, reject}`; `passed` is true when
state ∈ `{ok, warn}`. The warn state is recorded in the report as a
non-blocking note per ADR-0005 D5 G6 rationale.

`failing_gate_names` is the tuple of gate names whose `passed=False`.
Order is canonical G1→G7 for reproducibility.

## 9. Fail-loud contract

Spec §3.5: the validator MUST raise `ValueError` rather than silently
pass when evidence is missing. Concrete cases:

| Trigger | Raised by |
|---|---|
| `BaselineTrainingResult.logreg_auc_per_fold` length 0 | G7 — silent pass would be undetectable |
| `TuningResult.all_trials` empty or fewer than 2 distinct hparam dicts | G4 — PBO undefined |
| Any per-fold realised return list is empty (CPCV degeneracy) | G3 — DSR undefined |
| `bars_for_pnl` does not cover `[min(t0), max(t1)]` | P&L simulator |
| `predicted_proba_per_fold` length ≠ `cpcv.get_n_splits()` | validator init |

## 10. Determinism

Phase 4.5 introduces no new randomness. The DSR bootstrap CI is the
only stochastic component and is seeded via the global
`APEX_SEED` (already wired through `bootstrap_sharpe_ci_stationary`).
Everything else is deterministic given a `(BaselineTrainingResult,
TuningResult, features, y, bars)` tuple.

The report generator wires the same `APEX_REPORT_NOW` /
`APEX_REPORT_WALLCLOCK_MODE` env-var contract introduced in PR #141
for byte-reproducible artefacts under CI.

## 11. References used (canonical)

- López de Prado, M. (2018). *Advances in Financial Machine Learning*,
  Wiley. §3.7 (betting on probabilities), §7.4 (nested CV), §11
  (DSR introduction).
- Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting, and
  Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J.
  (2017). "The probability of backtest overfitting." *Journal of
  Computational Finance*, 20(4).
- Politis, D. N., & Romano, J. P. (1994). "The stationary bootstrap."
  *Journal of the American Statistical Association*, 89(428),
  1303-1313.
- Brier, G. W. (1950). "Verification of forecasts expressed in terms
  of probability." *Monthly Weather Review*, 78(1), 1-3.
- ADR-0002 (Quant Methodology Charter), Section A item 7.
- ADR-0005 (Meta-Labeling and Fusion Methodology), D5 + D8.
