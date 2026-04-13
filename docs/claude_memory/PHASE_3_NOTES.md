# Phase 3 — Feature Validation Harness Notes

**Spec document**: `docs/phases/PHASE_3_SPEC.md`
**Started**: 2026-04-11 (design phase)
**Current sub-phase**: Pre-3.1 (design gate completed)

---

## Sub-Phase Progress

| Sub-Phase | Status | Notes |
|---|---|---|
| 3.1 Pipeline Foundation | COMPLETE | PR #108 merged |
| 3.2 Feature Store | COMPLETE | PR #109 merged |
| 3.3 IC Measurement | COMPLETE | PR #110 merged |
| 3.4 HAR-RV | IN_PROGRESS | PR #111 open — 20 tests, 91% coverage |
| 3.5 Rough Vol | IN_PROGRESS | PR #112 open — 23 tests, 94% coverage |
| 3.6 OFI | IN_PROGRESS | PR #113 open — 23 tests, 93% coverage |
| 3.7 CVD + Kyle | IN_PROGRESS | PR #114 open — 31 tests, 94% coverage |
| 3.8 GEX | IN_PROGRESS | PR #116 open — 31 tests, 98% coverage |
| 3.9 Multicollinearity | PENDING | |
| 3.10 CPCV | PENDING | |
| 3.11 DSR/PBO | IN_PROGRESS | PR pending -- 46 tests, 93% coverage, MHT new |
| 3.12 Feature Report | IN_PROGRESS | PR pending — 53 tests, 95% coverage |
| 3.13 S02 Integration | PENDING | Adapter pattern, no S02 modification |

## IC Results (to be filled during validation)

| Feature | IC (BTC) | IC (ETH) | IC (SPY) | IC (QQQ) | IC_IR | Decision |
|---|---|---|---|---|---|---|
| HAR-RV | synth | synth | synth | synth | synth | Synthetic validated — real data pending Phase 5 |
| Rough Vol | synth | synth | synth | synth | synth | Synthetic validated — real data pending Phase 5 |
| OFI | — | — | — | — | — | — |
| CVD | — | — | — | — | — | — |
| Kyle Lambda | — | — | — | — | — | — |
| GEX | N/A | N/A | — | — | — | — |

## Technical Notes

- `features/` package is the new code location for Phase 3
- All calculators inherit from `FeatureCalculator` ABC
- Use Polars (not pandas) for all transformations
- Use NumPy for vectorized math
- Hypothesis property tests mandatory for math functions
- Target < 5ms per feature computation per tick (for S02 integration)
- TripleBarrierLabeler exposed via adapter pattern (D013) — does not inherit from core class
- ValidationPipeline uses composable ValidationStage ABCs (D014) — 6 stubs in 3.1
- SampleWeighter.uniqueness_weights uses O(n²) concurrency counting — acceptable for offline
- 154 tests, 93.10% coverage on features/, 1,413 total tests (0 regressions)
- D017: FeatureStore ABC extended with asset_id (no concrete impl existed in 3.1)
- D018: Content-addressable versioning: `{calculator}-{hash8}` from SHA-256 of canonical JSON
- D019: Redis TTL cache (300s), as_of in cache key prevents PIT poisoning
- TimescaleFeatureStore: COPY protocol for bulk insert, point-in-time via computed_at <= as_of
- FeaturePipeline.run() wired: takes pre-fetched bars, computes, persists per-calculator
- D020: IC bootstrap reimplemented (not reused from metrics.py — Sharpe-coupled)
- D021: ICResult extended with 9 optional fields (backward-compatible)
- D022: Minimum 20 samples for IC measurement
- D023: Degenerate IC series (std=0) treated as maximally significant
- SpearmanICMeasurer: Newey-West HAC t-stat, rolling IC, turnover-adj IC, IC decay
- ICStage wired as first non-stub ValidationPipeline stage (ADR-0004 gates: |IC|>=0.02, IC_IR>=0.50)
- ICReport: JSON + Markdown with KEEP/WEAK/REJECT decisions
- D024: Expanding-window refit for HAR-RV (O(n²) correctness over perf)
- D025: tanh(residual / (k * rolling_std)) with k=3.0 — smooth bounded signal
- D026: Strict wrapper over S07 har_rv_forecast() (same pattern as D013)
- HARRVCalculator: first concrete FeatureCalculator, template for 3.5-3.8
- HARRVValidationReport: thin wrapper over ICReport for Phase 3.4 scope
- 178 tests on features/, 1,442 total tests (0 regressions)
- D027: Intraday aggregate features emit realization columns at period-close only (3.5-3.8 gatekeeper)
- 5m mode look-ahead fix: residual/signal only on last bar of each day (forecast safe to broadcast)
- Timestamp monotonicity validated in compute() — unsorted input raises ValueError
- RoughVolCalculator: wraps S07 estimate_hurst_from_vol + variance_ratio_test (D026 wrapper)
- D027 applied to all 6 rough vol columns (all are realization, unlike HAR-RV forecast)
- VR sanity verified: VR≈1 on random walk, VR>1 on AR(1) momentum series
- 207 tests on features/, 1,491 total tests (0 regressions)
- D028: Forecast-like columns (series[:t]) safe to broadcast in 5m mode; realization columns (series[:t+1]) day-close only (D027)
- 3.5 hotfix: all 6 rough vol columns reclassified forecast-like → broadcast. rough_size_adjustment renamed rough_size_multiplier (raw S07 output)
- For 3.6-3.8: each calculator must explicitly classify output columns (forecast-like vs realization) in docstring
- 209 tests on features/, 1,493 total tests (0 regressions after hotfix)
- OFICalculator: implements canonical Cont 2014 (Δbid_size − Δask_size), NOT S02 price-delta proxy (D030)
- D028 applied: all 4 OFI columns realization-like at tick t ([t-w+1, t] inclusive). D027 N/A for tick-level features
- D029: signal variance gate — test_ofi_signal_varies_across_inputs (100 DataFrames, std > 0.01)
- Book-based mode auto-detected via bid_size/ask_size columns; trade-based fallback uses signed volume
- 232 tests on features/, 1,491 total tests (0 regressions)
- 3.6 hotfix: dynamic column names from self._windows (D031), remove dead max_window param, fix comment
- D031: configurable params must honor configurability everywhere. HAR-RV/Rough Vol audited: NOT affected
- 236 tests on features/, 27 OFI tests (0 regressions after hotfix)
- CVDKyleCalculator: implements CVD + Kyle lambda directly (D032), NOT wrapping S02 (formulas differ)
- S02 cvd() = normalized ratio Σ(buy-sell)/total_vol; we need raw cumulative sum
- S02 kyle_lambda() = Cov(ΔP,Q)/Var(Q) no intercept; we need OLS with intercept on strict past window
- D028 applied: cvd/cvd_divergence realization at tick t; kyle_lambda and derivatives forecast-like
- D029 variance gates × 3: cvd_divergence, liquidity_signal, combined_signal (each signal can degenerate independently)
- D030 proactive: 4 ValueError constraints (cvd_window, kyle_window, kyle_zscore_lookback, combined_weights)
- Kyle lambda clamped ≥ 0 (negative = economically unphysical), logged via structlog warning
- CVD divergence = tanh(-corr(price_changes, cvd_changes)) — negative correlation = divergence = positive signal
- 267 tests on features/, 31 CVD/Kyle tests, 1,546+ total tests (0 regressions)
- 3.7 hotfix: doc "expanding" → "rolling window" for Kyle lambda, test rename. Zero real bugs found by Copilot.
- 3 perf suggestions deferred to Phase 5 (ADR-0002 correctness-first). Tracking issue #115.
- Kyle lambda clamp rate: 50-73% on random walk (expected), 0% on illiquid data (correct). Not a bug.
- GEXCalculator: implements GEX inline (D033), NOT wrapping S02 (sign convention inverted, no S² formula)
- S02 update_gex() sign: calls=+1, puts=-1. Barbon-Buraschi: calls=-1, puts=+1. Irreconcilable.
- D028 applied: gex_raw/gex_normalized realization at t; gex_zscore/gex_regime/gex_signal forecast-like
- D029 variance gates × 3: gex_raw, gex_zscore, gex_signal
- D030 proactive: 3 ValueError constraints (zscore_lookback, regime thresholds, contract_multiplier)
- Magnitude sanity: SPY-like chain → |gex_raw| ∈ [1e7, 1e12], confirmed by dedicated test
- 298 tests on features/, 31 GEX tests, 1,582+ total tests (0 regressions)
- **Phase 3.4-3.8 calculator wave COMPLETE**: 5/5 calculators validated (HAR-RV, Rough Vol, OFI, CVD+Kyle, GEX)
- Route open for Phase 3.9 Multicollinearity + Orthogonalization
- 3.8 hotfix: data quality gate (spot_price constant per timestamp), case-insensitive option_type
- D034: snapshot-level IC measurement for features with multiple rows per timestamp (GEX). Row-level IC produces artificial zero returns. Applies to all future snapshot-granularity features.
- 300 tests on features/, 33 GEX tests, 1,584+ total tests (0 regressions after hotfix)
- Phase 3.11: features/hypothesis/ package (NEW) -- MHT, DSR wrapper, PBO calculator, report
- MHT genuinely new: holm_bonferroni() + benjamini_hochberg() in features/hypothesis/mht.py
- DeflatedSharpeCalculator wraps existing backtesting.metrics.deflated_sharpe_ratio() (no reimplementation)
- PBOCalculator: rank-based PBO from IS/OOS fold-level metrics (canonical Bailey et al. 2014 Eq 11-12)
- ADR-0004 thresholds confirmed: DSR > 0.95, PBO < 0.10 (spec PBOResult.is_overfit uses 0.50 as secondary)
- Critical test: 10 strategies (1 alpha + 9 random) -> only alpha survives Holm-Bonferroni
- 46 tests on features/hypothesis/, 93% coverage, 1,736 total tests (0 regressions)
- Phase 3.12: features/selection/ package (NEW) -- FeatureSelectionReport, SelectionDecision
- FeatureSelectionReportGenerator: configurable gates from ADR-0004 (IC>=0.02, IC_IR>=0.50, VIF<=5.0, DSR>=0.95, PSR>=0.90, p_holm<=0.05, PBO<0.10)
- Cherry-picking protection: missing multicoll/hypothesis evidence = explicit reject, not silent pass
- Synthetic 8-feature report: 3 KEEP (gex_signal, har_rv_signal, ofi_signal), 5 REJECT
- PBO of final set: 0.05 (strong evidence per ADR-0004)
- 53 tests on features/selection/, 95% coverage, 1,789 total tests (0 regressions)
