# Phase 3 — Feature Validation Harness Notes

**Spec document**: `docs/phases/PHASE_3_SPEC.md`
**Started**: 2026-04-11 (design phase)
**Current sub-phase**: Pre-3.1 (design gate completed)

---

## Sub-Phase Progress

| Sub-Phase | Status | Notes |
|---|---|---|
| 3.1 Pipeline Foundation | COMPLETE | PR #108 merged |
| 3.2 Feature Store | IN_PROGRESS | PR open, awaiting review |
| 3.3 IC Measurement | PENDING | |
| 3.4 HAR-RV | PENDING | S07 har_rv_forecast() ready |
| 3.5 Rough Vol | PENDING | S07 estimate_hurst_from_vol() ready |
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
| HAR-RV | — | — | — | — | — | — |
| Rough Vol | — | — | — | — | — | — |
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
- 108 tests, 95.02% coverage on features/, 1,367 total tests (0 regressions)
- D017: FeatureStore ABC extended with asset_id (no concrete impl existed in 3.1)
- D018: Content-addressable versioning: `{calculator}-{hash8}` from SHA-256 of canonical JSON
- D019: Redis TTL cache (300s), as_of in cache key prevents PIT poisoning
- TimescaleFeatureStore: COPY protocol for bulk insert, point-in-time via computed_at <= as_of
- FeaturePipeline.run() wired: takes pre-fetched bars, computes, persists per-calculator
