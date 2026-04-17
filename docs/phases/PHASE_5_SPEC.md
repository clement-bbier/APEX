> **⚠️ SUPERSEDED — 2026-04-17**
>
> This v1 specification (9 sub-phases, three tracks) is superseded by
> [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md), which is the canonical source of truth
> for Phase 5 as of 2026-04-17.
>
> **v2 differences**:
> - Sub-phases 5.6 (ZMQ P2P), 5.7 (SBE/FlatBuffers), 5.9 (Rust FFI) are **dropped** from Phase 5
>   and moved to [`PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md`](PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md).
> - Remaining sub-phases re-sequenced: **5.1 (DONE) → 5.2 → 5.3 → 5.5 → 5.4 → 5.8 → 5.10**.
> - Sub-phase 5.8 substitutes GDELT 2.0 + FinBERT for the proprietary WorldMonitor gRPC feed.
> - Sub-phase 5.2 expanded to include **producer writers** for the eight orphan-read S05 context keys.
>
> **Rationale**: see [`STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md).
> This v1 document is preserved as historical design record; do not act on it.

---

# PHASE 5 — Live Integration & Infrastructure Hardening — Specification

**Status**: v1 — SUPERSEDED by [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md).
Design-gate merged 2026-04-16 (PR #155). Sub-phase 5.1 Fail-Closed
merged 2026-04-17 (PR #177; issue #148 closed). Sub-phases 5.6 (ZMQ
P2P), 5.7 (SBE/FlatBuffers), and 5.9 (Rust FFI Hot Path) are
**dropped from Phase 5 scope** and moved to a new Phase 7.5
Infrastructure Hardening backlog per
[`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md).
Remaining sub-phases re-sequenced as 5.1 (DONE) → 5.2 → 5.3 → 5.5 →
5.4 → 5.8 → 5.10. **REVISION NOTE**: This v1 document stays as the
historical design record for the 9-sub-phase proposal; the canonical
active spec is [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md).

**Related ADRs**: ADR-0002 (Quant Methodology Charter), ADR-0005
(Meta-Labeling and Fusion Methodology), ADR-0006 (Fail-Closed
Pre-Trade Risk Controls — accepted 2026-04-17), ADR-0001 (ZMQ Broker
Topology — remains ACCEPTED; §3.6 supersession deferred to Phase 7.5).
**Branch**: `design-gate/phase-5` (merged).
**Predecessor**: Phase 4 (closed via PR #147).
**Successor**: Phase 6 (Alpha Generation — DMA, advanced
regime-switching, multi-asset expansion).

---

## 1. Objective

Phase 5 bridges the gap between Phase 4's **offline** ML pipeline and
a **production-grade live trading system**. It addresses three pillars:

1. **Safety-first hardening** — transition S05 from Fail-Open to
   Fail-Closed, eliminate all heuristic fallback values, and implement
   in-memory event-sourced state for deterministic risk decisions
   without network I/O on the hot path.
2. **Live wiring** — stream Phase 4's Meta-Labeler and IC-weighted
   fusion into the real-time S02 → S04 pipeline, add short-side
   capability, regime-conditional weights, and continuous drift
   monitoring via S09.
3. **Infrastructure hardening** — remove the ZMQ broker SPOF,
   migrate the hot-path serialization from JSON to zero-copy binary
   (SBE/FlatBuffers), integrate geopolitical NLP risk overlay, and
   prepare the Rust FFI bridge for nanosecond-grade execution.

Phase 5 is **not** a research phase. Every sub-phase delivers
production code with full CI coverage.

**Hard dependency chains:**

```
Track A — Safety & Live Integration (sequential)
5.1 Fail-Closed Pre-Trade Risk
      ↓
5.2 Event Sourcing / In-Memory State
      ↓
5.3 Streaming Inference Wiring
      ↓
5.4 Short-Side Meta-Labeler + Regime-Conditional Fusion
      ↓
5.5 Drift Monitoring & Feedback Loop

Track B — Infrastructure Hardening (sequential, can start after 5.2)
5.6 ZMQ Peer-to-Peer Bus
      ↓
5.7 SBE / FlatBuffers Serialization

Track C — Intelligence & Performance (parallel after 5.3)
5.8 Alt Data NLP — Geopolitical Risk Overlay
5.9 Rust FFI Hot Path Migration

Closure
5.10 Phase 5 Closure Report
```

Track A is **strictly sequential** — each sub-phase builds on the
previous. Track B can start once 5.2 is merged (the event-sourcing
architecture defines the new bus contract). Track C sub-phases are
independent of each other and require only that the core pipeline
(5.3) is stable.

**DMA Research (#154) is explicitly OUT OF SCOPE** for Phase 5.
It remains in the backlog for Phase 6 (pure research, no production
impact). This is a deliberate scope-control decision to keep Phase 5
focused on production readiness.

---

## 2. Prerequisites from Phase 4 Closure

Per `docs/phase_4_closure_report.md` §5–§6, these items were
identified as Phase 5 work:

| Item | Phase 5 sub-phase | Source |
|---|---|---|
| Streaming inference for Phase 3 calculators | 5.3 | #123, Phase 4 closure §5.1 |
| Drift monitoring | 5.5 | Phase 4 closure §5.2 |
| Short-side Meta-Labeler | 5.4 | Phase 4 closure §5.2 |
| Regime-conditional fusion weights | 5.4 | Phase 4 closure §5.2 |
| G7 reinstated as blocking on real data | 5.3 | Phase 4 closure §2 |

Additionally, 7 new GitHub issues (#148–#154) were created from the
Phase 4 backlog analysis. Their mapping:

| Issue | Title | Sub-phase |
|---|---|---|
| #148 | Fail-Open → Fail-Closed | 5.1 |
| #149 | Event Sourcing / In-Memory State | 5.2 |
| #123 | Streaming calculators | 5.3 |
| #150 | ZMQ P2P Bus | 5.6 |
| #151 | SBE Serialization | 5.7 |
| #152 | Rust FFI Hot Path | 5.9 |
| #153 | Alt Data NLP | 5.8 |
| #154 | DMA Research | OUT OF SCOPE (Phase 6) |

---

## 3. Sub-phase specifications

---

## 3.1 Sub-phase 5.1 — Fail-Closed Pre-Trade Risk Controls

### Objective
Transition S05 Risk Manager from Fail-Open (heuristic default values
on Redis failure) to Fail-Closed (immediate order rejection on any
state unavailability). This is the **non-negotiable safety
foundation** for all subsequent Phase 5 work.

### Scope
- **IN**: Remove all `_safe()` heuristic fallback values for Capital,
  Exposure, and PnL in S05; create `SystemRiskState` with explicit
  `HEALTHY | DEGRADED | UNAVAILABLE` enum; `process_order_candidate`
  returns `REJECTED_SYSTEM_UNAVAILABLE` in O(1) when state is not
  `HEALTHY`; structured critical logging to S10; chaos engineering
  test suite; ADR-0006 documenting the Fail-Closed pattern.
- **OUT**: Event-sourcing architecture (→ 5.2); performance
  optimization (→ 5.2); Rust rewrite of S05 (→ 5.9).

### Module structure
```
core/
├── state.py                   # SystemRiskState enum + state machine (EXTEND)

services/s05_risk_manager/
├── service.py                 # MODIFY — remove _safe(), add state check
├── fail_closed.py             # NEW — FailClosedGuard, state monitor

docs/adr/
├── ADR-0006-fail-closed-risk-controls.md  (NEW)

tests/unit/services/s05_risk_manager/
├── test_fail_closed.py        (~20 tests)
├── test_service_no_fallbacks.py  (~15 tests)

tests/integration/
├── test_fail_closed_chaos.py  (~8 tests)
```

### Algorithm notes
- The `FailClosedGuard` wraps every `process_order_candidate` call.
  If `SystemRiskState != HEALTHY`, the guard short-circuits in O(1)
  with `RiskDecision(status=REJECTED_SYSTEM_UNAVAILABLE)`.
- Redis heartbeat check: S05 reads a `risk:heartbeat` key with TTL
  5s. If the key is absent or stale, state transitions to `DEGRADED`.
  If Redis is unreachable (connection error), state transitions to
  `UNAVAILABLE`.
- **No graceful degradation**: there is no "partial risk" mode.
  Either all critical metrics (capital, exposure, PnL, position
  limits) are available, or 100% of orders are rejected. This is
  the SEC 15c3-5 mandate.
- Every rejection emits a `structlog.critical()` event with
  `rejection_reason`, `state`, and `timestamp_utc`. S10 dashboard
  consumes this via ZMQ topic `risk.system.state_change`.

### Criteria — Definition of Done
1. Chaos test: Redis killed mid-test → 100% of incoming
   `OrderCandidate` rejected within < 1ms.
2. Zero heuristic fallback values remain in S05 for Capital,
   Exposure, or PnL (verified by grep audit in CI).
3. ADR-0006 committed and referenced by code.
4. All unit + integration tests passing, coverage ≥ 90% on new code.
5. `mypy --strict` clean, `ruff` clean.
6. New ZMQ topic `risk.system.state_change` registered in
   `core/topics.py`.

### Dependencies
None (first sub-phase).

### Estimated scope
- LOC: ~400–600.
- Tests: ~43.
- Complexity: **medium** (behavioral change with safety implications).
- Copilot review cycles: **2**.

### References
- SEC Rule 15c3-5 (Market Access Rule).
- Knight Capital Group post-mortem (2012).
- CLAUDE.md §2: "Risk Manager (S05) is a VETO."
- GitHub issue #148.

---

## 3.2 Sub-phase 5.2 — Event Sourcing / In-Memory State

### Objective
Eliminate all network I/O (Redis reads) from S05's hot path by
transitioning to an event-sourced in-memory state machine. S05
subscribes to ZMQ topics for fills, mark-to-market, and position
updates, maintaining a local `dict`-based state that converges with
Redis asynchronously.

### Scope
- **IN**: `InMemoryRiskState` dict replacing 8× `asyncio.gather`
  Redis reads; ZMQ subscription to execution/M2M topics; async
  reconciliation loop (state vs Redis, periodic); P99 < 100μs
  benchmark on order validation.
- **OUT**: Rust rewrite (→ 5.9); Aeron transport (→ 5.6 evaluation);
  persistent event log / replay (Phase 6).

### Module structure
```
services/s05_risk_manager/
├── in_memory_state.py         # NEW — InMemoryRiskState
├── reconciliation.py          # NEW — async state↔Redis reconciler
├── service.py                 # MODIFY — replace Redis reads with local state

tests/unit/services/s05_risk_manager/
├── test_in_memory_state.py    (~18 tests)
├── test_reconciliation.py     (~12 tests)

tests/integration/
├── test_event_sourcing_convergence.py  (~6 tests)
```

### Algorithm notes
- `InMemoryRiskState` is a plain `dict[str, Decimal]` keyed by
  metric name. Updated by `on_message()` handler for topics:
  `execution.fill.*`, `risk.m2m.*`, `portfolio.position.*`.
- Order validation reads ONLY from `InMemoryRiskState` — zero
  network calls, zero `await`, pure CPU-bound computation.
- Reconciliation: every 5s, a background task reads Redis and
  compares. Discrepancies > 0.01% trigger `structlog.warning()`.
  If discrepancy > 1%, state transitions to `DEGRADED` (5.1
  Fail-Closed kicks in).
- The 5.1 `FailClosedGuard` remains as the outer shell — if
  in-memory state is stale (no ZMQ update for > 10s), state
  transitions to `DEGRADED`.

### Criteria — Definition of Done
1. Benchmark: P99 order validation latency < 100μs (profiler
   confirms zero network/socket calls in hot path).
2. Convergence test: after 1000 simulated fills, in-memory state
   matches Redis within Decimal tolerance.
3. All unit + integration tests passing, coverage ≥ 90%.
4. `mypy --strict` clean, `ruff` clean.
5. New ZMQ topics registered in `core/topics.py`.

### Dependencies
- Sub-phase 5.1 merged (Fail-Closed guard is the safety net for
  state staleness).

### Estimated scope
- LOC: ~500–700.
- Tests: ~36.
- Complexity: **medium–high** (state machine + reconciliation).
- Copilot review cycles: **2–3**.

### References
- Martin Thompson, "Mechanical Sympathy" (blog series).
- LMAX Exchange Architecture (Disruptor pattern).
- CLAUDE.md §5: "Hot paths must avoid object allocation in inner
  loops."
- GitHub issue #149.

---

## 3.3 Sub-phase 5.3 — Streaming Inference Wiring

### Objective
Wire Phase 4's trained Meta-Labeler and IC-weighted fusion into the
live S02 → S04 real-time pipeline. Phase 3 calculators transition
from batch-only to streaming mode (sub-millisecond per-tick
inference). Reinstate G7 as a blocking gate on real market data.

### Scope
- **IN**: S02 adapter streaming mode for Phase 3 calculators
  (gex, har_rv, ofi); S04 FusionEngine loads the persisted
  Meta-Labeler model + IC-weighted fusion config at startup;
  per-tick `predict_proba` → Kelly bet-size → `OrderCandidate`;
  Redis key `meta_label:latest:{symbol}` updated live; G7 gate
  reinstated as blocking.
- **OUT**: Short-side Meta-Labeler (→ 5.4); regime-conditional
  weights (→ 5.4); drift monitoring (→ 5.5); Rust hot path (→ 5.9).

### Module structure
```
services/s02_signal_engine/
├── streaming_adapter.py       # NEW — per-tick Phase 3 calculator wrapper

services/s04_fusion_engine/
├── live_meta_labeler.py       # NEW — loads persisted model, predict_proba per tick
├── live_fusion.py             # NEW — IC-weighted fusion in streaming mode
├── service.py                 # MODIFY — integrate live ML inference

tests/unit/services/s02_signal_engine/
├── test_streaming_adapter.py  (~16 tests)

tests/unit/services/s04_fusion_engine/
├── test_live_meta_labeler.py  (~14 tests)
├── test_live_fusion.py        (~10 tests)

tests/integration/
├── test_streaming_pipeline.py (~8 tests)
```

### Algorithm notes
- S02 streaming adapter: wraps each Phase 3 calculator in a stateful
  rolling-window context, but **must not** recompute full-window
  `FeatureCalculator.compute()` on every tick as the primary live path.
  Phase 5 shall define an incremental interface (for example,
  `compute_incremental(new_bar, evicted_bar | None)`) for calculators
  whose rolling statistics can be updated in O(1) or amortized O(1)
  time. On each tick, the adapter pushes the new bar into the window,
  updates internal state, and emits only the newly derived feature
  values for that tick. Existing batch `.compute()` remains supported
  as a compatibility fallback **only** for calculators that do not yet
  have an incremental implementation; any such fallback must document
  bounded window size and benchmark evidence that it still satisfies
  the latency budget. Target: < 1ms per calculator per tick, with the
  full signal → fusion → bet-size path meeting the Phase 5 P99 SLO.
- S04 loads the `.joblib` model + `.json` model card at startup.
  Card schema validation is mandatory — if the card fails validation,
  S04 refuses to start (fail-loud, no silent fallback to the old
  deterministic scorer).
- `predict_proba` output ∈ [0, 1] → Kelly bet-size `2p - 1` per
  ADR-0005 D8. Result published to Redis
  `meta_label:latest:{symbol}` for S05 `MetaLabelGate` consumption.
- G7 (RF − LogReg ≥ 0.03) reinstated as blocking on real data.
  If G7 fails on real data, the deployment is halted and the model
  must be retrained or the feature set expanded.

### Criteria — Definition of Done
1. Per-tick latency: < 1ms for the full signal → fusion → bet-size
   path (measured on synthetic tick stream, P99).
2. Redis key `meta_label:latest:{symbol}` updated within 5ms of
   each tick.
3. Model card validation at S04 startup — missing/invalid card
   prevents launch.
4. Integration test: 1000-tick synthetic stream produces consistent
   bet-sizes matching batch computation within floating-point
   tolerance.
5. All tests passing, coverage ≥ 88%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.2 merged (S05 in-memory state must be operational
  before wiring live predictions into it).
- Issue #123 (streaming calculators) resolved by this sub-phase.

### Estimated scope
- LOC: ~600–900.
- Tests: ~48.
- Complexity: **high** (core live integration).
- Copilot review cycles: **3**.

### References
- ADR-0005 D6, D7, D8.
- Phase 4 closure report §5.1 (streaming inference prerequisite).
- GitHub issue #123.

---

## 3.4 Sub-phase 5.4 — Short-Side Meta-Labeler + Regime-Conditional Fusion

### Objective
Extend the Meta-Labeler to support short-side trades (direction =
−1) and implement regime-conditional fusion weights that adapt to
the current market regime detected by S03.

### Scope
- **IN**: `direction ∈ {+1, −1}` in Triple Barrier labeling and
  Meta-Labeler feature builder; separate short-side model or
  direction-aware features; regime-conditional IC-weighted fusion
  (weights vary by `vol_regime` state from S03); CPCV validation
  of the short-side model.
- **OUT**: Multi-asset class expansion (Phase 6); options-based
  hedging strategies (Phase 6).

### Module structure
```
features/labeling/
├── triple_barrier_binary.py   # MODIFY — support direction=-1

features/meta_labeler/
├── feature_builder.py         # MODIFY — add direction feature
├── baseline.py                # MODIFY — train per-direction models

features/fusion/
├── regime_conditional.py      # NEW — regime-aware weight switching
├── ic_weighted.py             # EXTEND — per-regime IC reports

tests/unit/features/labeling/
├── test_short_side_labeling.py  (~12 tests)

tests/unit/features/meta_labeler/
├── test_short_side_model.py   (~14 tests)

tests/unit/features/fusion/
├── test_regime_conditional.py (~16 tests)
```

### Algorithm notes
- Short-side labeling: when `direction = −1`, upper barrier = loss
  (price rises past stop-loss), lower barrier = profit (price drops
  to take-profit). Binary target: 1 iff lower barrier hit.
- Feature builder adds `direction_code` (±1) as a 9th feature.
  The model learns asymmetric regime effects.
- Regime-conditional fusion: `RegimeConditionalFusion` holds N
  frozen weight vectors (one per regime state: LOW/NORMAL/HIGH/
  CRISIS). On each tick, S03's current regime selects the active
  weight vector. Weights per regime are computed from regime-
  stratified IC reports.
- Transition smoothing: at regime boundaries, weights blend linearly
  over a 5-bar window to avoid whipsaw from regime oscillation.

### Criteria — Definition of Done
1. Short-side model passes G1–G6 gates on synthetic scenario with
   directional alpha.
2. Regime-conditional fusion Sharpe ≥ global fusion Sharpe on
   synthetic multi-regime scenario.
3. Transition smoothing test: fusion score is continuous across
   regime boundaries (no jumps > 2σ).
4. All tests passing, coverage ≥ 90%.
5. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.3 merged (streaming pipeline must exist for live
  regime-conditional switching).

### Estimated scope
- LOC: ~500–700.
- Tests: ~42.
- Complexity: **medium–high** (directional asymmetry + regime logic).
- Copilot review cycles: **2–3**.

### References
- López de Prado (2018) §3.4 (directional labeling).
- ADR-0005 D1 (long-only MVP → extended).
- Phase 4 closure §5.2 (short-side + regime-conditional debt).

---

## 3.5 Sub-phase 5.5 — Drift Monitoring & Feedback Loop

### Objective
Implement continuous model-quality monitoring in S09 FeedbackLoop to
detect feature drift, calibration degradation, and signal decay. When
drift exceeds thresholds, S09 publishes alerts and can trigger
automatic model recalibration or position de-risking via S05.

### Scope
- **IN**: rolling AUC/Brier monitoring on live predictions vs
  realized outcomes; Population Stability Index (PSI) for feature
  drift; calibration curve divergence; alert ZMQ topics; automatic
  Kelly reduction when drift detected; recalibration trigger
  (publishes event, does NOT retrain inline).
- **OUT**: Automatic retraining pipeline (Phase 6); A/B testing
  framework for model comparison (Phase 6).

### Module structure
```
services/s09_feedback_loop/
├── drift_monitor.py           # NEW — PSI, rolling AUC, calibration
├── alert_engine.py            # NEW — threshold-based alert publisher
├── service.py                 # MODIFY — integrate drift monitoring

tests/unit/services/s09_feedback_loop/
├── test_drift_monitor.py      (~18 tests)
├── test_alert_engine.py       (~10 tests)

tests/integration/
├── test_drift_feedback_loop.py  (~6 tests)
```

### Algorithm notes
- PSI (Population Stability Index) computed on rolling 500-bar
  windows vs training distribution. PSI > 0.10 = warning,
  PSI > 0.25 = critical (feature distribution has shifted
  materially).
- Rolling AUC: computed on the last 200 realized labels (from
  Triple Barrier outcomes with known t1). If rolling AUC drops
  below G1 threshold (0.55) for 3 consecutive windows, S09
  publishes `feedback.drift.critical`.
- Calibration divergence: Brier score on rolling window. If
  Brier > G5 threshold (0.25), calibration has degraded.
- On critical drift: S09 publishes `feedback.drift.critical` →
  S05 can reduce Kelly multiplier by 50% as a defensive measure
  until manual review or automatic recalibration.
- Recalibration trigger: S09 publishes
  `feedback.recalibration.requested` with the current model card
  hash and drift metrics. A future Phase 6 orchestrator will
  consume this to schedule retraining.

### Criteria — Definition of Done
1. PSI correctly detects synthetic distribution shift (inject mean
   shift of 1σ → PSI > 0.25).
2. Rolling AUC degradation detected within 3 windows of synthetic
   model decay.
3. Alert topics registered in `core/topics.py`.
4. Integration test: full feedback loop from prediction → realized
   outcome → drift detection → alert.
5. All tests passing, coverage ≥ 90%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.3 merged (need live predictions to monitor).
- Sub-phase 5.4 optional (short-side monitoring is additive).

### Estimated scope
- LOC: ~450–650.
- Tests: ~34.
- Complexity: **medium** (statistical monitoring + alerting).
- Copilot review cycles: **2**.

### References
- Tsay (2010) Ch. 2 (time-varying parameters).
- PSI methodology (credit risk industry standard).
- Phase 4 closure §5.2 (drift monitoring prerequisite).

---

## 3.6 Sub-phase 5.6 — ZMQ Peer-to-Peer Bus

### Objective
Replace the centralized XSUB/XPUB broker (`zmq_broker.py`) with a
distributed peer-to-peer topology using Redis-based service discovery.
Eliminate the single point of failure.

### Scope
- **IN**: Each publisher BINDs its own ephemeral port; service
  registry in Redis with TTL + heartbeat; subscribers CONNECT
  directly to publishers; abstract `TransportLayer` interface for
  future Aeron swap; chaos test proving resilience.
- **OUT**: Aeron IPC implementation (evaluated, not shipped — Phase 6
  if benchmarks justify); UDP multicast (network-dependent, deferred).

### Module structure
```
core/
├── bus.py                     # MODIFY — implement P2P topology
├── transport.py               # NEW — TransportLayer ABC
├── service_registry.py        # NEW — Redis-based registry
├── zmq_broker.py              # DEPRECATE (keep for backward compat, flag)

tests/unit/core/
├── test_transport_layer.py    (~12 tests)
├── test_service_registry.py   (~14 tests)

tests/integration/
├── test_zmq_p2p_resilience.py (~10 tests)
```

### Algorithm notes
- Service registry: each publisher writes
  `service:{service_id}:endpoint = "tcp://{ip}:{port}"` to Redis
  with TTL = 10s. Heartbeat loop refreshes every 5s.
- Subscriber startup: reads all `service:*:endpoint` keys matching
  its subscription topics. CONNECTs directly to each publisher.
- Dynamic discovery: subscriber polls registry every 10s for new
  publishers (handles service restarts / scaling).
- `TransportLayer` ABC with methods: `bind()`, `connect()`,
  `publish()`, `subscribe()`. ZMQ implementation is the default.
  Aeron implementation is a stub for Phase 6 evaluation.
- Backward compatibility: services that haven't migrated can still
  use the broker via a `LegacyBrokerTransport` adapter (transitional,
  removed in Phase 6).

### Criteria — Definition of Done
1. Chaos test: kill any single service container → remaining
   services continue communicating within 2s recovery.
2. Latency reduction: measured P50/P99 transport latency lower than
   broker topology (one fewer network hop).
3. Service registry in Redis with TTL and heartbeat, tested.
4. `TransportLayer` ABC with ZMQ + stub Aeron implementations.
5. All tests passing, coverage ≥ 88%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.2 merged (event-sourcing defines the ZMQ topic
  contract that P2P must honor).

### Estimated scope
- LOC: ~600–850.
- Tests: ~36.
- Complexity: **high** (infrastructure, distributed systems).
- Copilot review cycles: **3**.

### References
- CME Group infrastructure whitepapers.
- Real Logic Aeron (https://github.com/real-logic/aeron).
- CLAUDE.md §2: "ZMQ topics are defined in core/topics.py."
- ADR-0001 (superseded by this sub-phase).
- GitHub issue #150.

---

## 3.7 Sub-phase 5.7 — SBE / FlatBuffers Serialization

### Objective
Migrate the hot-path message serialization from JSON
(`.model_dump_json()`) to zero-copy binary encoding
(FlatBuffers or SBE) to eliminate GC pressure from continuous
string allocation.

### Scope
- **IN**: Binary schemas for `Tick`, `Signal`, `OrderCandidate`,
  `RiskDecision`; compiled Python wrappers; `MessageBus` modified
  to send/receive raw `bytes`; backward-compatible JSON adapter
  for non-migrated services.
- **OUT**: Full SBE compliance certification (not required for
  internal use); Cap'n Proto evaluation (deferred).

### Module structure
```
core/
├── schemas/                   # NEW directory
│   ├── tick.fbs               # FlatBuffers schema
│   ├── signal.fbs
│   ├── order_candidate.fbs
│   └── risk_decision.fbs
├── serialization.py           # NEW — encode/decode wrappers
├── bus.py                     # MODIFY — bytes transport mode

tests/unit/core/
├── test_serialization.py      (~20 tests)
├── test_bus_binary_mode.py    (~10 tests)

tests/integration/
├── test_binary_pipeline.py    (~6 tests)
```

### Algorithm notes
- FlatBuffers chosen over SBE for Phase 5: richer tooling, Python
  code generation, zero-copy access. SBE remains an option for
  Phase 6 Rust hot path if FlatBuffers overhead is measured.
- `MessageBus.publish()` accepts both `BaseModel` (legacy JSON path)
  and `bytes` (new binary path). The bus detects the type and routes
  accordingly. No service needs to change its consumer code until
  explicitly migrated.
- JSON adapter: non-migrated services receive a thin
  `FlatBufferToJsonAdapter` that deserializes binary → Pydantic
  model transparently. Performance penalty accepted for backward
  compatibility during Phase 5.
- Schema versioning: each `.fbs` file includes a `schema_version`
  field. Consumers validate version on decode. Unknown versions
  raise `ValueError` (fail-loud).

### Criteria — Definition of Done
1. CPU profiling report: > 80% reduction in serialization CPU time
   for `Tick` messages.
2. GC stability: stress test (10,000 ticks/s for 60s) shows
   no GC pause > 10ms.
3. Schemas versioned and documented.
4. Backward-compatible: non-migrated services still consume JSON.
5. All tests passing, coverage ≥ 90%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.6 merged (P2P bus defines the transport; binary
  encoding is layered on top).

### Estimated scope
- LOC: ~500–700.
- Tests: ~36.
- Complexity: **medium** (schema design + dual-mode bus).
- Copilot review cycles: **2**.

### References
- FIX Trading Community — SBE specification.
- Google FlatBuffers (https://google.github.io/flatbuffers/).
- CLAUDE.md §5: "Hot paths must avoid object allocation in inner
  loops."
- GitHub issue #151.

---

## 3.8 Sub-phase 5.8 — Alt Data NLP — Geopolitical Risk Overlay

### Objective
Integrate a real-time geopolitical risk scoring pipeline using NLP
on alternative data feeds. The risk score modulates Kelly bet-sizing
in S04 and can trigger S05's circuit breaker on extreme events.

### Scope
- **IN**: `WorldMonitorConnector` for gRPC/Protobuf ingestion (S01);
  FinBERT or quantized LLM for sentiment scoring (S08);
  `GeopoliticalRiskScore [-1.0, 1.0]` stored in TimescaleDB; S04
  Kelly penalty on extreme negative scores; S05
  `GeopoliticalEventGuard` with VETO at score = -1.0; Fail-Closed
  on NLP model crash (heartbeat > 60s).
- **OUT**: Custom LLM fine-tuning (Phase 6); satellite imagery
  analysis (Phase 6); multi-language NLP (Phase 6).

### Module structure
```
services/s01_data_ingestion/
├── connectors/
│   └── worldmonitor.py        # NEW — gRPC Protobuf consumer

services/s08_macro_intelligence/
├── nlp/
│   ├── risk_scorer.py         # NEW — FinBERT inference pipeline
│   ├── model_card_nlp.json    # NEW — governance model card
│   └── onnx_runtime.py        # NEW — ONNX/TensorRT wrapper

services/s04_fusion_engine/
├── service.py                 # MODIFY — Kelly penalty on geopolitical risk

services/s05_risk_manager/
├── geopolitical_guard.py      # NEW — GeopoliticalEventGuard

tests/unit/services/s08_macro_intelligence/
├── test_risk_scorer.py        (~16 tests)

tests/unit/services/s05_risk_manager/
├── test_geopolitical_guard.py (~12 tests)

tests/integration/
├── test_geopolitical_pipeline.py  (~8 tests)
```

### Algorithm notes
- Latency budget: geopolitical event injected in S01 → S05 BLOCKED
  state in < 250ms end-to-end.
- FinBERT compiled via ONNX Runtime for GC-free inference. Fallback
  to CPU if GPU unavailable. P99 inference < 50ms per text chunk.
- Score mapping: FinBERT logits → softmax → weighted sum maps to
  `[-1.0, 1.0]`. Stored in TimescaleDB with point-in-time semantics.
- S04 Kelly penalty: `kelly_adj = kelly * max(0, 1 + geo_score)`
  where `geo_score ∈ [-1, 0]` reduces Kelly linearly.
  `geo_score > 0` (positive sentiment) does NOT increase Kelly
  (asymmetric, conservative).
- S05 `GeopoliticalEventGuard`: if `geo_score == -1.0`, VETO all
  orders. If NLP heartbeat absent > 60s, Fail-Closed (5.1 pattern).

### Criteria — Definition of Done
1. Latency test: event → BLOCKED in < 250ms.
2. `model_card_nlp.json` documents bias, P99 inference time, VRAM.
3. Backtest: ≥ 15% MDD reduction on ex-post crisis periods.
4. ZMQ topic `macro.geopolitics.*` in `core/topics.py`.
5. All tests passing, coverage ≥ 88%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.3 merged (live pipeline must exist for risk overlay
  integration).

### Estimated scope
- LOC: ~800–1200.
- Tests: ~36.
- Complexity: **high** (NLP + multi-service integration).
- Copilot review cycles: **3**.

### References
- Kelly, B. et al., "Text as Data" (JFE).
- FinBERT (https://github.com/ProsusAI/finBERT).
- CLAUDE.md §3: "S08 MacroIntelligence fires macro.catalyst.*
  events as they happen."
- GitHub issue #153.

---

## 3.9 Sub-phase 5.9 — Rust FFI Hot Path Migration

### Objective
Rewrite S01 (Market Data ingestion) and S05 (Risk validation) hot
paths in Rust, connected to the Python ecosystem via FFI (PyO3 or
shared-memory ring buffer). Achieve > 1M ticks/second/core for
L2 order book processing.

### Scope
- **IN**: Rust crates `apex_mc` (market data) and `apex_risk`
  (risk validation) extended with production-grade tick processing;
  PyO3 FFI bindings for S02/S08 Python consumers; zero-copy shared
  memory ring buffer for tick transmission; ADR documenting FFI
  architecture; benchmark suite.
- **OUT**: Full Rust monolith consolidation (Phase 6); Aeron
  transport in Rust (Phase 6); GPU acceleration (Phase 6).

### Module structure
```
rust/
├── apex_mc/
│   ├── src/
│   │   ├── ingestion.rs       # EXTEND — production tick parser
│   │   ├── ring_buffer.rs     # NEW — lock-free ring buffer
│   │   └── ffi.rs             # NEW — PyO3 bindings
│   └── Cargo.toml
├── apex_risk/
│   ├── src/
│   │   ├── validator.rs       # EXTEND — order validation logic
│   │   └── ffi.rs             # NEW — PyO3 bindings
│   └── Cargo.toml

services/s01_data_ingestion/
├── rust_bridge.py             # NEW — Python FFI consumer

services/s05_risk_manager/
├── rust_bridge.py             # NEW — Python FFI consumer

docs/adr/
├── ADR-0007-rust-ffi-architecture.md  (NEW)

tests/
├── rust/                      # Rust-side unit tests (cargo test)
├── unit/services/s01/
│   └── test_rust_bridge.py    (~10 tests)
├── unit/services/s05/
│   └── test_rust_bridge.py    (~10 tests)
├── integration/
│   └── test_ffi_pipeline.py   (~8 tests)
```

### Algorithm notes
- PyO3 chosen over raw shared memory for Phase 5 MVP: simpler
  error handling, automatic reference counting, existing CI
  infrastructure (`maturin build`). Shared-memory ring buffer
  is a Phase 6 optimization if PyO3 overhead is measured.
- The Rust tick parser handles L2 order book updates with
  nanosecond-precision timestamps. Decimal arithmetic via the
  `rust_decimal` crate (128-bit, matching Python `Decimal`
  semantics).
- FFI contract: Python calls `apex_mc.process_tick(raw_bytes) ->
  NormalizedTick` and `apex_risk.validate_order(candidate, state)
  -> RiskDecision`. Both functions are GIL-releasing.
- Benchmark target: > 1M ticks/second/core for `process_tick`.
  Measured via `criterion` benchmarks in Rust + Python wall-clock
  in integration tests.

### Criteria — Definition of Done
1. ADR-0007 committed (FFI architecture: PyO3 vs SHM decision).
2. Benchmark: > 1M ticks/s/core for `process_tick` (Rust).
3. Benchmark: Python→Rust→Python round-trip < 5μs per tick.
4. `cargo test --workspace` all passing.
5. `maturin build` + `import apex_mc, apex_risk` in Python.
6. Comparative benchmark: Python vs Rust on hot path (P50/P99/P999).
7. Integration tests: FFI transparent for S02/S08.
8. All Python tests passing, coverage ≥ 85%.
9. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.2 merged (event-sourced state is the Rust validation
  target).
- Track B (5.6, 5.7) preferred but not blocking (Rust operates at
  the transport layer boundary).

### Estimated scope
- LOC: ~1500–2500 (Rust + Python bindings).
- Tests: ~28 Python + ~40 Rust.
- Complexity: **very high** (polyglot, FFI, performance).
- Copilot review cycles: **4+**.

### References
- López de Prado (2018), AFML — research vs production separation.
- PyO3 (https://pyo3.rs/).
- CLAUDE.md §5: "CPU-bound math goes in Rust (apex_mc, apex_risk
  crates) — not in Python."
- GitHub issue #152.

---

## 3.10 Sub-phase 5.10 — Phase 5 Closure Report

### Objective
Mirror of PR #147 (Phase 4 closure) for Phase 5. Document all
sub-phases delivered, final benchmarks, technical debt for Phase 6,
and readiness assessment.

### Scope
- **IN**: Closure report document; updated memory files; Phase 6
  prerequisites list; final benchmark summary.
- **OUT**: New implementation code (closure is docs-only except
  memory files).

### Module structure
```
docs/
├── phase_5_closure_report.md  (NEW)

docs/claude_memory/
├── CONTEXT.md                 (UPDATED)
├── SESSIONS.md                (UPDATED)
├── PHASE_5_NOTES.md           (NEW)
```

### Content
- Sub-phase inventory (5.1–5.9) with PR numbers, LOC, test counts.
- Benchmark summary: latency improvements, throughput gains.
- Safety audit: Fail-Closed verification, chaos test results.
- Live integration status: streaming pipeline operational flag.
- Technical debt for Phase 6: DMA research (#154), Rust monolith
  consolidation, Aeron transport, automatic retraining, A/B testing.
- Phase 6 prerequisites checklist.

### Criteria — Definition of Done
1. `docs/phase_5_closure_report.md` committed.
2. Memory files updated.
3. All CI jobs green on closure branch.
4. PR link convention: same as PR #147 precedent.

### Dependencies
- All of 5.1–5.9 merged.

### Estimated scope
- LOC: N/A (docs only).
- Complexity: **low**.
- Copilot review cycles: **1**.

---

## 4. Sub-phase tracking table

Issue numbers and branches to be filled at issue-creation time.

| Sub-phase | Issue | Track | Branch | Status |
|---|---|---|---|---|
| 5.1 Fail-Closed Pre-Trade Risk | #148 | A | `phase-5/fail-closed` | not started |
| 5.2 Event Sourcing / In-Memory | #149 | A | `phase-5/event-sourcing` | not started |
| 5.3 Streaming Inference Wiring | #123 | A | `phase-5/streaming-inference` | not started |
| 5.4 Short-Side + Regime Fusion | — | A | `phase-5/short-side-regime` | not started |
| 5.5 Drift Monitoring | — | A | `phase-5/drift-monitoring` | not started |
| 5.6 ZMQ Peer-to-Peer Bus | #150 | B | `phase-5/zmq-p2p` | not started |
| 5.7 SBE / FlatBuffers | #151 | B | `phase-5/sbe-serialization` | not started |
| 5.8 Alt Data NLP | #153 | C | `phase-5/alt-data-nlp` | not started |
| 5.9 Rust FFI Hot Path | #152 | C | `phase-5/rust-ffi` | not started |
| 5.10 Closure Report | — | — | `chore/phase-5-closure` | not started |

---

## 5. Transverse concerns

### 5.1 Fail-loud heritage (Phases 3 + 4)

All Phase 5 code preserves the fail-loud pattern. Missing state →
`ValueError`. Invalid model card → `ValueError`. Stale heartbeat →
state transition to `DEGRADED`, not silent continuation.

### 5.2 CI contract

Phase 5 inherits the current CI pipeline:
1. `quality` — ruff + mypy strict + bandit
2. `rust` — cargo test + maturin build
3. `unit-tests` — pytest with coverage ≥ 75%
4. `integration-tests` — full pipeline with Redis
5. `backtest-gate` — non-blocking; Sharpe ≥ 0.5, max DD ≤ 0.12

Phase 5 targets raising the unit-test coverage gate to ≥ 85% and
tightening backtest acceptance targets to Sharpe ≥ 0.8 and max DD
≤ 8% once the CI workflow is updated accordingly.
Sub-phase 5.9 (Rust FFI) may add a `rust-bench` job to track
performance regressions.

### 5.3 Security

- S06 execution: Fail-Closed guard (5.1) ensures no orders pass
  through degraded state.
- NLP model (5.8): runs in isolated subprocess, no access to
  broker API keys.
- Rust FFI (5.9): memory safety guaranteed by Rust's ownership
  model; no `unsafe` blocks without documented justification.

### 5.4 UTC timestamps, Decimal prices

Inherited from CLAUDE.md §2/§10. Non-negotiable.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Fail-Closed over-rejects in volatile markets | Missed trading opportunities | Configurable heartbeat TTL; S10 alerting; manual override (human, not code) |
| Event-sourcing state divergence | Stale risk limits | Reconciliation loop (5.2) with 1% divergence threshold |
| Streaming latency > 1ms budget | Bet-size stale by next tick | Profiling gates in CI; Rust fallback (5.9) |
| NLP model hallucination | False circuit breaker activation | Ensemble scoring (multiple models); human-in-loop for VETO override |
| FFI memory corruption | System crash | Rust memory safety; no `unsafe`; integration test suite |
| ZMQ P2P service discovery race | Missed messages at startup | Redis TTL + subscriber retry loop; integration chaos tests |
| Phase 5 scope creep | Delayed Phase 6 | DMA Research explicitly deferred; scope tracked in §4 table |

---

## 7. Phase 6 preview (out of scope, for context only)

The following items are explicitly **not** in Phase 5 and form the
Phase 6 backlog:

- **#154 DMA Research** — Dynamic Model Averaging vs Meta-Labeling
  (HMM regime-switching). Pure research, no production code.
- **Rust monolith consolidation** — merge S01 + S05 Rust hot paths
  into a single binary (Phase 3 of the Rust migration plan in #152).
- **Aeron IPC transport** — if Phase 5.6 benchmarks show ZMQ P2P
  is insufficient for HFT latency targets.
- **Automatic retraining pipeline** — orchestrated by
  `feedback.recalibration.requested` events from 5.5.
- **A/B model testing** — champion/challenger framework for live
  model comparison.
- **Multi-asset expansion** — options, futures, commodities.

---

## 8. References (aggregate)

### Project
- CLAUDE.md — development contract.
- MANIFEST.md — architecture source of truth.
- ADR-0001 through ADR-0005 — existing decisions.
- Phase 3 closure (PR #124), Phase 4 closure (PR #147) — precedents.
- `docs/phase_4_closure_report.md` §5–§6 — Phase 5 prerequisites.

### Academic
- López de Prado, M. (2018), *Advances in Financial Machine
  Learning*, Wiley.
- Martin Thompson, "Mechanical Sympathy" blog series.
- LMAX Exchange Architecture (Disruptor pattern).
- Kelly, B. et al., "Text as Data" (JFE).
- Tsay, R. (2010), *Analysis of Financial Time Series*, Wiley.

### Industry
- SEC Rule 15c3-5 (Market Access Rule).
- Knight Capital Group post-mortem (2012).
- FIX Trading Community — SBE specification.
- CME Group infrastructure whitepapers.
- Real Logic Aeron (https://github.com/real-logic/aeron).
- Google FlatBuffers (https://google.github.io/flatbuffers/).
- PyO3 (https://pyo3.rs/).
- FinBERT (https://github.com/ProsusAI/finBERT).
