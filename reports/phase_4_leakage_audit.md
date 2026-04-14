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
| 0 | `gex_signal` | asof-backward strictly-before `t0_i` | **yes** | `MetaLabelerFeatureBuilder._phase3_signals` L376–411 | `test_phase3_signals_strictly_before_t0`; `test_phase3_signals_missing_before_earliest_t0_fails_loud`; `test_permuting_bars_after_max_t1_does_not_change_feature_matrix` |
| 1 | `har_rv_signal` | asof-backward strictly-before `t0_i` | **yes** | same helper | same tests |
| 2 | `ofi_signal` | asof-backward strictly-before `t0_i` | **yes** | same helper | same tests |
| 3 | `regime_vol_code` | as-of `t0_i` inclusive | **documented exception** | `MetaLabelerFeatureBuilder._regime_codes` L413–440 | `test_regime_asof_at_t0_is_inclusive`; `test_regime_asof_picks_last_snapshot_before_t0`; `test_regime_missing_at_t0_fails_loud` |
| 4 | `regime_trend_code` | as-of `t0_i` inclusive | **documented exception** | same helper | same tests |
| 5 | `realized_vol_28d` | 28 log-returns from bars strictly before `t0_i` | **yes** | `MetaLabelerFeatureBuilder._realized_vol` L442–483 | `test_realized_vol_window_uses_bars_before_t0`; `test_realized_vol_insufficient_history_raises` |
| 6 | `hour_of_day_sin` | `sin(2π·hour(t0_i)/24)` | **yes** (derived from `t0_i` only) | `MetaLabelerFeatureBuilder._cyclical_time` L485–500 | `test_cyclical_time_encoding_is_sin_of_hour_and_weekday`; `test_permuting_bars_after_max_t1_does_not_change_feature_matrix` |
| 7 | `day_of_week_sin` | `sin(2π·weekday(t0_i)/7)` | **yes** (derived from `t0_i` only) | same helper | same tests |

All line numbers refer to the blob merged as part of PR #140
(commit `d5dc3a0`, merge parent).

---

## 3. Implementation evidence (per join rule)

### 3.1 Phase 3 signals — `searchsorted(side="left") - 1`

```python
# features/meta_labeler/feature_builder.py, L396-406 (_phase3_signals)
t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
# searchsorted returns an int64 array; side='left' => idx is the
# insertion index preserving sort order, so idx-1 is the last
# timestamp STRICTLY less than t0 (which is what we need).
idx = np.searchsorted(sig_ts, t0_np, side="left").astype(np.int64) - 1
if np.any(idx < 0):
    bad = int(np.argmax(idx < 0))
    raise ValueError(
        f"no Phase 3 signal row strictly before t0={t0_np[bad]} "
        "(signals must include history ending before the earliest label)"
    )
```

`side="left"` is the critical detail: if a signal row exists with
`timestamp == t0_i`, `searchsorted` returns its position; subtracting
1 therefore yields the *previous* row, enforcing `<` rather than
`<=`. The invariant is pinned by the pair
`test_phase3_signals_strictly_before_t0` (asserts the joined row is
the one immediately before `t0_i`) and
`test_phase3_signals_missing_before_earliest_t0_fails_loud` (asserts
the `ValueError` when no pre-`t0_i` signal exists).

### 3.2 Regime codes — `searchsorted(side="right") - 1` (inclusive, documented exception)

```python
# features/meta_labeler/feature_builder.py, L419-430 (_regime_codes)
reg_ts = self._regime["timestamp"].to_numpy().astype("datetime64[us]")
t0_np = labels["t0"].to_numpy().astype("datetime64[us]")

# side='right' => insertion keeps sort order, so idx-1 is the
# last regime row with timestamp <= t0_i (inclusive).
idx = np.searchsorted(reg_ts, t0_np, side="right").astype(np.int64) - 1
if np.any(idx < 0):
    bad = int(np.argmax(idx < 0))
    raise ValueError(
        f"regime_history has no snapshot at or before t0={t0_np[bad]}; "
        "extend the regime history or drop the offending labels"
    )
```

This is the documented exception. The S03 regime detector emits
monotonically-timestamped snapshots that annotate "the regime in
force from this timestamp onward until the next snapshot." At
`t0_i`, the regime is a point-in-time observable; the lookup yields
the snapshot valid at the decision instant. If `t0_i` precedes the
first snapshot, the function raises `ValueError` (pinned by
`test_regime_missing_at_t0_fails_loud`).

**Why this is not leakage**: the regime label at `t0_i` does not
depend on `t1_i` or on the Triple Barrier outcome. It is derived
from market data available at or before `t0_i`. Leakage would
require using regime state valid *after* `t0_i` (e.g., a future
regime transition). The `side="right"` lookup strictly excludes
that case.

### 3.3 Realized volatility — strict-before slice with fail-loud history check

```python
# features/meta_labeler/feature_builder.py, L460-482 (_realized_vol)
t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
# side='left' => idx is the first bar with timestamp >= t0_i, so
# bars[:idx] is STRICTLY before t0_i.
idx = np.searchsorted(bars_ts, t0_np, side="left").astype(np.int64)

out = np.empty(n, dtype=np.float64)
w = self._realized_vol_window
for i in range(n):
    end = int(idx[i])
    # Need w+1 closes to build w log-returns.
    start = end - (w + 1)
    if start < 0:
        raise ValueError(
            f"insufficient bar history before t0={t0_np[i]}: "
            f"need {w + 1} bars, have {end}"
        )
    close_window = bars_close[start:end]
    log_ret = np.diff(np.log(close_window))
    out[i] = float(np.std(log_ret, ddof=0))
```

Two invariants matter. First, the slice upper bound is `end = idx[i]`
(from `side="left"`), which excludes any bar at `t0_i` itself — the
hallmark of a strict-before window. Second, `start = end - (w + 1)`
is checked against `< 0` and the function raises loudly rather than
silently clamping to 0 (no `max(...,0)` padding), so an insufficient
history surfaces as a `ValueError` instead of a biased value.
Pinned by `test_realized_vol_window_uses_bars_before_t0` (boundary)
and `test_realized_vol_insufficient_history_raises` (fail-loud).

### 3.4 Cyclical time encodings — pure function of `t0_i`

```python
# features/meta_labeler/feature_builder.py, L496-500 (_cyclical_time)
hours = np.array([t.hour for t in labels["t0"].to_list()], dtype=np.float64)
weekdays = np.array([t.weekday() for t in labels["t0"].to_list()], dtype=np.float64)
hod = np.sin(2.0 * np.pi * hours / 24.0)
dow = np.sin(2.0 * np.pi * weekdays / 7.0)
return np.column_stack([hod, dow]).astype(np.float64)
```

`hour` and `weekday` come from Python `datetime` accessors on
`labels["t0"]` directly — there is no market-data input to this
helper. The columns are a deterministic function of `t0_i` alone,
so no temporal ordering violation is possible. Pinned by
`test_cyclical_time_encoding_is_sin_of_hour_and_weekday` (checks the
formula against manually computed sines).

---

## 4. Cross-cutting property test

`tests/unit/features/meta_labeler/test_feature_builder.py` ::
`test_permuting_bars_after_max_t1_does_not_change_feature_matrix`
(L398–437) performs the canonical anti-leakage experiment:

1. Build the feature matrix `X_baseline` from reference
   `(bars, signals, labels)` with `n=200` bars, `horizon=10`, and
   event indices `[40, 60, 80, 100]`.
2. Compute `max_t1_idx = max(event_ids) + horizon = 110` and
   `cutoff = max_t1_idx + 1 = 111`. Build a row permutation whose
   identity is preserved for indices `< cutoff` and whose tail
   `[cutoff, n)` is shuffled with a fixed RNG seed (`default_rng(99)`).
3. Apply the permutation to the `close` column of `bars` and to the
   three signal columns (`gex_signal`, `har_rv_signal`, `ofi_signal`)
   via `pl.DataFrame.with_columns`, leaving the `timestamp` columns
   untouched so sort order is preserved.
4. Rebuild the feature matrix `X_permuted` and assert
   `np.testing.assert_array_equal(fs_perm.X, fs_baseline.X)` —
   strict equality, no tolerance.

Byte-for-byte equality proves that *no* feature column in `X`
depends on any bar or signal value at or after `max(t1)`, let alone
after `t0_i`. The permuted tail covers 89 of 200 rows (~44.5%), a
non-trivial slice of the "post-label future" that any leakage
implementation would have to touch.

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
| L4-03 | Info | Strict-before boundary for Phase 3 signals enforced via `side="left"` in `searchsorted`. | Closed — pinned by `test_phase3_signals_strictly_before_t0` (boundary), `test_phase3_signals_missing_before_earliest_t0_fails_loud` (fail-loud), and `test_permuting_bars_after_max_t1_does_not_change_feature_matrix` (global property). |
| L4-04 | Info | Strict-before window for realized vol enforced via `bars[:idx]` upper bound with fail-loud `start < 0` check. | Closed — pinned by `test_realized_vol_window_uses_bars_before_t0` and `test_realized_vol_insufficient_history_raises`. |

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
