# Phase 4.4 - Nested CPCV tuning report

- Generated at: `2026-04-14T18:14:38.963112+00:00`
- Seed: `42`
- Config: **fast (CI default)**
- Samples: `400`
- Outer CPCV folds: `6` / Inner CPCV folds: `3`
- Search-space cardinality: `8` trials
- Total trials in ledger: `48`
- Wall-clock: `16.76s`
- Stability index: `0.3333` (fraction of outer folds whose best hparams equal the mode)

## Outer-fold winners

| Fold | n_estimators | max_depth | min_samples_leaf | OOS AUC |
|---|---|---|---|---|
| 1 | 60 | 3 | 5 | 0.7482 |
| 2 | 30 | 5 | 5 | 0.7074 |
| 3 | 30 | 3 | 5 | 0.7382 |
| 4 | 60 | 5 | 10 | 0.7599 |
| 5 | 60 | 3 | 5 | 0.7445 |
| 6 | 60 | 5 | 10 | 0.6959 |

## Aggregate OOS performance

- Mean best-OOS AUC: `0.7324` (std `0.0229`)
- Selection criterion: inner-CV-mean weighted AUC (honest nested CV).

## Top-5 trials globally by OOS AUC

| Rank | Hparams | mean_inner_cv_auc | OOS AUC |
|---|---|---|---|
| 1 | `n_estimators=60, max_depth=5, min_samples_leaf=5` | 0.6968 | 0.7740 |
| 2 | `n_estimators=30, max_depth=5, min_samples_leaf=5` | 0.6846 | 0.7644 |
| 3 | `n_estimators=30, max_depth=3, min_samples_leaf=10` | 0.7535 | 0.7615 |
| 4 | `n_estimators=60, max_depth=3, min_samples_leaf=10` | 0.7715 | 0.7611 |
| 5 | `n_estimators=60, max_depth=5, min_samples_leaf=10` | 0.7026 | 0.7599 |

## Notes

- Inputs are synthetic with calibrated alpha in `ofi_signal`; real Phase 3 signal history will be substituted in Phase 4.5.
- Full trial ledger is persisted in `tuning_trials.json` for Phase 4.5 PBO / DSR computation (Bailey et al. 2014).
- The CI default runs a narrower grid (8 trials x 6 outer x 3 inner = 144 fits + 48 refits) to keep the report under a minute.
- Set `APEX_FULL_TUNING=1` to run the PHASE_4_SPEC section 3.4 spec grid (18 x 15 x 4 = 1,080 inner fits + 270 outer refits).
