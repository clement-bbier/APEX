# Phase 4.2 — Sample Weights Distribution Diagnostic

| Field | Value |
|---|---|
| Branch | `phase/4.2-sample-weights` |
| Issue | #126 |
| Date | 2026-04-14 |
| Fixture seed | `42` (numpy `default_rng`) |
| Bars | 1,000 (1-minute UTC, synthetic) |
| Events | 100 (holding periods ∈ [5, 50] bars, uniform starts across first 90% of bars) |
| Module under test | `features/labeling/sample_weights.py` |
| Coverage | 94% (52 passing tests) |

---

## 1. Purpose

This report exercises the canonical ADR-0005 D2 implementation on a
synthetic but realistic fixture (100 overlapping labels over 1,000 bars,
mild positive drift + Gaussian noise). It verifies:

1. The normalization invariant `sum(w) == n_samples` holds to float
   precision (tolerance `1e-9`).
2. The uniqueness distribution reacts correctly to overlap
   (`u ∈ (0, 1]`, left-skewed when many labels overlap).
3. The combined weight `w = u × r` has positive skew (a few high-signal
   samples carry most of the loss, as expected for a meta-labeler
   training set).

No production data was used; everything below is reproducible from the
committed test fixtures (seed `42`).

---

## 2. Concurrency `c_t`

Computed by `features.labeling.sample_weights.compute_concurrency`
over all 1,000 bars.

| Metric | Value |
|---|---|
| `min` | 0 |
| `p05` | 0 |
| `p50` | 3 |
| `p95` | 6 |
| `max` | 8 |
| `mean` | 2.810 |
| `std` | 1.861 |
| Bars with `c ≥ 1` | 845 / 1,000 |

Up to 8 labels are active simultaneously at the busiest bars; 15.5% of
bars have no active label (expected — holding periods stop ≤ 50 bars and
the last 10% of bars receive no new starts, so the tail empties out).

---

## 3. Uniqueness `u_i`

Per-sample `u_i = mean(1 / c_t for t in [t0_i, t1_i])`.

| Metric | Value |
|---|---|
| `min` | 0.1429 |
| `p05` | 0.1671 |
| `p50` | 0.2584 |
| `p95` | 0.6710 |
| `max` | 0.8889 |
| `mean` | 0.2974 |
| `std` | 0.1395 |

### Histogram (10 equal-width bins)

| Range | Count | Bar |
|---|---:|---|
| [0.1429, 0.2175) | 26 | `##########################` |
| [0.2175, 0.2921) | 39 | `########################################` |
| [0.2921, 0.3667) | 15 | `###############` |
| [0.3667, 0.4413) | 10 | `##########` |
| [0.4413, 0.5159) | 4 | `####` |
| [0.5159, 0.5905) | 0 |  |
| [0.5905, 0.6651) | 0 |  |
| [0.6651, 0.7397) | 3 | `###` |
| [0.7397, 0.8143) | 2 | `##` |
| [0.8143, 0.8889) | 1 | `#` |

Right-skewed toward zero: most labels land in the densely-overlapped
region (c ≈ 3–4) and therefore share information with peers. The small
high-uniqueness tail corresponds to events starting in the last 10% of
the window where future overlap is sparse — exactly the behavior López
de Prado §4.4 Figure 4.1 illustrates.

All `u_i ∈ (0, 1]` as required by ADR-0005 D2.

---

## 4. Return attribution `r_i`

Per-sample `r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|` with
per-bar log-returns drawn i.i.d. from `N(μ=1e-4, σ=1e-3)`.

| Metric | Value |
|---|---|
| `min` | 5.996e-05 |
| `p05` | 1.806e-04 |
| `p50` | 8.598e-04 |
| `p95` | 4.109e-03 |
| `max` | 6.828e-03 |
| `mean` | 1.337e-03 |
| `std` | 1.286e-03 |

All values are strictly non-negative (absolute-value contract), and
positively skewed — a minority of samples pick up disproportionately
larger run-length moves, which is what the combined weight will then
amplify.

---

## 5. Combined weights `w_i` (normalized)

`w_i = u_i × r_i`, then scaled so `sum(w) == n_samples == 100`.

| Metric | Value |
|---|---|
| `min` | 0.0331 |
| `p05` | 0.0803 |
| `p50` | 0.5040 |
| `p95` | 3.5623 |
| `max` | 10.1959 |
| `mean` | 1.0000 (normalization invariant) |
| `std` | 1.5477 |
| `sum(w)` | 100.0 (vs 100 target) |
| `|sum(w) − n_samples|` | 1.42e-14 (tolerance 1e-9) |

### Histogram (10 equal-width bins)

| Range | Count | Bar |
|---|---:|---|
| [0.0331, 1.0494) | 78 | `########################################` |
| [1.0494, 2.0656) | 11 | `#####` |
| [2.0656, 3.0819) | 3 | `#` |
| [3.0819, 4.0982) | 3 | `#` |
| [4.0982, 5.1145) | 1 |  |
| [5.1145, 6.1308) | 1 |  |
| [6.1308, 7.1470) | 2 | `#` |
| [7.1470, 8.1633) | 0 |  |
| [8.1633, 9.1796) | 0 |  |
| [9.1796, 10.1959) | 1 |  |

The long right tail is the expected signature of the meta-labeler
weighting scheme: a few signal-rich samples (high uniqueness × strong
attribution) carry the gradient, while the mass concentrates below
mean. This is the behavior PHASE_4_SPEC §3.2 assumes for the Random
Forest training loss in sub-phase 4.3.

---

## 6. Invariants checked

| Invariant | Expected | Observed | Status |
|---|---|---|---|
| `sum(w) == n_samples` | 100 ± 1e-9 | 100.0 (drift 1.42e-14) | PASS |
| `u_i ∈ (0, 1]` | All in (0, 1] | min 0.1429, max 0.8889 | PASS |
| `r_i ≥ 0` | Non-negative | min 5.996e-05 | PASS |
| `w_i ≥ 0` | Non-negative | min 0.0331 | PASS |
| Anti-leakage (`shuffle post-t1 ret` invariance) | Unchanged | Hypothesis 200 cases | PASS |
| Disjoint events → `u_i == 1.0` | All ones | `test_disjoint_spans_all_ones` | PASS |
| LdP §4.4 Table 4.1 triangle | 11/18, 4/9, 11/18 | Exact to 1e-12 | PASS |

---

## 7. Reproduction

```bash
python3 -c "
from datetime import UTC, datetime, timedelta
import numpy as np
import polars as pl
from features.labeling.sample_weights import (
    combined_weights, compute_concurrency,
    return_attribution_weights, uniqueness_weights,
)

rng = np.random.default_rng(42)
N_BARS, N_EVENTS = 1000, 100
start = datetime(2024, 6, 1, 9, 30, tzinfo=UTC)
bars = pl.Series(
    [start + timedelta(minutes=i) for i in range(N_BARS)],
    dtype=pl.Datetime('us', 'UTC'),
)
t0_idx = rng.integers(0, int(N_BARS * 0.9), size=N_EVENTS)
hold   = rng.integers(5, 51, size=N_EVENTS)
t1_idx = np.minimum(t0_idx + hold, N_BARS - 1)
t0 = pl.Series([bars[int(i)] for i in t0_idx], dtype=pl.Datetime('us','UTC'))
t1 = pl.Series([bars[int(i)] for i in t1_idx], dtype=pl.Datetime('us','UTC'))
log_returns = pl.Series(
    rng.normal(1e-4, 1e-3, size=N_BARS).tolist(), dtype=pl.Float64,
)
w = combined_weights(t0, t1, bars, log_returns).to_numpy()
assert abs(w.sum() - N_EVENTS) < 1e-9
"
```

Seed `42`, `numpy` 2.2.x, `polars` 1.39.x. Any deviation in these
percentiles larger than ~1% between runs indicates a regression in the
numerics.

---

## 8. References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*.
  Wiley, Chapter 4.4 (Average Uniqueness) and 4.5 (Sample Weights by
  Return Attribution), Table 4.1.
- [`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md`](../../docs/adr/ADR-0005-meta-labeling-fusion-methodology.md) — section D2.
- [`docs/phases/PHASE_4_SPEC.md`](../../docs/phases/PHASE_4_SPEC.md) — section 3.2.
- [`reports/phase_4_2/audit.md`](audit.md) — pre-implementation audit.
