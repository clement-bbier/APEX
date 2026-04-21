# APEX Architectural Decisions Log

Mini-ADR format for decisions made during Claude Code sessions.
Each entry follows the template in `templates/DECISION_TEMPLATE.md`.

---

## D001 — Custom Feature Store over Feast (2026-04-11)

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Session | 001 |
| Decision | Build a custom lightweight Feature Store using TimescaleDB + Polars |
| Status | ACCEPTED |

### Context

Phase 3.2 requires a Feature Store for versioned, reproducible feature persistence
with point-in-time queries.

### Alternatives Considered

1. **Feast (Tecton open-source)**: Full-featured but heavy deployment, designed for
   multi-team ML platforms. Overkill for single-operator APEX.
2. **Tecton (paid)**: Enterprise-grade, far too expensive for personal project.
3. **Custom on TimescaleDB + Polars**: Lightweight, uses existing infra (Phase 2),
   supports point-in-time queries natively via SQL.

### Justification

- APEX is single-operator; Feast's collaboration features add no value.
- TimescaleDB already deployed in Phase 2 with hypertable compression.
- Polars is already in the stack for data transformation.
- Custom store estimated at ~200 LOC; Feast deployment estimated at ~2 days of config.

### References

- Sculley et al. (2015). "Hidden Technical Debt in ML Systems". NeurIPS.
- Kleppmann (2017). Designing Data-Intensive Applications, Ch. 11.

---

## D002 — vectorbt PRO Deferred to Phase 5 (2026-04-11)

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Session | 001 |
| Decision | Do not purchase vectorbt PRO for Phase 3; re-evaluate for Phase 5 |
| Status | ACCEPTED |

### Context

vectorbt PRO ($400/year) provides vectorized backtesting. Phase 3 validates features
via IC measurement, not strategy backtesting.

### Justification

- Phase 3 measures Information Coefficient, not strategy performance.
- IC measurement requires Polars + NumPy + scipy.stats.spearmanr, all free.
- vectorbt's value proposition is backtesting, which is Phase 5's scope.
- $400/year is significant for a personal project; defer until ROI is clearer.

---

## D003 — Coverage Gate Incremental Raise to 75% (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 004 |
| Decision | Raise CI coverage gate from 40% to 75% (not directly to 85%) |
| Status | ACCEPTED |

### Context

CLAUDE.md documents an 85% coverage target. The CI gate was at 40% — a significant
drift. After narrowing the overly broad omit list (removing S01 and S10 wildcards),
the true baseline coverage measured at 80% on 6,861 LOC.

### Justification

- Jumping directly to 85% would make CI fragile — any new file without tests would break it
- 75% gives 5% headroom below the 80% baseline, absorbing normal fluctuation
- Incremental progression is safer: 40% → 75% → 80% → 85% over future sprints
- Each bump should coincide with a test-writing sprint, not just gate increases

---

## D004 — Backtest Thresholds Deferred to Phase 5 (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 004 |
| Decision | Keep backtest thresholds at Sharpe 0.5 / DD 12% and continue-on-error: true |
| Status | ACCEPTED |

### Context

CLAUDE.md specifies Sharpe >= 0.8 and DD <= 8%. The CI backtest-gate uses relaxed
thresholds (0.5/12%) and is non-blocking due to a known Sharpe calculation bug in
full_report().

### Justification

- Raising thresholds without fixing the Sharpe bug would create false failures
- Making the gate blocking while full_report() is buggy would break CI
- Follow-up issue #102 created to track the fix
- Thresholds should be raised in Phase 5 after feature validation confirms data quality

---

## D005 — S04 StrategySelector Registry Pattern (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 005 |
| Decision | Replace if/elif chain with StrategyProfile dataclass + STRATEGY_REGISTRY dict |
| Status | ACCEPTED |

### Context

S04 `StrategySelector.is_active()` and `get_size_multiplier()` used hardcoded if/elif
chains — adding a new strategy required modifying two methods (OCP violation, issue #75).

### Alternatives Considered

1. **Protocol-based**: Define a Strategy Protocol with `is_active()` and `get_size_multiplier()` per strategy class. More Pythonic but overkill for 4 strategies with simple declarative rules.
2. **Dataclass + Registry (chosen)**: `StrategyProfile` frozen dataclass with `active_vol_regimes`, `active_trend_regimes`, `use_or_logic`, `size_multiplier`. Adding a strategy = adding a dict entry.

### Justification

- All 4 existing strategies have pure declarative rules (regime set membership + optional OR logic)
- Registry pattern is simpler, more testable, and fully preserves existing behavior
- `use_or_logic` flag handles short_momentum's OR semantics (trend OR vol match)

---

## D006 — S01 Normalizer DI via Factory Callable (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 005 |
| Decision | Connectors accept normalizer factory via constructor DI; ConnectorFactory injects |
| Status | ACCEPTED |

### Context

S01 connectors imported concrete normalizer classes directly (layering violation,
issue #77). Normalizers require `bar_size` at construction, but `bar_size` is a
fetch-time parameter — so a factory callable is needed, not a pre-built instance.

### Alternatives Considered

1. **Raw data return (Option A)**: Connectors return raw API data, orchestrators normalize. Breaks the `DataConnector` ABC (`AsyncIterator[list[Bar]]`) and requires type-per-connector raw types.
2. **Factory DI (chosen)**: Connectors accept `bar_normalizer_factory: Callable[[BarSize], NormalizerStrategy]`. ConnectorFactory registration functions import and inject normalizers.

### Justification

- Preserves DataConnector ABC contract (zero interface change)
- No change to job_runner at all
- Connectors only import `NormalizerStrategy` base (abstraction, not concrete)
- Factory pattern handles dynamic `bar_size` parameter naturally

---

## D007 — StateStore.client Property (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 005 |
| Decision | Add `StateStore.client` property as public API; deprecate `_ensure_connected()` |
| Status | ACCEPTED |

### Context

S05, S06, S10 all accessed `state._ensure_connected()` and `state._redis` directly
(DIP violation, issue #76). StateStore already had `connect()` (async) but no public
way to get the Redis client.

### Justification

- `.client` property is the natural public API complement to `connect()`
- `_ensure_connected()` kept as deprecated delegate for backward compat
- All 4 call sites (S05, S06, S10×2) migrated to `state.client`

---

## D008 — S06 Broker ABC + BrokerFactory (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 006 |
| Decision | Extract Broker ABC from 3 concrete brokers; route via BrokerFactory |
| Status | ACCEPTED |

### Context

S06 Execution had 3 brokers (Alpaca, Binance, PaperTrader) with no common interface.
ExecutionService imported all 3 concrete classes and used if/elif branching to route
orders (DIP + OCP violation, issue #72).

### Alternatives Considered

1. **Protocol-based**: Define a `SupportsOrderPlacement` Protocol. Lighter-weight but
   doesn't enforce lifecycle methods (connect/disconnect).
2. **ABC (chosen)**: `Broker` ABC with `connect/disconnect/is_connected/place_order/cancel_order`.
   Strongly typed, enforces contract at class definition time.

### Justification

- `place_order(ApprovedOrder) -> ExecutedOrder | None` unifies sync (paper) and async
  (live) fill models: paper returns ExecutedOrder, live returns None.
- BrokerFactory centralises routing: paper mode always returns PaperTrader, live mode
  routes by crypto suffix. Adding IBKR = 1 new file + 1 factory entry.
- ExecutionService._execute() reduced from 35 lines with 4 branches to 5 lines.
- Raw venue-specific methods preserved as `_submit_raw_order()` for direct access.

---

## D009 — S02 SignalPipeline Stepwise Decomposition (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 006 |
| Decision | Decompose _process_tick into SignalPipeline with PipelineState dataclass |
| Status | ACCEPTED |

### Context

S02 SignalEngine._process_tick was ~270 lines performing 7 distinct operations on the
hottest path in the system (every tick). Impossible to unit-test any step in isolation
(SRP violation, issue #73).

### Alternatives Considered

1. **Simple helper methods on SignalEngine**: Extract 7 private methods. Simple but
   still couples all state to the service class; no reusable state object.
2. **PipelineState + SignalPipeline (chosen)**: Separate class with shared mutable state
   dataclass. Each step reads/writes explicit fields.

### Justification

- PipelineState makes inter-step data flow explicit and inspectable
- Each step is independently unit-testable with minimal fixtures
- SignalPipeline can be reused (e.g. backtesting engine could call individual steps)
- SignalEngine._process_tick reduced to 3 lines: pipeline.run() + publish
- 16 new unit tests covering all 7 pipeline steps

---

## D010 — ADR-0004 Feature Validation Methodology Published (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 007 |
| Decision | Publish ADR-0004 defining canonical 6-step feature validation pipeline |
| Status | ACCEPTED |

### Context

Phase 3 requires validating ~6 candidate features. Without a canonical methodology
defined before coding begins, the risk of false discovery is extreme (Bailey-LdP 2014:
~75% of published strategies are artifacts).

### Justification

- 6-step pipeline: IC measurement, IC stability, multicollinearity, MDA feature importance,
  CPCV backtest, PSR/DSR/PBO statistical significance
- Each step has quantitative acceptance/rejection thresholds (no subjective judgment)
- Maps directly to Phase 3 sub-phases (3.3, 3.9, 3.10, 3.11)
- 11 Tier-1 academic references cited

---

## D011 — Academic References Centralized (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 007 |
| Decision | Create docs/ACADEMIC_REFERENCES.md as single source of truth for all citations |
| Status | ACCEPTED |

### Context

References were scattered across ADRs, PHASE_3_SPEC, docstrings, and MANIFEST.md.
No central index existed for verifying Tier-1 compliance or finding canonical sources.

### Justification

- 56 references across 9 domain sections
- Tier-1 criteria codified (journals, university presses, approved authors)
- Forbidden sources explicitly listed (blogs, YouTube, Medium, Reddit)
- Supports ADR-0002 requirement that all implementations cite canonical references

---

## D012 — ONBOARDING.md Published (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 007 |
| Decision | Create docs/ONBOARDING.md as 15-min quick-start for new dev or Claude Code session |
| Status | ACCEPTED |

### Context

New Claude Code sessions had to piece together context from CLAUDE.md, CONTEXT.md,
PHASE_3_NOTES.md, and various docs. No single entry point existed.

### Justification

- 11 sections covering setup, workflow, conventions, gates, red flags, navigation
- Explicit "Workflow for new Claude Code session" checklist (step 4)
- "Where to find things" navigation table
- Reduces onboarding time from ~30 min to ~15 min

---

## D013 — TripleBarrierLabeler Adapter Pattern (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 008 |
| Decision | Expose TripleBarrierLabeler via Polars adapter, not via inheritance |
| Status | ACCEPTED |

### Context

Phase 3.1 needs a pipeline-friendly interface for Triple Barrier labeling.
`core/math/labeling.py::TripleBarrierLabeler` already implements the math.

### Alternatives Considered

1. **Inherit from TripleBarrierLabeler**: Extend with Polars methods. Risk: couples
   features/ to core/math internal API; breaking changes propagate.
2. **Adapter (chosen)**: `TripleBarrierLabelerAdapter` wraps the core labeler,
   converting Polars DataFrames to/from the native interface.

### Justification

- Adapter isolates features/ from core/math implementation details
- Core labeler can evolve independently (Liskov Substitution preserved)
- Zero duplication of labeling math

---

## D014 — ValidationPipeline Composable Stage Pattern (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 008 |
| Decision | ADR-0004 pipeline as composable ValidationStage ABCs injected into ValidationPipeline |
| Status | ACCEPTED |

### Context

ADR-0004 defines 6 sequential validation steps. Phase 3.1 provides the skeleton;
concrete stages arrive in sub-phases 3.3, 3.9, 3.10, 3.11.

### Justification

- Each stage is independently testable and replaceable (OCP)
- Stages can be added/removed without modifying ValidationPipeline (Strategy pattern)
- Stub stages log and return `skipped` — observable in tests
- Pipeline propagates StageContext for inter-stage communication

---

## D017 — FeatureStore ABC Extended with asset_id (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 010 |
| Decision | Add `asset_id: UUID` parameter to all FeatureStore ABC methods |
| Status | ACCEPTED |

### Context

Phase 3.1 FeatureStore ABC was feature-name-scoped only (`save(name, version, df)`).
The multi-asset system requires per-asset feature storage.

### Alternatives Considered

1. **Encode asset_id in name** (e.g. `f"{asset_id}:{feature_name}"`): Hacky, loses type safety, breaks registry queries.
2. **Add asset_id parameter (chosen)**: Clean, typed, aligns with PHASE_3_SPEC §2.2 which uses `symbol: str`.

### Justification

- No concrete implementation existed yet (3.2 creates the first one)
- All abstract methods updated: `save`, `load`, `list_versions`, `latest_version`
- ABC now also uses `FeatureVersion` dataclass instead of raw `str` version parameter
- Backward compatible in spirit: 3.1 tests still pass (ABC test checks method names, not signatures)

---

## D018 — Content-Addressable Versioning Strategy (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 010 |
| Decision | Use `{calculator_name}-{sha256_hash8}` as version identifier |
| Status | ACCEPTED |

### Context

Phase 3.2 needs a deterministic versioning scheme for feature batches.

### Alternatives Considered

1. **Semver** (`0.1.0`, `0.2.0`): Requires manual version bumps, no content awareness.
2. **Timestamp-based** (`har_rv-20260413`): Not content-addressable, different params could collide.
3. **Content-addressable hash (chosen)**: SHA-256 of canonical JSON `(calculator_name, params, computed_at)` truncated to 8 hex chars.

### Justification

- Deterministic: same inputs always produce the same version string (Hypothesis-verified, 1000 examples)
- Discriminating: different params produce different versions
- Short: `har_rv-a1b2c3d4` is human-readable
- Content hash on IPC bytes provides separate integrity verification (`content_hash` field)

---

## D019 — Redis TTL Cache Strategy (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 010 |
| Decision | Use TTL-based Redis cache (300s) with as_of in cache key, no manual invalidation |
| Status | ACCEPTED |

### Context

Feature Store needs a read cache to avoid repeated TimescaleDB queries for the same data.

### Alternatives Considered

1. **Event-based invalidation**: Invalidate cache on new version registration. Complex, premature.
2. **TTL-only (chosen)**: Simple, self-healing, no invalidation logic needed.

### Justification

- Feature data is immutable (versions are append-only), so stale cache = missing a new version, not stale data
- Including `as_of` in cache key prevents PIT cache poisoning (different as_of = different cache entry)
- TTL keeps memory bounded without explicit eviction
- Manual invalidation deferred to Phase 9+ (observability)

---

## D020 — IC Bootstrap Reimplemented (Not Reused from metrics.py) (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 011 |
| Decision | Reimplement stationary bootstrap in features/ic/stats.py instead of reusing backtesting/metrics.py |
| Status | ACCEPTED |

### Context

`backtesting/metrics.py` has `_stationary_bootstrap_sharpe_ci()` (Politis & Romano 1994), but it is tightly coupled to Sharpe ratio computation (takes returns, risk_free_rate, annual_factor). IC measurement needs a generic mean-bootstrap on IC series.

### Alternatives Considered

1. **Reuse and wrap**: Extract the block-sampling logic from metrics.py into a shared helper. Invasive refactor for minimal gain.
2. **Reimplement (chosen)**: ~30 lines of Politis-Romano block sampling, purpose-built for IC mean CI.

### Justification

- The Politis-Romano algorithm is simple (~30 LOC) — the coupling cost of wrapping exceeds reimplementation cost
- IC bootstrap needs `np.mean()` as the statistic; Sharpe bootstrap uses a complex risk-adjusted ratio
- No shared interface that cleanly abstracts both use cases without over-engineering

---

## D021 — Extend ICResult with Optional Fields (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 011 |
| Decision | Extend ICResult dataclass with optional fields (default=None) rather than creating ICResultFull |
| Status | ACCEPTED |

### Context

Phase 3.1 defined ICResult with 6 fields. Phase 3.3 needs 9 additional fields (ic_std, ic_t_stat, ic_hit_rate, turnover_adj_ic, ic_decay, is_significant, feature_name, horizon_bars, newey_west_lags).

### Alternatives Considered

1. **New ICResultFull dataclass**: Clean separation but requires parallel type handling everywhere.
2. **Extend with optional fields (chosen)**: Backward-compatible, single type throughout.

### Justification

- All existing code constructing ICResult with 6 positional args continues to work unchanged
- mypy catches any field access on optional fields that aren't None-checked
- Single type simplifies pipeline, report, and serialization code

---

## D022 — Minimum 20 Samples for IC Measurement (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 011 |
| Decision | Require ≥ 20 valid (non-NaN) observations for IC measurement; return zero ICResult below threshold |
| Status | ACCEPTED |

### Context

Spearman rank correlation on very small samples (< 20) produces noisy, unreliable IC estimates. Need a floor.

### Justification

- 20 is a common minimum for rank correlation in financial literature
- Below 20, the p-value from spearmanr is unreliable and bootstrap CI is meaningless
- Returns `ic=0.0, is_significant=False, p_value=1.0` — conservative, logged as warning
- `safe_spearman` separately enforces ≥ 10 valid pairs per block

---

## D023 — Degenerate IC Series Handling (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 011 |
| Decision | When all per-block IC values are identical (std=0), treat as maximally significant if IC ≠ 0 |
| Status | ACCEPTED |

### Context

A perfect predictor (feature == forward_return) produces IC=1.0 on every block. std(IC)=0, so IC_IR=mean/std is undefined (0/0), and Newey-West SE=0 makes t-stat=0/0.

### Justification

- A perfectly consistent IC is the BEST possible result, not an error
- Set ic_ir=1e6, t_stat=1e6, p_value=0.0 — effectively infinite significance
- This correctly passes ADR-0004 thresholds (|IC|>=0.02 AND IC_IR>=0.50)
- The degenerate case only arises with synthetic/test data; real features will have IC variance

---

## D024 — Expanding-Window Refit for HAR-RV (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 012 |
| Decision | Use expanding-window refit (fit on [0, t-1] to forecast t) rather than global fit or rolling window |
| Status | ACCEPTED |

### Context

The HAR-RV model fits OLS coefficients β_D, β_W, β_M. A single global fit on the entire series then "forecasting" past points leaks future information through the coefficients — this is the primary look-ahead trap (PHASE_3_SPEC §5.1).

### Justification

- Expanding window guarantees forecasts at time t never see data at or after t
- O(n²) cost is acceptable for offline feature computation (252 daily rows in ~1-2s)
- Future optimization path: incremental OLS / Kalman filter (out of scope 3.4)
- Characterized by 2 dedicated look-ahead tests (identical-past-different-future)

---

## D025 — tanh Normalization with k=3.0 (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 012 |
| Decision | Normalize HAR-RV residual to signal via tanh(residual / (k * rolling_std)) with k=3.0 |
| Status | ACCEPTED |

### Context

The HAR-RV residual (realized - forecast) has unbounded range. The signal must be in [-1, +1] for downstream consumption. Three options: z-score clipped, min-max on rolling window, tanh scaling.

### Justification

- tanh is smooth, strictly bounded in (-1, +1), and does not saturate abruptly
- k=3.0 maps ±1σ residuals to ≈±0.32 and ±3σ to ≈±0.71 — good spread, not saturated
- rolling_std (window=60, expanding until 60 available) adapts to local volatility regime
- Validated by test: mean |signal| < 0.7 on well-behaved synthetic data

---

## D026 — Strict Wrapper over S07 har_rv_forecast (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 012 |
| Decision | HARRVCalculator wraps S07 RealizedVolEstimator.har_rv_forecast() — no reimplementation of OLS |
| Status | ACCEPTED |

### Context

S07 already implements the HAR-RV OLS regression. Reimplementing in features/ would create divergence risk (same as TripleBarrierLabeler adapter decision D013).

### Justification

- Single source of truth for HAR-RV math remains in S07
- Parity test verifies calculator output matches direct S07 call
- Pattern consistent with D013 (adapter/wrapper, not reimplementation)
- Establishes the template for 3.5-3.8 calculators

---

## D027 — Intraday Aggregate Features Emit at Period-Close Only (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 013 |
| Decision | Features computed from aggregated-period data must emit realization columns (residual, signal) ONLY on the last bar of the period |
| Status | ACCEPTED |

### Context

PR #111 Phase 3.4 HAR-RV calculator. In `bar_frequency="5m"` mode, the initial implementation computed daily residuals (based on full-day realized_variance) and broadcast them to every bar of the day. The 9:30 bar received a residual that depended on the 15:55 bar — look-ahead within the day.

Copilot AI review caught this during PR #111. The existing look-ahead test (`test_forecast_at_t_uses_only_data_before_t`) ran in daily mode only and did not catch it.

### Rule (applies to 3.5-3.8 and beyond)

For any feature computed from aggregated intraday data:
- **Forecast-like columns** (depend on PAST aggregates) → safe to broadcast to all bars of the current period.
- **Realization columns** (depend on CURRENT-period aggregate) → emit ONLY on the last bar of the period; NaN elsewhere.

### Characterization

Every future calculator with period aggregates must include a test equivalent to `test_5m_mode_residual_nan_before_day_close` that verifies:
- forecast non-NaN on all post-warm-up bars
- residual/signal non-NaN on at most 1 bar per period (the last)

### References

- PR #111 Copilot review comment #1
- PHASE_3_SPEC §5.1 Look-Ahead Bias

---

## D028 — Forecast-like Columns Safe to Broadcast in Intraday Mode (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 015 |
| Decision | Output columns computed from daily_series[:t] (strict past, excluding current day t) are forecast-like and safe to broadcast to all intraday bars of day t. Day-close-only emission (D027) applies ONLY to columns computed from daily_series[:t+1] or full-day aggregates including day t. |
| Status | ACCEPTED |

### Context

PR #112 Phase 3.5 Rough Volatility. Initial implementation claimed "all 6 columns depend on current day's RV" (justifying day-close emission per D027), but the code actually used `daily_rv[:t]` (prior days only). Copilot caught the contradiction between code and docstring.

### Resolution

The code (`daily_rv[:t]`) was correct — all 6 Rough Vol columns are forecast-like estimates that use only prior days' statistics. The docstring and PR description were wrong. Switched to broadcast-to-all-intraday-bars in 5m mode (like HAR-RV's `har_rv_forecast`).

### Rule refinement for 3.6-3.8

When implementing a calculator with intraday (5m) mode, explicitly classify each output column:
- **Forecast-like** (uses `series[:t]`, strict past) → safe broadcast to all bars
- **Realization** (uses `series[:t+1]` or current-period aggregate) → day-close-only per D027

Document the classification in the class docstring. Verify with a "different-intraday-same-past" test that forecast-like columns are invariant to current-day intraday data.

### Implication

- **Rough Vol (3.5)**: all 6 columns are forecast-like → broadcast
- **HAR-RV (3.4)**: forecast is forecast-like (broadcast); residual and signal are realization-like (day-close) because residual requires current day's realized_rv

### References

- D027 (original rule, refined here)
- PR #112 Copilot review comment #3
- PHASE_3_SPEC §5.1 Look-Ahead Bias

---

## D029 — Signal Variance Gate on Output Columns (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 016 |
| Decision | Every calculator output column must include a test verifying the column varies across inputs |
| Status | ACCEPTED |

### Context

PR #112 Phase 3.5 Rough Volatility. The `rough_size_adjustment` column was effectively constant (all values clamped to 1.0 due to a misapplied `[0, 1]` bound on a multiplicative factor). No test caught this — bound checks and non-NaN checks all passed. Would have produced IC = 0 on that column in 3.9/3.10 with no diagnostic trace.

### Rule (applies to 3.7, 3.8, and retrofits)

For each output column C of any FeatureCalculator:
- Add `test_<name>_varies_across_inputs` or equivalent.
- Generate N >= 100 different synthetic DataFrames.
- Assert `std(C.mean() for each df) > epsilon` (typical 0.01).
- Alternative: `std(C) > epsilon` within a single non-trivial input.

### First Application

- `test_ofi_signal_varies_across_inputs` in PR #113 Phase 3.6

### Retrofits Required

- 3.7 CVDKyleCalculator: add variance gate per output column
- 3.8 GEXCalculator: add variance gate per output column
- Optional: retrofit HAR-RV (3.4) and Rough Vol (3.5) in a future tidy-up PR

### References

- PR #112 Copilot review, size_adjustment constant bug
- D028 (forecast vs realization classification)

---

## D030 — S02 OFI Price-Proxy vs Cont 2014 Size-Delta (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 016 |
| Decision | OFICalculator implements canonical Cont 2014 (Δbid_size − Δask_size) directly, not wrapping S02's price-delta proxy |
| Status | ACCEPTED |

### Context

S02 `MicrostructureAnalyzer.ofi()` (`services/signal_engine/microstructure.py`) computes OFI as `Σ(ΔBid_price − ΔAsk_price) / total_volume`. This is a price-based proxy for queue-volume changes. The canonical Cont, Kukanov & Stoikov (2014) formula uses order book SIZE deltas: `Σ(Δbid_size − Δask_size)`.

### Why Not Wrap S02

- S02's formula answers a different question (price-level shifts) than Cont 2014 (order book depth changes)
- Feature validation must use the canonical academic formula to produce comparable IC results
- Wrapping S02 would produce scientifically incorrect OFI for the validation harness
- D026 (wrapper strict) is honored in spirit — we would wrap if the formulas matched

### Implication

- S02 is NOT modified (anti-scope-creep)
- If S02's OFI needs upgrading to Cont 2014 formula, that is a separate issue (out of Phase 3 scope)
- Lee-Ready classifier exists only inline in VPIN — not reusable standalone. Trade-based fallback uses signed volume directly

### References

- D026 (wrapper strict — honored where applicable)
- Cont, Kukanov & Stoikov (2014) JFE 104(2)
- S02 `services/signal_engine/microstructure.py` lines 61-81

---

## D031 — Configurable Parameters Must Honor Configurability Everywhere (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 017 |
| Decision | When a constructor parameter is exposed as configurable, every downstream reference must honor it dynamically |
| Status | ACCEPTED |

### Context

PR #113 Phase 3.6 OFI. Constructor accepted `windows` tuple but `output_columns()` and `with_columns()` were hardcoded to `ofi_10/50/100`. Custom windows (e.g. `(5, 20, 60)`) would produce silently mislabeled columns (values for window=5 stored in column named `ofi_10`). Copilot caught this during review.

### Rule (applies to 3.7, 3.8, retrofits)

For every FeatureCalculator constructor parameter:
- Generate derived names/sizes/indices dynamically from the parameter, never hardcode.
- Validate parameter invariants in `__init__` (length match, range, sum-to-one if weights, etc.) — raise `ValueError` with explicit message.
- Add tests that instantiate with non-default values and verify downstream propagation.

### Audit Results

- **HAR-RV (3.4)**: NOT affected — column names invariant of constructor params.
- **Rough Vol (3.5)**: NOT affected — column names invariant of constructor params.
- **OFI (3.6)**: Fixed in this hotfix — dynamic column names from `self._windows`.

### References

- PR #113 Copilot review comment #1
- D026 (strict wrapper)

---

## D032 — CVD/Kyle Lambda Implemented Directly (Not Wrapping S02) (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 018 |
| Decision | CVDKyleCalculator implements CVD and Kyle lambda directly, not wrapping S02 microstructure.py |
| Status | ACCEPTED |

### Context

Phase 3.7 CVDKyleCalculator needs (a) raw cumulative CVD, (b) Kyle lambda via OLS with intercept on a strict-past rolling window. S02 provides both functions but with different semantics:

- S02 `cvd()` returns a normalized ratio `Σ(buy-sell)/total_vol` ∈ [-1,1] — not the raw cumulative sum needed for divergence tracking.
- S02 `kyle_lambda()` uses `Cov(ΔP,Q)/Var(Q)` without intercept and without rolling/expanding window protection — no look-ahead defense.

### Why Not Wrap S02

- S02's formulas answer different questions than what feature validation requires
- Wrapping would require either modifying S02 (anti-scope-creep) or applying ad-hoc corrections that negate the wrapper benefit
- Same pattern as D030 (OFI) where S02's price-delta proxy differs from Cont 2014 canonical formula

### Justification

- S02 is NOT modified (anti-scope-creep, same as D030)
- D026 (wrapper strict) honored in spirit — we would wrap if formulas matched
- OLS with intercept captures baseline price drift, producing a cleaner lambda estimate
- Rolling window with strict past exclusion enforces D024 look-ahead safety

### References

- D026 (strict wrapper — honored where applicable)
- D030 (OFI precedent: implement directly when S02 formula differs)
- Kyle (1985) Econometrica 53(6)
- S02 `services/signal_engine/microstructure.py` lines 83-126

---

## D033 — GEX Implemented Directly (Not Wrapping S02) (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 020 |
| Decision | GEXCalculator implements GEX directly, not wrapping S02 CrowdBehaviorAnalyzer.update_gex() |
| Status | ACCEPTED |

### Context

Phase 3.8 GEXCalculator needs dealer-adjusted gamma exposure per Barbon-Buraschi (2020): calls contribute negatively, puts positively, with S² dollar scaling and strict-past z-score. S02 provides `update_gex()` but with fundamentally different semantics:

- S02 sign convention: calls = +1, puts = -1 (**opposite** of Barbon-Buraschi)
- S02 formula: `gamma * OI * 100` (no S² scaling for dollar GEX)
- S02 uses `float`, no strict-past protection, no rolling z-score

### Why Not Wrap S02

- Sign convention is **inverted** — wrapping would require negating the result and re-signing every option, defeating the wrapper purpose
- Formula lacks S² factor for proper dollar GEX — wrapping would require multiplying by S² post-hoc
- No rolling z-score or regime classification in S02
- Same pattern as D030 (OFI) and D032 (CVD/Kyle): implement directly when S02 formula differs

### Justification

- S02 is NOT modified (anti-scope-creep)
- D026 (wrapper strict) honored in spirit — would wrap if sign convention and formula matched
- Barbon-Buraschi sign convention characterized by 2 dedicated tests
- GEX formula: `Σ(sign_i * OI_i * gamma_i * S² * multiplier)` where sign = -1 calls, +1 puts

### References

- D026 (strict wrapper — honored where applicable)
- D030 (OFI precedent), D032 (CVD/Kyle precedent)
- Barbon & Buraschi (2020) "Gamma Fragility"
- S02 `services/signal_engine/crowd_behavior.py` lines 43-79

---

## D034 — Snapshot-Level IC Measurement for Snapshot-Granularity Features (2026-04-13)

| Field | Value |
|---|---|
| Date | 2026-04-13 |
| Session | 021 |
| Decision | For features with multiple rows per timestamp, IC must be computed at snapshot level (one row per unique timestamp) |
| Status | ACCEPTED |

### Context

PR #116 Copilot review caught that GEX integration tests computed forward returns by row-shifting `result_df`, which has `n_options_per_snapshot` rows per timestamp. Most adjacent rows shared the same snapshot, producing artificial zero returns (`log(spot/spot) = 0`) and IC sensitive to option chain density. The IC measurement was semantically incorrect.

### Rule

For features whose output columns are broadcast across multiple rows sharing the same timestamp (e.g., GEX across option rows):
1. Aggregate result DataFrame by timestamp (one row per snapshot)
2. Take signal value (broadcast = identical within snapshot)
3. Compute forward returns at snapshot level
4. Measure IC on snapshot-level pairs

Row-level IC on such features produces artificial zero returns on same-snapshot adjacent rows and IC sensitive to broadcast density.

### Applies To

- GEX (3.8): multiple option rows per timestamp
- Future snapshot-based features (OI imbalance, IV surface features)

### Does NOT Apply To

- Bar-level features (HAR-RV, Rough Vol): one row per bar
- Tick-level features (OFI, CVD+Kyle): one row per tick

### References

- PR #116 Copilot review comment #4
- PHASE_3_SPEC §2.8

## D035 — Coexistence of `features/weights.py` Prototype and Canonical Phase 4.2 Sample Weights (2026-04-14)

### Context

Phase 4.2 (issue #126) requires the canonical bar-indexed uniqueness ×
return-attribution sample weights from López de Prado (2018) §§4.4-4.5,
consumed by sub-phases 4.3 / 4.4 / 4.5 of the Meta-Labeler training
pipeline. The repository already contains `features/weights.py` with a
Phase 3.1 prototype `SampleWeighter` class that:

- operates on `list[datetime]` entry/exit times (not Polars Series),
- implements a *duration-weighted* uniqueness formula (not the
  bar-indexed LdP §4.4 canonical form),
- raises `NotImplementedError` for `return_attribution_weights`,
- is wired into `features/pipeline.py` and covered by 21 passing tests
  in `tests/unit/features/test_weights.py`,
- is also exercised by `test_pipeline.py` and
  `test_pipeline_with_store.py`.

### Decision

Create the canonical module at `features/labeling/sample_weights.py`
as a **sibling**, not a refactor. The Phase 3.1 prototype remains
untouched. Phase 4.2 introduces the ADR-0005 D2 implementation with
Polars-native `pl.Series` I/O, vectorized O(n_samples + n_bars)
algorithms, and full `return_attribution_weights` + `combined_weights`
coverage.

Both modules will coexist for the remainder of Phase 4. Migration of
`features/pipeline.py` onto the canonical API is logged as technical
debt to be addressed in the Phase 4 closure report (issue #133),
alongside deletion of the now-redundant prototype.

### Rationale

1. **Non-negotiable: 21 existing tests stay green.** Refactoring
   `features/weights.py` in-place would force touching `pipeline.py`
   and those 21 tests in the same PR, dramatically expanding the
   Phase 4.2 scope and risking regressions in paths unrelated to the
   meta-labeler.
2. **Clean SRP boundary.** The canonical module lives inside
   `features/labeling/` next to its direct consumer schema from
   Phase 4.1 (`triple_barrier.py`). This matches PHASE_4_SPEC §3.2.
3. **Explicit documentation.** Both the module docstring and
   `reports/phase_4_2/audit.md` call out the coexistence and the
   migration contract, so no future reader mistakes the old prototype
   for canonical behavior.

### Consequences

- Short term: two modules named `weights` in the repo. Mitigated by
  distinct paths (`features/weights.py` vs
  `features/labeling/sample_weights.py`) and explicit docstring notes.
- Long term: must retire the prototype before Phase 5, or at the Phase
  4 closure report. Tracked under issue #133.
- Test double-maintenance: `test_weights.py` (21 tests, Phase 3.1)
  remains; Phase 4.2 adds `test_sample_weights_{uniqueness,attribution,combined}.py`
  (52 tests).

### References

- [`reports/phase_4_2/audit.md`](../../reports/phase_4_2/audit.md) §0 / §1
- [`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md`](../adr/ADR-0005-meta-labeling-fusion-methodology.md) D2
- [`docs/phases/PHASE_4_SPEC.md`](../phases/PHASE_4_SPEC.md) §3.2
- LdP (2018) §§4.4-4.5 and Table 4.1


---

## 2026-04-17 — Phase 5.1 Fail-Closed Pre-Trade Risk Controls

**Scope**: Sub-phase 5.1 of Phase 5. Issue #148. PR #177 (merged 2026-04-17, main at `1b7c3b5`). ADR-0006 ACCEPTED.

**Decision**: Transition S05 Risk Manager from the Phase 1/2 Fail-Open posture (`_safe()` heuristic defaults on Redis failure) to **Fail-Closed**: any non-`HEALTHY` `SystemRiskState` rejects 100% of incoming `OrderCandidate` in O(1) with `BlockReason.SYSTEM_UNAVAILABLE`. Three-state machine `HEALTHY | DEGRADED | UNAVAILABLE`, heartbeat TTL 5 s in Redis key `risk:heartbeat`, transition envelope published on `Topics.RISK_SYSTEM_STATE_CHANGE`.

**Why now**: SEC Rule 15c3-5 + Knight Capital 2012 post-mortem. The Phase 1/2 fallback values (capital = 100 000, positions = [], correlation = {}) were a latent production-kill risk: a transient Redis outage could authorize unbounded position sizing. No live trading can begin without this.

**Rationale**: Chosen over three alternatives:
1. Keep Fail-Open with wider monitoring alerts — rejected: SEC 15c3-5 is non-negotiable.
2. Partial degradation (allow small orders during DEGRADED) — rejected per ADR-0006 §D7: no safe way to define "small" without a working risk model.
3. Event sourcing + in-memory state (Phase 5.2) instead — rejected as sequencing: event sourcing is harder and depends on a safety foundation.

**Consequences**:
- S05 loses the mock-comfort of default values. Tests now seed Redis with fakeredis (see `tests/unit/s05/test_service_no_fallbacks.py`, `tests/unit/s05/test_risk_chain.py`).
- `FailClosedGuard` sits as STEP 0 of the risk chain. Observability dashboard (S10) subscribed to `risk.system.state_change` in PR #178 (Batch A of the post-audit execution).
- The 8 pre-trade context keys are now **hard prerequisites** — confirmed orphan reads in
  [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md). Resolving those writers is part of Phase 5.2 scope (PHASE_5_SPEC_v2).

**Residual debt**:
- `services/risk_manager/service.py` reached 530 LOC; SOLID-S decomposition deferred to Batch D of the post-audit execution (`RiskChainOrchestrator` + `ContextLoader` + `RiskDecisionBuilder`).
- Heartbeat-TTL empirical calibration after 30 days of paper trading (issue #176).

**References**:
- [`docs/adr/ADR-0006-fail-closed-risk-controls.md`](../adr/ADR-0006-fail-closed-risk-controls.md)
- [`core/state.py`](../../core/state.py) §SystemRiskMonitor (lines 365–600)
- [`services/risk_manager/fail_closed.py`](../../services/risk_manager/fail_closed.py)
- SEC Rule 15c3-5; Knight Capital 2012 post-mortem.


---

## 2026-04-17 — Phase 5 Re-Sequencing (STRATEGIC_AUDIT_2026-04-17)

**Scope**: Strategic audit reviewing PHASE_5_SPEC v1 (9 sub-phases) against the operator's constraints and the 7 guiding principles.

**Decision**: Drop sub-phases **5.6 (ZMQ P2P bus)**, **5.7 (SBE/FlatBuffers)**, and **5.9 (Rust FFI hot path)** from Phase 5. Move to a new **Phase 7.5 Infrastructure Hardening** backlog, revisited only if live-trading benchmarks prove they are bottlenecks. Re-sequence remaining sub-phases as **5.1 (DONE) → 5.2 → 5.3 → 5.5 → 5.4 → 5.8 → 5.10**. Substitute the proprietary `WorldMonitorConnector` in 5.8 with **GDELT 2.0 + FinBERT** (Principle 3).

**Why**:
- **Principle 1** (cash generation): the three dropped sub-phases were ~4–10 weeks of work that solve HFT-scale problems not yet measurable in a no-live-pipeline system.
- **Principle 3** (acknowledged constraints): solo operator on one host; a SPOF-argument broker replacement does not buy resilience. Rust FFI for hot paths has no current bottleneck to prove.
- **Principle 7** (AQR senior-quant tie-breaker): ship alpha first, optimize transport layer second.

**Consequences**:
- Phase 5 critical path shortens by ~6–10 weeks.
- PHASE_5_SPEC v1 marked as partial supersession; PHASE_5_SPEC_v2.md to be published in Batch C.
- Three backlog MDs marked DEFERRED; three GitHub issues (#150/#151/#152) to be closed in Batch E.
- 5.5 (drift monitoring) promoted ahead of 5.4 (short-side) so the safety instrumentation exists before the alpha extension.

**References**:
- [`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md)
- [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md)

---

## 2026-04-18 — APEX Multi-Strat Charter v1.0 ratified (PR #184)

**Decision**: Adopt the APEX Multi-Strat Platform Charter as the binding constitutional document for the next 12–24 months of development.

**File**: [`docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md`](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) (v1.0)

**PR**: #184 (merged 2026-04-18)

**Eight binding decisions (Q1–Q8 from the structured CIO interview)**:

1. Microservices per strategy at `services/strategies/<name>/` (+20% ops overhead accepted)
2. Dedicated `services/portfolio/strategy_allocator/` microservice (distinct from fusion and risk)
3. Disciplined `services/data/panels/` microservice (all strategies consume panels)
4. Capital allocation: Phase 1 Risk Parity pure; Phase 2 Risk Parity + Sharpe overlay ±20%
5. Trigger-based four-gate lifecycle with 6 boot strategies in fixed deployment order
6. Two-tier circuit breakers (soft per-strategy + hard global portfolio)
7. Seven-step VETO Chain of Responsibility (STEP 0-2 and 7 GLOBAL; STEP 3-6 PER-STRATEGY)
8. Three budget categories (Low/Medium/High Vol) with tolerant decommissioning (9M Sharpe<0 → review)

**Topology**: Classification by domain (`data/`, `signal/`, `portfolio/`, `execution/`, `research/`, `ops/`, `strategies/`) — abandonment of linear S01–S10 numbering in favor of institutional folder structure. Refactor scheduled in Document 3.

**Benchmarks** (3-level ladder):
- Level 1 Survival: Return >15%, Sharpe >1.0, DD <15% simultaneously
- Level 2 Legitimacy: Alpha >10% vs BTC+ETH+SPY, Beta <0.5, Sharpe >1.5
- Level 3 Institutional: Sharpe >2.0 rolling 12M, DD <10%, cross-strategy correlation <0.3

**Participants**:
- CIO: Clement Barbier (ratifier)
- Head of Strategy Research: Claude Opus 4.7 (claude.ai interview conductor + Charter drafter prompter)
- Head of Architecture Review: Claude Opus 4.7 (Multi-Strat Readiness Audit 2026-04-18)
- Implementation Lead: Claude Code (Charter authored on branch `docs/strategy-charter-document-1`)

**Immediate downstream actions**:

1. Document 2 (STRATEGY_DEVELOPMENT_LIFECYCLE.md) — queued, authoring begins next.
2. Document 3 (PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) — queued after Document 2 ratifies.
3. Documentation sync PR (this mission) — adds STATUS banners to pre-Charter docs.
4. Multi-Strat Infrastructure Lift (Phases A-B-C-D) — scheduled in Document 3, begins after Doc 3 ratification.

**Review cadence**: Charter reviewed semi-annually (per Charter §9.6). Emergency review triggered by 3+ decommissionings in 12M, 3+ hard CB trips in 12M, or Charter fundamentally blocking a desired strategy deployment.

---

## 2026-04-20 — APEX Strategy Development Lifecycle Playbook v1.0 ratified (PR #186)

**Decision**: Adopt the Lifecycle Playbook as the binding operational layer of the APEX Multi-Strat Platform.

**File**: [`docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`](../strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) (v1.0)

**PR**: #186 (merged 2026-04-20)

**What the Playbook binds:**

The Playbook prescribes mechanical operational detail for every stage of a strategy's lifecycle — who acts, what evidence is consumed, what artifacts are produced, what triggers the next step. From this point forward, deviations from Playbook procedures require an ADR + Playbook version bump per §16.4.

**Key constitutional additions (Playbook-specific, not in Charter):**

1. **10 canonical stress scenarios** (§4.2.2) — the fixed Gate 2 test battery: equity flash crash, vol spike, Fed surprise, SNB-class FX shock, geopolitical oil shock, liquidity evaporation, correlation breakdown, crypto tail event, single-symbol gap, data feed outage.
2. **StrategyHealthCheck state machine** (§8.0) — 6 states with formal transition table; canonical spec for STEP 3 of the VETO chain.
3. **Master decommissioning checklist** (§10.3.2) — identical for all 6 Charter §9.2 rules.
4. **Per-strategy Charter template** (§2.3) — reusable across all strategies; 12 sections.
5. **18-month candidate aging out** (§13.3.3) — backlog hygiene discipline.

**Participants:**
- CIO: Clement Barbier (ratifier)
- Head of Strategy Research: Claude Opus 4.7 (Playbook author; applied 5 review corrections after initial draft)
- Implementation Lead: Claude Code (authored on branch `docs/strategy-lifecycle-document-2`; applied corrections)

**5 review corrections applied before merge:**

1. §5.2.4 + §5.3: pod-crash reset semantics clarified (3-reset limit formalized)
2. §10.4.1: running-peak methodology (not inception-peak) — matches Charter §9.2 Rule #4 intent
3. §8.0 ADDED: canonical StrategyHealthCheck state machine specification
4. §14.1: CIO authority distinction (Rules #1/#2 via review_mode can be cleared; Rules #3/#4/#5 auto-decomm cannot be blocked)
5. Coherence sweep for "inception-peak" references

**Downstream actions:**

1. Documentation sync PR (this PR) — adds Playbook pointers to CLAUDE.md, MANIFEST.md, CONTEXT.md, DECISIONS.md, SESSIONS.md, PROJECT_ROADMAP.md.
2. Document 3 (PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) — next authoring mission; sequences Multi-Strat Infrastructure Lift Phases A-B-C-D against the 6 boot strategies' gate timelines.
3. Multi-Strat Infrastructure Lift begins after Doc 3 ratification.

**Review cadence**: Playbook reviewed annually alongside Charter semi-annual reviews (§16.5).

---

## 2026-04-20 — APEX Multi-Strat Aligned Roadmap v3.0 ratified (PR #188 + #189)

**Decision**: Adopt the Multi-Strat Aligned Roadmap as the binding **executional layer** of the APEX Multi-Strat Platform. With this ratification, the Charter-Playbook-Roadmap trilogy is fully canonical on main.

**File**: [`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (v3.0)

**PRs**: #188 (merged 2026-04-20 — Roadmap + 4 ADRs authored at `docs/adr_pending_roadmap_v3/` due to path-protection hook); #189 (merged 2026-04-20 — post-merge fixups: move 4 ADRs to canonical `docs/adr/`, add SUPERSEDED banners to `docs/phases/PHASE_5_SPEC_v2.md` and `docs/PROJECT_ROADMAP.md`, fix Roadmap §10 / §14.2 link paths).

**What the Roadmap binds:**

The Roadmap is the time-ordered execution plan for the 24-month horizon from Charter ratification. It schedules *when* each Charter-mandated deliverable ships and *in what order*, respecting Playbook gate floors (Gate 3 ≥ 8 weeks paper, Gate 4 exactly 60 days ramp) as non-negotiable. Phase A is ready to begin; the remaining phases and six boot strategies are sequenced through month 24 with indicative week windows and documented slip tolerances.

**Key binding content (Roadmap-specific, not in Charter or Playbook):**

1. **Multi-Strat Infrastructure Lift phase schedule** (§2–§5):
   - Phase A (weeks 1–8) — foundational contracts: `strategy_id` on 5 Pydantic models; `Topics.signal_for`; CI `backtest-gate` un-muzzled (closes #102); Redis orphan-read resolution; per-strategy key dual-write; CI coverage gate raise 75→85 scheduled as `[phase-A.13]`.
   - Phase B (weeks 6–14) — `StrategyRunner` ABC at `services/strategies/_base.py`; `LegacyConfluenceStrategy` wraps current S02 unchanged (Principle 6); `StrategyHealthCheck` state machine with 14 transitions; per-strategy S10 dashboard panels.
   - Phase C (weeks 12–22) — `services/portfolio/strategy_allocator/` (Risk Parity Phase 1 + Sharpe overlay dormant); `RiskGuard` ABC + data-driven chain orchestrator; chain extends from 6 steps to 7 steps per Charter §8.2 with `PerStrategyExposureGuard` as STEP 6; chain latency <5ms p99 preserved.
   - Phase D (weeks 18–28) — `services/data/panels/` publishes `PanelSnapshot` on `panel.{universe_id}`; per-strategy feedback-loop partitioning; `backtesting.portfolio_runner.run_portfolio` with `by_strategy_breakdown` + cross-strategy correlation.
   - Phase D.5 (weeks 26–28) — physical topology migration from `services/s01-s10/` to `services/{data,signal,portfolio,execution,research,ops,strategies}/` via 7 staged PRs with `sys.modules`-aliasing import shims; individually revertible.

2. **Six boot strategies' indicative lifecycle ranges** (§6–§8):
   - Strategy #1 Crypto Momentum: Lifecycle Weeks 10-36 → Live Full W37 (~month 8.5).
   - Strategy #2 Trend Following: Lifecycle Weeks 20-50 → Live Full W53 (~month 12).
   - Strategy #3 Mean Rev Equities: Lifecycle Weeks 40-70.
   - Strategy #4 VRP: Weeks 52-86.
   - Strategy #5 Macro Carry: Weeks 64-100.
   - Strategy #6 News-driven: Weeks 76-120 (Live Full beyond 24-month horizon; Roadmap v4.0 rescopes).

3. **Portfolio-level benchmarks calendar-mapped** (§9):
   - Survival (Charter §10.1) candidate at month 9 — Strategy #1 Live Full.
   - Legitimacy (Charter §10.2) candidate at month 15 — Strategies #1 + #2 live; allocator in 2-strategy Risk Parity.
   - Institutional (Charter §10.3) candidate at month 24 — Strategies #1 + #2 + #3 live; Phase 2 Sharpe overlay activation trigger evaluated.

4. **Four ADRs authored alongside** (Charter §12.4):
   - ADR-0007 Strategy as Microservice — formalizes Charter §5.1 (Q1).
   - ADR-0008 Capital Allocator Topology — formalizes Charter §5.2, §6 (Q2 + allocator framework).
   - ADR-0009 Panel Builder Discipline — formalizes Charter §5.3 (Q3).
   - ADR-0010 Target Topology Reorganization — formalizes Charter §5.4 (domain topology + migration procedure).

5. **10-scenario contingency playbook** (§11) — phase slips, Gate failures, allocator inadequacy, multi-strat regressions, repeated stress-test failures, portfolio hard-CB trips during Gate 4, 3-strategies-DEGRADED correlation breakdown, new-candidate pre-emption, operator unavailability, catastrophic >20% loss.

**Supersession on merge**: Roadmap v3.0 supersedes [`docs/phases/PHASE_5_SPEC_v2.md`](../phases/PHASE_5_SPEC_v2.md) and [`docs/PROJECT_ROADMAP.md`](../PROJECT_ROADMAP.md) (SUPERSEDED banners applied via PR #189). Pre-Charter documents remain in-repo for historical reference; active scheduling authority is Roadmap v3.0.

**Participants:**
- CIO: Clement Barbier (ratifier)
- Head of Strategy Research: Claude Opus 4.7 (Roadmap author; ADR-0007/8/9/10 authored alongside)
- Implementation Lead: Claude Code (authored on branch `docs/phase-5-v3-roadmap-document-3`; 5 Copilot review fixes applied in commit `c952e07` — missing audit file added, supersession wording corrected, Phase A coverage language clarified, ADR-0010 shim upgraded to `sys.modules` aliasing, compose paths corrected)

**5 Copilot review fixes applied before merge (PR #188 post-review commit):**

1. FIX 1: Added `docs/audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md` (701 lines; was untracked despite being cited).
2. FIX 2: Roadmap §0.4 wording — "A follow-up PR (post-merge action per §16.1) adds a SUPERSEDED banner" (was "The PR that merges this Roadmap adds").
3. FIX 3: Phase A §2.3 item 3 + new §2.2.6 coverage-gate raise issue `[phase-A.13]` + §2.6 exit criteria.
4. FIX 4: ADR-0010 §D4 shim approach upgraded from re-export to explicit `sys.modules` aliasing preserving submodule paths.
5. FIX 5: ADR-0010 §D4 PR 7 + §7.4 `docker/docker-compose.yml` and `docker/docker-compose.test.yml` (was ambiguous `docker-compose.yml`).

**Downstream actions:**

1. Documentation sync PR (PR #190) — adds Roadmap + 4-ADR pointers to CLAUDE.md, MANIFEST.md, CONTEXT.md, DECISIONS.md, SESSIONS.md. The six one-line cross-refs on ADR-0001 through ADR-0006 are **deferred to a follow-up PR** (blocked by the `docs/adr/` path-protection hook in this authoring session; CIO applies post-merge, ~2 minutes manual work).
2. **Phase A execution begins**: 13 issues `[phase-A.1]` through `[phase-A.13]` opened and assigned per Roadmap §2.2.
3. **Strategy #1 (Crypto Momentum) informal research is in-progress**; Gate 1 PR opens at week ~10 once Phase A §2.2.1/§2.2.2 land.
4. **Quarterly Roadmap reviews scheduled** at months 3, 6, 9, 12, 15, 18, 21, 24 per Roadmap §12.3.
5. **Annual Roadmap revision** at month 12 (v3.1), month 24 (v4.0), month 36 (v5.0) per Roadmap §12.4.

**Review cadence**: Roadmap quarterly execution-progress reviews (§12.3); annual version revision (§12.4); Charter + Playbook semi-annual reviews continue per their governance (Charter §9.6, Playbook §16.5).
