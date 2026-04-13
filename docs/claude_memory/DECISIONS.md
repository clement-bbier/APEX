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
