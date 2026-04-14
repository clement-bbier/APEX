# ADR-0005 — Meta-Labeling and Fusion Methodology

| Field | Value |
|---|---|
| Status | Proposed — 2026-04-14 |
| Decider | Clement Barbier (system architect) |
| Supersedes | None |
| Superseded by | None |
| Related | ADR-0002 (Quant Methodology Charter), ADR-0004 (Feature Validation Methodology) |

---

## 1. Context

Phase 3 delivered a validated pool of three keep-features
(`gex_signal`, `har_rv_signal`, `ofi_signal`) with full IC, CPCV,
multicollinearity, and DSR/PBO evidence per ADR-0004. Phase 4 builds
the decision layer on top: a supervised binary classifier that learns
**when to trust** the primary signals (the "Meta-Labeler", López de
Prado 2018, §3.6) and an explicit fusion layer that combines the N
signals into a single per-bar score.

This ADR establishes the methodological contract under which Phase 4
code is considered production-acceptable. ADR-0004 addressed
signal-level feature validation; it is silent on supervised ML
specifics. This ADR adds the ML-layer rules: label leakage, class
imbalance, hyperparameter snooping, model versioning, production
calibration drift, and model artifact audit trail.

**Pre-existing state (from 2026-04-14 audit):**

- `core/math/labeling.py` and `features/labels.py` already implement
  a `TripleBarrierLabeler` with vol-adaptive barriers and ternary
  labels `{-1, 0, +1}`. Phase 4.1 extends this implementation rather
  than re-writing it, and aligns its output with the binary
  Meta-Labeler target defined in this ADR (D1).
- `services/s04_fusion_engine/meta_labeler.py` ships a **deterministic
  rules-based** MetaLabeler (weighted sum of `n_triggers`, `vpin`,
  `hurst_exponent`, etc.) that returns `meta_score ∈ [-1, +1]`. It is
  labelled in-code as "Phase 5: deterministic rules, Phase 6:
  trained classifier". Phase 4 promotes that roadmap forward: the
  trained classifier shipped in sub-phase 4.3 is the replacement,
  behind a stable interface.
- `services/s05_risk_manager/meta_label_gate.py` already reads
  `meta_label:latest:{symbol}` from Redis and modulates Kelly sizing
  by `confidence ∈ [0, 1]`. Phase 4 persists the trained
  classifier's calibrated probability at that Redis key (wiring
  itself is Phase 5 work).
- `features/hypothesis/` (DSR, PBO, MHT) and `features/cv/cpcv.py`
  (`CombinatoriallyPurgedKFold` with `t1` purging + embargo) are
  reused as-is for Meta-Labeler validation (no reimplementation).
- `features/integration/config.py` (`FeatureActivationConfig`) is the
  canonical source of activated features and is loaded verbatim by
  the Meta-Labeler feature builder.
- `backtesting/metrics.py` provides the three-scenario transaction
  cost model (zero, realistic, stress) required by ADR-0002 D7.

Nothing in this ADR invalidates existing code. Every decision below
is either a constraint on new Phase 4 modules or an explicit extension
of a pre-existing API.

---

## 2. Decision

### D1 — Labeling: Triple Barrier Method is mandatory ground truth

For every training example fed to the Meta-Labeler, labels are
produced via the Triple Barrier Method (López de Prado 2018, §3.4).
Sub-phase 4.1 extends `core/math/labeling.py` and `features/labels.py`
with the following binding parameters:

- **Upper barrier (take-profit)**: `price_t + k_up × σ_t × price_t`
  where `k_up ∈ {1.0, 2.0}` is configurable per training run.
  Phase 4 default: `k_up = 2.0`.
- **Lower barrier (stop-loss)**: `price_t − k_down × σ_t × price_t`
  with `k_down` typically symmetric. Phase 4 default:
  `k_down = 1.0` (asymmetric profile matches the existing
  `TripleBarrierConfig` defaults and the MetaLabelGate long-only
  bias).
- **Vertical barrier (time-limit)**: horizon `H ∈ {1h, 4h, 1d}` bound
  to feature cadence. Equities daily bars: default `H = 1d`.
  Crypto 5-minute bars: default `H = 4h` (48 bars).
- **Volatility estimator `σ_t`**: EWMA of squared log returns with
  `vol_lookback = 20` bars (matches existing
  `TripleBarrierConfig.vol_lookback`). The window must end strictly
  before `t` (no lookahead into the labeled bar).
- **Label convention (binary target)**: the Meta-Labeler consumes the
  binary projection `y = 1 if BarrierLabel.label == +1 else 0`. The
  ternary `{-1, 0, +1}` output of `BarrierLabel.label` is preserved
  for audit trail and direction-aware analysis, but the classifier
  trains on the binary target. Vertical-barrier time-outs
  (`label == 0`) are labeled `y = 0` (non-profitable, consistent
  with "no edge taken").
- **Direction assumption**: Phase 4 MVP is **long-only**. Signals
  are interpreted as "time to buy". Short-side Meta-Labeler is
  out-of-scope and tracked as a Phase 4.X extension.
- **Reference prices**: raw close prices, not fractionally
  differentiated. Fractional differentiation (Phase 2) is for
  feature stationarity only; P&L measurement uses raw prices.

### D2 — Sample weights: uniqueness × return attribution

Every sample carries two weights (López de Prado §4.4–4.5) computed
in sub-phase 4.2:

- **Uniqueness weight** `u_i`: inverse of the average concurrency
  count of label-span `[t0_i, t1_i]` with other label spans.
  Formally, `u_i = mean(1 / c_t for t in [t0_i, t1_i])` where `c_t`
  is the number of labels whose span covers bar `t`. This prevents
  oversampling periods with many overlapping labels.
- **Return attribution weight** `r_i`:
  `r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|` where `ret_t` is
  the log return of bar `t`. Weights samples by the P&L magnitude
  attributable to the label span, not just the hit/miss outcome.

**Final training weight**: `w_i = u_i × r_i`, then normalized so that
`sum(w_i) = n_samples`. Weights are passed through
`sklearn.fit(X, y, sample_weight=w)`. CPCV fold construction itself
is NOT weighted; weights live inside `.fit()`.

### D3 — Classifier choice: Random Forest is default

- **Primary classifier**: `sklearn.ensemble.RandomForestClassifier`
  with `class_weight="balanced"` and `n_jobs=-1`. Rationale:
  interpretable feature importances, robust to class imbalance,
  few critical hyperparameters, widely validated in quant literature
  (López de Prado 2018, §6 and §8 endorse RF).
- **Mandatory baseline**:
  `sklearn.linear_model.LogisticRegression` with
  `class_weight="balanced"` and `max_iter=500` is trained on every
  Meta-Labeler training run. The RF candidate is rejected unless
  `mean_CPCV_AUC(RF) − mean_CPCV_AUC(LogReg) ≥ 0.03`. This prevents
  shipping a complex model that underperforms a linear baseline.
- **Alternatives allowed with written justification** in the
  sub-phase PR body:
  - Gradient Boosting
    (`sklearn.ensemble.GradientBoostingClassifier`,
    `lightgbm.LGBMClassifier`, `xgboost.XGBClassifier`) when RF
    under-fits and the PR body documents the symptom (e.g., RF
    train AUC ≈ OOS AUC, suggesting bias rather than variance).
- **Out of scope**: Deep learning (MLP, LSTM, Transformer) is
  explicitly deferred. A future ADR is required if empirical
  evidence of RF/GB under-fitting on the activated signal set
  motivates neural architectures.

### D4 — Validation: nested CPCV

- **Outer loop**: `CombinatoriallyPurgedKFold` from
  `features/cv/cpcv.py` with `n_splits=6`, `n_test_splits=2`,
  `embargo_pct=0.02`, yielding C(6, 2) = 15 outer folds. This
  matches Phase 3.10's canonical setup.
- **Inner loop**: hyperparameter tuning runs inside each outer
  training fold via another CPCV pass with `n_splits=4`,
  `n_test_splits=1`. Nested CV prevents hyperparameter snooping
  across outer test folds.
- **Purging**: uses `t0` (label start = entry time) and `t1`
  (label end = exit time) from `BarrierLabel`. Compatible with the
  `split(X, t1)` signature of `CombinatoriallyPurgedKFold`;
  sub-phase 4.2 extends the splitter (backward-compatibly) to
  accept an optional `t0` argument if required for sample-weight
  uniqueness alignment.
- **Sample weights** (D2) are passed as `sample_weight=w_train`
  into `fit()` at every fold. The tuning objective inside the
  inner loop uses weighted AUC (`sklearn.metrics.roc_auc_score`
  with `sample_weight=w_val`).

### D5 — Decision gates for Meta-Labeler deployment

A trained Meta-Labeler candidate is deployable if and only if **all**
of the following gates pass on the CPCV outer OOS folds:

| # | Gate | Threshold | Measurement source |
|---|---|---|---|
| G1 | Mean OOS AUC | ≥ 0.55 | `sklearn.metrics.roc_auc_score` |
| G2 | Min per-fold OOS AUC | ≥ 0.52 | degenerate-fold guard |
| G3 | Deflated Sharpe Ratio on bet-sized P&L | ≥ 0.95 | `features/hypothesis/dsr.py` |
| G4 | Probability of Backtest Overfitting on tuning trials | < 0.10 | `features/hypothesis/pbo.py` |
| G5 | Brier score (calibration) | ≤ 0.25 | `sklearn.metrics.brier_score_loss` |
| G6 | Minority class frequency in training set | ≥ 10 % | warn if 5–10 %, reject if < 5 % |
| G7 | RF − LogReg mean OOS AUC | ≥ 0.03 | D3 baseline-beat rule |

The DSR gate (G3) is measured under the **realistic** transaction
cost scenario per ADR-0002 D7 (see D8 below). Zero-cost and stress
scenarios are informational only; the deployment decision uses
realistic.

If any gate fails, the model is rejected. The sub-phase 4.5 closure
report records the failing gate with the observed numerical value
and must propose either (a) a mitigation (feature engineering,
resampling, regularization) or (b) an explicit escalation back to
Phase 3 for additional features.

**Thresholds rationale:**
- `AUC ≥ 0.55`: López de Prado (2018, §3.6) notes Meta-Labelers
  routinely achieve AUC 0.55–0.65 on labeled quant datasets; below
  0.55 there is no actionable edge after calibration.
- `AUC min-per-fold ≥ 0.52`: degenerate-fold protection. A single
  fold AUC < 0.52 signals a market regime where the model actively
  mis-predicts.
- `DSR ≥ 0.95` and `PBO < 0.10`: inherited from ADR-0004; same
  thresholds apply at the ML layer for consistency.
- `Brier ≤ 0.25`: a maximally uncalibrated binary classifier
  predicting `P = 0.5` on all samples scores Brier = 0.25. A
  deployable model must beat that naïve baseline.
- `Minority class ≥ 10 %`: `class_weight="balanced"` handles mild
  imbalance (10–50 %) but cannot rescue extreme cases (< 5 %).
  Mid-range warns but does not reject, allowing the sub-phase
  author to document the known imbalance.
- `RF − LogReg ≥ 0.03`: conventional quant-ML heuristic —
  complexity must pay for itself.

### D6 — Reproducibility

- **Global seed**: environment variable `APEX_SEED`, default `42`.
  Propagated to `numpy.random.default_rng`, `sklearn`
  `random_state`, and any stochastic component. Set via
  `os.environ["APEX_SEED"]` before any training call.
- **Model serialization**: `joblib` format, `.joblib` extension.
  ONNX is allowed when a downstream consumer justifies it in the
  sub-phase PR (interoperability, Rust integration, etc.).
- **Model card (JSON)**: mandatory alongside every serialized
  model. Written to
  `models/meta_labeler/{training_date}_{commit_sha8}.json` by the
  persistence module. Required fields (schema_version = 1):

  ```json
  {
    "schema_version": 1,
    "model_type": "RandomForestClassifier",
    "hyperparameters": {"n_estimators": 300, "max_depth": 10, "...": "..."},
    "training_date_utc": "2026-05-01T14:30:00Z",
    "training_commit_sha": "4cbbdfc...",
    "training_dataset_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "cpcv_splits_used": [[[0,1,2,3], [4,5]], ["..."]],
    "features_used": ["gex_signal", "har_rv_signal", "ofi_signal",
                      "regime_vol", "regime_trend", "realized_vol_28d",
                      "hour_of_day", "day_of_week"],
    "sample_weight_scheme": "uniqueness_x_return_attribution",
    "gates_measured": {"G1_mean_auc": 0.581, "G2_min_auc": 0.534,
                       "G3_dsr": 0.972, "G4_pbo": 0.073,
                       "G5_brier": 0.223, "G6_minority_freq": 0.18,
                       "G7_auc_over_logreg": 0.041},
    "gates_passed": {"G1": true, "G2": true, "G3": true, "G4": true,
                     "G5": true, "G6": true, "G7": true, "aggregate": true},
    "baseline_auc_logreg": 0.540,
    "notes": "Trained on 8,432 triple-barrier labels from ..."
  }
  ```

  The model card is schema-validated at write time and at every
  load. Schema violations raise `ValueError`; no silent-pass.

- **Deterministic round-trip**: sub-phase 4.6 ships a round-trip
  test (serialize → load → predict on 1,000 fixed test rows) that
  must yield **bit-exact** predicted probabilities. Non-determinism
  (e.g., threaded RF with shared random state) is a deployment
  blocker.

### D7 — Fusion Engine: IC-weighted baseline

Sub-phase 4.7 MVP (additive module `features/fusion/`, not a
replacement of `services/s04_fusion_engine/`):

```
fusion_score(symbol, t) = Σ_i (w_i × signal_i(symbol, t))

where
    w_i = |IC_IR_i| / Σ_j |IC_IR_j|
    IC_IR_i is sourced from the Phase 3.3 ICReport for each activated
    feature (loaded via FeatureActivationConfig).
    Weights are fixed at Fusion Engine construction time from a
    reference IC measurement window. They are NOT re-calibrated per
    call (no lookahead).
```

**Integration with existing `s04_fusion_engine`**: the Phase 4
`features/fusion/ic_weighted.py` module produces a scalar
`fusion_score`. The wiring of that score into
`FusionEngine._compute_fusion_score()` is explicitly Phase 5 work
and is **NOT** part of Phase 4 scope. Phase 4.7 ships library code
and unit tests only; it does not modify `services/s04_fusion_engine/`.

**Out of scope for 4.7 MVP (future sub-phase)**:
- Regime-conditional weights (different `w_i` per S03 regime state).
- Adaptive rolling-window re-calibration.
- Hierarchical Risk Parity (HRP) on signal correlations.
- Shrinkage or robust estimators of `IC_IR`.

### D8 — Transaction costs in P&L evaluation

All P&L evaluations feeding ADR-0005 gate measurements (G3 DSR, G4
PBO, sub-phase 4.5 statistical validation, sub-phase 4.8 E2E test)
use the three-scenario model from `backtesting/metrics.py` per
ADR-0002 D7:

- **Zero-cost**: upper-bound sanity check, informational only.
- **Realistic**: 5 bps per side + half-spread estimate + Kyle λ
  linear impact (`slippage = spread_bps/2 + kyle_lambda × size`,
  pre-existing model).
- **Stress**: 15 bps per side + full-spread + 2× Kyle λ impact.

The D5 G3 DSR gate must pass **under realistic**. Failing under
stress is permissible but must be documented in the sub-phase 4.5
closure report.

### D9 — Streaming deployment (deferred, documented)

Phase 4 trains and evaluates the Meta-Labeler **offline on batch
data** and predicts on batches in the sub-phase 4.8 E2E test. The
production streaming path (one-sample `predict_proba` calls wired
into the S02 → S04 flow) is Phase 5 work, already tracked by
technical-debt issue #123 (streaming calculators) and the
pre-existing `MetaLabelGate` in S05.

- **Training cadence** (when deployed): weekly re-fit by default.
  Monthly is acceptable for slow-horizon signals (e.g., HAR-RV with
  daily bars). Daily re-fit is **not recommended** — it adds label
  noise without meaningful information gain at the horizons used.
- **Drift monitoring** (Phase 5): see D10.

### D10 — Drift monitoring (deferred, documented)

Post-deployment drift monitoring is Phase 5 work. This ADR records
the intended methodology so Phase 4 artifacts are compatible:

- **Feature drift**: Population Stability Index (PSI) on every
  Meta-Labeler input feature, computed weekly against the training
  distribution baseline. Alert threshold `PSI > 0.25`.
- **Label drift**: Kolmogorov-Smirnov test on the empirical binary
  label distribution, computed when post-trade ground truth is
  available. Alert on `p_KS < 0.01`.
- **Baseline distributions**: stored in the model card
  `notes` field as histograms (feature percentiles P5 / P25 / P50 /
  P75 / P95) at training time, so drift monitoring can be wired
  without requiring the original training dataset.

---

## 3. Consequences

### Positive

- The Meta-Labeler reuses all Phase 3 validation tooling
  (`features/cv/cpcv.py`, `features/hypothesis/`,
  `backtesting/metrics.py`) with zero reimplementation.
- Sample weighting (D2) addresses the overlap-induced effective-size
  inflation that is the silent killer of naïve label-overlap
  training.
- Gates D5 establish an **objective pass/fail contract** for
  deployment. No "we think it looks good" escape hatch.
- The model card schema (D6) makes the audit trail self-sufficient:
  a deployed model can be traced to its commit SHA, dataset hash,
  CPCV splits, and gate evidence without consulting external
  documentation.
- The IC-weighted baseline (D7) is trivially measurable and
  upper-bounds more sophisticated fusion approaches, giving a clear
  success benchmark for future extensions (regime-conditional,
  adaptive, HRP).
- The long-only direction assumption + binary labels (D1) keep the
  Phase 4 MVP scope tight and testable. Short-side is a clean,
  separable extension.

### Negative

- Nested CPCV + hyperparameter tuning is **computationally
  expensive**: ~15 outer folds × ~18 inner tuning trials × 4 inner
  folds = 1,080 model fits per training run. Wall-clock budget
  documented in sub-phase 4.4.
- The Random Forest default may **under-fit** with only three
  Phase 3 features. The ADR allows escalation to Gradient Boosting
  with justification, but this adds sub-phase complexity and
  potentially a late discovery of feature-set insufficiency.
- The **calibration gate G5** may reject an otherwise-high-AUC
  model. This is intentional — a poorly calibrated classifier
  produces garbage bet-sizes — but it will cause sub-phase
  iterations and may require Platt scaling or isotonic regression
  wrappers (deferred to future work unless needed).
- **Three features** from Phase 3.12 is a thin input basis. Phase 4
  may reveal that the activated set is insufficient for the
  Meta-Labeler to clear G1 AUC. If so, the closure report must
  explicitly escalate back to Phase 3 for additional feature
  candidates rather than silently loosening the gates.
- The existing deterministic `MetaLabeler` in `s04_fusion_engine/`
  stays in place until the trained classifier is wired in a future
  sub-phase. During the Phase 4 design-gate → closure window the
  two co-exist; consumers must read the model card to determine
  which is authoritative. This is a small but real audit-trail
  wrinkle.

---

## 4. Alternatives Considered

### A. Skip Triple Barrier and use naïve forward-return thresholds

Rejected. Forward-return thresholding ignores path dependence: a
trade whose forward return is +0.3 % but touched −2 % en route would
be labeled as a success, contradicting the economic reality of a
stop-out. The Triple Barrier Method is the canonical solution
(López de Prado 2018, §3.4).

### B. Use an end-to-end neural classifier instead of Meta-Labeler on primary signals

Rejected for Phase 4. The Meta-Labeler architecture separates
**signal generation** (Phase 3 features) from **trade confidence
estimation** (Phase 4 classifier). This separation keeps each layer
interpretable and allows independent failure diagnosis. An
end-to-end neural model couples the two and loses this property.
Re-evaluate in a future ADR if empirical evidence motivates.

### C. Ship without sample weights and rely on CPCV alone for leakage control

Rejected. CPCV controls temporal leakage; sample uniqueness weights
control the orthogonal problem of **effective training-set size
inflation** caused by overlapping label spans. Both are required
(López de Prado §4.4 is explicit on this). Skipping D2 would
over-fit the classifier to concurrent-label clusters.

### D. Use k-fold inside the inner loop, CPCV outer only

Rejected. k-fold inner ignores label overlap between inner train
and inner val sets, which biases hyperparameter selection optimistic
even when the outer CPCV is honest. Nested CPCV is strictly
correct; the compute cost is the price.

### E. Tighter AUC gate (e.g., G1 ≥ 0.60)

Rejected for Phase 4 MVP. Empirical quant-ML literature reports
Meta-Labeler AUC in the 0.55–0.65 range (López de Prado 2018, §3.6
case studies). A 0.60 gate would likely reject a genuinely useful
model given the thin 3-feature basis. The G7 "beat LogReg by 0.03"
rule provides a complementary defense against accepting a model
that is high-AUC but not meaningfully better than linear.

---

## 5. References

1. López de Prado, M. (2018). *Advances in Financial Machine
   Learning*. Wiley. Chapters 3 (Labeling, Triple Barrier),
   4 (Sample Weights, Uniqueness, Return Attribution),
   6 (Ensemble Methods, Random Forest defaults),
   7 (Cross-Validation in Finance), 8 (Feature Importance).
2. Bailey, D. H. & López de Prado, M. (2014). "The Deflated Sharpe
   Ratio: Correcting for Selection Bias, Backtest Overfitting and
   Non-Normality." *Journal of Portfolio Management*, 40(5),
   94-107.
3. Bailey, D. H., Borwein, J. M., López de Prado, M. & Zhu, Q. J.
   (2014). "The Probability of Backtest Overfitting." *Journal of
   Computational Finance*, 20(4), 39-69.
4. Breiman, L. (2001). "Random Forests." *Machine Learning*,
   45(1), 5-32.
5. Ke, G., Meng, Q., Finley, T. et al. (2017). "LightGBM: A Highly
   Efficient Gradient Boosting Decision Tree." *NeurIPS 2017
   Proceedings*.
6. Platt, J. (1999). "Probabilistic Outputs for Support Vector
   Machines and Comparisons to Regularized Likelihood Methods." In
   *Advances in Large Margin Classifiers*. (Reference for
   calibration, deferred.)
7. Brier, G. W. (1950). "Verification of Forecasts Expressed in
   Terms of Probability." *Monthly Weather Review*, 78(1), 1-3.
   (Source of the Brier score used in G5.)
8. ADR-0002 — Quant Methodology Charter.
9. ADR-0004 — Feature Validation Methodology.
