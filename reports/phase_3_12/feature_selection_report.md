# Phase 3 Feature Selection Report

Generated: 2026-04-14T00:05:46Z
Candidates: 8
Kept: 3
Rejected: 5
PBO of final set: 0.0500

## Decision summary

| Feature | Calculator | Decision | DSR | VIF | IC_IR | p_holm | Reasons |
|---|---|---|---|---|---|---|---|
| gex_signal | GEX | **keep** | 0.970 | 1.01 | 1.500 | 0.0100 | — |
| har_rv_signal | HAR-RV | **keep** | 0.960 | 3.57 | 1.200 | 0.0080 | — |
| ofi_signal | OFI | **keep** | 0.960 | 2.10 | 1.000 | 0.0150 | — |
| cvd_signal | CVD+Kyle | reject | 0.950 | 2.30 | 0.800 | 0.0200 | cluster_dropped_by_ic_ranking |
| rough_hurst | Rough Vol | reject | 0.890 | 1.80 | 0.900 | 0.0450 | dsr=0.890 < 0.95 |
| rough_vol_signal | Rough Vol | reject | 0.850 | 1.50 | 0.700 | 0.0400 | dsr=0.850 < 0.95 |
| combined_signal | CVD+Kyle | reject | 0.550 | 1.20 | 0.300 | 0.3000 | ic_mean=0.0100 < 0.02; ic_ir=0.300 < 0.5; ic_p_value=0.2000 > 0.05; dsr=0.550 < 0.95; psr=0.600 < 0.9; p_value_holm=0.3000 > 0.05 |
| liquidity_signal | CVD+Kyle | reject | 0.400 | 1.10 | 0.100 | 0.5000 | ic_mean=0.0050 < 0.02; ic_ir=0.100 < 0.5; ic_p_value=0.5000 > 0.05; dsr=0.400 < 0.95; psr=0.500 < 0.9; p_value_holm=0.5000 > 0.05 |

## Per-feature details

### gex_signal (KEEP)

- **Calculator**: GEX
- **IC (mean / IR / p-value)**: 0.0900 / 1.500 / 0.0005
- **Turnover-adjusted IC**: 0.0810
- **VIF**: 1.01 (cluster 0)
- **Sharpe / PSR / DSR / Min-TRL**: 1.850 / 0.970 / 0.970 / 200
- **p-value (Holm-adjusted)**: 0.0100
- **All gates passed.**

### har_rv_signal (KEEP)

- **Calculator**: HAR-RV
- **IC (mean / IR / p-value)**: 0.0800 / 1.200 / 0.0010
- **Turnover-adjusted IC**: 0.0720
- **VIF**: 3.57 (cluster 1)
- **Sharpe / PSR / DSR / Min-TRL**: 1.600 / 0.960 / 0.960 / 220
- **p-value (Holm-adjusted)**: 0.0080
- **All gates passed.**

### ofi_signal (KEEP)

- **Calculator**: OFI
- **IC (mean / IR / p-value)**: 0.0700 / 1.000 / 0.0020
- **Turnover-adjusted IC**: 0.0630
- **VIF**: 2.10 (cluster 2)
- **Sharpe / PSR / DSR / Min-TRL**: 1.500 / 0.950 / 0.960 / 230
- **p-value (Holm-adjusted)**: 0.0150
- **All gates passed.**

### cvd_signal (REJECT)

- **Calculator**: CVD+Kyle
- **IC (mean / IR / p-value)**: 0.0500 / 0.800 / 0.0100
- **Turnover-adjusted IC**: 0.0450
- **VIF**: 2.30 (cluster 2)
- **Sharpe / PSR / DSR / Min-TRL**: 1.300 / 0.940 / 0.950 / 250
- **p-value (Holm-adjusted)**: 0.0200
- **Reject reasons**:
  - cluster_dropped_by_ic_ranking

### rough_hurst (REJECT)

- **Calculator**: Rough Vol
- **IC (mean / IR / p-value)**: 0.0600 / 0.900 / 0.0050
- **Turnover-adjusted IC**: 0.0540
- **VIF**: 1.80 (cluster 3)
- **Sharpe / PSR / DSR / Min-TRL**: 1.230 / 0.910 / 0.890 / 380
- **p-value (Holm-adjusted)**: 0.0450
- **Reject reasons**:
  - dsr=0.890 < 0.95

### rough_vol_signal (REJECT)

- **Calculator**: Rough Vol
- **IC (mean / IR / p-value)**: 0.0400 / 0.700 / 0.0200
- **Turnover-adjusted IC**: 0.0360
- **VIF**: 1.50 (cluster 4)
- **Sharpe / PSR / DSR / Min-TRL**: 1.100 / 0.900 / 0.850 / 400
- **p-value (Holm-adjusted)**: 0.0400
- **Reject reasons**:
  - dsr=0.850 < 0.95

### combined_signal (REJECT)

- **Calculator**: CVD+Kyle
- **IC (mean / IR / p-value)**: 0.0100 / 0.300 / 0.2000
- **Turnover-adjusted IC**: 0.0090
- **VIF**: 1.20 (cluster 5)
- **Sharpe / PSR / DSR / Min-TRL**: 0.500 / 0.600 / 0.550 / 600
- **p-value (Holm-adjusted)**: 0.3000
- **Reject reasons**:
  - ic_mean=0.0100 < 0.02
  - ic_ir=0.300 < 0.5
  - ic_p_value=0.2000 > 0.05
  - dsr=0.550 < 0.95
  - psr=0.600 < 0.9
  - p_value_holm=0.3000 > 0.05

### liquidity_signal (REJECT)

- **Calculator**: CVD+Kyle
- **IC (mean / IR / p-value)**: 0.0050 / 0.100 / 0.5000
- **Turnover-adjusted IC**: 0.0045
- **VIF**: 1.10 (cluster 6)
- **Sharpe / PSR / DSR / Min-TRL**: 0.300 / 0.500 / 0.400 / 800
- **p-value (Holm-adjusted)**: 0.5000
- **Reject reasons**:
  - ic_mean=0.0050 < 0.02
  - ic_ir=0.100 < 0.5
  - ic_p_value=0.5000 > 0.05
  - dsr=0.400 < 0.95
  - psr=0.500 < 0.9
  - p_value_holm=0.5000 > 0.05

## PBO analysis

Final set of 3 features, PBO = 0.0500.
Strong evidence of genuine edge (PBO < 0.10 configured gate).

## References

- Grinold & Kahn (1999) Ch. 14 — IC-based alpha model construction
- Harvey, Liu & Zhu (2016) — Multiple testing in cross-sectional return predictors
- Bailey & López de Prado (2014) — DSR
- Bailey et al. (2014) — PBO
- ADR-0004 Feature Validation Methodology
