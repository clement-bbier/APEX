# Phase 4.3 - Baseline Meta-Labeler diagnostic report

- Generated at: `2026-04-14T16:28:37.934119+00:00`
- Seed: `42`
- Samples: `1200`
- CPCV folds: `15`
- Smoke gate (RF mean OOS AUC >= 0.55): **PASS**

## Mean metrics

- RF mean OOS AUC: `0.7630` (std `0.0254`)
- LogReg mean OOS AUC: `0.7864`
- RF mean OOS Brier: `0.1971`
- RF - LogReg gap: `-0.0234` (Phase 4.5 gate: >= +0.03)

## Per-fold OOS metrics

| Fold | RF AUC | LogReg AUC | RF Brier |
|---|---|---|---|
| 1 | 0.7925 | 0.8145 | 0.1856 |
| 2 | 0.7887 | 0.8113 | 0.1884 |
| 3 | 0.7818 | 0.7991 | 0.1907 |
| 4 | 0.8153 | 0.8293 | 0.1791 |
| 5 | 0.7645 | 0.7807 | 0.1952 |
| 6 | 0.7644 | 0.7879 | 0.1963 |
| 7 | 0.7576 | 0.7844 | 0.1989 |
| 8 | 0.7843 | 0.8163 | 0.1895 |
| 9 | 0.7475 | 0.7673 | 0.2026 |
| 10 | 0.7336 | 0.7698 | 0.2072 |
| 11 | 0.7592 | 0.8047 | 0.2002 |
| 12 | 0.7379 | 0.7572 | 0.2073 |
| 13 | 0.7635 | 0.7785 | 0.1957 |
| 14 | 0.7169 | 0.7311 | 0.2148 |
| 15 | 0.7367 | 0.7638 | 0.2053 |

## Feature importances (RF, final fit)

| Feature | Importance |
|---|---|
| `ofi_signal` | 0.5206 |
| `day_of_week_sin` | 0.0898 |
| `realized_vol_28d` | 0.0896 |
| `har_rv_signal` | 0.0879 |
| `gex_signal` | 0.0864 |
| `hour_of_day_sin` | 0.0858 |
| `regime_vol_code` | 0.0215 |
| `regime_trend_code` | 0.0184 |

## Calibration bins (aggregate OOS, 10-bin uniform)

| Bin | Mean predicted | Observed positive rate |
|---|---|---|
| 1 | 0.0918 | 0.0000 |
| 2 | 0.1652 | 0.1505 |
| 3 | 0.2532 | 0.2898 |
| 4 | 0.3504 | 0.3732 |
| 5 | 0.4466 | 0.3899 |
| 6 | 0.5491 | 0.5582 |
| 7 | 0.6538 | 0.7173 |
| 8 | 0.7521 | 0.7942 |
| 9 | 0.8407 | 0.8704 |
| 10 | 0.9142 | 0.8571 |

## Notes

- Inputs are synthetic with calibrated alpha in `ofi_signal`; real Phase 3 signal history will be substituted in Phase 4.5.
- DSR / PBO gates are **not** evaluated here (deferred to Phase 4.5).
