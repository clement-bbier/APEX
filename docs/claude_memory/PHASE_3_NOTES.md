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
| 3.6 OFI | PENDING | S02 ofi() ready |
| 3.7 CVD + Kyle | PENDING | S02 cvd(), kyle_lambda() ready |
| 3.8 GEX | PENDING | Risk: options data availability |
| 3.9 Multicollinearity | PENDING | |
| 3.10 CPCV | PENDING | |
| 3.11 DSR/PBO | PENDING | backtesting/metrics.py has PSR/DSR |
| 3.12 Feature Report | PENDING | |
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
