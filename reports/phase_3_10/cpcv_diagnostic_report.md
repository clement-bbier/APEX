# Phase 3.10 -- CPCV Diagnostic Report

Generated from synthetic predictive input (seed=42, N=1000 bars, label horizon=10).

## Configuration

| Parameter | Value |
|---|---|
| n_splits | 6 |
| n_test_splits | 2 |
| Total splits | C(6, 2) = 15 |
| embargo_pct | 0.01 (10 bars) |
| Synthetic data | Random walk, 5 features, cumsum(N(0,1)) |
| Label | y[i] = 1 if price[i+10] > price[i] else 0 |
| Classifier | 1-NN (deterministic, pure numpy, no external dependencies) |
| Purging interval | [t0[group_start], t1[group_end-1]] per Lopez de Prado S7.4.1 |
| Seed | 42 (fully reproducible) |

## Split summary

| Split # | Train size | Test size | Purged+Embargoed |
|---------|-----------|-----------|------------------|
| 0 | 656 | 334 | 10 |
| 1 | 636 | 334 | 30 |
| 2 | 636 | 334 | 30 |
| 3 | 637 | 333 | 30 |
| 4 | 647 | 333 | 20 |
| 5 | 646 | 334 | 20 |
| 6 | 626 | 334 | 40 |
| 7 | 627 | 333 | 40 |
| 8 | 637 | 333 | 30 |
| 9 | 646 | 334 | 20 |
| 10 | 627 | 333 | 40 |
| 11 | 637 | 333 | 30 |
| 12 | 647 | 333 | 20 |
| 13 | 637 | 333 | 30 |
| 14 | 658 | 332 | 10 |

## Distribution of sizes across 15 splits

| Metric | Train | Test | Purged+Embargoed |
|---|---|---|---|
| Mean | 640.0 | 333.3 | 26.7 |
| Min | 626 | 332 | 10 |
| Max | 658 | 334 | 40 |

With the corrected purging interval (t0 as start), more samples are purged
than with the initial implementation that used t1 as interval start
(avg 26.7 vs 13.3 previously).  This is expected: the wider interval
[t0, t1] catches training samples whose labels began before but ended
during the test period.

## Leakage stress test

### Without CPCV (random shuffled K-fold, 5-fold)

| Metric | Value |
|---|---|
| OOS accuracy | 0.8550 |

Shuffled K-fold on autocorrelated data allows the 1-NN classifier to
exploit temporal proximity between train and test samples.  The nearest
neighbor of a test sample is typically a temporally adjacent training
sample, achieving **85.5% accuracy** -- far above the 50% chance baseline.

### With CPCV (purged + embargoed, C(6,2)=15 splits)

| Metric | Value |
|---|---|
| OOS accuracy | 0.5166 |

CPCV with purging and embargo eliminates the temporal leakage.  Accuracy
drops to **51.7%**, very close to the 50% theoretical chance level for a
random walk.

### Accuracy drop

| Metric | Value |
|---|---|
| K-fold accuracy | 0.8550 |
| CPCV accuracy | 0.5166 |
| Drop | 0.3384 (33.8 percentage points) |

This 33.8pp drop demonstrates that CPCV eliminates the vast majority of
the leakage that standard K-fold allows on autocorrelated financial data.

### Note on classifier choice

The initial draft used sklearn RandomForestClassifier (n_estimators=100).
After Copilot review, this was replaced with a deterministic 1-NN classifier
in pure numpy.  Reasons:

- **No external dependencies**: sklearn is not in CI requirements.
- **Deterministic**: 1-NN produces identical results across platforms
  regardless of BLAS implementation or RNG seeding differences.
- **Sensitive to the same leakage**: 1-NN on autocorrelated features
  exploits temporal proximity identically to RF -- a test sample's
  nearest neighbor is typically its temporal neighbor.
- **Larger accuracy drop**: 1-NN actually shows a larger leakage effect
  (33.8pp vs 25.2pp with RF) because it is more directly sensitive to
  neighbor proximity.

## Edge cases characterized

| Edge case | Behavior |
|---|---|
| n_splits > n_samples | ValueError raised with informative message |
| embargo_size = 0 (embargo_pct=0) | No embargo applied, train+test = n |
| n_test_splits = 1 | Degenerates to C(N,1) = N sequential splits |
| t1 not monotonic | ValueError raised with "monotonically non-decreasing" message |
| t1 length != n | ValueError raised with "len(t1) != len(X)" message |
| t0 omitted | Falls back to t1 as interval start (may under-purge) |
| t0[i] > t1[i] | ValueError raised with "Label start cannot exceed label end" |
| Non-contiguous test groups (e.g., groups 0 and 4) | Purging checks each group interval independently |
| Last test group at series end | Embargo clamped to n-1, no overflow |

## Conclusion

The CPCV implementation correctly eliminates three types of information leakage
in financial time series cross-validation:

1. **Index leakage**: train and test indices are always disjoint by construction.
2. **Label leakage**: purging removes training samples whose label end time (t1)
   falls within the test group's temporal range [t0_start, t1_end], preventing
   the model from training on outcomes determined by test-period data.
3. **Autocorrelation leakage**: embargo removes training samples immediately
   after each test group boundary, preventing exploitation of serial dependence
   in features.

The leakage stress test provides empirical evidence: on a synthetic random walk
dataset with horizon-10 forward labels, CPCV reduces out-of-sample accuracy from
85.5% (inflated by leakage) to 51.7% (at the theoretical chance level of 50%).
This 33.8pp drop characterizes the magnitude of leakage that CPCV prevents.

The corrected purging interval (using t0 as start per Lopez de Prado S7.4.1)
purges approximately twice as many samples as the initial implementation that
used t1 as the interval start, confirming that the wider interval is necessary
to capture all label-leaking observations.

The implementation is ready to serve as the cross-validation backbone for
Phase 3.11 (DSR/PBO), where the C(N,k) split paths provide the combinatorial
distribution needed for Probability of Backtest Overfitting estimation.

## References

- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 7. Wiley.
- Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2017).
  "The Probability of Backtest Overfitting." *Journal of Computational Finance*, 20(4), 39-69.
