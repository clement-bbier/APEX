# ADR-0004: Feature Validation Methodology

> *Note (2026-04-18): This ADR continues to govern its respective subsystem. See [APEX Multi-Strat Charter](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) §12.4 for the inventory of existing and anticipated ADRs in the multi-strat context.*

| Field | Value |
|---|---|
| Status | ACCEPTED |
| Date | 2026-04-12 |
| Decider | Clement Barbier (system architect) |
| Supersedes | None |
| Superseded by | None |

---

## 1. Context

Phase 3 of APEX will validate approximately six candidate features for
integration into the S02 Signal Engine: HAR-RV (realized volatility
forecasting), Rough Volatility (fractional Brownian motion), OFI (Order
Flow Imbalance), CVD (Cumulative Volume Delta), Kyle's Lambda (price
impact coefficient), and GEX (Gamma Exposure).

Each feature will be tested as a predictive signal for forward returns.
The risk of false discovery is extreme: Bailey and Lopez de Prado (2014)
demonstrated that approximately 75% of published trading strategies are
statistical artifacts when proper multiple-testing corrections are not
applied. Harvey, Liu, and Zhu (2016) reached similar conclusions for
asset pricing factors.

Without a canonical, reproducible validation methodology established
*before* any feature coding begins, Phase 3 risks shipping features
that appear to work in-sample but fail in production. This ADR defines
the mandatory validation pipeline.

## 2. Decision

Every candidate feature MUST pass the following six-step pipeline before
acceptance into the APEX signal ensemble. No step may be skipped. Each
step produces a versioned artifact stored in the Feature Store
(see ADR-0003 for schema).

### Step 1 -- Information Coefficient (IC)

Measure the rank correlation (Spearman rho) between the feature value
at time *t* and the forward return over a specified horizon.

| Parameter | Value |
|---|---|
| Correlation method | Spearman rank (non-parametric, robust to outliers) |
| Forward horizons | 1-bar, 5-bar, 20-bar |
| Acceptance threshold | \|IC\| >= 0.02 (minimum), \|IC\| >= 0.05 (strong) |
| IC Information Ratio | IC_IR = mean(IC) / std(IC) >= 0.50 |
| Asset universes | BTC, ETH, SPY, QQQ (minimum 4) |

The IC is the simplest and most robust measure of a feature's predictive
power. A feature that cannot achieve \|IC\| >= 0.02 on any horizon has no
informational content worth harvesting.

**References:**
- Grinold, R.C. (1989). "The Fundamental Law of Active Management."
  *Journal of Portfolio Management*, 15(3), 30-37.
- Grinold, R.C. & Kahn, R.N. (1999). *Active Portfolio Management*.
  McGraw-Hill, Ch. 4.

### Step 2 -- IC Stability Over Time

A feature with high average IC but extreme temporal instability is
dangerous: it may have worked only during a specific regime that no
longer holds.

| Parameter | Value |
|---|---|
| Decomposition | By calendar year (2022, 2023, 2024, ...) |
| Regime decomposition | Calm, volatile, trending, ranging |
| Rejection criterion | IC fluctuation > 50% between adjacent years |
| Rolling IC window | 60-day rolling, plotted as time series |

**References:**
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
  Wiley, Ch. 8 ("Feature Importance").

### Step 3 -- Multicollinearity Check

If the candidate feature is added to an existing feature set, redundancy
must be measured. Two highly correlated features provide no additional
information and inflate variance.

| Parameter | Value |
|---|---|
| Metric | Pearson correlation matrix of all candidate + accepted features |
| Rejection threshold | \|correlation\| > 0.70 with any accepted feature |
| Mitigation | Gram-Schmidt orthogonalization or PCA residualization |
| VIF threshold | VIF < 5.0 for all features in combined set |

**References:**
- Belsley, D.A., Kuh, E. & Welsch, R.E. (1980). *Regression
  Diagnostics: Identifying Influential Data and Sources of
  Collinearity*. Wiley.
- Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*.
  Cambridge University Press, Ch. 6.

### Step 4 -- Feature Importance (MDA)

Even a feature with non-zero IC may add nothing to an ensemble if
existing features already capture the same signal. Mean Decrease Accuracy
(MDA) via permutation importance measures marginal contribution.

| Parameter | Value |
|---|---|
| Method | Permutation importance (sklearn) |
| Model | Random Forest classifier (default hyperparameters) |
| Acceptance criterion | First feature: MDA > 0 (beats random noise). Subsequent: MDA > median MDA of accepted features. |
| Cross-validation | 5-fold stratified, no lookahead |

**Bootstrap case rationale:** For the first feature candidate, there is no
prior baseline. We require strictly positive MDA to ensure the feature
beats random noise -- a weaker but non-trivial gate. Once the first
feature is accepted, subsequent features must clear the median bar to
maintain aggregate information content.

**References:**
- Breiman, L. (2001). "Random Forests." *Machine Learning*, 45(1), 5-32.
  DOI: 10.1023/A:1010933404324
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
  Wiley, Ch. 8.

### Step 5 -- CPCV Backtest

Test the feature in a minimal predictive model using Combinatorial
Purged Cross-Validation. CPCV prevents lookahead bias by purging
training samples that overlap with the test period and adding an
embargo buffer.

| Parameter | Value |
|---|---|
| Model | Logistic regression or minimal Random Forest |
| CV method | CPCV: C(N, k) with N=10 splits, k=2 test folds |
| Purging | Remove training samples within embargo window of test |
| Embargo | 5 bars (configurable per asset class) |
| Metric | Out-of-sample accuracy, Sharpe of predicted returns |

**References:**
- Bailey, D.H. & Lopez de Prado, M. (2017). "An Open-Source
  Implementation of the Critical-Line Algorithm for Portfolio
  Optimization." *Journal of Computational Finance*.
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
  Wiley, Ch. 12 ("Backtesting through Cross-Validation").

### Step 6 -- Statistical Significance (PSR / DSR / PBO)

The final gate ensures that the observed performance is not a statistical
artifact of data mining.

| Parameter | Value |
|---|---|
| PSR threshold | Probabilistic Sharpe Ratio > 0.95 |
| DSR requirement | Deflated Sharpe Ratio accounting for all trials |
| PBO threshold | Probability of Backtest Overfitting < 0.10 |
| PBO method | Rank-based PBO (Bailey et al. 2017) |
| Number of trials | Total candidate features tested (for Bonferroni) |

**References:**
- Bailey, D.H. & Lopez de Prado, M. (2012). "The Sharpe Ratio
  Efficient Frontier." *Journal of Risk*, 15(2), 3-44.
  DOI: 10.21314/JOR.2012.255
- Bailey, D.H. & Lopez de Prado, M. (2014). "The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting and
  Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.
- Bailey, D.H., Borwein, J., Lopez de Prado, M. & Zhu, Q.J. (2017).
  "The Probability of Backtest Overfitting." *Journal of Computational
  Finance*, 20(4), 39-69.

## 3. Alternatives Considered

### A. Simple backtesting without CPCV
Standard train/test split or k-fold without purging. Rejected because
financial time series exhibit strong autocorrelation, making standard
CV produce optimistically biased estimates. Lopez de Prado (2018, Ch. 7)
demonstrates this bias can inflate Sharpe by 2-3x.

### B. IC measurement alone without feature importance
IC only measures marginal signal. Without MDA or correlation checks,
the pipeline would accept redundant features that add variance without
information. Grinold's Fundamental Law (1989) shows that breadth (number
of independent bets) matters as much as skill (IC per bet).

### C. Sharpe ratio without DSR/PBO corrections
Bailey and Lopez de Prado (2014) demonstrated that without deflation
for the number of trials attempted, approximately 75% of reported
Sharpe ratios above 1.0 are false discoveries. Using raw Sharpe alone
would guarantee accepting overfitted features.

## 4. Consequences

### Positive
- Prevents ~80% of false positive features (Lopez de Prado estimate)
- Every accepted feature has a complete, reproducible validation dossier
- Pipeline is versioned and auditable (Feature Store artifacts)
- Aligns with institutional-grade quantitative research standards
- Provides clear rejection criteria -- no subjective judgment needed

### Negative
- Slower than a naive pipeline (~2-3 days per feature vs 2-3 hours)
- May reject "intuitively good" features that lack statistical edge
- Requires implementation of validation infrastructure (FeatureValidator,
  CPCV splitter, PSR/DSR calculators) before any feature can be tested
- GEX validation may be blocked by options data availability

## 5. Implementation

The validation pipeline maps directly to Phase 3 sub-phases:

| ADR Step | Phase 3 Sub-phase | Deliverable |
|---|---|---|
| Step 1 (IC) | 3.3 IC Measurement | `features/validation/ic_measurer.py` |
| Step 2 (Stability) | 3.3 IC Measurement | IC decomposition reports |
| Step 3 (Multicol) | 3.9 Multicollinearity | `features/validation/multicol.py` |
| Step 4 (MDA) | 3.9 Multicollinearity | Permutation importance module |
| Step 5 (CPCV) | 3.10 CPCV | `features/validation/cpcv_splitter.py` |
| Step 6 (PSR/DSR/PBO) | 3.11 Multiple Testing | `backtesting/metrics.py` extensions |

See `docs/phases/PHASE_3_SPEC.md` for detailed deliverables and
acceptance criteria per sub-phase.

## 6. References

1. Bailey, D.H. & Lopez de Prado, M. (2012). "The Sharpe Ratio
   Efficient Frontier." *Journal of Risk*, 15(2), 3-44.
2. Bailey, D.H. & Lopez de Prado, M. (2014). "The Deflated Sharpe
   Ratio." *Journal of Portfolio Management*, 40(5), 94-107.
3. Bailey, D.H. & Lopez de Prado, M. (2017). "An Open-Source
   Implementation of the Critical-Line Algorithm." *Journal of
   Computational Finance*.
4. Bailey, D.H., Borwein, J., Lopez de Prado, M. & Zhu, Q.J. (2017).
   "The Probability of Backtest Overfitting." *Journal of Computational
   Finance*, 20(4), 39-69.
5. Belsley, D.A., Kuh, E. & Welsch, R.E. (1980). *Regression
   Diagnostics*. Wiley.
6. Breiman, L. (2001). "Random Forests." *Machine Learning*, 45(1),
   5-32. DOI: 10.1023/A:1010933404324
7. Grinold, R.C. (1989). "The Fundamental Law of Active Management."
   *Journal of Portfolio Management*, 15(3), 30-37.
8. Grinold, R.C. & Kahn, R.N. (1999). *Active Portfolio Management*.
   McGraw-Hill, 2nd ed.
9. Harvey, C.R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section
   of Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
   DOI: 10.1093/rfs/hhv059
10. Lopez de Prado, M. (2018). *Advances in Financial Machine
    Learning*. Wiley.
11. Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*.
    Cambridge University Press.
