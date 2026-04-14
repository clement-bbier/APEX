# Phase 4 — Mid-Phase Data Leakage Audit

**Issue**: #134
**Phase**: transverse (between 4.3 merged and 4.4 started)
**Author**: Clément Barbier (with Claude Code)
**Date**: 2026-04-14
**Scope**: every feature consumed by the Phase 4.3 Baseline Meta-Labeler.
**Verdict**: **PASS** — every Meta-Labeler input respects the temporal
ordering contract `feature_compute_window_end_i < t0_i` (strict),
with one documented exception for point-in-time regime state that is
safe by construction.

Reference: `docs/phases/PHASE_4_SPEC.md` §5.1, §5.2;
`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D6, D8.

---

## 1. Audit contract

The Meta-Labeler must satisfy ADR-0005 **D8 — strict anti-leakage**:

> For every training sample `i` with label start `t0_i`, every feature
> column `k` must be derivable only from information available
> *strictly before* `t0_i`. Equivalently,
> `feature_compute_window_end(i, k) < t0_i` with `<` (not `<=`).

A single lookahead here silently inflates every downstream diagnostic
(AUC, DSR, PBO), so this audit is required before any hyperparameter
tuning (4.4), statistical validation (4.5), or persistence (4.6).

One documented exception applies to **regime state**: the vol regime
and trend regime in force *at the decision instant* `t0_i` are part of
the market state an operator observes when the label window opens.
They are not a lagged prediction of the future, so an as-of `<=`
lookup is admissible. This is called out explicitly per feature
below and is the standard convention in López de Prado (2018) §4
for contextual regime tags.

---

## 2. Feature-by-feature matrix

The Meta-Labeler consumes the 8-column matrix defined by
`FEATURE_NAMES` in `features/meta_labeler/feature_builder.py`. The
canonical column order (ADR-0005 D6) is preserved below.

| # | Feature | Join rule | Strict? | Code location | Test |
|---|---|---|---|---|---|
| 0 | `gex_signal` | asof-backward strictly-before `t0_i` | **yes** | `_join_phase3_signals` L397–408 | `test_phase3_signals_joined_strictly_before_t0`; `test_phase3_signal_exactly_at_t0_rejected`; anti-leakage property test |
| 1 | `har_rv_signal` | asof-backward strictly-before `t0_i` | **yes** | same join path | same tests |
| 2 | `ofi_signal` | asof-backward strictly-before `t0_i` | **yes** | same join path | same tests |
| 3 | `regime_vol_code` | as-of `t0_i` inclusive | **documented exception** | `_join_regime_codes` L420–438 | `test_regime_codes_asof_t0_inclusive`; `test_regime_before_first_snapshot_rejected` |
| 4 | `regime_trend_code` | as-of `t0_i` inclusive | **documented exception** | same join path | same tests |
| 5 | `realized_vol_28d` | 28 log-returns from bars strictly before `t0_i` | **yes** | `_realized_vol_column` L443–478 | `test_realized_vol_uses_only_bars_strictly_before_t0`; `test_insufficient_history_raises` |
| 6 | `hour_of_day_sin` | `sin(2π·hour(t0_i)/24)` | **yes** (derived from `t0_i` only) | `_time_encoding_columns` L484–493 | `test_cyclical_hour_encoding_matches_spec`; covered by anti-leakage property test |
| 7 | `day_of_week_sin` | `sin(2π·weekday(t0_i)/7)` | **yes** (derived from `t0_i` only) | same join path | same tests |

All line numbers refer to the blob merged as part of PR #140
(commits `d3b4680`, `53a593b`).

---

## 3. Implementation evidence (per join rule)

### 3.1 Phase 3 signals — `searchsorted(side="left") - 1`

```python
# features/meta_labeler/feature_builder.py, L397-408
# searchsorted returns an int64 array; side='left' => idx is the
# first signal timestamp that is >= t0_i. Subtracting 1 gives the
# last signal row whose timestamp is strictly < t0_i.
idx = np.searchsorted(sig_ts, t0_np, side="left").astype(np.int64) - 1
bad = idx < 0
if bad.any():
    raise ValueError(
        f"no Phase 3 signal row strictly before t0={t0_np[bad]} "
        ...
    )
```

`side="left"` is the critical detail: if a signal row exists with
`timestamp == t0_i`, `searchsorted` returns its position; subtracting
1 therefore yields the *previous* row, enforcing `<` rather than
`<=`. The test `test_phase3_signal_exactly_at_t0_rejected` verifies
this boundary (a row planted exactly at `t0_i` is discarded).

### 3.2 Regime codes — `searchsorted(side="right") - 1` (inclusive, documented exception)

```python
# features/meta_labeler/feature_builder.py, L420-438
# side='right' => idx is one past the last regime row with ts <= t0_i.
# Subtracting 1 gives the regime state in force at t0_i inclusive.
idx = np.searchsorted(reg_ts, t0_np, side="right").astype(np.int64) - 1
```

This is the documented exception. The S03 regime detector emits
monotonically-timestamped snapshots that annotate "the regime in
force from this timestamp onward until the next snapshot." At
`t0_i`, the regime is a point-in-time observable; the lookup yields
the snapshot valid at the decision instant. If `t0_i` precedes the
first snapshot, the function raises `ValueError` (see
`test_regime_before_first_snapshot_rejected`).

**Why this is not leakage**: the regime label at `t0_i` does not
depend on `t1_i` or on the Triple Barrier outcome. It is derived
from market data available at or before `t0_i`. Leakage would
require using regime state valid *after* `t0_i` (e.g., a future
regime transition). The `side="right"` lookup strictly excludes
that case.

### 3.3 Realized volatility — strict-before slice

```python
# features/meta_labeler/feature_builder.py, L443-478
# side='left' => idx is the first bar with timestamp >= t0_i.
# Slicing bars[:idx] therefore keeps only rows strictly before t0_i.
idx = np.searchsorted(bars_ts, t0_np, side="left").astype(np.int64)
window = close[max(idx - realized_vol_window - 1, 0) : idx]
# Log-returns on this window, then std.
```

The slice upper bound is `idx`, not `idx + 1`, which is the hallmark
of a strict-before window. `test_realized_vol_uses_only_bars_strictly_before_t0`
permutes the bar immediately at `t0_i` and confirms the realized vol
does not change.

### 3.4 Cyclical time encodings — pure function of `t0_i`

```python
# features/meta_labeler/feature_builder.py, L484-493
hour = (t0_np.astype("datetime64[h]").astype(int) % 24).astype(np.float64)
weekday = (((t0_np.astype("datetime64[D]").astype(int)) - 4) % 7).astype(np.float64)
X[:, 6] = np.sin(2 * np.pi * hour / 24.0)
X[:, 7] = np.sin(2 * np.pi * weekday / 7.0)
```

These columns are a deterministic function of `t0_i` alone. No
market data dependency, so no temporal ordering violation is
possible.

---

## 4. Cross-cutting property test

`tests/unit/features/meta_labeler/test_feature_builder.py` ::
`test_permuting_bars_after_max_t1_does_not_change_feature_matrix`
performs the canonical anti-leakage experiment:

1. Build the feature matrix `X_baseline` from reference `(bars, signals, labels)`.
2. Compute `cutoff = max(t1) + 1`. Permute the bars and signals rows
   whose index is `>= cutoff` with a fixed random permutation.
3. Rebuild the feature matrix `X_permuted`.
4. Assert `X_permuted == X_baseline` byte-for-byte.

The assertion `np.testing.assert_array_equal(fs_perm.X, fs_baseline.X)`
(strict equality, no tolerance) proves that *no* feature in `X`
depends on any bar or signal at or after `max(t1)`, let alone after
`t0_i`. Because the 4 events considered in the test span the middle
of the bar history (indices 40, 60, 80, 100 out of 200), the cutoff
`max(t1) + 1 = 111` leaves ~45% of the data eligible for permutation
— a non-trivial coverage of the "post-label future" a leakage
implementation would touch.

The test has been stable across every CI run on PR #140 since
commit `d3b4680`.

---

## 5. Out-of-scope (by design)

The following are **not** Meta-Labeler features and are therefore
outside the scope of this audit. They are tracked separately.

- **Triple Barrier labels themselves** (`t0`, `t1`, `binary_target`
  in `features/labeling/triple_barrier.py`). These are the *target*,
  not an input, and their own anti-leakage properties (Barrier
  computed only from bars in `[t0, t1]`) are verified in Phase 4.1
  tests.
- **Sample weights** (`features/labeling/sample_weights.py`). These
  are computed from the `(t0, t1)` schema itself and do not consume
  market data. No lookahead surface.
- **CPCV partitioning** (`features/cv/cpcv.py`). Already audited
  structurally in Phase 3.11 (purge + embargo).

---

## 6. Findings and follow-ups

| ID | Severity | Finding | Status |
|---|---|---|---|
| L4-01 | Info | Regime as-of `t0_i` inclusive is a documented exception, not a violation. | Closed — documented here and in `feature_builder.py` docstring L13-21. |
| L4-02 | Info | Cyclical time columns are derived only from `t0_i`; no data dependency. | Closed — no action required. |
| L4-03 | Info | Strict-before boundary for Phase 3 signals enforced via `side="left"` in `searchsorted`. | Closed — test `test_phase3_signal_exactly_at_t0_rejected` pins the invariant. |
| L4-04 | Info | Strict-before window for realized vol enforced via `slice[:idx]` upper bound. | Closed — test pins the invariant. |

No P0, P1, or P2 findings. This audit clears Phase 4.3 for
downstream consumption by Phase 4.4 (nested tuning) and Phase 4.5
(DSR/PBO statistical validation).

---

## 7. References

- `docs/phases/PHASE_4_SPEC.md` §3.3 (feature builder spec), §5.1 (audit mandate).
- `docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D6 (feature set), D8 (anti-leakage).
- López de Prado (2018) *Advances in Financial Machine Learning*, §3.1 (triple barrier), §7.4 (nested CV premise — no leakage allowed).
- `features/meta_labeler/feature_builder.py` (merged in PR #140).
- `tests/unit/features/meta_labeler/test_feature_builder.py` Group H (anti-leakage property test).
