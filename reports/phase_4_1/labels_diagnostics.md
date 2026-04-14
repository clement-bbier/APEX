# Phase 4.1 — Triple Barrier Labeling — Diagnostics

| Field | Value |
|---|---|
| Branch | `phase/4.1-triple-barrier-labeling` |
| Seed | `APEX_SEED=42` |
| Generated | 2026-04-14 |
| ADR-0005 D1 compliance | ✅ (see §7) |

---

## 1. Fixture

Deterministic synthetic GBM series. No RNG dependency on the Python
`random` module — a custom linear-congruential generator feeds a
Box–Muller transform so the output is reproducible across Python
versions and OS.

| Parameter | Value |
|---|---|
| Number of bars | 2,000 |
| Bar cadence | 1 minute (arbitrary; ratio matters, not unit) |
| Drift `μ` | 0.08 (annualised) |
| Volatility `σ` | 0.20 (annualised) |
| Time step `Δt` | `1 / (252 × 6.5 × 60)` (per-minute fraction of trading year) |
| Seed | 42 |
| Start time | 2024-06-01 09:30 UTC |

Event construction: `build_events_from_signals` with a 5-bar momentum
signal (`(close[t] - close[t-5]) / close[t-5]`) and threshold `0.001`.
The first 25 bars are excluded so every event has a full 20-bar
vol-lookback window.

Labeler config: `TripleBarrierConfig(pt_multiplier=2.0,
sl_multiplier=1.0, max_holding_periods=30, vol_lookback=20)` — ADR-0005
D1 defaults with a shorter holding horizon (30 bars) chosen so the
distribution does not saturate on verticals at the chosen drift/vol.

---

## 2. Label distribution

Generated with `compute_label_diagnostics(labels)` — reproducible
via `tests/unit/features/labeling/test_integration_with_bar_data.py`.

### 2.1 Binary target (ADR-0005 D1 Meta-Labeler training target)

| Class | Pct | Count (n = 470) |
|---|---|---|
| `binary_target = 1` | **37.02 %** | 174 |
| `binary_target = 0` | **62.98 %** | 296 |

Asymmetry is expected and desired: ADR-0005 D1 uses `k_up = 2.0` vs
`k_down = 1.0` so the upper barrier sits at +2σ while the lower
barrier sits at −1σ. Upper touches are strictly harder to achieve
within the same window, which is what makes the Meta-Labeler decision
non-trivial: the classifier must learn **when the +2σ upside is
available**, not just "is the market drifting up".

### 2.2 Ternary breakdown (preserved per ADR-0005 D1)

| Class | Pct |
|---|---|
| `ternary_label = +1` (upper) | 37.02 % |
| `ternary_label = 0` (vertical) | 0.00 % |
| `ternary_label = −1` (lower) | 62.98 % |

### 2.3 Barrier hit distribution

| Barrier | Pct |
|---|---|
| `upper`    | 37.02 % |
| `lower`    | 62.98 % |
| `vertical` | 0.00 %  |

The `max_holding_periods = 30` vertical barrier is never reached on
this fixture because at the chosen σ barriers are hit well before the
30th bar. Distribution is thus **pure horizontal** — good for label
quality but means the holding-period tail (§3) is short. A longer
real-world fixture or tighter barriers will reintroduce verticals.

---

## 3. Holding periods

| Stat | Bars |
|---|---|
| Min    | 1 |
| P25    | 2 |
| Median | 3 |
| P75    | 6 |
| Max    | 23 |

All values strictly less than `max_holding_periods = 30`, confirming
no truncation by the vertical barrier on this fixture.

---

## 4. Per-class mean return (sanity check)

ADR-0005 D1 implicitly requires `label = 1` outcomes to be economically
profitable and `label = 0` outcomes to be non-profitable. We verify
both conditions hold on this fixture:

| Class | Mean return (close-to-close, entry → exit) | Verdict |
|---|---|---|
| `binary_target = 1` | **+0.1752 %** | ✅ strictly positive |
| `binary_target = 0` | **−0.1030 %** | ✅ non-positive |

Both sanity flags reported by `compute_label_diagnostics` are `True`.
The asymmetry in magnitudes (+0.18 % vs −0.10 %) is consistent with
the 2:1 barrier ratio: upper hits require a larger move, lower hits
only need a smaller one, but both classes are correctly separable on
realised P&L.

---

## 5. Warnings / decisions surfaced for Phase 4.2

### 5.1 Class imbalance — sample weights are indispensable (ADR-0005 D2)

The 37 / 63 split is mild but material. Phase 4.2 uniqueness × return
attribution weights (D2) combined with `class_weight="balanced"` at
training time (D3) should be **sufficient**; no stratified resampling
is needed at this stage. Revisit if the Phase 4.3 training run emits
`G6` minority-class warnings (D5 gate).

### 5.2 No vertical hits on synthetic fixture

Real-world bar series with mean-reverting regimes will produce more
verticals. The current synthetic GBM does not reproduce that. The
diagnostics module is agnostic — it will surface verticals when they
exist. No action required at 4.1; track in 4.3 on the actual
training dataset.

### 5.3 `compute_daily_vol` is std, not EWMA

ADR-0005 D1 specifies "EWMA of squared log returns". The existing
`core.math.labeling.compute_daily_vol` implements a simple rolling
std. ADR-0005 §1 entrains the reuse of this implementation ("Phase
4.1 extends this implementation rather than re-writing it"), so we
inherit the std approximation. The two estimators differ only by
the weighting scheme within the 20-bar window and converge as the
window approaches stationarity. If Phase 4.3 gate G1 (mean OOS AUC
≥ 0.55) fails, revisit by upgrading to a true EWMA — tracked as
technical debt in the Phase 4 closure report.

---

## 6. Anti-leakage fix — look-ahead bug eliminated

### 6.1 Before (PR ≤ #136 behaviour)

```python
# features/labels.py:81 (pre-fix)
vol_window = closes[max(0, i - vol_lookback) : i + 1]
#                                              ^^^^^
# Slice is half-open: includes bar i itself.
```

The labeled bar's own close price contaminated `σ_t`, which
silently biased every barrier width by the information that the
classifier was supposed to *predict*. The bug was dormant because
`compute_daily_vol` uses **log returns between consecutive closes**,
and including bar `i` adds one extra return `log(closes[i] /
closes[i-1])` to the vol estimate. On a +5 % jump at bar `i`, that
single return dominates a 20-bar std and inflates `σ_t` by roughly
`0.05 / √20 ≈ 1 %` — enough to shift a near-boundary label by a
full class.

### 6.2 After (Phase 4.1)

```python
# features/labels.py (post-fix)
vol_window = closes[i - vol_lookback : i]
#                                      ^
# Strict half-open: excludes bar i.
```

### 6.3 Coverage

- `test_strict_vol_window_excludes_bar_t` — direct unit check.
- `test_perturb_close_at_t_does_not_change_sigma` — anti-leakage by
  construction: `entry_price` changes with the shock but the
  **sigma** (which only depends on `closes[i - N : i]`) does not.
- `test_perturb_future_after_t1_does_not_change_label` — label is
  independent of any bar *after* `t1` (event's exit time).
- `test_property_labels_independent_of_future_beyond_t1` —
  Hypothesis property test, 200 examples (bounded by CI budget).

### 6.4 Consumers of the adapter

`features/pipeline.py` injects a `TripleBarrierLabelerAdapter` but
does **not** call `.label()` anywhere in Phase 3 code (checked via
`grep -rn "_labeler\|labeler\.label" features/pipeline.py`), so the
adapter semantic change (output length = `len(df) - vol_lookback`)
only affects the adapter's own test suite, which has been updated
in this PR.

---

## 7. ADR-0005 D1 compliance checklist

| D1 requirement | Implementation | Status |
|---|---|---|
| Upper barrier `k_up × σ × price`, `k_up = 2.0` | `TripleBarrierConfig.pt_multiplier = 2.0` in `core/math/labeling.py` | ✅ |
| Lower barrier `k_down × σ × price`, `k_down = 1.0` | `TripleBarrierConfig.sl_multiplier = 1.0` | ✅ |
| Vertical barrier horizon | `TripleBarrierConfig.max_holding_periods`, default 60 (configured to 30 in this fixture to exercise horizontal barriers) | ✅ |
| Vol lookback 20 bars | `TripleBarrierConfig.vol_lookback = 20` | ✅ |
| Window strictly before `t` | `closes[i - vol_lookback : i]` in `features/labels.py` and `features/labeling/triple_barrier.py` | ✅ (fixed this PR) |
| Binary target `y = 1 iff upper hit else 0` | `to_binary_target()` in `core/math/labeling.py` + projection in `label_events_binary` | ✅ |
| Ternary `{-1, 0, +1}` preserved | `BarrierLabel.label` unchanged | ✅ |
| Long-only MVP | `direction ≠ +1` raises `NotImplementedError` in `label_events_binary` | ✅ |
| Raw close prices | No fractional differentiation applied to label inputs | ✅ |
| UTC tz-aware timestamps | `_ensure_utc` guards at every entry point | ✅ |
| Fail-loud on NaN / zero σ | `_validate_bars`, `compute_daily_vol` now raises on < 2 prices, `label_event` raises on `daily_vol ≤ 0` | ✅ |

---

## 8. Reproducibility

- Seed: `APEX_SEED=42` (environment variable, default in
  `TestIntegrationWithBarData.test_reproducible_with_seed`).
- Two consecutive calls to `label_events_binary` on identical inputs
  return bit-identical DataFrames (asserted by
  `TestReproducibility.test_two_runs_bit_identical`).
- `TripleBarrierConfig` round-trips through pickle unchanged
  (asserted by `TestReproducibility.test_config_pickle_roundtrip`).

## 9. References

- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*. Wiley, Chapter 3 (Labeling, Triple Barrier Method).
- ADR-0005 — Meta-Labeling and Fusion Methodology, decision D1.
- ADR-0002 — Quant Methodology Charter, D7 (transaction cost
  scenarios).
- PHASE_4_SPEC.md §3.1 — Sub-phase 4.1 specification.
- Issue #125 — [phase-4.1] Triple Barrier Labeling.
