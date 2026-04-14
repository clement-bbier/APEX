# Phase 3 Closure Report

**Status**: Phase 3 complete (sub-phases 3.1 to 3.13 all merged to `main`)
**Generated**: 2026-04-14T02:00:00Z
**Repo HEAD at closure**: `69692f53ddaa20b0df013bd847c759dbdaba1d81`

---

## Executive summary

Phase 3 delivered the complete feature validation harness: five signal
calculators grounded in peer-reviewed methodologies, the full validation
pipeline (IC -> multicollinearity -> CPCV -> hypothesis testing), and the
final selection decision framework. The machinery is tested, reproducible,
and documented.

Final outcome: **3 of 8** candidate features passed all decision gates per
ADR-0004: `gex_signal`, `har_rv_signal`, `ofi_signal`. PBO of the final
set: **0.0500** (threshold per ADR-0004: `< 0.10`).

Phase 4 (Fusion Engine + Meta-Labeler) can start once this closure PR is
merged.

---

## 1. Sub-phase inventory

### 1.1 Sub-phases delivered

All LOC figures are raw `git show --stat` insertions on the merge commit,
i.e. implementation + tests + docs combined for each PR.

| #    | Title                                        | PR    | Merged on  | LOC (ins) |
|------|----------------------------------------------|-------|------------|-----------|
| 3.1  | Feature Engineering Pipeline Foundation      | #108  | 2026-04-13 | ~2,185    |
| 3.2  | Feature Store Architecture (TimescaleDB)     | #109  | 2026-04-13 | ~2,366    |
| 3.3  | Information Coefficient measurement          | #110  | 2026-04-13 | ~1,875    |
| 3.4  | HAR-RV calculator (Corsi 2009)               | #111  | 2026-04-13 | ~1,340    |
| 3.5  | Rough Volatility calculator (Gatheral 2018)  | #112  | 2026-04-13 | ~1,380    |
| 3.6  | OFI calculator (Cont et al. 2014)            | #113  | 2026-04-13 | ~1,305    |
| 3.7  | CVD + Kyle Lambda (Kyle 1985)                | #114  | 2026-04-13 | ~1,461    |
| 3.8  | GEX calculator (Barbon & Buraschi 2020)      | #116  | 2026-04-13 | ~1,546    |
| 3.9  | Multicollinearity analyzer + orthogonalizer  | #118  | 2026-04-13 | ~1,644    |
| 3.10 | CPCV with purging + embargo (LdP 2018)       | #119  | 2026-04-13 | ~1,507    |
| 3.11 | DSR + PBO + MHT statistical layer            | #120  | 2026-04-13 | ~1,672    |
| 3.12 | Feature selection report generator           | #121  | 2026-04-14 | ~2,034    |
| 3.13 | S02 feature adapter (scaffolding)            | #122  | 2026-04-14 | ~1,470    |

**13 / 13 sub-phases merged.** Total raw insertions across the 13 merge
commits: ~21,785 lines. Net delta against the pre-Phase-3 HEAD (commit
`b289025`) on the Phase-3-relevant tree
(`features/` + `tests/` + `reports/` + `docs/phases/` + `docs/adr/`):
**93 files changed, 17,890 insertions(+), 98 deletions(-)**. The gap
between raw and net is accounted for by iterative modifications to shared
files across PRs.

### 1.2 Module tree

```
features/
├── base.py                # ABC (Phase 3.1)
├── pipeline.py            # FeaturePipeline (Phase 3.1)
├── registry.py            # FeatureRegistry (Phase 3.1)
├── weights.py             # weight helpers (Phase 3.1)
├── fracdiff.py            # fractional differentiation (Phase 3.1)
├── labels.py              # triple-barrier labels (Phase 3.1)
├── orthogonalizer.py      # residual orthogonalisation (Phase 3.9)
├── multicollinearity.py   # VIF + clustering (Phase 3.9)
├── versioning.py          # schema pinning (Phase 3.1)
├── exceptions.py          # shared exceptions
├── calculators/           # Phase 3.4-3.8 (5 modules, ~1,956 LOC)
│   ├── har_rv.py
│   ├── rough_vol.py
│   ├── ofi.py
│   ├── cvd_kyle.py
│   └── gex.py
├── ic/                    # Phase 3.3 (5 modules, ~919 LOC)
│   ├── base.py
│   ├── forward_returns.py
│   ├── measurer.py
│   ├── stats.py
│   └── report.py
├── cv/                    # Phase 3.10 (4 modules, ~593 LOC)
│   ├── base.py
│   ├── purging.py
│   ├── embargo.py
│   └── cpcv.py
├── hypothesis/            # Phase 3.11 (4 modules, ~779 LOC)
│   ├── dsr.py
│   ├── pbo.py
│   ├── mht.py
│   └── report.py
├── selection/             # Phase 3.12 (2 modules, ~555 LOC)
│   ├── decision.py
│   └── report_generator.py
├── integration/           # Phase 3.13 (3 modules, ~462 LOC)
│   ├── config.py
│   ├── s02_adapter.py
│   └── warmup_gate.py
├── store/                 # Phase 3.2 (2 modules, ~483 LOC)
│   ├── base.py
│   └── timescale.py
└── validation/            # per-calculator validation reports (~551 LOC)
    ├── pipeline.py
    ├── stages.py
    ├── har_rv_report.py
    ├── rough_vol_report.py
    ├── ofi_report.py
    ├── cvd_kyle_report.py
    └── gex_report.py
```

Total `features/` LOC (non-`__init__.py` Python): **~8,271**.
Total `tests/unit/features/` LOC (non-`__init__.py` Python): **~10,532**.

## 2. Calculator status (Phase 3.4 to 3.8)

| Calculator | Signal columns                                              | Validation | Tests (file) | Open issues               |
|------------|-------------------------------------------------------------|------------|--------------|---------------------------|
| HAR-RV     | `har_rv_signal`                                             | OK         | 668 LOC      | —                         |
| Rough Vol  | `rough_hurst`, `rough_vol_signal`                           | OK         | 752 LOC      | —                         |
| OFI        | `ofi_signal`                                                | OK         | 669 LOC      | —                         |
| CVD + Kyle | `cvd_signal`, `liquidity_signal`, `combined_signal`         | OK         | 757 LOC      | #115 (perf, Phase 5)      |
| GEX        | `gex_signal`                                                | OK         | 867 LOC      | —                         |

All five calculators pass the Phase 3 IC / variance validation gates.
Per-feature selection decisions are in §3.

## 3. Final feature selection (Phase 3.12)

Source of truth: [`reports/phase_3_12/feature_selection_report.json`](../reports/phase_3_12/feature_selection_report.json).

### 3.1 KEEP

| Feature         | Calculator | IC mean | IC_IR | DSR  | VIF  | p_holm |
|-----------------|------------|---------|-------|------|------|--------|
| `gex_signal`    | GEX        | 0.0900  | 1.500 | 0.97 | 1.01 | 0.0100 |
| `har_rv_signal` | HAR-RV     | 0.0800  | 1.200 | 0.96 | 3.57 | 0.0080 |
| `ofi_signal`    | OFI        | 0.0700  | 1.000 | 0.96 | 2.10 | 0.0150 |

### 3.2 REJECT

| Feature            | Calculator | Primary reject reason      |
|--------------------|------------|----------------------------|
| `cvd_signal`       | CVD+Kyle   | `cluster_dropped_by_ic_ranking` (same cluster as `ofi_signal`, lower IC) |
| `rough_hurst`      | Rough Vol  | `dsr=0.890 < 0.95`         |
| `rough_vol_signal` | Rough Vol  | `dsr=0.850 < 0.95`         |
| `combined_signal`  | CVD+Kyle   | multiple gates failed (IC, IR, p_value, DSR, PSR, p_holm) |
| `liquidity_signal` | CVD+Kyle   | multiple gates failed (IC, IR, p_value, DSR, PSR, p_holm) |

### 3.3 PBO of final set

`PBO = 0.0500` (threshold per ADR-0004: `< 0.10`). **PASS.**

The final KEEP set of 3 features passes the ADR-0004 overfitting gate,
providing evidence that the selection is not the result of spurious
cherry-picking across the candidate space.

## 4. Validation pipeline — end-to-end composability

The Phase 3 machinery composes as follows for any candidate feature:

1. **Calculator** -> signal column (Phase 3.4-3.8).
2. **IC measurement** (Phase 3.3) — Spearman rank correlation with
   forward returns, rolling IC_IR, turnover-adjusted IC, Newey-West
   HAC-corrected p-values.
3. **Multicollinearity analysis** (Phase 3.9) — VIF computation,
   hierarchical clustering on correlation distance, keep-best-of-cluster
   via IC ranking.
4. **CPCV splits generation** (Phase 3.10) — combinatorially purged
   k-fold with Lopez de Prado §7.4.1-2 purging + embargo.
5. **Hypothesis testing** (Phase 3.11) — PSR, DSR, Min-TRL, rank-PBO
   of candidate set, Holm-Bonferroni / Benjamini-Hochberg multiple
   hypothesis correction.
6. **Selection decision** (Phase 3.12) — aggregates all above evidence
   into keep/reject verdict with cherry-picking protection (missing
   evidence = explicit reject reason, never silent pass).
7. **S02 Adapter** (Phase 3.13, scaffolding) — bridges activated
   features to S02's `SignalComponent` API for eventual production
   wiring. Not currently wired; streaming work tracked in #123.

Validation of composability:
[`tests/integration/test_phase_3_pipeline.py`](../tests/integration/test_phase_3_pipeline.py)
exercises steps 1-6 on synthetic data (1 true alpha + 9 random noise
features) and asserts only the true alpha survives all gates. See §8
for test results.

## 5. Technical debt

### 5.1 Tracked in GitHub issues

- **#115** — CVD-Kyle perf vectorisation. Deferred to Phase 5. Current
  implementation is acceptable for Phase 3 scope but would not meet
  tight-latency requirements in hot-path deployment.
- **#123** — Streaming mode for Phase 3 calculators. Phase 5
  prerequisite if adapter wiring into S02 is decided. The S02 adapter
  (Phase 3.13) `xfails` its `< 1 ms` DoD because underlying calculators
  are batch-only. Three remediation options are documented in the issue.

### 5.2 Known limitations (not blocking)

- **Adapter weight propagation**: `S02FeatureAdapter` sets
  `SignalComponent.weight` but S02's `SignalScorer.compute()` currently
  ignores this field (uses its own `WEIGHTS.get(name, 0.1)` fallback).
  `DEFAULT_WEIGHT = 0.1` matches S02's fallback so out-of-the-box
  behaviour is consistent. Proper component-level weighting is a future
  S02 modification — out of Phase 3 scope.
- **Feature count**: 3 activated features is a modest basis for the
  Phase 4 Meta-Labeler. The ML model's expressive capacity is bounded;
  Phase 4 may reveal that additional features are needed before useful
  classification is possible. If so, this is a Phase 4 escalation
  (e.g., reconsidering rejected features, engineering new ones), not a
  Phase 3 gap.

### 5.3 Discovered during closure

The end-to-end integration test (§8) exposed one structural note worth
recording, but no new defects:

- The IC measurement layer (`SpearmanICMeasurer.measure_rich`) compares
  `feature[t]` against `forward_returns[t]`. Callers are expected to
  pre-shift their return series so that `forward_returns[t]` represents
  the realised return over the horizon starting at `t`. The `horizon_bars`
  parameter governs Newey-West lag selection only, not the alignment.
  This is the existing, documented behaviour and matches how S02 and the
  validation pipeline use the API; the closure test was adjusted to
  construct synthetic data consistently.

No new issue was created; no remediation required.

## 6. Phase 4 prerequisites

Each item is confirmed by either a direct code check or by the end-to-end
pipeline test (§8):

- [x] Signal columns of 5 calculators produced by validated modules.
- [x] IC results (mean, IR, turnover-adj, p-value) available per feature.
- [x] Multicollinearity recommendations + cluster mapping available.
- [x] CPCV splits generator functional with purging + embargo.
- [x] DSR, PBO, MHT computable on arbitrary strategy returns.
- [x] Selection report generator consumes all three upstream reports.
- [x] S02 adapter scaffolded (not a blocker: Phase 4 operates in batch).
- [x] ADR-0002 (methodology charter) + ADR-0004 (feature validation)
      both compatible with introducing a Meta-Labeler ML layer.
- [x] [`reports/phase_3_12/feature_selection_report.json`](../reports/phase_3_12/feature_selection_report.json)
      machine-parseable and ready for consumption by Phase 4 Fusion Engine.

**Phase 4 can start.** A dedicated design-gate PR will be raised
separately (not in this closure PR).

## 7. Phase 3 statistics

| Metric                                                | Value                 |
|-------------------------------------------------------|-----------------------|
| Sub-phases completed                                  | 13 / 13               |
| Total PRs merged (Phase 3)                            | 13                    |
| Total unit tests in repo (post-closure)               | 1,834                 |
| Total LOC net delta in tracked Phase 3 tree           | +17,890 / -98         |
| Total LOC in `features/` (non-`__init__.py`)          | ~8,271                |
| Total LOC in `tests/unit/features/` (non-`__init__`)  | ~10,532               |
| Active ADRs covering Phase 3                          | ADR-0002, ADR-0004    |
| Features candidates evaluated                         | 8                     |
| Features activated post-selection                     | 3                     |

## 8. End-to-end pipeline integration test

- **Test**: [`tests/integration/test_phase_3_pipeline.py::TestPhase3EndToEndPipeline::test_synthetic_alpha_survives_full_pipeline`](../tests/integration/test_phase_3_pipeline.py)
- **Marker**: `@pytest.mark.integration` (excluded from the default
  `tests/unit/` suite; picked up by the integration CI job).
- **Scenario**: 10 synthetic strategies (1 true alpha with controlled
  correlation to forward returns, 9 pure-noise random features) traverse
  the complete Phase 3 pipeline described in §4.

**Expected assertions**:

- Exactly 1 feature receives `decision="keep"` (the true alpha).
- 9 features receive `decision="reject"` with explicit `reject_reasons`
  (no silent skip — ADR-0004 §6).
- PBO of the final KEEP set `< 0.10`.
- `to_json()` + `to_markdown()` produce non-empty, deterministic output.

**Result on this commit**: **PASS** (1 passed in ~6.5 s).

## 9. References

- Lopez de Prado, M. (2018) *Advances in Financial Machine Learning*,
  Chapters 3, 4, 5, 7.
- Bailey & Lopez de Prado (2014) *The Deflated Sharpe Ratio*.
- Bailey, Borwein, Lopez de Prado, Zhu (2014) *The Probability of
  Backtest Overfitting*.
- Belsley, Kuh & Welsch (1980) *Regression Diagnostics*, VIF.
- Holm (1979); Benjamini & Hochberg (1995) — Multiple hypothesis testing.
- Grinold & Kahn (1999) *Active Portfolio Management*, Ch. 14.
- Harvey, Liu & Zhu (2016) *...and the Cross-Section of Expected Returns*.
- Gamma, Helm, Johnson, Vlissides (1994) *Design Patterns*, Adapter.
- ADR-0002 Methodology Charter.
- ADR-0004 Feature Validation Methodology.

## 10. Closure sign-off

- [x] End-to-end integration test passes.
- [x] All Phase 3 PRs merged (13 / 13).
- [x] Technical debt documented with GitHub issues.
- [x] Phase 4 prerequisites confirmed.
- [x] `docs/claude_memory/CONTEXT.md` updated.
- [x] `docs/claude_memory/SESSIONS.md` updated.

Signed: Claude Code (Opus 4.6) on behalf of Barbier Clément — 2026-04-14.
