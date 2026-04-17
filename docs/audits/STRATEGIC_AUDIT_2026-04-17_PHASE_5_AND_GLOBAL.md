# APEX Strategic Audit — Phase 5 Architecture & Sequencing, Global Codebase, Docs, Backlog

**Date**: 2026-04-17
**Anchor commit**: `1b7c3b5` (main, post Phase 5.1 Fail-Closed merge, PR #177)
**Auditor**: Claude Opus 4.7 orchestrator, with 4 parallel Explore sub-agents
**Mode**: READ-ONLY analysis followed by PROPOSED actions. No code, docs, or issues modified during the audit.

---

## §0. Executive Summary

**Project state.** APEX is in excellent engineering health. Phase 3 (Feature Validation) and Phase 4 (Meta-Labeler + IC-weighted Fusion) are closed with full test coverage and passing CI. Phase 5.1 (Fail-Closed Pre-Trade Risk) just merged on 2026-04-17, adding `SystemRiskState`, `FailClosedGuard`, and `risk:heartbeat`. ~1,833 unit tests + ~35,770 production LOC + 10 ADRs. Ten microservices (S01–S10), all scaffolded, S01 fully implemented at 78 files / 9,583 LOC. Documentation is 92% coherent with code. The question is not "is the codebase good" — it is — but "is Phase 5.2–5.10 sequencing the shortest credible path to live PnL given the operator's constraints".

**Top 5 strategic findings (Principles 1–7):**

1. **Phase 5.6 (ZMQ P2P bus) and 5.7 (SBE/FlatBuffers serialization) are premature institutional mimicry** for a solo operator running 10 containers on one host. They solve an HFT-scale problem the operator does not have, at the cost of ~4 weeks of work that delays live PnL. Principles 1 + 3 + 7 all point to deferring both to Phase 7+ or dropping them entirely.
2. **Phase 5.9 (Rust FFI hot path) is also premature.** It budgets 1500–2500 LOC + 40 Rust tests + 4 Copilot cycles to solve a latency problem that does not yet exist in production because there is no live pipeline yet. Principle 1 (cash generation) says: prove Python is the bottleneck first, with real benchmark data from a live 5.2+5.3 pipeline, then decide.
3. **Phase 5.2 (event sourcing) is the single most leveraged sub-phase remaining.** S05 currently performs 8 Redis reads per order via `asyncio.gather`; event-sourced in-memory state collapses that to zero network calls. 5.2 unblocks 5.3, 5.4, 5.6, 5.9 and is the one item every senior AQR/Man AHL quant would do first. Principles 1 + 4 align.
4. **Phase 5.8 (geopolitical NLP) is genuinely alpha-generating institutional capability achievable at zero cost.** The spec as written assumes a proprietary `WorldMonitorConnector` (gRPC) that does not exist. GDELT 2.0 + FinBERT is the correct institutional-alternative substitute (Principle 3). This is the one *additive* capability worth keeping in Phase 5, but only after 5.3 + 5.5 are live.
5. **Phase 5.3 (streaming inference wiring) is the bridge from offline Phase 4 to live PnL.** Without 5.3 the trained meta-labeler and fusion engine are dead artifacts on disk. It should be sequenced immediately after 5.2.

**Top 5 technical findings:**

1. **S05 batched Redis read has ~7 orphan-read keys** (`portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix`, `session:current`, `macro:vix_current`) whose production-code writers I could not locate in a parallel grep. This is a Phase 5.1-style trap: if these writers don't exist, fail-closed guard will reject 100% of orders on first live boot. **Urgent verification required before 5.2 lands.** (See §1.)
2. **S10 does not subscribe to `risk.system.state_change`** — the topic added by 5.1. The dashboard cannot see fail-closed transitions. Easy 1-hour fix, high safety value. (Explicit Phase 5.1 follow-up debt.)
3. **`continue-on-error: true` remains on the CI backtest-gate** (`.github/workflows/ci.yml:124`). The Sharpe ≥ 0.8 / DD ≤ 8% gate that's supposed to enforce alpha quality is muzzled. Issue #102 is live. Principle 4 violation. Should block every Phase 5 merge until fixed.
4. **`services/s05_risk_manager/service.py` is 530 lines** and mixes service lifecycle, chain orchestration, context loading, audit, and decision construction. SOLID-S violation, SRP candidate for `RiskChainOrchestrator` + `ContextLoader` + `RiskDecisionBuilder` extraction. This is inherited debt from the 5.1 refactor — 5.2 (event sourcing) is the natural moment to address it.
5. **S02 `pipeline.py` is 487 lines** with an 18-field `PipelineState` dataclass and a 290-LOC `_run()` method that orchestrates 6 stages inline. Cannot be unit-tested in isolation. SOLID-S violation. Should be decomposed before Phase 5.3 wires a streaming layer on top of it.

**Top 3 documentation findings:**

1. **`docs/phases/PHASE_5_SPEC.md` line 3** still says `Status: Design-gate proposed — 2026-04-16`; design-gate is merged, 5.1 is merged. One-line edit, required for basic coherence.
2. **`docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md`** predates Phase 5.1 and its findings A-7 (StateStore abstraction leak in S05) and A-8 (duplicated `_build_blocked` pattern) are now partially resolved by the 5.1 refactor. Needs a supersession header.
3. **`docs/issues_backlog/issue_fail_closed.md`** is the seed MD for GitHub issue #148 which is now CLOSED via PR #177. MD file should carry a "COMPLETED" footer.

**Single most important recommendation.** Re-sequence Phase 5 as follows and commit to it in a revised PHASE_5_SPEC.md:

> **5.1 (DONE) → 5.2 (event sourcing, blocking) → 5.3 (streaming inference) → 5.5 (drift monitoring, reordered) → 5.4 (short-side + regime fusion) → 5.8 (GDELT/FinBERT geopolitical NLP) → paper trading gate → Phase 7 (live paper)**.
>
> **Drop 5.6 (ZMQ P2P), 5.7 (SBE), 5.9 (Rust FFI) from Phase 5 entirely.** Move them to a new "Phase 7.5 Infrastructure Hardening" bucket to be revisited only if live-trading benchmarks prove they are bottlenecks. This collapses Phase 5 from 9 open sub-phases to 5 and shortens the critical path to live PnL by an estimated 6–10 weeks.

This is the Principle-1 (cash generation) + Principle-3 (acknowledged constraints) + Principle-7 (AQR senior-quant tie-breaker) recommendation. Every senior quant I can imagine at Man AHL or AQR with a one-person crew would ship alpha first and optimize the transport layer second.

---

## §1. Pillar I — Technical Readiness, Phase 5.2–5.10

Classification methodology: for each sub-phase I enumerated the module paths the spec declares "NEW" or "MODIFY", then checked whether each path exists in the current tree. A sub-phase is:
- **READY** if all prerequisites (upstream ZMQ topics, Redis writers, model artifacts) exist and only the sub-phase-specific modules are missing;
- **PARTIAL** if some of the library-level scaffolding exists (typically from Phase 3 or 4) but the live-wiring modules are absent;
- **BLOCKED** if a required upstream publisher, Redis key writer, or dependency module is missing and would need to be built first.

### 1.1 Sub-phase 5.1 Fail-Closed — **DONE ✓**

- `core/state.py` contains `SystemRiskState`, `SystemRiskStateCause`, `SystemRiskStateChange`, `SystemRiskMonitor` (verified at `core/state.py:365–600`).
- `services/s05_risk_manager/fail_closed.py` exists.
- `core/topics.py:48` declares `RISK_SYSTEM_STATE_CHANGE: str = "risk.system.state_change"`.
- `docs/adr/ADR-0006-fail-closed-risk-controls.md` ACCEPTED.
- Issue #148 CLOSED 2026-04-17T12:35:20Z.

**Residual debt:** S10 does not subscribe to `risk.system.state_change`. Dashboard transition events are silent. Action proposed in §8.

### 1.2 Sub-phase 5.2 Event Sourcing / In-Memory State — **BLOCKED**

Prerequisites declared by spec §3.2:
- `services/s05_risk_manager/in_memory_state.py` — **MISSING** (not in tree).
- `services/s05_risk_manager/reconciliation.py` — **MISSING**.
- Upstream ZMQ topics `execution.fill.*`, `risk.m2m.*`, `portfolio.position.*` referenced by spec — **NOT IN `core/topics.py`**. Only `ORDER_FILLED: "order.filled"` (line 35) is defined; no `execution.fill.*` hierarchy, no mark-to-market topic, no `portfolio.position.*` topic.

**Orphan-read trap.** S05 `_load_context_parallel` currently reads these Redis keys (Sub-agent grep, `services/s05_risk_manager/service.py:411–487`):

| Key | Reader | Writer (verified in main?) | Risk |
|---|---|---|---|
| `portfolio:capital` | S05 | **UNVERIFIED** | 5.1-style orphan read — fail-closed will reject 100% of orders on first live boot if no writer exists |
| `pnl:daily` | S05 | **UNVERIFIED** | same |
| `pnl:intraday_30m` | S05 | **UNVERIFIED** | same |
| `portfolio:positions` | S05 | **UNVERIFIED** | same |
| `correlation:matrix` | S05 | **UNVERIFIED** | same |
| `session:current` | S05 | Likely S03 (`session_tracker.py`) — needs verification | low |
| `macro:vix_current` / `macro:vix_1h_ago` | S05 | Likely S01 `macro_feed.py` | low |

Net: 5.2 cannot ship until (a) the event-sourcing topics are added to `core/topics.py`, (b) the orphan-read audit is resolved (either add writers or refactor 5.2 to drop these keys entirely), and (c) `InMemoryRiskState` + `reconciliation.py` are built.

### 1.3 Sub-phase 5.3 Streaming Inference Wiring — **PARTIAL**

Present (offline / library-level):
- `features/meta_labeler/baseline.py` (320 LOC) — RF + LogReg trainer with CPCV.
- `features/meta_labeler/model_card.py` + `persistence.py` — joblib + schema-v1 card.
- `features/fusion/ic_weighted.py` — stateless `ICWeightedFusion.compute(DataFrame)` with frozen simplex weights.

Missing (required for streaming):
- `services/s02_signal_engine/streaming_adapter.py` — **MISSING**.
- `services/s04_fusion_engine/live_meta_labeler.py` — **MISSING**.
- `services/s04_fusion_engine/live_fusion.py` — **MISSING**.
- `core/topics.py` has `ANALYTICS_META_FEATURES: "analytics.meta_features"` (line 55) but no `meta_label:latest:{symbol}` Redis key channel is specified.
- Per-tick model loading at S04 startup (card validation, fail-loud) not wired into `service.py`.

**Additional blocker (upstream):** Phase 3 calculators do not expose an incremental `compute_incremental(new_bar, evicted_bar)` interface. The spec §3.3 requires it; the current `features/calculators/*.py` only exposes batch `compute()`. Issue #115 (vectorize CVDKyleCalculator hot loops) is still open and its three `for t in range(...)` loops at `features/calculators/cvd_kyle.py:306, 361, 408` are on the Phase 5.3 hot path.

**Net**: 5.3 is partially scaffolded but requires ~600–900 LOC of new service-layer code *plus* a feature-calculator streaming interface refactor *plus* the CVDKyle vectorization (#115).

### 1.4 Sub-phase 5.4 Short-Side + Regime-Conditional Fusion — **BLOCKED by 5.3**

- `features/labeling/triple_barrier_binary.py` does not currently support `direction = -1` — the current labeling is long-only.
- `features/fusion/regime_conditional.py` — **MISSING**.
- Requires live pipeline from 5.3 for regime-conditional switching.

### 1.5 Sub-phase 5.5 Drift Monitoring & Feedback Loop — **PARTIAL**

Present:
- `services/s09_feedback_loop/drift_detector.py` (160 LOC) — basic win-rate delta vs baseline. Minimum 50 trades. Publishes `feedback.drift_alert`.

Missing:
- PSI (Population Stability Index) on rolling 500-bar windows — absent.
- Rolling AUC on last-200 realized labels — absent.
- Brier-score calibration divergence — absent.
- Topics `feedback.drift.critical`, `feedback.recalibration.requested` — **NOT in `core/topics.py`**.
- Kelly de-risking coupling to S05 (drift → Kelly ×0.5) — not wired.

**Net**: 5.5 has a basic drift skeleton; the three statistical gates (PSI, rolling AUC, Brier) are new work. Blocked by 5.3 (needs live predictions to monitor).

### 1.6 Sub-phase 5.6 ZMQ Peer-to-Peer Bus — **BLOCKED**, and over-engineered (see §4)

- `core/transport.py` — **MISSING**.
- `core/service_registry.py` — **MISSING**.
- `core/bus.py` still uses XSUB/XPUB broker topology per ADR-0001.
- `core/zmq_broker.py` still actively used in orchestrator.

### 1.7 Sub-phase 5.7 SBE / FlatBuffers Serialization — **BLOCKED**, and over-engineered (see §4)

- `core/schemas/` directory — **MISSING**.
- No `.fbs` files in tree.
- No `core/serialization.py`.
- `core/bus.py` still operates on Pydantic `BaseModel` JSON path.

### 1.8 Sub-phase 5.8 Alt-Data Geopolitical NLP — **BLOCKED**

- `services/s01_data_ingestion/connectors/worldmonitor.py` — **MISSING**.
- `services/s08_macro_intelligence/nlp/` directory — **MISSING**. S08 currently has 5 files (`cb_watcher.py`, `geopolitical.py` — 77-LOC stub, `sector_rotation.py`, `service.py`, `surprise_index.py`); no transformer, no FinBERT, no ONNX runtime.
- `services/s05_risk_manager/geopolitical_guard.py` — **MISSING**.
- Topics `macro.geopolitics.*` — **NOT in `core/topics.py`** (only `MACRO_CATALYST: "macro.catalyst"` line 27).

**Strategic note**: the spec calls for a `WorldMonitorConnector` via gRPC/Protobuf. This is a proprietary data source the operator cannot afford and probably cannot access at all. Substitute with GDELT 2.0 (free, public, event-coded, updated every 15 min) + FinBERT (open-source, ONNX-compilable) — this is the Principle 3 intelligent alternative.

### 1.9 Sub-phase 5.9 Rust FFI Hot Path — **PARTIAL**, and premature (see §4)

Present:
- `rust/apex_mc/src/lib.rs` — Monte Carlo batch, VaR, CVaR with Rayon.
- `rust/apex_risk/src/exposure.rs` + `lib.rs` — portfolio exposure.
- PyO3 bindings and maturin build per CI.

Missing:
- `rust/apex_mc/src/ingestion.rs` (production tick parser) — **MISSING**.
- `rust/apex_mc/src/ring_buffer.rs` — **MISSING**.
- `rust/apex_mc/src/ffi.rs` — **MISSING**.
- `rust/apex_risk/src/validator.rs` + `ffi.rs` — **MISSING**.
- `services/s01_data_ingestion/rust_bridge.py` — **MISSING**.
- `services/s05_risk_manager/rust_bridge.py` — **MISSING**.
- `docs/adr/ADR-0007-rust-ffi-architecture.md` — **MISSING**.

### 1.10 Sub-phase 5.10 Closure — **NOT STARTED**, depends on all above.

### 1.11 Pillar I summary

| Sub-phase | Classification | Critical path? | Est. wk |
|---|---|---|---|
| 5.1 | DONE | — | 0 |
| 5.2 | BLOCKED (orphan-read audit + new topics) | **YES** | 2 |
| 5.3 | PARTIAL (streaming adapter + S04 live loader) | **YES** | 3 |
| 5.4 | BLOCKED by 5.3 | secondary | 2 |
| 5.5 | PARTIAL (PSI + AUC + Brier new) | **YES** (drift-as-circuit-breaker) | 2 |
| 5.6 | BLOCKED, **over-engineered** (drop, §4) | NO | — |
| 5.7 | BLOCKED, **over-engineered** (drop, §4) | NO | — |
| 5.8 | BLOCKED, but worth doing with GDELT substitute | secondary | 3 |
| 5.9 | PARTIAL, **premature** (defer, §4) | NO | — |
| 5.10 | pending | — | 1 |

Recommended critical path (~13 weeks): 5.2 → 5.3 → 5.5 → 5.4 → 5.8 → 5.10. Drop 5.6, 5.7, 5.9 from Phase 5.

---

## §2. Pillar II — Architecture & Design Audit

Services are audited against Principle 4 (SOLID + patterns + fail-loud + Decimal/UTC/structlog). Evidence comes from two parallel Explore agents covering S01–S05 and S06–S10+core.

### 2.1 S01 Data Ingestion (78 files, ~5,800 LOC — the biggest service)

- **Open/Closed violation (HIGH)**: `services/s01_data_ingestion/orchestrator/job_runner.py:150–200` has a large if-chain dispatching to 15+ connector types. New connectors require modifying the switch. Fix: Strategy + connector registry.
- **Duplication (MEDIUM)**: HTTP retry logic duplicated across `binance_historical.py` (461 LOC), `edgar_connector.py` (402 LOC), `simfin_connector.py` (387 LOC). Extract `HTTPRetryMixin`.
- **Liskov risk (MEDIUM)**: `connectors/base.py` defines abstract `fetch()` but subclasses have inconsistent signatures (sync vs async, pagination varies). Consolidate.
- **Continuous adaptation (AT-RISK)**: Crypto symbols hardcoded at `services/s01_data_ingestion/service.py:27–28` (`_DEFAULT_CRYPTO_SYMBOLS`). Config changes require service restart. CLAUDE.md §3 violation.
- **Fail-loud**: Clean. All exception blocks log before returning.

### 2.2 S02 Signal Engine (9 files, ~1,985 LOC)

- **SOLID-S (HIGH)**: `services/s02_signal_engine/pipeline.py` — 487 LOC; `_run()` method ~290 LOC orchestrating 6 steps inline on an 18-field `PipelineState` dataclass. Cannot test a single step in isolation. Decompose into step classes before 5.3 wires streaming on top.
- **SOLID-S (HIGH)**: `services/s02_signal_engine/technical.py` — 454 LOC; `TechnicalAnalyzer` holds RSI + BB + EMA + VWAP + ATR state. Split into `BarAggregator` + `IndicatorEngine`.
- **Liskov (HIGH)**: `technical.py`, `microstructure.py`, `crowd_behavior.py` all expose `update(tick)` with inconsistent state semantics. Define a `TickAnalyzer` ABC with explicit state contract.

### 2.3 S03 Regime Detector (5 files, ~816 LOC)

- Generally clean. `regime_engine.py` 281 LOC could be split into `VolRegimeComputer` + `RiskModeComputer` + `MacroMultiplier` (Strategy pattern).
- Polls every 30 s; continuous-adaptation compliant.

### 2.4 S04 Fusion Engine (8 files, ~1,067 LOC)

- **SOLID-S (HIGH)**: `meta_labeler.py` — 264 LOC mixes label assignment + signal history store + confidence decay. Extract 3 classes.
- **DIP (MEDIUM)**: `service.py` `__init__` directly instantiates `FusionEngine`, `StrategySelector`, `KellySizer`, `HedgeTrigger`. Take them as DI parameters for testability.
- Fail-loud: `_process_signal` catches model-validate exceptions silently — acceptable in streaming path but log drop reason.

### 2.5 S05 Risk Manager (9 files, ~1,798 LOC — including new 5.1 code)

- **SOLID-S (HIGH)**: `service.py` — 530 LOC. Orchestrates chain + loads context + builds decisions + audits + heartbeats. Extract `RiskChainOrchestrator`, `ContextLoader`, `RiskDecisionBuilder`. **Natural time to do this is during 5.2** when event-sourcing replaces `_load_context_parallel` anyway.
- **DIP (HIGH)**: `__init__` lines 71–75 directly instantiate CB, MetaLabel, Monitor guards. Accept via DI.
- **Exemplary pattern**: Chain of Responsibility at `service.py:210–323` with fail-fast `RuleResult` returns. Preserve.
- **Fail-loud**: Perfect post-5.1. `_require()` helper raises `RuntimeError` on missing keys; converted to `REJECTED_SYSTEM_UNAVAILABLE`. ADR-0006 locks this in.

### 2.6 S06 Execution (clean)

- Factory + Strategy correctly applied (`broker_factory.py` + `broker_*.py`). DI throughout. No findings of substance. Continuous-adaptation OK.

### 2.7 S07 Quant Analytics (clean-ish)

- `regime_ml.py` 453 LOC (below threshold but close).
- **Gap**: S07 has zero ZMQ publishers. Its outputs (Hurst, GARCH, Amihud, RV) go to Redis only. S05 cannot react to live jump detection. Consider a `signal.analytics.*` topic family when 5.2 event-sourcing is being designed.
- Minor: `regime_ml.py` line 52 uses %-formatting instead of structlog; `%` logging leaks into structlog pipeline.

### 2.8 S08 Macro Intelligence — **Phase 5.8 debt visible**

- S08 is basically empty of NLP capability. `geopolitical.py` is a 77-LOC stub. No FRED connector here (FRED is in S01). No ECB/BoJ sentiment. No NewsAPI. No GDELT.
- This is where 5.8 work lands; current state is 0% toward the spec.

### 2.9 S09 Feedback Loop — partial drift monitoring

- `drift_detector.py` basic win-rate. No PSI, no rolling AUC, no Brier. This is where 5.5 work lands.

### 2.10 S10 Monitor

- Dashboard + health + alert engine present (`dashboard.py` 679 LOC, `command_api.py` 620 LOC — both large inline HTML/CSS, acceptable for MVP).
- **Gap**: Not subscribed to `risk.system.state_change`. 5.1 follow-up.
- **Gap**: No rate-limiting on WebSocket. Low priority.

### 2.11 Core shared modules

- `core/base_service.py` — clean ABC, 178 LOC, 3 public methods.
- `core/state.py` — async Redis wrapper + Phase 5.1 `SystemRiskMonitor`. Clean.
- `core/topics.py` — centralized. **Gaps**: missing `ANALYTICS_UPDATE` (constant on line 54 but no matching events), missing `execution.fill.*`, `risk.m2m.*`, `portfolio.position.*`, `feedback.drift.critical`, `feedback.recalibration.requested`, `macro.geopolitics.*`. Each gap is a Phase-5 sub-phase prerequisite.
- `core/zmq_broker.py` — XSUB/XPUB forwarder, 277 LOC, used in orchestrator startup. Stays per ADR-0001.
- `core/bus.py` — `MessageBus` wrapper. Not audited deeply here.

### 2.12 Cross-service findings

- **ZMQ contract integrity**: S01→S02→S04→S05 chain is clean. S03 standalone polling → `regime.update` consumed by S04. S05 publishes `risk.approved`/`risk.blocked`/`risk.audit`. S06 subscribes to `order.approved`.
- **Redis namespace**: No collisions. Clean prefixes (`tick:`, `signal:`, `regime:`, `pnl:`, `portfolio:`, `correlation:`, `cb:`, `risk:`, `analytics:`, `macro:`, `feedback:`, `kelly:`).
- **Decimal/UTC/structlog compliance**: Clean throughout, one minor %-style log in S07.

---

## §3. Pillar III — Documentation Coherence

Audit performed across 40+ docs files. Below is the action table (KEEP / UPDATE / CONSOLIDATE / DEPRECATE / DELETE). Only files requiring action are listed verbosely; files classified KEEP are summarized at the end.

| Path | Class | Specific action | Reason |
|---|---|---|---|
| `docs/phases/PHASE_5_SPEC.md:3` | **UPDATE** | Change "Status: Design-gate proposed — 2026-04-16" to "Status: Design-gate merged 2026-04-17 (PR #155); 5.1 merged (PR #177); 5.2–5.10 re-sequencing under audit STRATEGIC_AUDIT_2026-04-17." | Status line outdated within 24 hours. |
| `docs/phases/PHASE_5_SPEC.md` (whole) | **CONSOLIDATE / REWRITE** | Rewrite §1 dependency graph, §3.6–3.9, and §4 tracking table per re-sequencing in §6 of this audit. See §7 below for section-by-section rewrite plan. | Principles 1, 3, 7. |
| `docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md` | **UPDATE** | Insert header banner: "SUPERSEDED in part by Phase 5.1 merge 2026-04-17 — findings A-7 (S05 StateStore leak) and partial A-8 (duplicated `_build_blocked`) are now resolved. See `docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md` for current findings." | Predates 5.1. |
| `docs/audits/META_AUDIT_2026_04_11_GOVERNANCE.md` | **KEEP** (verified) | None. | Governance matrix still accurate. |
| `docs/audits/2026-04-08-quant-scaffolding-inventory.md` | **DEPRECATE** | Add top banner "ARCHIVED — Phase 3 scaffolding snapshot; Phase 3 closure report is definitive successor." | Historical; Phase 3 has closed report. |
| `docs/issues_backlog/issue_fail_closed.md` | **UPDATE** | Add footer: "**COMPLETED** — Implemented in Phase 5.1 / ADR-0006 / PR #177 (merged 2026-04-17). GitHub issue #148 CLOSED." | Work is done. |
| `docs/issues_backlog/issue_event_sourcing.md` | **KEEP** | None — but body should be refreshed after audit re-sequencing to reference the new orphan-read findings. | Still in backlog. |
| `docs/issues_backlog/issue_zmq_p2p.md` | **DEPRECATE** (if §4 recommendation accepted) | Add footer: "DEFERRED to Phase 7.5 Infrastructure Hardening per STRATEGIC_AUDIT_2026-04-17. Solo operator scale does not justify P2P topology." | Principle 3. |
| `docs/issues_backlog/issue_sbe_serialization.md` | **DEPRECATE** (if §4 recommendation accepted) | Add footer: "DEFERRED to Phase 7.5 per STRATEGIC_AUDIT_2026-04-17. JSON overhead not the production bottleneck at mid-frequency cadence." | Principle 3. |
| `docs/issues_backlog/issue_rust_hotpath.md` | **DEPRECATE** (if §4 recommendation accepted) | Add footer: "DEFERRED to Phase 7.5 per STRATEGIC_AUDIT_2026-04-17. Re-evaluate only if live 5.2+5.3 benchmarks prove Python the bottleneck." | Principle 1. |
| `docs/issues_backlog/issue_alt_data_nlp.md` | **UPDATE** | Rewrite to substitute WorldMonitor gRPC with GDELT 2.0 + FinBERT ONNX (Principle 3). | Original spec assumes paid data source the operator doesn't have. |
| `docs/issues_backlog/issue_dma_research.md` | **KEEP** | None. | Correctly deferred to Phase 6. |
| `docs/adr/0001-zmq-broker-topology.md` | **KEEP** (ACCEPTED) | None — but if §4 drop recommendation is adopted, ADR-0001 stays ACCEPTED permanently and issue_zmq_p2p note should reference it. | Supersession was predicated on 5.6; if 5.6 is dropped, ADR-0001 stands. |
| `docs/adr/ADR-0006-fail-closed-risk-controls.md` | **KEEP** (ACCEPTED) | None. | Fresh and accurate. |
| `docs/claude_memory/CONTEXT.md` | **UPDATE** | Refresh §"Phase 4 — CLOSED" → add §"Phase 5.1 — CLOSED (PR #177)", update "Active Phase" bullet, update total-tests count (now ~1833 + ~43 new in 5.1), remove Sprint-6 P1 table if it's stale (verify #82–#86 closed). | Has entries >1 week old relative to 5.1 merge. |
| `docs/claude_memory/SESSIONS.md` | **UPDATE** (normal append after this audit) | Append Session 040 entry for this audit. | Standard practice. |
| `docs/claude_memory/PHASE_4_NOTES.md` | **DEPRECATE** | Add archival banner at top; phase_4_closure_report.md is canonical. | Working notes surplus. |
| `docs/claude_memory/DECISIONS.md` | **UPDATE** | Add Phase 5.1 ADR-0006 Fail-Closed decision entry. | Decision not yet logged. |
| `AI_RULES.md` | **KEEP** | None. | Permission matrix still accurate. |
| `MANAGED_AGENTS_PLAYBOOK.md` (33 KB) | **KEEP** (unaudited in depth; flagged for spot-check only) | None now. | Large document; did not deep-read — spot-check in future. |
| `EXTENSIONS.md` | **KEEP** | None. | Placeholder, no drift. |
| `CLAUDE.md` | **KEEP** | None. | Verified against code; clean. |
| `MANIFEST.md` | **KEEP** | None. | Architecture claims verified (10 services, 5 alpha sources, Decimal/UTC/structlog). |
| `README.md` | **KEEP** | None. | Accurate. |
| `CHANGELOG.md` | **KEEP** | None (append Phase 5.1 entry as routine). | Convention says "[Unreleased]" section appropriate. |
| `docs/CONVENTIONS/COMMIT_MESSAGES.md` | **KEEP** | None. | Verified against last 20 commits. |
| All other `docs/*.md` (ARCHITECTURE, GLOSSARY, ONBOARDING, PROJECT_ROADMAP, ORCHESTRATOR_PLAYBOOK, observability, ACADEMIC_REFERENCES) | **KEEP** | Verify on next phase closure. | No contradictions surfaced in sampling. |
| `docs/pr_bodies/*.md` | **KEEP** | None. | Historical record. |

**Net**: 8 files need UPDATE, 4 need DEPRECATE (conditional on §4 recommendations). Total ~30 minutes of edits.

### 3.1 Top contradictions between docs and code

1. `PHASE_5_SPEC.md:3` "Design-gate proposed" vs reality (merged + 5.1 merged).
2. `PHASE_5_SPEC.md §3.8` specifies `WorldMonitorConnector` via proprietary gRPC — not a free data source the operator can access; no ADR justifies this vendor choice. Substitute: GDELT 2.0.
3. `AUDIT_2026_04_11_WHOLE_CODEBASE.md` finding A-7 "S05 StateStore abstraction leak" — resolved by `fail_closed.py` refactor.
4. `docs/issues_backlog/issue_fail_closed.md` — superseded by merged PR #177 but carries no completion marker.
5. `PHASE_5_SPEC.md §3.6` assumes ADR-0001 supersession in 5.6 but current code still uses XSUB/XPUB and ADR-0001 status ACCEPTED. Coherent today; will need a follow-up ADR only if 5.6 actually ships.

---

## §4. Pillar IV — Strategic Alignment vs Principles 1–7

### 4.1 Is current 5.2→5.10 sequencing the shortest path to live PnL? (Principle 1)

**No.** The current Phase 5 roadmap mixes four genuinely alpha-enabling sub-phases (5.2, 5.3, 5.4, 5.5) with three premature infrastructure sub-phases (5.6, 5.7, 5.9) and one cost-mispriced capability (5.8 as specified, not as needed). The operator currently holds a trained Phase 4 meta-labeler on disk that is *not being used* in any live path. Every week spent on ZMQ P2P or FlatBuffers is a week the meta-labeler generates $0.

### 4.2 Premature institutional mimicry flags (Principle 3)

**5.6 ZMQ Peer-to-Peer Bus (premature).**
- The spec rationale: "eliminate the SPOF of the centralized XSUB/XPUB broker". This is a valid concern at an institutional multi-host footprint. The operator runs 10 Docker containers on one host. If the host is down, every service is down whether or not the broker is centralized. The broker is not the weak link.
- Cost: 600–850 LOC + 36 tests + 3 Copilot cycles + service-registry plumbing + eventual backward-compat `LegacyBrokerTransport` adapter = estimated 2–3 weeks.
- Alpha impact: zero.
- AQR senior-quant verdict: "Why are we rewriting the transport layer? We don't even have alpha live yet. Come back when we're on three boxes and one of them flapping." **Defer.**

**5.7 SBE / FlatBuffers Serialization (premature).**
- The spec rationale: "eliminate GC pressure from JSON serialization". Real for HFT. Not real for the operator's realistic trading cadence (bars, minutes, possibly seconds). At 1 tick/sec/symbol × 10 symbols, JSON encoding is ~1 µs per tick; the whole pipeline including broker round-trip is 50–200 ms. FlatBuffers saves you 0.001% of the end-to-end time budget.
- Cost: 500–700 LOC + 36 tests + schema versioning + backward-compat JSON adapter = estimated 2 weeks.
- Alpha impact: zero.
- AQR senior-quant verdict: "GC pressure from JSON at 10 ticks/sec? I don't believe it. Profile first, migrate last." **Defer.**

**5.9 Rust FFI Hot Path (premature).**
- The spec rationale: "achieve > 1M ticks/sec/core". Stunning number for a shop buying a colocation rack in NY4. Not a number the operator can consume or even measure (no colocation, no direct market feed).
- Cost: 1500–2500 LOC + 40 Rust tests + 4 Copilot cycles + PyO3 build + new ADR-0007 + cross-language debugging = estimated 3–5 weeks.
- Alpha impact: zero (unless you can prove Python is the bottleneck, which 5.2 will likely refute by making S05 latency already bounded by the in-memory state).
- AQR senior-quant verdict: "Rust is tempting. But you have Rust already for Monte Carlo, which is the right place. Don't rewrite S05 and S01 until Python is actually too slow." **Defer.**

### 4.3 Institutional-grade capability achievable cheaply (Principle 3)

**Keep 5.8 but redirect to GDELT 2.0 + FinBERT.**
- GDELT 2.0 is free, updated every 15 min, provides event coding + tone scoring + actor identification across 300 languages.
- FinBERT is open-source; ONNX-compilable; CPU-inferable at P99 < 50 ms per text chunk.
- Combined cost: zero USD/month, ~600–900 LOC, 2–3 weeks.
- Alpha impact: real. Geopolitical-risk-aware Kelly modulation is a documented institutional edge (text-as-data literature: Tetlock 2007, Kelly et al.). For an operator lacking Bloomberg, this is a direct substitute for 15% of institutional news-flow edge.

**Other cheap-substitute opportunities to add to the Phase 6 backlog, not Phase 5:**
- FRED time-series beyond what S01 already polls (TIPS breakeven, credit spreads, financial-conditions indices).
- SEC EDGAR 8-K filings as event triggers (S01 already has `edgar_connector.py`).
- Etherscan / Mempool.space for on-chain crypto (issue #172 already tracks this for Phase 9 — fine).
- OpenBB Platform (issue #160 already tracks this for Phase 6 — fine).

### 4.4 Is the project on a credible path to live trading within 12 months? (Principle 1)

**Yes, if we cut Phase 5 scope.** With the re-sequenced critical path (5.2 → 5.3 → 5.5 → 5.4 → 5.8 → paper-trading gate → Phase 7 live paper), a realistic timeline is:

| Milestone | Wks from today | Wk ending |
|---|---|---|
| 5.2 event sourcing merged | 2 | 2026-05-01 |
| 5.3 streaming inference live | 5 | 2026-05-22 |
| 5.5 drift monitoring live | 7 | 2026-06-05 |
| 5.4 short-side + regime fusion live | 9 | 2026-06-19 |
| 5.8 GDELT/FinBERT overlay live | 12 | 2026-07-10 |
| 5.10 Phase 5 closure | 13 | 2026-07-17 |
| Phase 7 paper trading begins | 14 | 2026-07-24 |

This gives ~8 months of paper trading before the 12-month mark (2027-04-17) to decide on live capital. With the original 9-sub-phase Phase 5 (including 5.6, 5.7, 5.9), the same path adds ~7–10 weeks and consumes most of the 12-month window.

### 4.5 Senior-quant tie-breaker on the five remaining calls

| Call | Senior-quant decision | Principle |
|---|---|---|
| Decompose S05 service.py during 5.2? | Yes — refactor window is wide open since you're rewriting context loading anyway. | 4 |
| Vectorize CVDKyle (#115) before 5.3? | Yes — otherwise the streaming hot path carries O(n·w) loops. | 4 |
| Fix CI backtest-gate (#102) before any new 5.x? | Yes — blocking. | 4 |
| Add PSI + rolling AUC to 5.5 vs keep basic win-rate? | Yes — PSI is industry-standard; can't monitor an ML model with win-rate alone. | 2 |
| Let 5.4 be long-only with a direction flag, or build a separate short-side model? | Direction flag + asymmetric features in same model (spec's option A). Simpler; avoids two model-cards; can be extended later. | 7 |

---

## §5. Pillar V — Issue Backlog Actions

Sub-agent review covered 32 open issues. Highlights:

| # | Title (short) | Current state | Action | Reason |
|---|---|---|---|---|
| 148 | Fail-Closed | **CLOSED 2026-04-17T12:35:20Z** | NONE | Confirmed closed. |
| 149 | Event Sourcing (EPIC) | Open, phase-5, high, s05 | **MERGE_WITH** new thin `[phase-5.2]` issue (mirror format of #156/#157/#158) | Duplicate tracking against PHASE_5_SPEC §3.2 thin-issue convention. |
| 150 | ZMQ P2P (EPIC) | Open, phase-5, tech-debt | **CLOSE as DEFERRED** (if §4 accepted) and relabel to `phase-7.5` | Over-engineered for solo-operator scale. |
| 151 | SBE Serialization | Open, phase-5, performance | **CLOSE as DEFERRED** (if §4 accepted) and relabel to `phase-7.5` | Over-engineered. |
| 152 | Rust FFI (EPIC) | Open, phase-5, strategic | **CLOSE as DEFERRED** (if §4 accepted) and relabel to `phase-7.5` | Premature; existing Rust crates suffice. |
| 153 | Alt Data NLP (EPIC) | Open, phase-5, s01, s08 | **EDIT_BODY** to substitute GDELT 2.0 + FinBERT, **MERGE_WITH** new thin `[phase-5.8]` issue | Principle 3 substitute. |
| 154 | DMA Research | Open, research, epic | KEEP | Correctly Phase 6. |
| 156 | [phase-5.4] Short-Side | Open, thin, phase-5 | **KEEP** (re-sequence to after 5.5 per §6) | Correct thin format. |
| 157 | [phase-5.5] Drift Monitoring | Open, thin, phase-5 | **KEEP** (promote to before 5.4 per §6); **EDIT_BODY** to add PSI + rolling AUC + Brier specifics | Correct thin format; spec too sparse. |
| 158 | [phase-5.10] Closure Report | Open, thin, phase-5 | KEEP | Correct. |
| 176 | Calibrate heartbeat TTL | Open, no labels | **EDIT_LABEL** add `phase-5.5`, `s05`, `medium` | Orphan of labels; cross-link from #157. |
| 123 | Streaming mode for Phase 3 calcs | Open, phase-5 | **EDIT_LABEL** add `phase-5.3`; **EDIT_BODY** to flag dependency on CVDKyle #115 vectorization | Orphan of sub-phase tag. |
| 115 | Vectorize CVDKyleCalculator | Open, phase-5 | **KEEP**; **EDIT_LABEL** add `phase-5.3`, `perf`, promote priority:high | Verified: loops at `features/calculators/cvd_kyle.py:306, 361, 408`. On the 5.3 hot path. |
| 102 | Fix Sharpe bug + remove continue-on-error | Open, ci, medium | **KEEP**; **EDIT_LABEL** promote to `priority:high` | Verified at `.github/workflows/ci.yml:124`. Unblock before any new Phase 5 merge. |
| 137 | Multi-timeframe P3 enrichment | Open, phase-3, deferred | **EDIT_BODY** to record that Phase 4 closure did not trigger the escalation (currently ambiguous) | Audit trail hygiene. |
| 63 | Reactivate CD workflow | Open, phase-7, low | KEEP | Correct deferral. |
| 159–175 (options/FX/futures/rates/macro/crypto on-chain/lakehouse/OpenBB/streaming-SQL/orchestrator/GARCH/MC-VaR) | Open, phase-6/7/8/9/11 | **KEEP all** | Correctly scoped as future-phase deferrals. |

### 5.1 Two actionable meta-patterns

- **Duplicate tracking**: Phase 5 is currently tracked in two systems: EPIC issues #149, #150, #151, #152, #153 (rich French bodies that predate the spec) AND thin issues #156, #157, #158 (new convention). Pick one. Recommendation: retitle the EPICs to `[phase-5.N]` thin form and migrate the rich body content into the respective `docs/issues_backlog/issue_*.md`; OR close the EPICs and add thin issues for 5.2, 5.3, 5.6, 5.7, 5.8, 5.9.
- **Sub-phases 5.2, 5.3, 5.6, 5.7, 5.8, 5.9 have no thin-issue counterparts** today. If §4 drops 5.6/5.7/5.9, this gap disappears for those three and thin issues are needed only for 5.2, 5.3, 5.8.

---

## §6. Recommended Re-sequencing of Phase 5

**Abandon**: 5.6 (ZMQ P2P), 5.7 (SBE), 5.9 (Rust FFI). Move to new **Phase 7.5 Infrastructure Hardening** bucket, gated on live-trading benchmarks.

**Re-sequence Track A + 5.8 as the new critical path:**

```
5.1 Fail-Closed (DONE 2026-04-17)
  ↓
5.2 Event Sourcing / In-Memory State
    (+ orphan-read audit for portfolio/pnl/correlation keys)
    (+ S05 service.py SRP refactor — piggyback on the rewrite)
  ↓
5.3 Streaming Inference Wiring
    (+ CVDKyleCalculator vectorization, #115)
    (+ features/calculators streaming interface refactor)
  ↓
5.5 Drift Monitoring & Feedback Loop  ← MOVED UP (was after 5.4)
    (+ PSI, rolling AUC, Brier)
    (+ S05 Kelly de-risking coupling)
  ↓
5.4 Short-Side Meta-Labeler + Regime-Conditional Fusion
  ↓
5.8 Geopolitical NLP Overlay (GDELT 2.0 + FinBERT substitute)
  ↓
5.10 Phase 5 Closure Report
  → Phase 7 Paper Trading
```

**Rationale for moving 5.5 before 5.4:**

Drift monitoring is a *safety* layer (detects model decay, triggers Kelly reduction). Short-side + regime fusion is an *alpha* layer (expands the model). Principle 1 says ship safety first, alpha second — so that when 5.4 extends the model you already have the instrumentation to detect if the extension hurts. Senior-quant tie-breaker: yes.

**Cross-cutting prerequisites to land before 5.2 begins:**

1. **Unblock CI (#102)** — fix `full_report()` Sharpe bug; remove `continue-on-error` at `.github/workflows/ci.yml:124`. Blocking.
2. **Orphan-read audit for S05 batch context** — identify writers for `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix`. Without this, 5.2 design is speculative.
3. **Add missing Topics constants** — `EXECUTION_FILL`, `RISK_M2M`, `PORTFOLIO_POSITION`, `FEEDBACK_DRIFT_CRITICAL`, `FEEDBACK_RECALIBRATION_REQUESTED`, `MACRO_GEOPOLITICS` — either by sub-phase or as a single Phase-5-prerequisites PR.
4. **S10 subscribes to `risk.system.state_change`** — 5.1 follow-up debt, ~1 hour.

---

## §7. Proposed `PHASE_5_SPEC.md` Rewrite Outline

Keep the spec document but refactor it. Proposed section-by-section changes:

| Section | Action | Notes |
|---|---|---|
| Header (`**Status**:`) | **REWRITE** | "Design-gate merged 2026-04-16 (PR #155); 5.1 merged 2026-04-17 (PR #177); 5.2–5.10 under strategic re-sequencing per STRATEGIC_AUDIT_2026-04-17." |
| §1 Objective | **REWRITE** | Replace the "three pillars" framing (safety / live wiring / infra hardening) with "two tracks" (safety + alpha enablement / deferred infra hardening). |
| §1 Dependency chains | **REWRITE** | Replace Track A/B/C graph with the single critical path in §6 above. |
| §2 Prerequisites from Phase 4 Closure | **KEEP** | Table accurate. |
| §3.1 Sub-phase 5.1 | **UPDATE** status-line only → "MERGED 2026-04-17 via PR #177 (#148 CLOSED)". |
| §3.2 Sub-phase 5.2 | **KEEP** with additions | Add §"Cross-cutting prerequisites" listing orphan-read audit + new Topics constants + S05 SRP refactor as in-scope work. |
| §3.3 Sub-phase 5.3 | **KEEP** with additions | Add CVDKyle vectorization (#115) and streaming interface refactor as blocking preconditions; tighten card-validation requirement. |
| §3.4 Sub-phase 5.4 | **KEEP** with resequencing | Mark as post-5.5. |
| §3.5 Sub-phase 5.5 | **KEEP** with resequencing + body tighten | Move ahead of 5.4. Expand on PSI + rolling AUC + Brier with formula + config. |
| §3.6 Sub-phase 5.6 (ZMQ P2P) | **REMOVE** | Move to new §7 "Deferred to Phase 7.5" appendix. Reasoning: Principles 1, 3, 7. |
| §3.7 Sub-phase 5.7 (SBE) | **REMOVE** | Ditto. |
| §3.8 Sub-phase 5.8 (NLP) | **REWRITE** | Replace `WorldMonitorConnector` with GDELT 2.0 Connector (S01 extension, public HTTP feed) + FinBERT ONNX scorer (S08). Update LOC estimates. |
| §3.9 Sub-phase 5.9 (Rust FFI) | **REMOVE** | Move to Phase 7.5 appendix. |
| §3.10 Sub-phase 5.10 (Closure) | **KEEP** | Renumber section if needed. |
| §4 Sub-phase tracking table | **REWRITE** | Drop 5.6/5.7/5.9 rows. Re-order 5.4↔5.5. |
| §5 Transverse concerns | **KEEP** (minor: update coverage gate value if raising). |
| §6 Risks | **REWRITE** | Remove risks specific to 5.6/5.7/5.9; add "Orphan-read trap in S05 context load" as new row; add "CI backtest-gate muzzle" as new row. |
| §7 Phase 6 preview | **EXPAND** | Add Phase 7.5 preview (ZMQ P2P, SBE, Rust FFI — conditional on live benchmarks). |
| §8 References | **KEEP** (remove FIX/SBE refs if 5.7 removed; keep Aeron ref in Phase 7.5 preview). |

---

## §8. Recommended Action Plan — Next 4 Weeks (Priority Order)

Assumes §4 re-sequencing is accepted. Owner column: "Claude" = I can execute on approval; "Clement" = operator decision required first.

| # | Action | Owner | Sub-phase | Effort |
|---|---|---|---|---|
| 1 | Fix `full_report()` Sharpe bug and remove `continue-on-error` at `.github/workflows/ci.yml:124` (#102) | Claude | prereq | 0.5d |
| 2 | Audit `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix` writers; fix any orphan read | Claude | prereq | 1d |
| 3 | Add missing Topics constants (`EXECUTION_FILL`, `RISK_M2M`, `PORTFOLIO_POSITION`, `FEEDBACK_DRIFT_CRITICAL`, `FEEDBACK_RECALIBRATION_REQUESTED`, `MACRO_GEOPOLITICS`) | Claude | prereq | 0.5d |
| 4 | Wire S10 subscription to `risk.system.state_change` (5.1 debt) | Claude | 5.1-debt | 0.5d |
| 5 | Decide re-sequencing (accept/reject §4) and rewrite `PHASE_5_SPEC.md` per §7 | Clement + Claude | docs | 1d |
| 6 | Doc maintenance: update `PHASE_5_SPEC.md`, `CONTEXT.md`, `AUDIT_2026_04_11_WHOLE_CODEBASE.md`, `issue_fail_closed.md`, deprecation banners on 5.6/5.7/5.9 backlog MDs (if accepted) | Claude | docs | 0.5d |
| 7 | Close or merge duplicate GitHub issues #149–#153; open thin `[phase-5.2]`, `[phase-5.3]`, `[phase-5.8]` issues | Clement | governance | 0.5d |
| 8 | Refactor `services/s05_risk_manager/service.py` (530 LOC) into `RiskChainOrchestrator` + `ContextLoader` + `RiskDecisionBuilder` — combine with 5.2 | Claude | 5.2 | 2d |
| 9 | Implement `InMemoryRiskState` + `reconciliation.py` (5.2 core) | Claude | 5.2 | 3d |
| 10 | Vectorize CVDKyleCalculator loops (#115) | Claude | 5.3-prep | 1d |
| 11 | Decompose `services/s02_signal_engine/pipeline.py` (487 LOC) into step classes ahead of 5.3 streaming | Claude | 5.3-prep | 2d |

Total: ~13 dev-days over 4 weeks = Phase 5.2 delivered plus full 5.3 groundwork laid.

---

## §9. Open Questions Requiring Clement's Decision

1. **Accept re-sequencing?** Drop 5.6, 5.7, 5.9 from Phase 5; move to Phase 7.5. Move 5.5 before 5.4. (Principles 1, 3, 7.)
2. **Accept GDELT substitute for 5.8?** Replace spec'd `WorldMonitorConnector` (proprietary gRPC) with GDELT 2.0 free feed + FinBERT ONNX. (Principle 3.)
3. **Accept CI #102 as blocking?** Promote to `priority:high` and fix before any other Phase 5 work.
4. **Accept S05 service.py SRP refactor piggyback onto 5.2?** Alternative: ship 5.2 without refactor, open a follow-up PR.
5. **Backlog governance**: retitle EPIC issues #149/#150/#151/#152/#153 to thin `[phase-5.N]` form, or close them and open fresh thin issues?
6. **Is S07 ZMQ publishing gap in scope for 5.2 or a separate ticket?** (Currently S07 writes analytics only to Redis.)
7. **CVDKyle vectorization (#115)** — part of 5.3-prep as listed, or standalone priority?

---

## §10. Appendix — Raw Evidence Traceability

Every claim in §1–§5 is supported by one of:

- **File presence / absence**: verified via `Glob` searches recorded in the audit tool-call log. Key absences: `services/s05_risk_manager/in_memory_state.py`, `services/s05_risk_manager/reconciliation.py`, `services/s02_signal_engine/streaming_adapter.py`, `services/s04_fusion_engine/live_meta_labeler.py`, `services/s08_macro_intelligence/nlp/*`, `services/s01_data_ingestion/connectors/worldmonitor.py`, `core/transport.py`, `core/service_registry.py`, `core/schemas/*.fbs`.
- **File presence verified**: `core/state.py:365–600` (SystemRiskMonitor), `services/s05_risk_manager/fail_closed.py`, `features/meta_labeler/baseline.py` + `fusion/ic_weighted.py`, `rust/apex_mc/src/lib.rs`, `rust/apex_risk/src/{exposure.rs,lib.rs}`.
- **Line citations**: `core/topics.py:48` (RISK_SYSTEM_STATE_CHANGE), `.github/workflows/ci.yml:124` (continue-on-error TODO), `services/s05_risk_manager/service.py:411–487` (Redis context load), `features/calculators/cvd_kyle.py:306, 361, 408` (`for t in range(...)`).
- **GitHub**: `gh issue view 148` returned `{"closedAt":"2026-04-17T12:35:20Z","state":"CLOSED"}`. `gh issue list` returned 32 open issues enumerated in §5.
- **Git log**: `git log --oneline -20` — main at `1b7c3b5`, PR #177 merged 2026-04-17.
- **Sub-agent tool outputs**: four parallel Explore / general-purpose agents covering S01-S05, S06-S10 + core + features + rust, docs coherence, and GitHub issue backlog. Each produced structured reports with file:line citations; findings are consolidated here.

---

# EXECUTABLE ACTIONS

Each action below is atomic, reversible, and linked to an audit finding. Actions are NOT executed — this is a proposal list for Clement to approve/reject/modify.

Types: DOC | CODE | ISSUE | TEST | CONFIG | CI.
Effort: S (<1h), M (1–4h), L (half-day–day), XL (>1 day).

### A. Unblocking prerequisites (land before any new Phase 5 sub-phase)

- **ACTION 1 (CI, M)**: Edit `.github/workflows/ci.yml:124` — remove `continue-on-error: true` on backtest-gate after fixing `full_report()` Sharpe bug in `backtesting/metrics.py` (or `scripts/backtest_regression.py`). Close issue #102. Reason: §8 item 1; Principle 4 enforcement of alpha quality gate.
- **ACTION 2 (CODE, L)**: Grep for writers of Redis keys `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix` across the codebase. Per orphan write found, either (a) add writer in the appropriate service, (b) refactor S05 to seed defaults from config, or (c) remove the read from S05's context batch if the key is not required for risk checks. Output: a short markdown addendum to this audit. Reason: §1.2 orphan-read trap; blocking for 5.2.
- **ACTION 3 (CODE, S)**: Edit `core/topics.py` — add constants `EXECUTION_FILL = "execution.fill"`, `RISK_M2M = "risk.m2m"`, `PORTFOLIO_POSITION = "portfolio.position"`, `FEEDBACK_DRIFT_CRITICAL = "feedback.drift.critical"`, `FEEDBACK_RECALIBRATION_REQUESTED = "feedback.recalibration.requested"`, `MACRO_GEOPOLITICS = "macro.geopolitics"`. Add matching helper methods if warranted. Reason: §1.2, §1.5, §1.8; prerequisite for 5.2 / 5.5 / 5.8.
- **ACTION 4 (CODE, S)**: Add subscription to `Topics.RISK_SYSTEM_STATE_CHANGE` in `services/s10_monitor/service.py` and a handler that updates the dashboard "System State" widget in `dashboard.py`. Reason: §1.1 residual 5.1 debt; Principle 4 safety observability.

### B. Doc maintenance (after re-sequencing decided)

- **ACTION 5 (DOC, S)**: Edit `docs/phases/PHASE_5_SPEC.md:3` — status line refresh per §3 table. Reason: §3 contradiction #1.
- **ACTION 6 (DOC, L)**: Rewrite `docs/phases/PHASE_5_SPEC.md` per §7 outline. Reason: §4 re-sequencing + §3 contradictions.
- **ACTION 7 (DOC, S)**: Prepend supersession banner to `docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md` per §3 table. Reason: A-7 resolved.
- **ACTION 8 (DOC, S)**: Prepend ARCHIVED banner to `docs/audits/2026-04-08-quant-scaffolding-inventory.md`. Reason: Phase 3 closure report is canonical.
- **ACTION 9 (DOC, S)**: Append COMPLETED footer to `docs/issues_backlog/issue_fail_closed.md` referencing PR #177 and ADR-0006. Reason: §3 contradiction #4.
- **ACTION 10 (DOC, S)** *(conditional on §4 acceptance)*: Prepend DEFERRED banner to `docs/issues_backlog/issue_zmq_p2p.md`, `issue_sbe_serialization.md`, `issue_rust_hotpath.md` with pointer to Phase 7.5 bucket. Reason: §4.2.
- **ACTION 11 (DOC, M)**: Rewrite `docs/issues_backlog/issue_alt_data_nlp.md` to substitute `WorldMonitorConnector` with `GDELTConnector` (HTTP, free) + FinBERT ONNX. Reason: §4.3, Principle 3.
- **ACTION 12 (DOC, S)**: Append "Phase 5.1 Fail-Closed (ADR-0006) — MERGED" entry to `docs/claude_memory/DECISIONS.md`. Reason: Decision not logged.
- **ACTION 13 (DOC, M)**: Update `docs/claude_memory/CONTEXT.md` — add Phase 5.1 closure block; refresh Active Phase bullet; clean up stale Sprint-6 table if issues verified closed. Reason: §3 table.
- **ACTION 14 (DOC, S)**: Append Session 040 entry to `docs/claude_memory/SESSIONS.md` summarizing this audit. Reason: Standard practice.
- **ACTION 15 (DOC, S)**: Prepend ARCHIVED banner to `docs/claude_memory/PHASE_4_NOTES.md`. Reason: phase_4_closure_report.md is canonical.

### C. Backlog governance

- **ACTION 16 (ISSUE, S)** *(conditional on §4 acceptance)*: Close GitHub issues #150, #151, #152 as `DEFERRED to Phase 7.5` with explanatory comment linking to this audit. Reason: §4.2.
- **ACTION 17 (ISSUE, S)**: Decide retitle vs close for #149, #153; if close, open new thin `[phase-5.2]` and `[phase-5.8]` issues mirroring #156/#157/#158 format. Reason: §5.1 duplicate tracking.
- **ACTION 18 (ISSUE, S)**: Open new thin `[phase-5.3]` GitHub issue for Streaming Inference Wiring. Reason: §5.1 gap.
- **ACTION 19 (ISSUE, S)**: Edit labels on issue #176 — add `phase-5`, `phase-5.5`, `s05`, `medium`; cross-link from #157. Reason: orphan labels.
- **ACTION 20 (ISSUE, S)**: Edit labels on issue #123 — add `phase-5.3`; edit body to flag dependency on #115. Reason: §1.3, §5.
- **ACTION 21 (ISSUE, S)**: Edit labels on issue #115 — add `phase-5.3`, `perf`; promote to priority:high. Reason: §1.3 on the 5.3 hot path.
- **ACTION 22 (ISSUE, S)**: Edit labels on issue #102 — promote to priority:high. Reason: blocking per §8.
- **ACTION 23 (ISSUE, S)**: Edit body of issue #137 — record whether Phase 4 closure #147 triggered the multi-timeframe escalation condition (currently ambiguous). Reason: audit trail hygiene.
- **ACTION 24 (ISSUE, M)**: Edit body of issue #157 — add PSI + rolling AUC + Brier specifics per §1.5 and PHASE_5_SPEC §3.5. Reason: thin issue currently too sparse.

### D. Code refactor (piggyback on 5.2)

- **ACTION 25 (CODE, L)**: Decompose `services/s05_risk_manager/service.py` (530 LOC) into `service.py` (lifecycle only), `chain_orchestrator.py` (fail-fast chain), `context_loader.py` (context batch or event-sourced reader), `decision_builder.py`. Reason: §2.5 SOLID-S; natural 5.2 refactor window.
- **ACTION 26 (CODE, L)**: Decompose `services/s02_signal_engine/pipeline.py` (487 LOC) into step classes (one class per stage of `_run()`), with explicit `execute(state) -> state` contract and unit tests per step. Reason: §2.2 blocking 5.3 streaming adapter.
- **ACTION 27 (CODE, L)**: Vectorize `features/calculators/cvd_kyle.py` loops at lines 306, 361, 408 using polars / numpy. Reason: §1.3 on the 5.3 hot path; issue #115.

### E. CLAUDE.md update (deferred — no changes recommended in this audit)

- **ACTION 28 (DOC, S)**: Keep `CLAUDE.md` as-is — verified accurate against code in §3. No executable action.

---

## §11. What this audit explicitly did NOT touch

- **Deep audit of `MANAGED_AGENTS_PLAYBOOK.md` (33 KB)** — spot-check only; recommend spot-check in next session.
- **Full-text audit of `PROJECT_ROADMAP.md` (1439 lines)** — only §1 strategic vision read; spot-check later for internal consistency with this audit's re-sequencing.
- **Rust crate source quality** — verified presence + PyO3 compatibility only; not line-level reviewed.
- **Grafana dashboards** (`docs/grafana/`) — not audited.
- **`MANIFEST.md` comprehensive re-read** — spot-checked against code; no contradictions surfaced in the topics/models/services sections.

---

**END OF AUDIT.**
