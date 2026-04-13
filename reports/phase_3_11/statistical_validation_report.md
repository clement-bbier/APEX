# Phase 3.11 -- Statistical Validation Diagnostic

Generated from synthetic data (seed=42, N=1000 obs, n_strategies=10, n_folds=15).

## Setup

- 1 "true alpha" strategy: returns ~ N(0.006, 0.01) per period (strong positive drift)
- 9 "random" strategies: returns ~ N(0, 0.01) per period (pure noise)
- CPCV: n_splits=6, n_test_splits=2 -> 15 folds per strategy
- MHT correction: Holm-Bonferroni at alpha=0.05
- DSR threshold: 0.95 (ADR-0004 Step 6)
- PBO threshold: 0.10 (ADR-0004 Step 6)

## Per-Strategy Signatures (sorted by DSR)

| Strategy | Sharpe | PSR | DSR | Min-TRL | p_raw | p_holm | p_BH | Decision |
|---|---|---|---|---|---|---|---|---|
| true_alpha | 9.165 | 1.000 | 1.000 | 11 | 0.0000 | 0.0000 | 0.0000 | PASS |
| random_05 | 0.765 | 0.935 | 0.477 | 1174 | 0.5226 | 1.0000 | 1.0000 | FAIL |
| random_02 | 0.526 | 0.852 | 0.299 | 2467 | 0.7011 | 1.0000 | 1.0000 | FAIL |
| random_08 | 0.276 | 0.709 | 0.153 | 8936 | 0.8472 | 1.0000 | 1.0000 | FAIL |
| random_06 | 0.225 | 0.673 | 0.130 | 13510 | 0.8702 | 1.0000 | 1.0000 | FAIL |
| random_03 | -0.024 | 0.481 | 0.052 | >1e9 | 0.9476 | 1.0000 | 1.0000 | FAIL |
| random_04 | -0.340 | 0.249 | 0.012 | >1e9 | 0.9878 | 1.0000 | 1.0000 | FAIL |
| random_09 | -0.634 | 0.104 | 0.002 | >1e9 | 0.9977 | 1.0000 | 1.0000 | FAIL |
| random_07 | -0.698 | 0.082 | 0.002 | >1e9 | 0.9985 | 1.0000 | 1.0000 | FAIL |
| random_01 | -1.273 | 0.006 | 0.000 | >1e9 | 1.0000 | 1.0000 | 1.0000 | FAIL |

## PBO Results

- **PBO**: 0.0667 (OK -- below 0.10 threshold)
- **Passes ADR-0004**: Yes
- **Number of folds**: 15
- **Number of features**: 10

## Decision Summary

- **1 / 10** strategies pass after MHT correction (Holm at alpha=0.05)
- **9 / 10** correctly rejected
- True positive rate: 1/1 = 100%
- False discovery rate: 0/9 = 0%

## Without MHT Correction (sanity check)

- 1 / 10 strategies would pass at raw alpha=0.05
- 0 false positives in this run (true_alpha is strongly significant)
- DSR deflation alone (n_trials=10) is sufficient to reject all randoms here
  because the true_alpha has such a strong signal (Sharpe ~9.2)
- In cases with weaker true signals, MHT correction becomes critical to
  prevent false discoveries from marginal strategies (e.g. random_05 at
  raw PSR=0.935 would almost pass without n_trials deflation)

## Key Observations

1. **DSR deflation is powerful**: With n_trials=10, even random_05 (raw PSR=0.935)
   is correctly deflated to DSR=0.477. Without deflation, PSR alone would have
   flagged it as nearly significant.

2. **PBO confirms edge**: PBO=0.067 < 0.10 confirms that the IS-best strategy
   (true_alpha) consistently outperforms OOS, ruling out overfitting.

3. **Holm-Bonferroni is conservative**: All random strategies get p_holm=1.000,
   providing zero false positives at the cost of some power -- acceptable
   when the stakes are real capital deployment.

4. **Min-TRL diagnostic**: true_alpha needs only 11 observations to be significant
   at 95% confidence. Positive-Sharpe randoms need thousands; negative-Sharpe
   strategies correctly show the sentinel value (>1e9 = "non-viable"), confirming
   the signal strength gap.

## Existing Code Reuse

| Component | Source | Status |
|---|---|---|
| `probabilistic_sharpe_ratio()` | `backtesting/metrics.py` | Reused (no changes) |
| `deflated_sharpe_ratio()` | `backtesting/metrics.py` | Reused (no changes) |
| `minimum_track_record_length()` | `backtesting/metrics.py` | Reused (no changes) |
| `probability_of_backtest_overfitting_cpcv()` | `backtesting/metrics.py` | Available (not modified) |
| `backtest_overfitting_probability()` | `backtesting/metrics.py` | Deprecated, not used |
| Holm-Bonferroni | **NEW** `features/hypothesis/mht.py` | Implemented |
| Benjamini-Hochberg | **NEW** `features/hypothesis/mht.py` | Implemented |
| `DeflatedSharpeCalculator` | **NEW** `features/hypothesis/dsr.py` | Wraps existing PSR/DSR |
| `PBOCalculator` | **NEW** `features/hypothesis/pbo.py` | Rank-based PBO from IS/OOS |
| `HypothesisTestingReport` | **NEW** `features/hypothesis/report.py` | Combines all above |

## References

- Bailey & Lopez de Prado (2014). "The Deflated Sharpe Ratio." *JPM* 40(5), 94-107.
- Bailey, Borwein, Lopez de Prado, Zhu (2014). "Probability of Backtest Overfitting." *JCF*.
- Holm (1979). "A simple sequentially rejective multiple test procedure." *Scand. J. Stat.* 6:65-70.
- Benjamini & Hochberg (1995). "Controlling the False Discovery Rate." *JRSS B* 57(1):289-300.
