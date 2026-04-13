# Phase 3.9 — Multicollinearity Analysis Report

## Input scope

- Signal columns (N=8): har_rv_signal, vr_signal, ofi_signal, cvd_divergence, liquidity_signal, combined_signal, gex_signal, gex_raw
- Non-NaN rows after drop: 1000
- Condition number: 3.5303

## Correlation matrix (Pearson)

| | har_rv_signal | vr_signal | ofi_signal | cvd_divergence | liquidity_signal | combined_signal | gex_signal | gex_raw |
|---|---|---|---|---|---|---|---|---|
| har_rv_signal | 1.0000 | 0.8481 | -0.0079 | -0.0019 | -0.0073 | -0.0650 | 0.0213 | -0.0056 |
| vr_signal | 0.8481 | 1.0000 | -0.0202 | -0.0003 | 0.0129 | -0.0701 | 0.0406 | -0.0030 |
| ofi_signal | -0.0079 | -0.0202 | 1.0000 | 0.8067 | -0.0006 | -0.0019 | -0.0558 | 0.0141 |
| cvd_divergence | -0.0019 | -0.0003 | 0.8067 | 1.0000 | 0.0023 | 0.0307 | -0.0510 | 0.0449 |
| liquidity_signal | -0.0073 | 0.0129 | -0.0006 | 0.0023 | 1.0000 | 0.0142 | 0.0063 | -0.0275 |
| combined_signal | -0.0650 | -0.0701 | -0.0019 | 0.0307 | 0.0142 | 1.0000 | -0.0222 | 0.0221 |
| gex_signal | 0.0213 | 0.0406 | -0.0558 | -0.0510 | 0.0063 | -0.0222 | 1.0000 | -0.0234 |
| gex_raw | -0.0056 | -0.0030 | 0.0141 | 0.0449 | -0.0275 | 0.0221 | -0.0234 | 1.0000 |

## VIF per signal (threshold=5.0)

| Signal | VIF | Status |
|---|---|---|
| har_rv_signal | 3.5738 | OK |
| vr_signal | 3.5849 | OK |
| ofi_signal | 2.8814 | OK |
| cvd_divergence | 2.8857 | OK |
| liquidity_signal | 1.0024 | OK |
| combined_signal | 1.0092 | OK |
| gex_signal | 1.0063 | OK |
| gex_raw | 1.0051 | OK |

## Collinear pairs

| Signal A | Signal B | rho |
|---|---|---|
| har_rv_signal | vr_signal | 0.8481 |
| ofi_signal | cvd_divergence | 0.8067 |

## Cluster assignments

| Signal | Cluster |
|---|---|
| har_rv_signal | 3 |
| vr_signal | 3 |
| ofi_signal | 1 |
| cvd_divergence | 1 |
| liquidity_signal | 5 |
| combined_signal | 4 |
| gex_signal | 2 |
| gex_raw | 6 |

## Recommended drops

- `cvd_divergence`
- `vr_signal`

## References

- Belsley, Kuh & Welsch (1980)
- Lopez de Prado (2018) Ch. 8
- Lopez de Prado (2020) Ch. 6

## Variance retention after orthogonalization (residualize)

| Signal | Original variance | Post-ortho variance | Retention % |
|---|---|---|---|
| har_rv_signal | 0.978550 | 0.978550 | 100.0% |
| vr_signal | 1.021120 | 0.286583 | 28.1% |
| ofi_signal | 1.029295 | 1.029295 | 100.0% |
| cvd_divergence | 0.982018 | 0.343022 | 34.9% |
| liquidity_signal | 0.996683 | 0.996683 | 100.0% |
| combined_signal | 1.039926 | 1.039926 | 100.0% |
| gex_signal | 1.051950 | 1.051950 | 100.0% |
| gex_raw | 0.949370 | 0.949370 | 100.0% |

## Conclusion

Two collinear pairs were identified: (har_rv_signal, vr_signal) and (ofi_signal, cvd_divergence). Both pairs exceed the |rho| >= 0.70 threshold. The recommended strategy is drop_lowest_ic, which removes vr_signal (IC=0.06) and cvd_divergence (IC=0.04) in favor of their higher-IC counterparts. After residualization, the orthogonalized signals retain the unique information not explained by the keeper signal, though with substantially reduced variance. The remaining 6 independent signals (after drop) all have VIF < 5.0.

Generated from synthetic predictive input (seed=42, N=1000 bars).
