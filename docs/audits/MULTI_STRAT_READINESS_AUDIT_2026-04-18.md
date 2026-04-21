# APEX Multi-Strategy Platform Readiness Audit

**Date**: 2026-04-18
**Anchor commit**: `d53ef4e` (branch `fix/ci-backtest-gate-sharpe`, post Phase 5.1 + Batch A–E audit cleanup, main HEAD `a40dca5`)
**Auditor**: Claude Opus 4.7 (claude.ai, Head of Architecture Review), orchestrator of 6 parallel Explore sub-agents
**Mode**: READ-ONLY. No source code, docs, GitHub issues, branches, or PRs modified. Only this report file was written.
**Companion audit**: `docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md` (referenced, not duplicated)

---

## §0. Executive Verdict

**Verdict: READY-WITH-GAPS — leaning toward NOT-READY on the signal pipeline.**

The APEX codebase is in excellent *single-strategy* engineering health. Foundations that matter for a multi-strategy platform are present and well-designed (frozen Pydantic contracts, centralized ZMQ topics, `FeatureCalculator` ABC with dependency injection, CPCV walk-forward, Chain-of-Responsibility risk guards post-Batch D). Every service is asyncio-only, Decimal-only, UTC-only, with structured logging. The Phase 3 feature layer in particular is genuinely multi-strategy-ready today.

**However**, the system has no concept of a `strategy_id` anywhere — zero hits across `core/models/*`, zero hits in S05, zero hits in S02 — and the two services that would host multi-strategy orchestration (S02 Signal Engine, S04 Fusion Engine) are architected as a **single global signal path** with hardcoded 5-component confluence, regime-deterministic strategy selection, and no allocator abstraction. The backtest engine cannot replay a portfolio of strategies, S09 pools all trades under one global `trades:all` Redis list, S10 has zero per-strategy panels, and there is no `docs/STRATEGY_LIFECYCLE.md` to onboard a new agent onto Strategy #2.

This is not a fatal situation — it is a deliberate Phase 1 contract-complete-for-one-strategy design choice — but committing to the Strategy Research Charter as-written (6 heterogeneous strategies, different timeframes, different asset classes, different signals) without addressing the P0 gaps below would cause weeks of rework as Strategy #2 collides with Strategy #1 on `signal.technical.*`, fights for capital in S05 with no per-strategy book, and is invisible in S09/S10.

**A senior infra lead at Citadel/Millennium hosting 20+ strategy pods would not sign off on the current architecture for a multi-strat deployment.** They would demand (at minimum): strategy_id on every cross-boundary model, a StrategyAllocator abstraction between S04 and S05, per-strategy Redis partitioning in S09, and a documented strategy lifecycle. That said — none of the gaps are structural rewrites. They are *additions*. Nothing that currently works needs to be unwritten (Principle 6).

### ✅ What is definitively READY for multi-strat

- **Frozen Pydantic v2 contracts everywhere** — Signal, OrderCandidate, ApprovedOrder, ExecutedOrder, TradeRecord, Regime, Bar, NormalizedTick. Adding `strategy_id: str` as a new field is an additive, backwards-preserving change.
- **Centralized ZMQ topics** (`core/topics.py` — 30 constants + 4 factory helpers). Clean single source of truth. Factories enable per-strategy suffixes (`signal.technical.strat1.BTCUSDT`) without breaking consumers.
- **Feature layer is multi-strategy-ready today** — `FeatureCalculator` ABC (features/base.py:19), `FeaturePipeline` accepts `calculators: list[FeatureCalculator]` via constructor injection (pipeline.py:53–63), each calculator is a pure function with no global state, `FeatureRegistry` + `FeatureStore` support point-in-time per-strategy feature subsets. Strategy A (HAR-RV + Rough Vol) and Strategy B (OFI + CVD) can coexist with zero code change in features/.
- **CPCV walk-forward with embargo/purging** exists in `backtesting/walk_forward.py:374` (CombinatorialPurgedCV) with PBO and deployment-gate recommendation (DEPLOY / INVESTIGATE / DISCARD) already in place — ready to validate each strategy independently.
- **Risk Manager Chain-of-Responsibility decomposition post-Batch D** (6 guards in `services/risk_manager/chain_orchestrator.py`) is the correct structural shape to later host a `PerStrategyExposureGuard`.
- **Data layer breadth** — S01 already connects Alpaca (equities), Binance (crypto), Yahoo (ETFs/FX/indices), FRED (macro), EDGAR+SimFin (fundamentals). Multi-asset NormalizedBar schema is consistent across asset classes via `AssetClass` enum and `Bar` model.
- **Core infrastructure** — BaseService ABC, StateStore, MessageBus (ZMQ XSUB/XPUB broker per ADR-0001), Redis/fakeredis seam, Rust FFI (`apex_mc`, `apex_risk`), mypy strict, 75% coverage gate, 1,833+ unit tests.

### ⚠️ What has gaps (1–3 days of work each)

- **`strategy_id` field missing on Signal, OrderCandidate, ApprovedOrder, ExecutedOrder, TradeRecord.** Single field addition on 5 frozen models + allow-list migration in downstream consumers. ~1 day.
- **Topic factory for per-strategy suffix** — add `Topics.signal_for(strategy_id, symbol)` → `signal.technical.{strategy_id}.{symbol}` in `core/topics.py` + update S02/S04 subscribe/publish to use it. ~0.5 day.
- **Per-strategy Redis key partitioning in S09** — `trades:all` → `trades:{strategy_id}:all`; `kelly:{symbol}` → `kelly:{strategy_id}:{symbol}`. DriftDetector already per-symbol-capable, add strategy dimension. ~1 day.
- **S10 dashboard per-strategy panels** — add strategy filter to `services/command_center/dashboard.py` (0 current hits for "strategy"). ~1 day.
- **CI `backtest-gate` still muzzled** (`continue-on-error: true`, .github/workflows/ci.yml:130). Issue #102 in-flight on current branch `fix/ci-backtest-gate-sharpe`. Unblocks Sharpe ≥ 0.8 / DD ≤ 8% enforcement per CLAUDE.md §6. ~done-in-flight.
- **`docs/STRATEGY_LIFECYCLE.md` does not exist.** No "how to add a strategy" guide. Agents handed Strategy #2 tomorrow would reverse-engineer from code. ~1 day to write.

### 🔴 What has fundamental gaps (architectural refactor before multi-strat begins)

- **S02 Signal Engine is single-path and non-pluggable.** `services/signal_engine/pipeline.py` has a 290-LOC `_run()` method hardcoded around a 5-component `SignalComponent` list. No ABC for signal generators. No registry. Adding Strategy #2 (mean-reversion intraday equities) requires modifying `pipeline.py` + `signal_scorer.py` directly, which will Git-conflict with Strategy #1 work. **Fix**: introduce `StrategyRunner` ABC + registry pattern, make each of the 6 strategies a plug-in that S02 loads by config. ~1–2 weeks. Principle-2 critical for multi-strat.
- **S04 Fusion Engine is fundamentally single-strategy-per-signal.** `services/fusion_engine/service.py` selects ONE strategy per signal via `StrategyRegistry` (4 hardcoded strategies: momentum_scalp, mean_reversion, spike_scalp, short_momentum), determined by **current regime**, not by signal provenance. If Strategy A and Strategy B both emit on `signal.technical.BTCUSDT`, they produce two independent `OrderCandidate`s with no portfolio aggregation, no position netting, no cross-strategy capital allocation. **No allocator abstraction exists anywhere in the codebase** (zero grep hits for `StrategyAllocator`, `PortfolioAllocator`, `RiskParity`, `BlackLitterman`). **Fix**: extract S04 into (signal-level fusion per strategy) + new `S11 StrategyAllocator` service that consumes per-strategy OrderCandidates and publishes portfolio-netted candidates. ~2–3 weeks. Principle-2 critical.
- **Backtest engine cannot replay a portfolio.** `BacktestEngine.run(ticks)` returns `list[TradeRecord]`. No `Strategy` ABC, no `run_portfolio(strategies, allocator, data)`, no per-strategy breakdown in `full_report()`. Multi-strategy validation (required for Charter sign-off on Strategy #1) is impossible today. ~1–2 weeks.
- **S05 Chain Orchestrator violates Open/Closed.** Guards are wired by constructor injection in `RiskChainOrchestrator.__init__()` (chain_orchestrator.py:81–96) with `process()` linking them in hardcoded order. Adding `PerStrategyExposureGuard` requires modifying the orchestrator. **Fix**: make the chain data-driven (list of guards passed in, ordered). ~2–3 days.

### Single-sentence top recommendation

**Do NOT proceed to the Strategy Research Charter interview until a 2-week "multi-strat infrastructure lift" is merged**, specifically: (i) `strategy_id` added to core models + topic factories, (ii) S02 refactored to a plug-in `StrategyRunner` architecture, (iii) a new `S11_strategy_allocator` microservice (or a rigorous S04 multi-strategy refactor) between S04 and S05, (iv) per-strategy Redis partitioning in S09 and dashboard, (v) `run_portfolio` + per-strategy breakdowns in the backtest engine, (vi) `docs/STRATEGY_LIFECYCLE.md` published — then and only then invest the 1–2h Charter interview, because otherwise the Charter will be aspirational against infrastructure that cannot host it.

---

## §1. Service Inventory

Factsheets use LOC from `wc -l` or agent-reported counts. Topics are traced from `core/topics.py` + direct grep in each service.

### S01 — Data Ingestion
- **Purpose**: Market-data, macro, calendar, fundamentals connectors; normalizers; quality checks; TimescaleDB serving layer.
- **LOC**: ~9,583 prod (78 Python files, largest service by far — ref. STRATEGIC_AUDIT_2026-04-17 §2.1). Tests: ~15,000+ LOC.
- **Key modules**: `service.py` (186 LOC), `connectors/` (21 files, historical + live + calendar + fundamentals), `normalizers/` (14 files + router), `orchestrator/` (9 files, backfill/scheduler), `quality/` (10 files), `observability/` (5 files), `serving/` (6 files FastAPI + Timescale).
- **ZMQ published**: `tick.crypto.*`, `tick.us_equity.*`, `tick.futures.*`, `macro.update`. Session patterns via `session.pattern.*` (S03-bound). Health via `service.health.s01_data_ingestion`.
- **ZMQ subscribed**: None (source-of-truth service).
- **Redis writes**: `session:current` (likely), `macro:vix_current`, `macro:vix_1h_ago` (writers unverified per STRATEGIC_AUDIT §1.2 orphan-read trap).
- **Redis reads**: Asset registry, connector state.
- **External**: Alpaca (alpaca-py), Binance (REST+WS), Yahoo, FRED, Massive, SimFin, SEC EDGAR, BOJ/ECB/FOMC scrapers, TimescaleDB (`asyncpg`), Prometheus, OpenTelemetry.
- **Tests**: `tests/unit/s01_*/` (~40 test files), `tests/integration/s01_*/`.

### S02 — Signal Engine
- **Purpose**: Generate technical signals from tick stream. Multi-component confluence scoring + multi-timeframe alignment.
- **LOC**: 1,986 prod (9 files). `pipeline.py` 487, `technical.py` 454, `crowd_behavior.py` 230, `vpin.py` 200, `microstructure.py` 194, `mtf_aligner.py` 171, `service.py` 155, `signal_scorer.py` 94.
- **Key modules**: `SignalEngineService`, `SignalPipeline` (7-stage `_run()`), `TechnicalAnalyzer`, `MicrostructureAnalyzer`, `VPINCalculator`, `MTFAligner`, `CrowdBehaviorAnalyzer`, `SignalScorer`.
- **ZMQ published**: `signal.technical.{symbol}` (service.py:135).
- **ZMQ subscribed**: `tick.*` prefix (service.py:31, 111).
- **Redis writes**: `signal:{symbol}` (service.py:139).
- **Redis reads**: None on hot path.
- **External**: None (pure computation on NormalizedTick stream).
- **Tests**: `tests/unit/s02_*/` (full coverage of all analyzers, pipeline stages, scorer, vpin, mtf).

### S03 — Regime Detector
- **Purpose**: Continuously recompute `macro_mult`, `session_mult`, trend/vol regimes, risk mode. ~30s cadence per CLAUDE.md §3.
- **LOC**: 816 prod (5 files). `regime_engine.py`, `session_tracker.py`, `cb_calendar.py`, `service.py` (192 LOC).
- **ZMQ published**: `regime.update`, `session.pattern.*`, `macro.catalyst.*`.
- **ZMQ subscribed**: `macro.update`, `tick.*` (VIX proxy).
- **Redis writes**: `regime:current`, `session:current`, CB calendar cache.
- **Redis reads**: Macro series cache.
- **Tests**: `tests/unit/s03_*/`.

### S04 — Fusion Engine
- **Purpose**: Per-signal regime-gated fusion scoring + Kelly sizing + meta-label veto → `OrderCandidate`.
- **LOC**: 1,134 prod (7 files). `service.py` 238, `meta_labeler.py` 264, `kelly_sizer.py` 167, `feature_logger.py` 136, `strategy.py` 124 (registry of 4 hardcoded strategies), `fusion.py` 116, `hedge_trigger.py` 88.
- **ZMQ published**: `order.candidate` (service.py:27, 203).
- **ZMQ subscribed**: `signal.technical.*` prefix (service.py:26, 86).
- **Redis writes**: `meta_label:latest:{symbol}` (referenced by S05).
- **Redis reads**: `regime:current`, `analytics:fast`, rolling Kelly stats.
- **External**: joblib-loaded meta-labeler model, ICWeightedFusion (stateless).
- **Tests**: `tests/unit/s04_*/` (Kelly, fusion, meta-labeler, strategy selector).

### S05 — Risk Manager
- **Purpose**: VETO-mode pre-trade risk validation. Chain of Responsibility with 6 guards post-Batch D.
- **LOC**: 2,036 prod (12 files). `circuit_breaker.py` 303, `chain_orchestrator.py` 285, `service.py` 238, `exposure_monitor.py` 186, `models.py` 185, `meta_label_gate.py` 183, `cb_event_guard.py` 164, `position_rules.py` 161, `context_loader.py` 130, `decision_builder.py` 105, `fail_closed.py` 95 (ADR-0006).
- **Key modules**: `RiskChainOrchestrator` (STEP 0 Fail-Closed → 1 CB Event → 2 Circuit Breaker → 3 Meta-Label Gate → 4 Position Rules (×4) → 5 Exposure Monitor (×4)).
- **ZMQ published**: `risk.approved`, `risk.blocked`, `risk.audit`, `risk.system.state_change` (via SystemRiskMonitor per ADR-0006).
- **ZMQ subscribed**: `order.candidate`.
- **Redis writes**: `risk:circuit_breaker:state`, `risk:heartbeat` (5.1).
- **Redis reads**: `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix`, `session:current`, `macro:vix_current`, `meta_label:latest:{symbol}`. **WARN**: 5 of these have unverified writers (STRATEGIC_AUDIT §1.2 orphan-read trap).
- **Tests**: `tests/unit/s05_*/`, full coverage of each guard.

### S06 — Execution
- **Purpose**: Broker routing (Alpaca / Binance / paper). Slippage + commission accounting.
- **LOC**: ~500–700 prod (estimated from file list: `broker_alpaca.py`, `broker_binance.py`, `broker_base.py`, `service.py` 193 LOC, `broker_factory.py`).
- **Key modules**: `Broker` ABC (broker_base.py), `AlpacaBroker`, `BinanceBroker`, paper broker, `broker_factory`.
- **ZMQ published**: `order.submitted`, `order.filled`, `order.cancelled`, `order.partial`.
- **ZMQ subscribed**: `risk.approved`.
- **External**: alpaca-py, binance (python-binance or similar), IP-whitelisted write-only API keys per CLAUDE.md §11.
- **Tests**: `tests/unit/s06_*/`, broker factory + per-broker adapters.

### S07 — Quant Analytics
- **Purpose**: Rolling statistical updates (Hurst, GARCH, Amihud, Jump Detection, Rough Vol — fast 5-min loop; Sharpe, Sortino, Calmar — slow 1-h loop).
- **LOC**: ~1,800+ prod including modules under s07 (`service.py` 134 + analytics modules).
- **ZMQ published**: `analytics.update`.
- **ZMQ subscribed**: `tick.*` for rolling buffers.
- **Redis writes**: `analytics:fast`, `analytics:slow`.
- **Tests**: `tests/unit/s07_*/`.

### S08 — Macro Intelligence
- **Purpose**: CB calendar watcher (`cb_watcher.py`), economic surprise index (`surprise_index.py`), sector rotation, geopolitical stub (77-LOC `geopolitical.py` placeholder — Phase 5.8 pending).
- **LOC**: ~500 prod (5 files). `service.py` 95 LOC.
- **ZMQ published**: `macro.catalyst.*` (FOMC/ECB/BOJ events).
- **ZMQ subscribed**: `macro.update`.
- **Tests**: `tests/unit/s08_*/`.

### S09 — Feedback Loop
- **Purpose**: Post-trade rolling win-rate, Kelly stats update, drift detection. Does NOT auto-adjust; alerts only.
- **LOC**: ~500–700 prod. `service.py`, `drift_detector.py` (~160 LOC), `trade_analyzer.py`, `signal_quality.py`.
- **ZMQ published**: `feedback.drift_alert`.
- **ZMQ subscribed**: `order.filled` (trade persistence).
- **Redis writes**: `kelly:{symbol}` (win_rate, avg_rr — **NOTE: per-symbol only, not per-strategy**), `feedback:baseline_win_rate`.
- **Redis reads**: `trades:all` (global trade list — **NOT per-strategy**).
- **Tests**: `tests/unit/s09_*/`.

### S10 — Monitor
- **Purpose**: FastAPI + Jinja2 dashboard, alerting engine (SMTP + Twilio), Prometheus scrape endpoints.
- **LOC**: ~1,500+ prod (`service.py` 175, `dashboard.py`, `alert_engine.py`, `command_api.py`, `metrics.py`).
- **ZMQ subscribed**: `service.health.*`, `risk.audit`, `risk.approved`, `risk.blocked`, `order.filled`, `regime.update`. **NOT** subscribed to `risk.system.state_change` per STRATEGIC_AUDIT §1.1 (Phase 5.1 follow-up debt).
- **Redis reads**: Everything (read-only dashboard per CLAUDE.md §11).
- **External**: HTTP dashboard (read-only, cannot trigger orders).
- **Tests**: `tests/unit/s10_*/`.

---

## §2. Contract Surface

### 2.1 ZMQ topics (core/topics.py, full authoritative list)

| Topic | Publisher | Subscriber(s) |
|---|---|---|
| `tick.crypto.*` | S01 | S02, S03, S07 |
| `tick.us_equity.*` | S01 | S02, S03, S07 |
| `tick.futures.*` | S01 (placeholder) | — |
| `macro.update` | S01 | S03, S08 |
| `signal.technical.*` | S02 | S04 |
| `signal.validated` | (unused today) | — |
| `regime.update` | S03 | S04, S05 (indirect via Redis), S10 |
| `macro.catalyst.*` | S08 (CB events) | S05 (CBEventGuard) |
| `session.pattern.*` | S03 | S10 |
| `order.candidate` | S04 | S05 |
| `order.approved` | S05 | S06 |
| `order.blocked` | S05 | S10 |
| `order.submitted` | S06 | S10 |
| `order.filled` | S06 | S09, S10 |
| `order.cancelled` | S06 | S10 |
| `order.partial` | S06 | S10 |
| `risk.breach` | S05 | S10 |
| `risk.circuit_open` | S05 | S10 |
| `risk.circuit_closed` | S05 | S10 |
| `risk.approved` | S05 | S06, S10 (audit) |
| `risk.blocked` | S05 | S10 |
| `risk.cb.tripped` | S05 | S10 |
| `risk.audit` | S05 | S10 |
| `risk.system.state_change` (ADR-0006) | SystemRiskMonitor | **S10 NOT subscribed — debt** |
| `service.health.*` | all S0x | supervisor |
| `analytics.update` | S07 | S04 |
| `analytics.meta_features` | S04 | S09 (training data) |
| `feedback.drift_alert` | S09 | S10 |

**Factories**: `Topics.tick(market, symbol)`, `Topics.signal(symbol)`, `Topics.health(service_id)`, `Topics.catalyst(event_type)`. **NO factory for per-strategy suffix.**

### 2.2 Redis keys (writer/reader map, evidence from S05 context_loader + STRATEGIC_AUDIT §1.2)

| Key | Writer | Reader |
|---|---|---|
| `regime:current` | S03 | S04, S05 |
| `session:current` | S03 (session_tracker) | S05 |
| `macro:vix_current` / `macro:vix_1h_ago` | S01 macro_feed (assumed) | S05 |
| `portfolio:capital` | **UNVERIFIED** | S05 |
| `pnl:daily` | **UNVERIFIED** | S05 |
| `pnl:intraday_30m` | **UNVERIFIED** | S05 |
| `portfolio:positions` | **UNVERIFIED** | S05 |
| `correlation:matrix` | **UNVERIFIED** | S05 |
| `signal:{symbol}` | S02 | (cache only) |
| `meta_label:latest:{symbol}` | S04 | S05 meta_label_gate |
| `analytics:fast` / `analytics:slow` | S07 | S04, S10 |
| `kelly:{symbol}` (hash: win_rate, avg_rr) | S09 | S04 KellySizer |
| `trades:all` (Redis list) | S06/S09 persistence | S09 fast_analysis |
| `risk:circuit_breaker:state` | S05 CircuitBreaker | S05 CircuitBreaker |
| `risk:heartbeat` (Phase 5.1) | SystemRiskMonitor | FailClosedGuard |
| `feedback:baseline_win_rate` | S09 | S09 DriftDetector |

**CRITICAL OBSERVATION for multi-strat**: every key is GLOBAL. None are strategy-partitioned. `kelly:{symbol}`, `trades:all`, `portfolio:capital`, `pnl:daily` — all are single-book, single-strategy keys.

### 2.3 Pydantic models (core/models/*)

All **frozen** (`ConfigDict(frozen=True)`). **Zero `strategy_id` fields across all models.**

| File | Class | Frozen | Strategy-aware? |
|---|---|---|---|
| tick.py | RawTick, NormalizedTick | ✓ | No |
| signal.py | Signal, MTFContext, TechnicalFeatures | ✓ | **No** |
| order.py | OrderCandidate, ApprovedOrder, ExecutedOrder, TradeRecord, NullOrder | ✓ | **No** |
| regime.py | Regime, MacroContext, SessionContext, CentralBankEvent | ✓ | No |
| data.py | Asset, Bar, DbTick, OrderBookLevel, MacroPoint, FundamentalPoint, CorporateEvent, EconomicEvent, DataQualityEntry, IngestionRun | ✓ | No |

All enums: `Direction`, `SignalType`, `OrderStatus`, `OrderType`, `TrendRegime`, `VolRegime`, `RiskMode`, `AssetClass`, `BarType`, `BarSize`. None reference strategy.

### 2.4 ABCs / base classes (full inventory via grep)

| File | ABC | Abstract methods |
|---|---|---|
| core/base_service.py:36 | `BaseService` | `on_message()`, `run()` |
| features/base.py:19 | `FeatureCalculator` | `name()`, `compute()`, `required_columns()`, `output_columns()` |
| features/validation/stages.py:93 | `ValidationStage` | `validate()`, `name` |
| features/store/base.py:28 | `FeatureStore` | `get()`, `put()`, `delete()`, `list()` |
| features/cv/base.py:58 | `BacktestSplitter` | `split()`, `n_splits` |
| features/cv/base.py:90 | `FeatureValidator` | `validate()` |
| features/ic/base.py:87 | `ICMetric` | `compute()` |
| services/data_ingestion/quality/base.py:41 | `QualityCheck` | `check()` |
| services/data_ingestion/connectors/base.py | `Connector` (name approximated) | `fetch()` |
| services/data_ingestion/connectors/calendar_base.py | `CalendarConnector` | source-specific methods |
| services/data_ingestion/normalizers/base.py | `Normalizer` | `normalize()` |
| services/execution/broker_base.py | `Broker` | `submit_order()`, `cancel_order()`, `get_positions()` |

**Missing ABCs that multi-strat would need**: `StrategyRunner`, `SignalGenerator`, `StrategyAllocator`, `RiskGuard` (s05 uses duck-typed `RuleResult` return only, no ABC — chain_orchestrator is concrete).

### 2.5 Registries / factories (full inventory)

| Name | File | Purpose | Plug-in? |
|---|---|---|---|
| `STRATEGY_REGISTRY` | services/fusion_engine/strategy.py | 4 hardcoded regime-profile strategies | Data-driven, but strategies are regime-keyed not strategy-keyed |
| `ConnectorFactory` | services/data_ingestion/orchestrator/connector_factory.py | Dispatch to connector by type | if-chain, see STRATEGIC_AUDIT §2.1 O/C violation |
| `FeatureRegistry` | features/registry.py:204 | TimescaleDB metadata catalog of computed features | Point-in-time catalog, NOT a code plug-in registry |
| `NormalizerRouter` | services/data_ingestion/normalizers/router.py | Dispatch by connector source | Router pattern |
| `BrokerFactory` (implicit in s06) | services/execution/broker_factory.py | Paper / Alpaca / Binance selection | Data-driven if CFG_BROKER env |

**No strategy registry. No `StrategyRunner` plug-in mechanism.**

---

## §3. Ten-Question Audit

### Q1 — Service Isolation: can a new strategy be developed in isolation?

**Evidence**:
- Agent S02 probe: "No plugin/registry keywords found" for `register`, `Registry`, `Plugin`, `Factory`, `add_signal`, `SignalTrigger` in services/signal_engine.
- `services/signal_engine/pipeline.py:237–328` — `build_components()` hardcodes 5 signal types (OFI, Bollinger, EMA, RSI, VWAP).
- `services/signal_engine/signal_scorer.py:43–49` — `WEIGHTS` dict (ClassVar) is a fixed map of component → weight.
- `services/fusion_engine/strategy.py:STRATEGY_REGISTRY` — 4 strategies baked in (momentum_scalp / mean_reversion / spike_scalp / short_momentum), each keyed by *regime profile*, not by strategy identity.
- No grep hits for `class StrategyRunner`, `class BaseStrategy`, `StrategyProtocol` anywhere in repo.

**Files that MUST be modified to add Strategy #1 (cross-sectional momentum crypto)**:
- `services/signal_engine/pipeline.py` (new stage for cross-sectional rank)
- `services/signal_engine/signal_scorer.py` (new WEIGHTS entry)
- `services/signal_engine/technical.py` or new module (cross-sectional computation spanning multiple symbols — currently each symbol has its own `TechnicalAnalyzer` instance)
- `services/fusion_engine/strategy.py` (new `StrategyProfile` entry)
- `services/fusion_engine/fusion.py` or `service.py` (selector logic)
- `core/models/signal.py` (if new `SignalType` enum value needed)

**Verdict: BLOCKER.**

**Gap**: Two agents cannot develop Strategy A and Strategy B in parallel without Git-conflicting on `pipeline.py`, `signal_scorer.py`, and `strategy.py`. All three files would become merge hot-spots.

**Recommended action**: Introduce `StrategyRunner` ABC (`features/strategies/base.py`) with methods `name() → str`, `on_tick(NormalizedTick) → list[Signal]`, `required_features() → list[str]`, `required_data_sources() → list[str]`. S02 becomes a thin orchestrator that loads `strategies: list[StrategyRunner]` via config and dispatches ticks to each. Each strategy owns its own module tree under `strategies/strat_1_momentum/`, `strategies/strat_2_meanrev/`, etc. **Effort: L (1–2 weeks)**. This is prerequisite #1 for multi-strat.

---

### Q2 — Signal Pipeline Extensibility (multiple parallel generators + allocator)

**Evidence**:
- S02 agent probe: "Single-Path Global Signal Engine." `SignalPipeline._run()` is one linear 7-stage flow per tick (pipeline.py:451–487). Per-symbol state only: `self._micro: dict[str, MicrostructureAnalyzer]` at service.py:56–67, never keyed by strategy.
- S04 agent probe, service.py:108–123: `FusionEngine.select_strategy(regime)` returns ONE strategy name per signal, deterministic from regime. If Strategy A and Strategy B both emit on `signal.technical.BTCUSDT`, S04 calls `_process_signal` for each, independently, with no cross-coordination, producing 2 independent OrderCandidates.
- Zero grep hits for `StrategyAllocator`, `CapitalAllocator`, `PortfolioAllocator`, `RiskParity`, `BlackLitterman` across the entire repo.
- No skeleton, no stub, no placeholder.

**Verbatim evidence** — `services/fusion_engine/fusion.py:compute_final_score`:
```
final = |signal.strength|
        × regime.macro_mult
        × confluence_bonus
        × session_mult
        × mtf_alignment
        × session_prime_bonus
```
Combination is **within-signal**, not **across-strategies**.

**Verdict: BLOCKER.**

**Gap**: No allocator exists. Multi-strategy signals would collide at S04 → S05 with no arbitration. Risk budget not allocated per strategy.

**Recommended action**: Two options —
- **(A, preferred, Citadel-style)**: New microservice `S11 StrategyAllocator` between S04 and S05. S04 becomes "per-strategy fusion" (adds `strategy_id` to `OrderCandidate`). S11 subscribes to `order.candidate`, buffers over 100ms window, solves risk-parity or Sharpe-weighted allocation, publishes `order.candidate.allocated` to S05. Effort: **XL (2–3 weeks)**.
- **(B, smaller)**: Add `portfolio_allocator` module inside S04 with the same buffering + allocation logic; no new service. Effort: **L (1–2 weeks)**. Less clean but faster.

---

### Q3 — Features Layer Reusability (per-strategy feature subsets)

**Evidence** (from features-probe agent):
- `features/base.py:19` — clean `FeatureCalculator` ABC:
```python
class FeatureCalculator(ABC):
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame: ...
    @abstractmethod
    def required_columns(self) -> list[str]: ...
    @abstractmethod
    def output_columns(self) -> list[str]: ...
```
- `features/pipeline.py:53–63` — `FeaturePipeline.__init__(calculators: list[FeatureCalculator], ...)` — explicit DI, no registry or hidden lookup.
- Zero Redis/ZMQ reads in any calculator file (`features/calculators/har_rv.py`, `rough_vol.py`, `ofi.py`, `cvd_kyle.py`, `gex.py`). All are pure functions of polars DataFrames.
- `features/registry.py:204` — `FeatureRegistry` is a TimescaleDB-backed metadata catalog with point-in-time lookup via `latest_version(asset_id, feature_name, as_of)`. Not a plug-in runtime registry, but serves that architectural role.
- `features/selection/decision.py` — `SelectionDecision` dataclass with `decision: Literal["keep", "reject"]`, driven by IC / VIF / PSR/DSR/PBO, supports per-strategy feature selection.
- `features/store/base.py:28` — `FeatureStore` ABC with `get()`, `put()`, `load(feature_names, as_of, version)` — supports point-in-time per-strategy feature subsets.

**Example that works today** (from agent probe):
```python
pipeline_a = FeaturePipeline(
    calculators=[HARRVCalculator(), RoughVolCalculator()],
    labeler=..., weighter=..., feature_store=...
)
pipeline_b = FeaturePipeline(
    calculators=[OFICalculator(), CVDKyleCalculator()],
    labeler=..., weighter=..., feature_store=...
)
```
Zero code change in `features/` required.

**Verdict: READY.** This is the bright spot of the audit.

**Minor caveats**:
- Warm-up is data-driven (expanding window for HAR-RV / Rough Vol, rolling for OFI/CVD/GEX), which is correct but each strategy bears the cost independently.
- Phase 5.3 spec requires an incremental `compute_incremental(new_bar, evicted_bar)` streaming interface that is NOT yet present — this is a known follow-up (STRATEGIC_AUDIT §1.3).

---

### Q4 — Backtest Engine Multi-Strat Support

**Evidence** (from backtest-probe agent):
- `backtesting/engine.py:157`:
```python
async def run(self, ticks: list[NormalizedTick]) -> list[TradeRecord]:
    """Replay ticks and return completed trade records."""
```
Single tick list in, single trade list out. No strategy parameter.
- `backtesting/metrics.py:full_report` signature at line 1362–1376 accepts `trades: list[TradeRecord], initial_capital, risk_free_rate` plus OOS params (n_trials, oos_fraction, embargo_days). Breakdowns: `by_session_breakdown`, `by_regime_breakdown`, `by_signal_breakdown`. **No `by_strategy_breakdown`.**
- `backtesting/walk_forward.py`: three validators —
  - `WalkForwardValidator:78` (date-based),
  - `TickBasedWalkForwardValidator:252` (tick-based),
  - `CombinatorialPurgedCV:374` (Bailey et al. 2015, produces PBO + deployment-gate recommendation).
  All three are single-strategy only.
- Zero grep for `class Strategy`, `class Portfolio`, `class Allocator`, `run_portfolio` in `backtesting/`.
- `scripts/backtest_regression.py:31` — invokes `engine.run(ticks)` then `full_report(trades)`. Single strategy, single asset.
- `.github/workflows/ci.yml:121–155` — `backtest-gate` job is MUZZLED (`continue-on-error: true`), runs a single BTCUSDT 1-min fixture (issue #102 active on current branch).

**Verdict: GAP (close to BLOCKER).**

**Gap**: Cannot validate Strategy #1 as a portfolio candidate. Cannot run walk-forward for 6 strategies + allocator. CPCV works per-strategy but no aggregation.

**Recommended action**:
1. Introduce `backtesting/strategy.py:BacktestStrategy` ABC with `name`, `run(ticks) -> list[TradeRecord]`.
2. Add `backtesting/engine.py:run_portfolio(strategies: list[BacktestStrategy], allocator: BacktestAllocator, ticks) -> PortfolioResult`.
3. Add `by_strategy_breakdown` to `full_report`.
4. Un-muzzle the CI backtest gate (issue #102, in-flight on current branch — ship it).

Effort: **L (1–2 weeks)**.

---

### Q5 — Risk Manager (S05) Multi-Strat Awareness

**Evidence** (from s05-probe agent):
- 12 files, 2,036 LOC post Batch D.
- `services/risk_manager/chain_orchestrator.py:81–96`: chain wiring via constructor injection with hardcoded order (6 steps).
- Zero grep hits for `strategy` or `strat_` across `services/risk_manager/`.
- All `RuleResult` signatures lack `strategy_id`. No per-strategy context field.
- `CircuitBreaker`, `ExposureMonitor`, `PositionRules`: all thresholds are global constants in `models.py:161–180`.
- Redis keys: `portfolio:capital`, `pnl:daily`, `portfolio:positions` — all single-book.
- **No RiskGuard ABC** — guards are concrete classes returning `RuleResult` by duck-typed convention.

**Verbatim** — `models.py:RuleResult`:
```python
class RuleResult(BaseModel):
    rule_name: str
    passed: bool
    reason: str
    block_reason: BlockReason | None = None
    meta: dict[str, str | int | float | bool] = Field(default_factory=dict)
```
No strategy context.

**Could I add `PerStrategyExposureGuard` without modifying existing code?**
- **No.** Orchestrator wiring is in `__init__` signature + `process()` method. Both would need modification. Violates Open/Closed Principle.

**Verdict: GAP.**

**Recommended actions**:
1. **Introduce `RiskGuard` ABC** with `async def check(candidate, context) -> RuleResult` and `name: str`.
2. **Make chain data-driven**: `RiskChainOrchestrator.__init__(guards: list[RiskGuard])` with `process()` iterating in list order. Adding a guard is then a config change (new list entry), not orchestrator modification.
3. **Add `strategy_id` to `RiskContext`** (in `context_loader.py`) and per-strategy Redis key partitions: `portfolio:capital:{strategy_id}`, `pnl:daily:{strategy_id}`, etc.
4. **New `PerStrategyExposureGuard`**: enforces per-strategy capital caps (e.g., "Strategy A ≤ 30%", "Strategy B ≤ 20%"). Reads `portfolio:allocation:{strategy_id}` from Redis (written by S11 StrategyAllocator or S09).

Effort: **M–L (3–5 days for the refactor, +2 days per-strategy state)**.

---

### Q6 — Data Layer Multi-Asset Readiness

**Evidence**:
- S01 has 21 connector files: Alpaca (equities WS + REST historical), Binance (WS + REST), Yahoo (daily bars for ETFs/indices/FX), FRED (macro), Massive (historical bars), SimFin + EDGAR (fundamentals), BOJ/ECB/FOMC (calendar scrapers). **Multi-asset breadth is strong.**
- `core/models/data.py:Bar` — consistent schema across asset classes: `asset_id, bar_type, bar_size, timestamp, open, high, low, close, volume, trade_count, vwap, adj_close`. Works for equities AND crypto AND FX.
- `core/models/tick.py:NormalizedTick` — consistent across crypto + equity. `session: SessionType` tags market session.
- `features/store/` — TimescaleDB-backed point-in-time feature store supports multi-asset feature matrices via `asset_id` key.
- **BUT**: S02 analyzer state is **per-symbol**, not **per-(symbol, timeframe)**: `self._micro: dict[str, MicrostructureAnalyzer]` in service.py:56–67. Multi-timeframe aggregation exists via `MTFAligner` but it's hardcoded to 5m/15m/1h/4h/1d inside `TechnicalAnalyzer` (s02, technical.py:454 LOC). A strategy needing a different timeframe set (e.g., Strategy #2: 5min-1h only, or Strategy #3: daily-5day) cannot select its own timeframe configuration.
- **Multi-asset simultaneous subscription**: S02 subscribes to prefix `tick.` and receives all symbols. But each `TechnicalAnalyzer` is symbol-isolated. **Cross-sectional computation (Strategy #1 crypto top-20 momentum) requires building a new cross-symbol aggregator that does not exist today.**

**Verdict: PARTIAL.**

**Gap**: Data acquisition layer is multi-asset; signal layer is single-symbol-at-a-time. Cross-sectional or multi-asset-basket strategies (Strategy #1, #3, #5) need a new cross-symbol aggregator / panel builder.

**Recommended action**: Add `features/panel/cross_sectional.py` — panel builder that assembles `polars.DataFrame[symbol × feature × timestamp]` for a configurable set of symbols. Wire into `StrategyRunner` ABC so each strategy declares its universe. Effort: **M (3–5 days)**.

---

### Q7 — Configuration & Parameterization

**Evidence**:
- `core/config.py`: single `Settings` class via Pydantic Settings (env vars + `.env`). Global scope.
- No `config/strategies/*.yaml` or `*.toml` anywhere. `ls config/` returns no results (the top-level `config/` directory does not exist; config is a Python module at `core/config.py`).
- `.env.example` (2,921 bytes) contains broker keys, Redis URL, ZMQ ports, trading mode — all **global**, single-strategy assumptions.
- `services/fusion_engine/strategy.py:STRATEGY_REGISTRY` — strategy profile parameters hardcoded in Python (not config).
- Kelly sizer constants, fusion weights, risk thresholds (`models.py:161–180`): all hardcoded.

**Verdict: GAP.**

**Gap**: No per-strategy config mechanism. All parameters are global env vars or hardcoded Python constants. Six sequentially-deployed strategies with different parameters (lookback, entry threshold, stop loss, position sizing) cannot be runtime-configured.

**Recommended action**: Introduce `config/strategies/{strat_id}.yaml` with schema:
```yaml
strategy_id: strat_1_crypto_momentum
universe: [BTCUSDT, ETHUSDT, ...]
timeframes: [4h, 1d]
lookback_days: 30
entry_threshold: 0.015
stop_loss_atr_mult: 2.0
sizing:
  method: kelly_capped
  max_fraction: 0.02
risk_budget:
  max_pct_capital: 0.30
```
Wire into `StrategyRunner` constructor. YAML schema validated by Pydantic on load. Effort: **S (1 day)** once `StrategyRunner` ABC exists (Q1).

---

### Q8 — Metrics & Observability Per Strategy

**Evidence** (from core/observability probe agent):
- `services/feedback_loop/service.py`:
```python
raw_trades = await self.state.lrange("trades:all", 0, KELLY_ROLLING_WINDOW - 1)
# ...
for symbol in symbols:
    sym_trades = [t for t in trades if t.symbol == symbol]
    await self.state.hset(f"kelly:{symbol}", "win_rate", ...)
```
Trades are pooled **globally** under `trades:all`. Kelly stats keyed by **symbol only**, not by `(strategy_id, symbol)`.
- `services/feedback_loop/drift_detector.py:DriftDetector`: single `DRIFT_THRESHOLD = 0.10`, single `MIN_TRADES = 50`. No per-strategy baseline tracking.
- `services/command_center/dashboard.py`: **zero grep hits for "strategy"**. Panels: system health grid, live equity curve, open positions, signals feed, circuit breaker, regime, Sharpe/DD/win rate — all global.
- `backtesting/metrics.py:full_report` produces `by_session_breakdown`, `by_regime_breakdown`, `by_signal_breakdown` — **no `by_strategy_breakdown`**.
- No correlation matrix across strategies (would need per-strategy equity curves to compute).

**Verdict: BLOCKER.**

**Gap**: Cannot report per-strategy Sharpe / drawdown / win rate / correlation. Cannot detect drift on Strategy A independently of Strategy B. Cannot show operator which strategy is bleeding capital.

**Recommended actions**:
1. Add `strategy_id` to `TradeRecord` (Q11 field addition).
2. Partition Redis: `trades:{strategy_id}:all`, `kelly:{strategy_id}:{symbol}`, `pnl:{strategy_id}:daily`.
3. Extend `DriftDetector` to accept `strategy_id` parameter; maintain per-strategy baselines.
4. Add per-strategy dashboard panels in S10 (requires `strategy_id` tagging upstream first).
5. Add `by_strategy_breakdown` + cross-strategy correlation matrix to `full_report`.

Effort: **M (3–5 days)** once upstream `strategy_id` propagation is done.

---

### Q9 — Test Coverage for Extensibility Points

**Evidence**:
- `tests/unit/features/` covers `FeatureCalculator` subclasses (HARRV, RoughVol, OFI, CVDKyle, GEX) each with positive/negative + hypothesis property tests. Good depth.
- `tests/unit/s05_risk_manager/` — covers individual guards: `test_fail_closed.py`, `test_cb_event_guard.py`, `test_meta_label_gate.py`, `test_position_rules.py`, `test_exposure_monitor.py`, `test_circuit_breaker.py`, `test_chain_orchestrator.py`.
- No contract/ABC-level test: e.g., no `tests/unit/features/test_calculator_contract.py` that proves any `FeatureCalculator` subclass obeys the ABC's invariants (required_columns ⊆ input.columns, warm-up respected).
- No "add-a-new-strategy" integration test template.
- No plug-in-pattern isolation test (i.e., "adding Calculator X does not break Calculator Y's outputs").

**Verdict: PARTIAL.**

**Gap**: When the ABC surface grows (StrategyRunner, RiskGuard, StrategyAllocator), there is no existing pattern for ABC contract tests. New contributors might break the contract silently.

**Recommended action**: Adopt a `tests/unit/contracts/` pattern — one file per ABC (`test_feature_calculator_contract.py`, `test_strategy_runner_contract.py`, `test_risk_guard_contract.py`). Each file imports all concrete subclasses from an explicit registry and parametrizes invariant assertions. Effort: **M (3 days)** once ABCs exist.

---

### Q10 — Documentation Completeness for Multi-Strat Handoff

**Evidence**:
- `docs/adr/` contains 6 ADRs: zmq-broker-topology (0001), quant-methodology-charter (0002), universal-data-schema (0003), feature-validation-methodology (0004), meta-labeling-fusion-methodology (0005), fail-closed-risk-controls (0006). **None treats strategy as a unit.** All are cross-cutting infra/methodology ADRs.
- Grep across `docs/` for "strategy": only `DECISIONS.md`, `SESSIONS.md`, `AUDIT_2026_04_11_WHOLE_CODEBASE.md` mention strategy in passing.
- **No file named `STRATEGY_LIFECYCLE.md`, `ADD_A_STRATEGY.md`, or `STRATEGY_DEVELOPMENT_GUIDE.md`.**
- `docs/claude_memory/CONTEXT.md` and `docs/claude_memory/PHASE_3_NOTES.md` exist (per CLAUDE.md §13) but are Phase-3-centric.
- `MANIFEST.md` (55 KB) is the canonical architecture doc but treats S02 and S04 as pipeline stages, not strategy hosts.

**Verdict: GAP.**

**Gap**: An agent handed "develop Strategy #2 (mean-reversion intraday equities)" tomorrow would have to reverse-engineer the pipeline from S02 + S04 source. No template, no lifecycle, no onboarding. The cost of getting the first Claude Code agent up to speed would recur for each of the 6 strategies.

**Recommended action**: Write `docs/STRATEGY_LIFECYCLE.md` covering: (a) `StrategyRunner` ABC contract, (b) config schema, (c) feature selection process (IC → VIF → PSR/DSR/PBO gates), (d) backtest validation sequence (walk-forward → CPCV → paper), (e) risk limits + allocator onboarding, (f) S10 dashboard wiring, (g) deployment checklist. Plus an ADR-0007 "Strategy as Plug-in" formalizing the multi-strat architecture. Effort: **S–M (1–2 days)** once the architecture is decided.

---

## §4. SOLID Scorecard per Service (multi-strat lens)

| Service | S | O | L | I | D | Multi-strat extensibility verdict |
|---|---|---|---|---|---|---|
| S01 | ⚠️ | 🔴 | ⚠️ | ✓ | ✓ | **Data layer OK.** Connector factory if-chain (O/C violation inherited from STRATEGIC_AUDIT §2.1) will matter when Strategy #5 (FX G10) or Strategy #4 (VIX IV) demand new connectors. Fix independent of multi-strat. |
| S02 | 🔴 | 🔴 | 🔴 | 🔴 | ⚠️ | **BLOCKER.** Pipeline.py is 487 LOC with 290-LOC `_run()`. No ABC for signal generators. Single-path hardcoded. **Primary multi-strat refactor target.** |
| S03 | ✓ | ✓ | ✓ | ✓ | ✓ | Clean. Global regime is correct for multi-strat (one shared regime view). |
| S04 | ⚠️ | 🔴 | ⚠️ | ⚠️ | ✓ | **BLOCKER.** Single-strategy-per-regime. No allocator. Strategy registry is closed-set of 4. **Primary multi-strat refactor target.** |
| S05 | ⚠️ | 🔴 | ✓ | 🔴 | ✓ | **GAP.** Post-Batch D decomposition is clean structurally but chain wiring violates O/C. No `RiskGuard` ABC. No per-strategy state. **Secondary refactor target.** |
| S06 | ✓ | ✓ | ✓ | ✓ | ✓ | Clean `Broker` ABC + factory. Multi-broker for multi-asset already works. Would need minor updates if `strategy_id` is tagged on orders. |
| S07 | ✓ | ✓ | ✓ | ✓ | ✓ | Clean. Global statistical analytics is appropriate (shared Hurst/GARCH/Amihud view). Per-strategy analytics are a features/ layer concern, not S07. |
| S08 | ✓ | ✓ | ✓ | ✓ | ✓ | Clean (small service). Macro intelligence is global by nature. |
| S09 | ⚠️ | ⚠️ | ✓ | ✓ | ✓ | **GAP** (S of single-dimension: drift+kelly, but both pooled globally). Needs per-strategy partitioning. |
| S10 | ⚠️ | ⚠️ | ✓ | ✓ | ✓ | **GAP** (zero strategy-awareness). Dashboard assumes one global book. |

Legend: ✓ clean · ⚠️ minor · 🔴 multi-strat blocker.

---

## §5. Critical Gaps List (prioritized)

### P0 — Must fix BEFORE multi-strat begins (blockers)

| # | Gap | Effort | Reference |
|---|---|---|---|
| P0-1 | **Add `strategy_id` field to `Signal`, `OrderCandidate`, `ApprovedOrder`, `ExecutedOrder`, `TradeRecord`** | S (1 day) | Q1, Q8 |
| P0-2 | **Introduce `StrategyRunner` ABC + registry; refactor S02 to dispatch ticks to a `list[StrategyRunner]` loaded from config** | L (1–2 weeks) | Q1 |
| P0-3 | **Introduce `StrategyAllocator` (either new S11 service or S04 multi-strategy refactor) with buffering + risk-parity/Sharpe-weighted allocation across per-strategy OrderCandidates** | XL (2–3 weeks) | Q2 |
| P0-4 | **Refactor `S05 RiskChainOrchestrator` to accept `guards: list[RiskGuard]` (data-driven); introduce `RiskGuard` ABC** | M (3–5 days) | Q5 |
| P0-5 | **Backtest engine `run_portfolio(strategies, allocator, data) -> PortfolioResult` + per-strategy breakdown in `full_report`** | L (1–2 weeks) | Q4 |
| P0-6 | **Un-muzzle CI `backtest-gate`** (remove `continue-on-error: true`, fix #102 Sharpe bug — in-flight on current branch `fix/ci-backtest-gate-sharpe`) | in-flight | Q4, CI |

### P1 — Should fix before 3rd strategy

| # | Gap | Effort | Reference |
|---|---|---|---|
| P1-1 | Per-strategy Redis key partitioning in S09 (`trades:{strategy_id}:all`, `kelly:{strategy_id}:{symbol}`) + DriftDetector per-strategy baseline | M (3 days) | Q8 |
| P1-2 | S10 dashboard per-strategy panels (filter by strategy, per-strategy equity curves, correlation matrix) | M (3–5 days) | Q8 |
| P1-3 | `config/strategies/{strat_id}.yaml` schema + `StrategyRunner` YAML loader | S (1 day) | Q7 |
| P1-4 | Cross-sectional / multi-asset panel builder (`features/panel/cross_sectional.py`) for Strategy #1, #3, #5 | M (3–5 days) | Q6 |
| P1-5 | `docs/STRATEGY_LIFECYCLE.md` + ADR-0007 "Strategy as Plug-in" | S (1–2 days) | Q10 |
| P1-6 | `tests/unit/contracts/` pattern for ABC invariants (StrategyRunner, RiskGuard, FeatureCalculator) | M (3 days) | Q9 |

### P2 — Nice to have

| # | Gap | Effort | Reference |
|---|---|---|---|
| P2-1 | `Topics.signal_for(strategy_id, symbol)` factory + migrate S02/S04 to per-strategy topic suffix | S (0.5 day) | §2.1 |
| P2-2 | Incremental `compute_incremental(new_bar, evicted_bar)` interface on FeatureCalculator (Phase 5.3 dependency) | L | STRATEGIC_AUDIT §1.3 |
| P2-3 | S10 subscribe to `risk.system.state_change` (Phase 5.1 follow-up debt) | XS (1h) | STRATEGIC_AUDIT §1.1 |
| P2-4 | Resolve orphan-read audit on `portfolio:capital`, `pnl:daily`, etc. (STRATEGIC_AUDIT §1.2) — required before multi-strat because per-strategy versions will inherit the same trap | M (2–3 days) | STRATEGIC_AUDIT §1.2 |
| P2-5 | Feature layer's `FeatureRegistry` extended to tag versions with `strategy_id` (currently tagged by `asset_id + feature_name + version`) | S (1 day) | Q3, Q8 |

---

## §6. Recommended Next Steps

Based on the evidence above, this audit maps to **Scenario B (READY-WITH-GAPS) with a NOT-READY tilt on the signal pipeline specifically**.

**Scenario chosen**: Scenario B — Proceed with a 2-3 week infrastructure lift BEFORE the Charter interview, in this specific order (each is prerequisite for the next):

### Phase A — Foundational contract changes (3–5 days, Claude Code agents can ship in parallel)

1. **Agent α**: Add `strategy_id: str = "default"` field to `Signal`, `OrderCandidate`, `ApprovedOrder`, `ExecutedOrder`, `TradeRecord` in `core/models/*`. Default value preserves current single-strategy semantics. Add `Topics.signal_for(strategy_id, symbol)` factory. File paths: `core/models/signal.py`, `core/models/order.py`, `core/topics.py`. (P0-1 + P2-1.)
2. **Agent β**: Un-muzzle CI backtest gate (in-flight on `fix/ci-backtest-gate-sharpe` — finish it). (P0-6.)
3. **Agent γ**: Resolve orphan-read audit (STRATEGIC_AUDIT §1.2): verify `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix` have production writers, or deprecate the reads. (P2-4 — prerequisite for multi-strat because per-strategy versions will inherit the trap.)

### Phase B — Pluggable signal layer (1–2 weeks)

4. **Agent δ**: Introduce `StrategyRunner` ABC at `features/strategies/base.py` + test contract at `tests/unit/contracts/test_strategy_runner_contract.py`. Refactor S02 service.py to hold `self._strategies: list[StrategyRunner]` loaded from config. Migrate the current hardcoded 5-component pipeline into a `StrategyRunner` subclass called `LegacyConfluenceStrategy` (preserves all current behavior; Principle 6). File paths: `features/strategies/base.py` (new), `features/strategies/legacy_confluence.py` (new, wraps current pipeline.py), `services/signal_engine/service.py` (modify). (P0-2.)
5. **Agent ε**: Write `docs/STRATEGY_LIFECYCLE.md` + `docs/adr/ADR-0007-strategy-as-plugin.md`. (P1-5.)

### Phase C — Allocator + per-strategy risk (2–3 weeks)

6. **Agent ζ**: New service `services/s11_strategy_allocator/` consuming `order.candidate` (tagged with `strategy_id`), buffering 100ms, publishing `order.candidate.allocated`. Risk-parity allocator + Sharpe-weighted alternative. MANIFEST.md updated per CLAUDE.md §8 checklist. (P0-3.)
7. **Agent η**: S05 chain refactor: `RiskChainOrchestrator(guards: list[RiskGuard])`. Introduce `RiskGuard` ABC. Add `PerStrategyExposureGuard` consuming new `portfolio:allocation:{strategy_id}` Redis key. (P0-4.)

### Phase D — Observability + backtest (1–2 weeks)

8. **Agent θ**: S09 per-strategy partitioning + DriftDetector per-strategy baseline. (P1-1.)
9. **Agent ι**: S10 per-strategy panels + correlation matrix. (P1-2.)
10. **Agent κ**: `backtesting/engine.py:run_portfolio()` + `backtesting/strategy.py:BacktestStrategy` ABC + `by_strategy_breakdown` in `full_report`. (P0-5.)

**Then and only then**: invest the 1–2h Strategy Research Charter interview. By that point the infrastructure will host the 6-strategy vision; the Charter's job is to choose which one to build first, with confidence that the platform can host the other 5.

**Total estimated effort**: 5–8 weeks with 2–3 parallel Claude Code agents. **Less than the cost of one rework cycle** after committing to a Charter the infrastructure cannot host.

**Alternative aggressive path** (if time-to-live-PnL is paramount over multi-strat purity): skip P0-3 initially, develop Strategy #1 alone on the current infrastructure with `strategy_id="strat_1"`, defer the allocator to when Strategy #2 is added. This works IF the operator commits in writing that Strategy #2 will not begin until the allocator lands. Risk: it won't.

---

## §7. Appendix: Raw Evidence

### 7.1 Repo tree (top level)

```
core/         docs/         services/     rust/         tests/
backtesting/  features/     supervisor/   scripts/      db/
models/       reports/      data/         graphify-out/ docker/
CLAUDE.md (11 KB)   MANIFEST.md (55 KB)   MANAGED_AGENTS_PLAYBOOK.md (33 KB)
CHANGELOG.md  README.md    AI_RULES.md    EXTENSIONS.md
pyproject.toml (5.2 KB)    requirements.txt (1.3 KB)    Makefile (1 KB)
```

### 7.2 Key grep outputs

- `grep -r "strategy_id" core/ services/ features/ backtesting/` → **0 matches**.
- `grep -r "class StrategyRunner\|class BaseStrategy\|StrategyProtocol" .` → **0 matches**.
- `grep -r "StrategyAllocator\|PortfolioAllocator\|RiskParity\|BlackLitterman" .` → **0 matches**.
- `grep -r "class RiskGuard\|class RiskRule" services/risk_manager/` → **0 matches** (ABCs absent).
- `grep -r "strategy" services/command_center/` → **0 matches**.
- `grep -r "run_portfolio\|multi_strategy" backtesting/` → **0 matches**.
- `grep "register\|Registry\|Plugin\|Factory" services/signal_engine/` → **0 matches**.

### 7.3 CI workflow summary (.github/workflows/ci.yml)

- Jobs: `quality` (ruff + mypy strict + bandit), `rust` (cargo test + maturin wheels), `unit-tests` (75% coverage gate via pytest-cov, TODO to raise to 85%), `integration-tests` (docker compose + fakeredis), `backtest-gate` (MUZZLED per `continue-on-error: true`, issue #102).
- Python 3.12, Redis 7-alpine, maturin >= 1.9.4.
- **Gate currently soft on Sharpe/DD**. Branch `fix/ci-backtest-gate-sharpe` fixes this (in-flight, HEAD d53ef4e).

### 7.4 pyproject.toml (5.2 KB — not read in full, key observations via CI job and modules loaded)

Pydantic v2, polars, asyncio (pytest-asyncio), alpaca-py, fakeredis, structlog, mypy strict, ruff, bandit. No strategy-related plug-in metadata (no `[project.entry-points]` section spotted in audit; would need to be added for plug-in discovery if that approach is chosen over explicit config-driven loading).

### 7.5 ADR deviations discovered

- ADR-0001 (ZMQ XSUB/XPUB broker): honored. S05→S06 via `order.approved` works. No deviation.
- ADR-0004 (Six-Step Feature Validation): honored. IC → multicollinearity → CPCV → PSR/DSR/PBO all implemented in `features/`.
- ADR-0005 (Meta-Labeling Fusion): honored. `features/meta_labeler/`, `features/fusion/ic_weighted.py` exist. Streaming wire-up is Phase 5.3 pending.
- ADR-0006 (Fail-Closed Risk): honored. `fail_closed.py` guard, `risk:heartbeat` key, `RISK_SYSTEM_STATE_CHANGE` topic. Minor debt: S10 not subscribed.
- **No ADR exists for strategy lifecycle / multi-strat architecture** — this is the ADR-0007 recommendation.

---

## §8. Questions for Clement

These emerged during the audit and need the operator's input before multi-strat architecture is finalized.

1. **Plug-in vs microservice per strategy?** Do you envision strategies as (a) **plug-ins inside a single S02**, each a `StrategyRunner` loaded by config (simpler, shared process, shared warmup cost, one container), or (b) **full microservices** (one `s02_strat_1_momentum`, `s02_strat_2_meanrev`, etc., each running full pipeline, orchestrator manages 10 + 6N containers)? Citadel typically runs (b) for isolation and independent deploys. For a solo operator running on one host, (a) is far more tractable. The audit assumes (a) in all effort estimates. Please confirm.

2. **Where does the allocator live?** Do you prefer (a) **S04 Fusion Engine absorbs allocator logic** (smaller diff, but S04 becomes two-concerned: signal-fusion + allocation), or (b) **new `S11 StrategyAllocator` microservice** (clean SRP, extra ZMQ hop, ~1 week more work)? Audit leans (b) on Principle 2 (institutional cleanliness) and Principle 5 (Single Responsibility).

3. **Multi-asset strategies: composite bar service or per-service subscription?** Strategy #3 (trend-following BTC+SPY+ETH+GLD, daily) needs simultaneous multi-asset bars across exchanges. Option (a): each strategy subscribes to multiple tick feeds and builds its own panel. Option (b): new `s01_panel_builder` publishes `panel.{frequency}.{universe_id}` aggregated panels. (a) is faster; (b) scales better across multiple multi-asset strategies. Your preference?

4. **Capital allocation method for the allocator**: risk-parity (volatility-inverse) is the institutional default. Black-Litterman allows injecting views (FOMC bias, regime-conditional). Sharpe-weighted is post-hoc and backward-looking. Which is primary? Audit assumes risk-parity as default; BL as phase-2.

5. **Strategy deployment cadence**: is the 12–18 month, one-strategy-every-2-months cadence hard? Because the P0-3 allocator work (2–3 weeks) can be deferred IF Strategy #1 ships alone first, but then locks the second strategy's go-live to after P0-3. Commit?

6. **Do the 6 strategies in the Charter share the same Risk Manager circuit breaker, or does each get its own?** Global circuit breaker (S05's today) is simpler; per-strategy circuit breakers let one strategy fail without halting the others. Institutional default: per-strategy soft breakers + a global hard breaker.

7. **Open/Closed on CLAUDE.md**: the current `CLAUDE.md` Section 2 bullet "**Risk Manager (S05) is a VETO — it cannot be bypassed under any circumstance**" remains true. But with per-strategy limits, is it acceptable for S05 to veto a specific strategy while letting others through? The allocator model makes this natural; audit recommends yes.

8. **Charter scope gate**: should the charter also specify failure budgets per strategy (e.g., "Strategy X is killed if 90-day rolling Sharpe < 0.3")? This drives what S09 needs to compute per-strategy and is best decided before multi-strat infra is built.

---

**END OF REPORT.** HARD STOP per protocol — no implementation work will be initiated.

Multi-Strat Readiness Audit complete. 2026-04-18, Claude Opus 4.7.
