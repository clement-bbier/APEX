## Phase 4.5 — Meta-Labeler Statistical Validation (G1–G7)

Closes #129. Implements the seven-gate deployment validator from ADR-0005 D5
and the bet-sized P&L simulator from ADR-0002 D7 / ADR-0005 D8.

### What this PR delivers

| Gate | Threshold | Source |
| --- | --- | --- |
| G1 | mean OOS AUC ≥ 0.55 | López de Prado (2018) §3.2 |
| G2 | min per-fold OOS AUC ≥ 0.52 | ADR-0005 D5 |
| G3 | DSR on bet-sized P&L (realistic costs) ≥ 0.95 | Bailey & López de Prado (2014) |
| G4 | PBO across tuning trials < 0.10 | Bailey/Borwein/López de Prado/Zhu (2017) |
| G5 | Brier score ≤ 0.25 | Brier (1950) |
| G6 | minority class freq ≥ 10% (warn 5–10%, reject < 5%) | ADR-0005 D5 |
| G7 | RF − LogReg mean OOS AUC ≥ 0.03 | ADR-0005 D5 |

### New modules

- `features/meta_labeler/pnl_simulation.py` — `simulate_meta_labeler_pnl`
  computes per-label realised returns under the López de Prado (2018) §3.7
  betting rule (`bet = 2p − 1`) and the additive cost model from
  ADR-0002 D7 / ADR-0005 D8 (zero / realistic 10 bps RT / stress 30 bps RT).
  Exact-match `searchsorted` lookup against `bars.timestamp`; fails loud
  on any miss to keep the contract aligned with the 4.1 Triple-Barrier
  output.
- `features/meta_labeler/validation.py` — `MetaLabelerValidator.validate`
  orchestrates all seven gates, builds per-fold P&L by re-fitting on
  `train ∪ val` with the best hyperparameter set, runs the
  Politis-Romano (1994) stationary-bootstrap CI on the realised Sharpe,
  pivots the trial ledger into the PBO matrix, and packages a frozen
  `ValidationReport` with per-gate verdicts.
- `scripts/generate_phase_4_5_report.py` — end-to-end report generator.
  Synthesises alpha-injected bars (close drift = `_BAR_DRIFT_PER_SIGMA *
  ofi_signal`) so the tuned RF has a real edge to exploit, runs
  4.3 baseline → 4.4 nested CPCV → 4.5 validator, emits
  `validation_report.{md,json}`. Mirrors the 4.4 report contract:
  `APEX_REPORT_NOW`, `APEX_REPORT_WALLCLOCK_MODE`, `--full`.

### New tests

- `tests/unit/features/meta_labeler/test_pnl_simulation.py`
  - Bet sizing: `bet = 2p − 1 ∈ [−1, +1]`, `gross = log_ret · bet`
  - Cost arithmetic: realistic = 10 bps RT, stress = 3× realistic
  - **Anti-leakage property tests**: permuting prices outside
    `{t0_i, t1_i}` (and after `max(t1)`) leaves every per-label P&L
    unchanged.
  - Fail-loud: missing timestamp, t1 past last bar, p outside [0, 1],
    non-finite p, t1 < t0, shape disagreement, tuple length mismatch,
    non-monotonic bars, non-positive close, missing columns, empty bars.
- `tests/unit/features/meta_labeler/test_validation_gates.py`
  - Per-gate happy / fail tests for G1, G2, G4, G5, G6, G7 using
    `dataclasses.replace` to tamper individual gate inputs.
  - End-to-end pipeline test: 4.3 → 4.4 → 4.5 on a 200-row synthetic
    fixture, plus a tampered run that confirms failing gates land in
    canonical order.
  - Validator init defaults + frozen-dataclass guard on `GateResult`.

### How the gates interact with the rest of Phase 4

- The validator consumes `BaselineMetaLabelResult` (Phase 4.3, PR #140)
  and `NestedTuningResult` (Phase 4.4, PR #141).
- The data-leakage audit (PR #142, issue #134) covers the upstream
  feature build — the proba feeding label `i` is the model prediction
  at `t0_i` from features available strictly before `t0_i`. The
  `test_pnl_unchanged_when_prices_outside_t0_t1_set_permuted` property
  test extends that guarantee to the P&L step.

### Cost contract (ADR-0002 D7 / ADR-0005 D8)

| Scenario | Per-side bps | Round-trip bps |
| --- | --- | --- |
| zero | 0 | 0 |
| realistic | 5 | 10 |
| stress | 15 | 30 |

Only the realistic scenario feeds the G3 DSR gate; zero / stress are
computed for the report so reviewers can see the cost sensitivity.

### How to verify locally

```bash
make lint
pytest tests/unit/features/meta_labeler/test_pnl_simulation.py -q
pytest tests/unit/features/meta_labeler/test_validation_gates.py -q
# Report generator: env-var driven, no CLI flags. Output dir is fixed
# (reports/phase_4_5/). APEX_REPORT_NOW must include a tz offset; the
# wallclock mode must be one of {record, zero, omit}. Set APEX_FULL_VALIDATION=1
# for the heavier 3x3x2 grid.
APEX_SEED=42 \
  APEX_REPORT_NOW=2026-04-14T00:00:00+00:00 \
  APEX_REPORT_WALLCLOCK_MODE=omit \
  python scripts/generate_phase_4_5_report.py
```

### References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*,
  Wiley. §3.7 Betting on Probabilities.
- Bailey, D. & López de Prado, M. (2014). The Deflated Sharpe Ratio.
  *Journal of Portfolio Management*.
- Bailey, D., Borwein, J., López de Prado, M. & Zhu, Q. (2017). The
  Probability of Backtest Overfitting. *Journal of Computational
  Finance*.
- Politis, D. & Romano, J. (1994). The Stationary Bootstrap. *JASA*.
- Brier, G. (1950). Verification of forecasts expressed in terms of
  probability. *Monthly Weather Review*.
- ADR-0002 (Quant Methodology Charter), Section A item 7.
- ADR-0005 (Meta-Labeling and Fusion Methodology), D5 + D8.
