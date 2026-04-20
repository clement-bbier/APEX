> **⚠️ SUPERSEDED on 2026-04-20**
>
> This document is no longer the active source of truth. It is retained for historical reference.
>
> **Active replacement**: [`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
>
> Any work referencing this document should be re-anchored against the active replacement. If this file's content appears to conflict with the active replacement, the active replacement prevails.

---

# PHASE 5 — Live Integration — Specification **v2**

**Status**: ACTIVE — replaces [PHASE_5_SPEC.md](PHASE_5_SPEC.md) v1 as the canonical Phase 5 source of truth.
**Date**: 2026-04-17
**Strategic basis**: [`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md).
**Related ADRs**: ADR-0002 (Quant Methodology Charter), ADR-0005 (Meta-Labeling and Fusion Methodology), ADR-0006 (Fail-Closed Pre-Trade Risk Controls, ACCEPTED 2026-04-17), ADR-0001 (ZMQ Broker Topology — remains ACCEPTED; supersession deferred to Phase 7.5).
**Predecessor**: Phase 4 (closed via PR #147).
**Successor**: Phase 6 (DMA research, advanced regime-switching, multi-asset expansion).

---

> **STATUS: ACTIVE (pre-Charter alignment)** (as of 2026-04-19)
>
> This document is the **current** Phase 5 execution specification. It governs in-flight work (5.1 DONE; 5.2, 5.3, 5.5, 5.4, 5.8, 5.10 pending).
>
> **The APEX Multi-Strat Charter v1.0 was ratified on 2026-04-18** ([docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)). It introduces multi-strategy architectural requirements that will be encoded in a **Phase 5 v3** specification (`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`, pending authoring as Document 3 of the Charter family).
>
> Until Document 3 is ratified:
> - Work scoped in this PHASE_5_SPEC_v2.md that has been started (5.2 Event Sourcing, etc.) continues per its current specification.
> - New work items not yet started should consult the Charter (§5, §6, §7, §8) for architectural target before implementation begins.
> - The Charter REPLACES or EXTENDS the following items (to be rescheduled in Document 3):
>   - The strict 5.2 → 5.3 → 5.5 → 5.4 → 5.8 → 5.10 sequence remains **mostly valid** for their operational content, but a **Multi-Strat Infrastructure Lift** (Phases A-B-C-D, ~5-8 weeks) is prepended to address the P0 gaps identified in [MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) §6.
>
> Document 3 (Phase 5 v3) will formalize the reordering and the infrastructure-lift phases. Until then, this v2 spec remains operational.

---

## 1. Scope summary

Phase 5 bridges the gap between Phase 4's offline ML pipeline and a paper-trading-ready live system. Seven sub-phases on a single strict sequence, one dropped category (infrastructure hardening moved to Phase 7.5).

| Sub-phase | Title | Status |
|---|---|---|
| 5.1 | Fail-Closed Pre-Trade Risk Controls | ✅ DONE (PR #177, 2026-04-17) |
| 5.2 | Event Sourcing / In-Memory State + Required Producers | NEXT |
| 5.3 | Streaming Inference Wiring | PENDING |
| 5.5 | Drift Monitoring & Feedback Loop | PENDING (promoted ahead of 5.4) |
| 5.4 | Short-Side Meta-Labeler + Regime-Conditional Fusion | PENDING |
| 5.8 | Geopolitical NLP Overlay (GDELT 2.0 + FinBERT) | PENDING |
| 5.10 | Phase 5 Closure Report | PENDING |

**Dropped from Phase 5** and moved to Phase 7.5 Infrastructure Hardening ([`PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md`](PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md)):

| Former sub-phase | Title | Rationale |
|---|---|---|
| 5.6 | ZMQ Peer-to-Peer Bus | Premature at solo-operator scale (one host, 10 containers — no SPOF isolation win). |
| 5.7 | SBE / FlatBuffers Serialization | JSON is not the bottleneck at mid-frequency cadence. |
| 5.9 | Rust FFI Hot Path Migration | Defer until live-trading benchmarks prove Python is the bottleneck. |

**Hard dependency chain:**

```
5.1 (DONE)
  ↓
5.2 Event Sourcing + Producers      ← unblocks all downstream; resolves orphan-read trap
  ↓
5.3 Streaming Inference Wiring      ← live alpha path (Phase 4 artifacts → production)
  ↓
5.5 Drift Monitoring                ← safety instrumentation before alpha extension
  ↓
5.4 Short-Side + Regime Fusion      ← alpha extension
  ↓
5.8 Geopolitical NLP (GDELT/FinBERT)
  ↓
5.10 Closure Report  →  Phase 7 Paper Trading
```

---

## 2. Transverse principles (binding on every sub-phase)

1. **Fail-loud heritage** preserved from Phases 3+4 and 5.1. Missing state → `ValueError`. Invalid model card → `ValueError`. Stale heartbeat → `DEGRADED` state transition, never silent continuation.
2. **Decimal / UTC / structlog** — non-negotiable per CLAUDE.md §10. No new code introduces `float` for PnL/capital/exposure; no `datetime.now()` without `timezone.utc`.
3. **No mocks in production, no silent fallbacks.** The Redis writer audit confirmed eight orphan-read keys in S05's pre-trade context. Sub-phase 5.2 resolves this by introducing **real producers**, not by restoring fallback defaults.
4. **Coverage gate**: unit-test coverage ≥ 85% on new code. Integration tests mandatory when a new ZMQ topic or Redis key is added.
5. **Budget discipline**: every sub-phase has a stated LOC / test count / week estimate. Overruns > 25% trigger a re-plan, not silent extension.
6. **ADR bookkeeping**: a new ADR is required whenever a sub-phase crosses a previously decided architectural boundary. ADR-0006 (5.1) is the precedent.

---

## 3. Sub-phase specifications

### 3.1 Sub-phase 5.1 — Fail-Closed Pre-Trade Risk Controls

**Status**: ✅ MERGED 2026-04-17 via PR #177 (commit `1b7c3b5`). Issue #148 CLOSED.

- ADR-0006 ACCEPTED.
- Deliverables: `SystemRiskState` / `SystemRiskStateCause` / `SystemRiskStateChange` / `SystemRiskMonitor` ([core/state.py:365-600](../../core/state.py)), `FailClosedGuard` ([services/s05_risk_manager/fail_closed.py](../../services/s05_risk_manager/fail_closed.py)), `Topics.RISK_SYSTEM_STATE_CHANGE` ([core/topics.py:48](../../core/topics.py)).
- Follow-up observability (S10 subscribe + dashboard endpoint + alert) merged in PR #178 (Batch A of the post-audit execution).
- Residual debt: S05 `service.py` now 530 LOC (SOLID-S). Decomposed in Batch D of the post-audit execution.

Nothing further in v2 scope for 5.1.

---

### 3.2 Sub-phase 5.2 — Event Sourcing / In-Memory State + Required Producers

#### Objective

Eliminate the eight-key Redis batch-read from S05's hot path. Replace with an event-sourced in-memory state machine fed by ZMQ topics. **Crucially, build the producers at the same time** — per the [Redis writer audit](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md), none of the eight keys currently have a production writer.

#### Scope

**IN:**

1. **Producers** (new writers + new ZMQ topics):
   - **`portfolio:capital`** — new `PortfolioTracker` component in S06 (or a lightweight S09 extension) that tracks available + total capital, updated on every fill. Topic: `portfolio.capital` (snapshot) + Redis key refresh.
   - **`pnl:daily`** + **`pnl:intraday_30m`** — new `PnLTracker` component in S09 (existing `trade_analyzer.py` is the natural home). Computes daily and rolling 30-min PnL; writes to Redis keys + emits on `portfolio.pnl` topic.
   - **`portfolio:positions`** — new aggregator reading `positions:{symbol}` hash from S06 (the per-symbol writer already exists) and emitting an aggregated list on `portfolio.position` topic + Redis key `portfolio:positions`. Owner: S09 or S07, to be decided in 5.2 design review.
   - **`session:current`** — S03 `session_tracker.py` gets a Redis persistence shim. Session transitions publish on existing `session.pattern.*` topic AND persist to `session:current`.
   - **`macro:vix_current`** + **`macro:vix_1h_ago`** — S01 `macro_feed.py` persistence shim. Every FRED VIX poll writes `macro:vix_current`; a rolling-snapshot task (new) copies it to `macro:vix_1h_ago` every hour.
   - **`correlation:matrix`** — **OUT OF 5.2 SCOPE.** For 5.2, S05 reads with a fallback to the identity matrix (explicit constant, logged as a 5.2 known gap; blocked-by-issue tracked for 5.5 or Phase 6). This is a deliberate Principle 1 trade-off: correlation is not on the short critical path to live PnL.

2. **Consumer** (`InMemoryRiskState`):
   - New module `services/s05_risk_manager/in_memory_state.py` exposing an `InMemoryRiskState` dataclass keyed by canonical field name (`capital`, `daily_pnl`, `intraday_loss_30m`, `positions`, `session`, `vix_current`, `vix_1h_ago`).
   - `on_message()` handler in S05 updates the state on each topic receipt.
   - Order validation reads **only** from in-memory state — zero network calls, zero `await` in the hot path.

3. **Reconciliation loop** (`services/s05_risk_manager/reconciliation.py`):
   - Every 5 s, compares in-memory state against Redis snapshot (Redis remains the durable store written by producers).
   - Discrepancies > 0.01 % emit `structlog.warning()`.
   - Discrepancies > 1 % transition `SystemRiskState` to `DEGRADED` (5.1 FailClosedGuard rejects 100 % of orders per ADR-0006 §D7).

4. **Staleness timeout**:
   - In-memory state carries a `last_update_ts` per field. If any required field is > 10 s stale, `SystemRiskState` → `DEGRADED`.

5. **New Topics constants** added to [`core/topics.py`](../../core/topics.py):
   - `PORTFOLIO_CAPITAL = "portfolio.capital"`
   - `PORTFOLIO_POSITION = "portfolio.position"`
   - `PORTFOLIO_PNL = "portfolio.pnl"`

6. **S05 SOLID-S refactor** (piggybacks on this sub-phase — from audit ACTION 25 / Batch D originally):
   - Extract `RiskChainOrchestrator`, `ContextLoader` (now feeds from in-memory state, not Redis), `RiskDecisionBuilder`.
   - `service.py` retains only BaseService lifecycle + dispatch.
   - If Batch D lands first, this sub-phase consumes its output.

**OUT (deferred):**

- Correlation matrix writer — 5.5 or Phase 6 (see §3.2 Producers list, `correlation:matrix` item).
- Rust rewrite of S05 — Phase 7.5 (deferred from v1 §3.9).
- Persistent event-log replay — Phase 6.

#### Module structure

```
services/s05_risk_manager/
├── in_memory_state.py           # NEW — InMemoryRiskState dataclass + update handlers
├── reconciliation.py            # NEW — periodic Redis ↔ in-memory comparison
├── chain_orchestrator.py        # NEW — extracted from service.py (Batch D)
├── context_loader.py            # NEW — reads from InMemoryRiskState (not Redis)
├── decision_builder.py          # NEW — approved/blocked constructor
├── service.py                   # MODIFY — slimmed to lifecycle + dispatch

services/s09_feedback_loop/
├── pnl_tracker.py               # NEW — daily + intraday_30m PnL
├── position_aggregator.py       # NEW — positions:{symbol} → portfolio:positions

services/s06_execution/
├── portfolio_tracker.py         # NEW — capital on-fill updates

services/s03_regime_detector/
├── session_tracker.py           # MODIFY — add Redis persistence shim

services/s01_data_ingestion/
├── macro_feed.py                # MODIFY — persist macro:vix_current; rolling-snapshot task

core/topics.py                   # MODIFY — add PORTFOLIO_* topics

tests/unit/services/s05_risk_manager/
├── test_in_memory_state.py      (~20 tests)
├── test_reconciliation.py       (~14 tests)
├── test_chain_orchestrator.py   (~16 tests)
├── test_context_loader.py       (~10 tests)
├── test_decision_builder.py     (~10 tests)

tests/unit/services/s06_execution/test_portfolio_tracker.py     (~10)
tests/unit/services/s09_feedback_loop/test_pnl_tracker.py       (~14)
tests/unit/services/s09_feedback_loop/test_position_aggregator.py  (~10)
tests/unit/services/s03_regime_detector/test_session_redis_shim.py  (~8)
tests/unit/services/s01_data_ingestion/test_macro_feed_redis.py    (~10)

tests/integration/
├── test_event_sourcing_convergence.py  (~8 tests)
```

#### Algorithm notes

- **In-memory state update**: on each ZMQ topic receipt, the handler mutates a single field and refreshes `last_update_ts`. No locking required because S05 uses single-threaded asyncio.
- **Order validation hot path**: zero `await` calls, zero network I/O. Pure dict reads + Decimal arithmetic. Target P99 latency < 100 µs (post-decomposition).
- **Reconciliation**: every 5 s, read all eight Redis keys, compare against in-memory. Use `Decimal` tolerance 0.01 % for financial fields; exact equality for enums (`Session`). Drift > 1 % = critical.
- **Correlation matrix fallback**: if `correlation:matrix` is absent, use `numpy.eye(n)` scaled to unit correlation (i.e., all pairs uncorrelated). Log the fallback at `structlog.warning()` level on every risk check; add a `correlation_fallback_active` boolean to every `risk.audit` event. **This is NOT a silent fallback** — it is an explicit, logged, observable design decision with a tracked issue for future closure.

#### Criteria — Definition of Done

1. **Orphan-read resolved** — all eight keys have a production writer or an explicit documented fallback (correlation only). Grep audit in CI confirms.
2. **Benchmark**: P99 order validation latency < 100 µs (profiler confirms zero socket/Redis calls in `process_order_candidate` hot path).
3. **Convergence test**: after 1000 simulated fills injected into the producers, in-memory state matches Redis within Decimal(0.0001) tolerance.
4. **Staleness test**: stopping a producer causes `SystemRiskState` → `DEGRADED` within 11 s (10 s staleness + 1 s scheduler slack). Every `OrderCandidate` subsequently rejected.
5. **S05 service.py reduced to ≤ 200 LOC** after decomposition; each extracted class ≤ 250 LOC, all unit-testable in isolation.
6. **mypy --strict clean**, **ruff clean**, **unit test coverage ≥ 90%** on new S05 modules, **≥ 85%** on new producer modules.
7. **New Topics constants added to [core/topics.py](../../core/topics.py)**.
8. **Integration test**: full loop from `order.filled` → `portfolio.capital` producer → S05 in-memory update → next `OrderCandidate` sees updated capital.

#### Dependencies

- 5.1 merged ✅.
- S05 `service.py` SOLID-S refactor (overlaps with Batch D of the post-audit execution; whichever lands first, the other rebases).

#### Estimated scope

- LOC: ~900–1,200 (producers + consumer + reconciliation + tests).
- Tests: ~130.
- Complexity: **high** (multi-service change; reconciliation is subtle).
- Estimated weeks: **2**.
- Copilot review cycles: 3.

#### References

- Martin Thompson, "Mechanical Sympathy".
- LMAX Disruptor pattern.
- ADR-0006 (5.1 fail-closed contract; the in-memory state must remain consistent with that contract).
- CLAUDE.md §3 (continuous adaptation), §5 (hot-path allocations).
- [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md).

---

### 3.3 Sub-phase 5.3 — Streaming Inference Wiring

#### Objective

Wire Phase 4's trained Meta-Labeler and IC-weighted Fusion into the live S02 → S04 tick path. Phase 3 calculators transition from batch-only to streaming. Reinstate G7 as a blocking gate on real market data.

#### Scope

**IN:**

- `services/s02_signal_engine/streaming_adapter.py` — new per-tick wrapper around Phase 3 calculators. Each calculator that supports incremental computation exposes `compute_incremental(new_bar, evicted_bar | None) -> features`. Calculators without an incremental interface fall back to bounded-window batch `compute()`, with documented window size + P99 latency evidence.
- `services/s02_signal_engine/pipeline.py` — SOLID-S decomposition (per-stage classes) — prerequisite from Batch D.
- `services/s04_fusion_engine/live_meta_labeler.py` — loads persisted `.joblib` model + `.json` model card at startup. Strict card validation: if invalid or mismatched SHA, S04 **refuses to start** (fail-loud; no fallback to deterministic scorer).
- `services/s04_fusion_engine/live_fusion.py` — IC-weighted fusion in streaming mode. Reads frozen weights from the persisted `ICWeightedFusionConfig`.
- `services/s04_fusion_engine/service.py` — per-tick `predict_proba → 2p-1 Kelly bet-size → OrderCandidate` publishes on `order.candidate`. Redis key `meta_label:latest:{symbol}` updated live (for S05 `MetaLabelGate` consumption).
- **G7 gate reinstated as blocking on real data.** If G7 fails during live operation, the deployment is halted; model must be retrained or feature set expanded.
- **CVDKyle vectorization (#115)** — prerequisite. The loops at `features/calculators/cvd_kyle.py:306, 361, 408` are on the streaming hot path.

**OUT (deferred):**

- Short-side (`direction = -1`) — 5.4.
- Regime-conditional weights — 5.4.
- Drift monitoring — 5.5.
- Rust hot path — Phase 7.5.

#### Module structure

```
services/s02_signal_engine/
├── streaming_adapter.py         # NEW — incremental calculator wrapper
├── pipeline.py                  # DECOMPOSED (from Batch D)
├── stages/                      # NEW — step classes per Batch D

services/s04_fusion_engine/
├── live_meta_labeler.py         # NEW
├── live_fusion.py               # NEW
├── service.py                   # MODIFY

features/calculators/
├── cvd_kyle.py                  # MODIFY — vectorize loops at :306, :361, :408 (issue #115)

tests/unit/services/s02_signal_engine/test_streaming_adapter.py   (~18)
tests/unit/services/s04_fusion_engine/test_live_meta_labeler.py   (~14)
tests/unit/services/s04_fusion_engine/test_live_fusion.py         (~10)
tests/unit/features/calculators/test_cvd_kyle_vectorized.py       (~6)
tests/integration/test_streaming_pipeline.py                      (~10)
```

#### Algorithm notes

- **Streaming adapter** wraps each calculator in a stateful rolling-window context. On each tick, pushes new bar → updates state → emits only the derived feature(s). Never recomputes full window on every tick unless the calculator explicitly opts in via `USE_BATCH_FALLBACK = True` with documented window size.
- **Model card validation at S04 startup** — mandatory `ModelCardV1.validate()` call; missing fields → `ValueError`; mismatched dataset SHA → `ValueError`. Card schema defined in `features/meta_labeler/model_card.py`.
- **Kelly bet-size** — `bet_size = 2 * predict_proba - 1`, clamped to configured bounds (per ADR-0005 D8). Published to Redis `meta_label:latest:{symbol}` within 5 ms of each tick.
- **G7 reinstated**: on real data, if RF AUC − LogReg AUC < 0.03 over a rolling 200-label window, S04 emits `feedback.drift.critical` and halts new `OrderCandidate` emission.

#### Criteria — Definition of Done

1. Per-tick latency < 1 ms P99 for full signal → fusion → bet-size path (synthetic stream).
2. Redis `meta_label:latest:{symbol}` updated within 5 ms of each tick (P99).
3. Model card validation at S04 startup — missing/invalid card prevents launch (integration test with corrupted card).
4. 1000-tick synthetic stream produces bet-sizes matching batch computation within floating-point tolerance.
5. CVDKyleCalculator vectorized; benchmark shows ≥ 10× speedup on 500-bar windows.
6. All tests pass; coverage ≥ 88% on new modules.
7. mypy --strict + ruff clean.

#### Dependencies

- 5.2 merged (in-memory risk state is the validation target of S05 feeding from S04).
- Batch D decomposition of S02 `pipeline.py` (or concurrent).
- Issue #115 (CVDKyle vectorization) resolved as part of 5.3.
- Issue #123 (streaming calculators) resolved as part of 5.3.

#### Estimated scope

- LOC: ~700–1,000.
- Tests: ~58.
- Complexity: **high**.
- Estimated weeks: **3**.
- Copilot review cycles: 3.

#### References

- ADR-0005 D6, D7, D8.
- Phase 4 closure report §5.1.
- GitHub issues #123, #115.

---

### 3.4 Sub-phase 5.5 — Drift Monitoring & Feedback Loop (PROMOTED AHEAD OF 5.4)

#### Objective

Detect feature drift, calibration degradation, and signal decay in real time. When drift crosses thresholds, S09 publishes alerts and can trigger S05 Kelly reduction or recalibration.

**Why before 5.4**: 5.4 extends the model (short-side, regime-conditional). Without drift instrumentation in place first, the extension's impact on production is unobservable. Ship safety before alpha per Principle 1.

#### Scope

**IN:**

- `services/s09_feedback_loop/drift_monitor.py` — new module implementing:
  - **PSI (Population Stability Index)** on rolling 500-bar windows vs training distribution. PSI > 0.10 = warning, PSI > 0.25 = critical.
  - **Rolling AUC** on last 200 realized labels (from Triple Barrier t1 outcomes). If below G1 (0.55) for 3 consecutive windows → critical.
  - **Brier score calibration divergence** on rolling window. If > G5 (0.25) → critical.
- `services/s09_feedback_loop/alert_engine.py` — new module publishing `feedback.drift.critical` and `feedback.recalibration.requested` topics on threshold breach.
- S05 `MetaLabelGate` extension: subscribes to `feedback.drift.critical` and applies Kelly × 0.5 defensive multiplier until manual reset (or automatic recalibration in Phase 6).
- New Topics constants in `core/topics.py`: `FEEDBACK_DRIFT_CRITICAL = "feedback.drift.critical"`, `FEEDBACK_RECALIBRATION_REQUESTED = "feedback.recalibration.requested"`.

**OUT:**

- Automatic retraining — Phase 6.
- A/B testing / champion-challenger — Phase 6.

#### Module structure

```
services/s09_feedback_loop/
├── drift_monitor.py             # NEW — PSI + rolling AUC + Brier
├── alert_engine.py              # NEW — threshold-based publisher
├── service.py                   # MODIFY — integrate drift monitor

services/s05_risk_manager/
├── meta_label_gate.py           # MODIFY — Kelly × 0.5 on drift.critical

core/topics.py                   # MODIFY — FEEDBACK_* constants

tests/unit/services/s09_feedback_loop/test_drift_monitor.py   (~20)
tests/unit/services/s09_feedback_loop/test_alert_engine.py    (~10)
tests/integration/test_drift_feedback_loop.py                 (~8)
```

#### Algorithm notes

- **PSI**: standard industry formula `sum_i (actual_pct_i − expected_pct_i) * ln(actual_pct_i / expected_pct_i)` over 10 deciles.
- **Rolling AUC**: computed on realized labels from completed Triple Barrier events (where `t1` has elapsed).
- **Kelly de-risking**: `kelly_adj = kelly * 0.5` when `drift.critical` event received within last 5 min. Manual-reset admin endpoint exposed via S10 `/api/v1/risk/drift-reset` (confirmation token required per S10 security model).
- **Recalibration trigger**: emits the current model card hash + drift metrics; a future Phase 6 orchestrator consumes this to schedule retraining. For 5.5 MVP: logs only, no consumer.

#### Criteria — Definition of Done

1. PSI detects a synthetic 1 σ mean shift (injected test) → PSI > 0.25 within 1 window.
2. Rolling AUC degradation detected within 3 consecutive windows of synthetic model decay.
3. Kelly × 0.5 applied within 100 ms of `drift.critical` receipt (integration test).
4. Topics registered; mypy --strict clean; ruff clean.
5. Coverage ≥ 90 %.

#### Dependencies

- 5.3 merged (live predictions required to monitor).

#### Estimated scope

- LOC: ~500–700.
- Tests: ~38.
- Complexity: **medium**.
- Estimated weeks: **2**.
- Copilot review cycles: 2.

#### References

- Tsay (2010) Ch. 2 (time-varying parameters).
- PSI methodology (credit-risk industry standard).
- Phase 4 closure §5.2.

---

### 3.5 Sub-phase 5.4 — Short-Side Meta-Labeler + Regime-Conditional Fusion

#### Objective

Extend the Meta-Labeler to `direction ∈ {+1, −1}` and implement regime-conditional fusion weights that adapt to the current volatility regime detected by S03.

#### Scope

**IN:**

- `features/labeling/triple_barrier_binary.py` — `direction = -1` support (upper barrier = stop-loss, lower barrier = take-profit; binary target flips).
- `features/meta_labeler/feature_builder.py` — add `direction_code` (±1) as a 9th feature.
- `features/meta_labeler/baseline.py` — train direction-aware model (single model with `direction_code` feature — senior-quant tie-breaker: simpler than two separate models).
- `features/fusion/regime_conditional.py` — new `RegimeConditionalFusion` holding N frozen weight vectors (one per regime state: LOW / NORMAL / HIGH / CRISIS). S03's regime selects the active weight vector at each tick.
- `features/fusion/ic_weighted.py` — extend with regime-stratified IC reports.
- Transition smoothing at regime boundaries: linear blend over 5-bar window to avoid whipsaw.
- CPCV validation of the short-side model; G1–G6 gates must pass on a synthetic directional-alpha scenario.

**OUT:**

- Multi-asset options hedging — Phase 11.

#### Module structure

```
features/labeling/
├── triple_barrier_binary.py     # MODIFY — direction=-1 support

features/meta_labeler/
├── feature_builder.py           # MODIFY — direction_code feature
├── baseline.py                  # MODIFY — direction-aware training

features/fusion/
├── regime_conditional.py        # NEW — regime-aware weight switching
├── ic_weighted.py               # EXTEND — per-regime IC

tests/unit/features/labeling/test_short_side_labeling.py       (~14)
tests/unit/features/meta_labeler/test_short_side_model.py      (~16)
tests/unit/features/fusion/test_regime_conditional.py          (~18)
```

#### Criteria — Definition of Done

1. Short-side model passes G1–G6 on synthetic directional-alpha scenario.
2. Regime-conditional fusion Sharpe ≥ global-fusion Sharpe on multi-regime synthetic scenario.
3. Regime transition smoothing — no fusion-score jumps > 2 σ across boundaries.
4. mypy --strict clean; ruff clean; coverage ≥ 90 %.

#### Dependencies

- 5.3 merged (streaming pipeline for live regime-conditional switching).
- 5.5 merged (drift instrumentation ready to observe the extension's impact).

#### Estimated scope

- LOC: ~500–700.
- Tests: ~48.
- Complexity: **medium–high**.
- Estimated weeks: **2**.
- Copilot review cycles: 2–3.

#### References

- López de Prado (2018) §3.4.
- ADR-0005 D1.
- Phase 4 closure §5.2.

---

### 3.6 Sub-phase 5.8 — Geopolitical NLP Overlay (GDELT 2.0 + FinBERT substitute)

#### Objective

Real-time geopolitical-risk scoring pipeline using open-source substitutes for the original proprietary WorldMonitor gRPC spec. Risk score modulates Kelly bet-sizing in S04 and can VETO orders in S05.

**Principle 3 substitute justification**: the v1 spec assumed a paid `WorldMonitorConnector`. The operator has no budget for this. GDELT 2.0 (free, public, event-coded, 15-min cadence, 300 languages) + FinBERT (open-source, ONNX-compilable, CPU-inferable) provides an institutional-grade equivalent at $0/month.

#### Scope

**IN:**

- `services/s01_data_ingestion/connectors/gdelt.py` — new HTTP/CSV connector for GDELT 2.0 events feed (GKG + EVENT). Polls every 15 min. Publishes on `macro.geopolitics.raw` topic.
- `services/s08_macro_intelligence/nlp/finbert_scorer.py` — FinBERT compiled to ONNX Runtime for CPU inference (no GPU required). Inference in isolated subprocess (no broker-key access). P99 < 50 ms per chunk.
- `services/s08_macro_intelligence/nlp/model_card_nlp.json` — governance model card documenting bias, inference P99, model size.
- `GeopoliticalRiskScore [-1.0, 1.0]` persisted to TimescaleDB with point-in-time semantics.
- `services/s04_fusion_engine/service.py` — Kelly penalty on negative geo_score (asymmetric: `geo_score > 0` does NOT increase Kelly).
- `services/s05_risk_manager/geopolitical_guard.py` — new guard in the risk chain. `geo_score == -1.0` → VETO all orders. NLP heartbeat absent > 60 s → `SystemRiskState.DEGRADED` (reuses ADR-0006 pattern).
- New Topics constants: `MACRO_GEOPOLITICS_RAW = "macro.geopolitics.raw"`, `MACRO_GEOPOLITICS_SCORE = "macro.geopolitics.score"`.

**OUT:**

- Custom LLM fine-tuning — Phase 6 (or Phase 11 if budget allows).
- Satellite imagery — Phase 11.
- Multi-language NLP — Phase 11 (FinBERT is English-first; GDELT already does cross-language event coding).

#### Module structure

```
services/s01_data_ingestion/
├── connectors/
│   └── gdelt.py                 # NEW — HTTP/CSV GDELT 2.0 feed

services/s08_macro_intelligence/
├── nlp/
│   ├── finbert_scorer.py        # NEW — ONNX Runtime wrapper
│   ├── model_card_nlp.json      # NEW — governance card
│   └── __init__.py

services/s04_fusion_engine/
├── service.py                   # MODIFY — Kelly penalty on geo_score

services/s05_risk_manager/
├── geopolitical_guard.py        # NEW

core/topics.py                   # MODIFY — MACRO_GEOPOLITICS_* constants

tests/unit/services/s01_data_ingestion/test_gdelt_connector.py    (~12)
tests/unit/services/s08_macro_intelligence/test_finbert_scorer.py  (~16)
tests/unit/services/s05_risk_manager/test_geopolitical_guard.py   (~12)
tests/integration/test_geopolitical_pipeline.py                   (~10)
```

#### Algorithm notes

- **Latency budget**: geopolitical event ingested in S01 → S05 BLOCKED state in < 250 ms end-to-end.
- **FinBERT ONNX**: compiled via `onnxruntime`; fallback to CPU if GPU unavailable. P99 < 50 ms per text chunk on modern laptop CPU.
- **Score mapping**: FinBERT logits → softmax → weighted sum into `[-1.0, 1.0]`. Storage: TimescaleDB with point-in-time `score_as_of` column.
- **Kelly penalty**: `kelly_adj = kelly * max(0, 1 + geo_score)` where `geo_score ∈ [-1, 0]` reduces Kelly linearly; `geo_score > 0` treated as 0 (asymmetric, conservative).
- **Guard VETO**: `geo_score <= -0.99` → `RiskDecision(approved=False, reason=GEOPOLITICAL_EVENT_BLOCK)`.
- **Heartbeat**: S08 NLP worker writes to `macro:nlp_heartbeat` every 10 s with TTL 60 s. S05 guard checks this key; missing → `DEGRADED`.

#### Criteria — Definition of Done

1. **Latency test**: event → BLOCKED in < 250 ms.
2. **Model card** documents bias metrics, inference P99, model size.
3. **Backtest**: ≥ 15 % MDD reduction on ex-post crisis periods (COVID-03/2020, Ukraine-02/2022).
4. **Topics registered**; mypy --strict clean; ruff clean; coverage ≥ 88 %.
5. **$0/month operational cost verified** (GDELT free tier + FinBERT open-source + CPU-only inference).

#### Dependencies

- 5.3 merged (live pipeline for overlay integration).
- 5.5 merged (drift instrumentation in place).

#### Estimated scope

- LOC: ~800–1,200 (connector + scorer + guard + tests).
- Tests: ~50.
- Complexity: **high**.
- Estimated weeks: **3**.
- Copilot review cycles: 3.

#### References

- Kelly, B. et al., "Text as Data" (JFE).
- GDELT Project 2.0 (https://www.gdeltproject.org/).
- FinBERT (https://github.com/ProsusAI/finBERT).
- ADR-0006 (fail-closed pattern reuse).

---

### 3.7 Sub-phase 5.10 — Phase 5 Closure Report

#### Objective

Mirror of PR #147 (Phase 4 closure) for Phase 5. Document sub-phase inventory, final benchmarks, Phase 6+ prerequisites, and paper-trading readiness assessment.

#### Scope

- `docs/phase_5_closure_report.md` — new, 10-section closure report.
- `docs/claude_memory/CONTEXT.md` — refreshed.
- `docs/claude_memory/PHASE_5_NOTES.md` — new, archival notes.
- `docs/claude_memory/SESSIONS.md` — final Phase 5 session entry.
- CHANGELOG.md — entries for 5.2/5.3/5.5/5.4/5.8.

#### Content

- Sub-phase inventory (5.1 / 5.2 / 5.3 / 5.5 / 5.4 / 5.8) with PR numbers, LOC, test counts.
- Latency + throughput benchmarks (order validation P99, streaming P99, NLP P99).
- Safety audit: Fail-Closed verification, drift-instrumentation sample events, GeopoliticalGuard unit tests.
- Phase 7 (paper trading) prerequisites checklist.
- Deferred-to-Phase-7.5 backlog summary.

#### DoD

1. Closure report committed.
2. Memory files updated.
3. All CI jobs green on closure branch.
4. Paper-trading entry criteria satisfied (capital seeded, producers running, drift baseline captured).

#### Estimated scope

- LOC: N/A (docs only).
- Complexity: **low**.
- Estimated weeks: **1**.

---

## 4. Sub-phase tracking table

| Sub-phase | Issue | Branch | Status |
|---|---|---|---|
| 5.1 Fail-Closed Pre-Trade Risk | #148 (CLOSED) | `phase-5/fail-closed` (merged) | ✅ DONE |
| 5.2 Event Sourcing + Producers | #149 (to retitle `[phase-5.2]` in Batch E) | `phase-5/event-sourcing` | NEXT |
| 5.3 Streaming Inference | #123 (relabeled in Batch E) | `phase-5/streaming-inference` | PENDING |
| 5.5 Drift Monitoring | #157 | `phase-5/drift-monitoring` | PENDING |
| 5.4 Short-Side + Regime Fusion | #156 | `phase-5/short-side-regime` | PENDING |
| 5.8 Geopolitical NLP | #153 (to retitle `[phase-5.8]` in Batch E) | `phase-5/gdelt-finbert` | PENDING |
| 5.10 Closure Report | #158 | `chore/phase-5-closure` | PENDING |

---

## 5. Cross-cutting concerns

### 5.1 Fail-loud heritage

All sub-phases preserve the fail-loud pattern. No silent fallbacks; explicit fallbacks (correlation matrix identity) are logged on every event.

### 5.2 CI contract

Phase 5 inherits the current CI pipeline:

1. `quality` — ruff + mypy strict + bandit.
2. `rust` — cargo test + maturin build.
3. `unit-tests` — pytest, coverage ≥ 85%.
4. `integration-tests` — full pipeline with Redis.
5. `backtest-gate` — **MUZZLED pending issue #102** (Batch A Tech Finding 3). Target thresholds to be restored to Sharpe ≥ 0.8, max DD ≤ 8 % after #102 merges.

### 5.3 Security

- S06 execution: 5.1 Fail-Closed guard ensures no orders pass through degraded state.
- NLP model (5.8): isolated subprocess, no broker-key access.
- All new producers (5.2): Redis keys scoped by namespace; no cross-service secret exposure.

### 5.4 UTC / Decimal / structlog — non-negotiable

Inherited from CLAUDE.md §2/§10. Every PR grep-audited in CI.

### 5.5 Deferred to Phase 7.5 (explicit acknowledgement)

Phase 5 v2 does **not** ship the following; see [`PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md`](PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md):

- ZMQ Peer-to-Peer bus (former 5.6).
- SBE / FlatBuffers zero-copy serialization (former 5.7).
- Rust FFI hot path migration (former 5.9).

The operator explicitly acknowledges this trade-off: live paper trading begins without these; if Phase 8 live-trading benchmarks demonstrate bottlenecks, Phase 7.5 is revisited.

---

## 6. Risks (updated post-audit)

| Risk | Impact | Mitigation |
|---|---|---|
| Orphan-read producers (5.2) introduce new bugs | Fail-closed rejects legitimate orders | Reconciliation loop + staleness timeout + integration test suite. |
| Correlation-matrix identity fallback masks concentration risk | Position sizing under-conservative | Logged on every risk event; issue tracked for 5.5 or Phase 6 closure. |
| S05 SRP refactor breaks 5.1 chain semantics | Silent change in fail-closed behavior | Port test suite unchanged; regression tests required before merge. |
| Streaming adapter P99 > 1 ms budget (5.3) | Bet-size stale by next tick | CI latency gate; calculator-by-calculator benchmarks before live path. |
| FinBERT hallucination triggers spurious VETO (5.8) | Missed trades during false positives | Score confidence threshold; manual-review panel in S10; VETO requires `geo_score ≤ -0.99`. |
| Drift monitor false positives (5.5) | Unnecessary Kelly de-risking | Manual reset endpoint; 3-consecutive-window requirement for critical. |
| Phase 5 scope creep (again) | Delays paper trading | This v2 spec is the scope; any additions require new ADR + PHASE_5_SPEC_v3. |

---

## 7. Phase 6 preview (out of scope, context only)

- **#154 DMA Research** — Dynamic Model Averaging vs Meta-Labeling (pure research).
- **Automatic retraining pipeline** — orchestrated by `feedback.recalibration.requested` from 5.5.
- **A/B / champion-challenger** model testing.
- **Correlation-matrix production writer** (deferred from 5.2).
- **Multi-asset expansion** preparatory work.

---

## 8. References

### Project

- [`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) (strategic basis).
- [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md) (5.2 prerequisite evidence).
- [`docs/adr/ADR-0006-fail-closed-risk-controls.md`](../adr/ADR-0006-fail-closed-risk-controls.md).
- Phase 4 closure: [`docs/phase_4_closure_report.md`](../phase_4_closure_report.md).
- Phase 3 closure: [`docs/phase_3_closure_report.md`](../phase_3_closure_report.md).
- CLAUDE.md; MANIFEST.md.

### Academic

- López de Prado, M. (2018), *Advances in Financial Machine Learning*, Wiley.
- Martin Thompson, "Mechanical Sympathy".
- LMAX Disruptor.
- Kelly, B. et al., "Text as Data" (JFE).
- Tsay, R. (2010), *Analysis of Financial Time Series*, Wiley.

### Industry / tools

- SEC Rule 15c3-5 (Market Access Rule).
- Knight Capital 2012 post-mortem.
- GDELT Project 2.0 (https://www.gdeltproject.org/).
- FinBERT (https://github.com/ProsusAI/finBERT).
- ONNX Runtime (https://onnxruntime.ai/).

---

**END OF PHASE_5_SPEC_v2.**
