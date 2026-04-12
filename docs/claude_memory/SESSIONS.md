# APEX Claude Code Sessions Log

Chronological log of all Claude Code sessions working on APEX.
Each entry follows the template in `templates/SESSION_TEMPLATE.md`.

---

## Session 001 — 2026-04-11

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Mission | Phase 3 design specification gate (#61) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~2 hours |

### Decisions Made

1. Phase 3 decomposed into 13 atomic sub-phases (3.1--3.13)
2. Custom lightweight Feature Store preferred over Feast
3. CPCV with purging as mandatory cross-validation (ADR-0002 compliance)
4. vectorbt PRO deferred to Phase 5 (not needed for IC validation)
5. 2 P0 managed agents ($3-7/month), 2 P1 agents (may exceed budget)

### Files Created/Modified

- `docs/phases/PHASE_3_SPEC.md` (created) — complete Phase 3 specification
- `docs/claude_memory/` (created) — persistent memory system (6 files)
- `CLAUDE.md` (modified) — added persistent memory section
- `docs/PROJECT_ROADMAP.md` (modified) — Phase 3 section updated
- `MANAGED_AGENTS_PLAYBOOK.md` (modified) — 4 Phase 3 agents added

### Key Findings

- S07 functions (HAR-RV, rough vol, microstructure) are PURE and ready for Phase 3 consumption
- S02 signal pipeline uses weighted confluence (5 components); Phase 3 features will become additional components
- All 6 candidate features (HAR-RV, Rough Vol, OFI, CVD, Kyle lambda, GEX) already have scaffolding in S02/S07
- GEX validation is high-risk due to options data availability

### Next Steps

- Begin Phase 3.1 (Feature Engineering Pipeline Foundation)
- Deploy apex-paper-watcher and apex-codebase-analyzer managed agents
- Address P1 audit issues (#64-#77) in parallel

---

## Session 002 — 2026-04-11

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Mission | Sprint 1 — Docs quick wins (#67, #78, #79, #80) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~1 hour |

### Decisions Made

1. Created centralized GLOSSARY.md with 46 terms across 8 categories
2. Adopted Conventional Commits convention for APEX (docs/CONVENTIONS/COMMIT_MESSAGES.md)
3. Refreshed PROJECT_ROADMAP.md to ground truth (Phase 2 sub-phases 2.7-2.12 DONE, appendices updated, ADR index expanded, risks R17-R19 added)
4. Added commit conventions as CLAUDE.md Section 12 (binding on all future Claude Code sessions)

### Files Created/Modified

- `docs/GLOSSARY.md` (created) — 46 terms, 8 categories, academic references
- `docs/CONVENTIONS/COMMIT_MESSAGES.md` (created) — Conventional Commits for APEX
- `docs/PROJECT_ROADMAP.md` (modified) — Phase 2 sub-phases DONE, open questions resolved, Appendix A corrected, ADR index expanded (0004-0015), risks R17-R19, governance P0 items closed
- `CLAUDE.md` (modified) — Section 12 commit conventions added
- `docs/claude_memory/SESSIONS.md` (modified) — this entry

### Key Findings

- PROJECT_ROADMAP had 15+ stale entries (IN PROGRESS/PENDING for completed work)
- Appendix A data coverage tables were inconsistent with Phase 2 completion state
- ADR index was missing 8 ADRs proposed by Phase 3 spec and meta-governance audit
- Existing glossary in Appendix C of ROADMAP was minimal (only acronym expansions, no definitions)

### Next Steps

- Begin Phase 3.1 (Feature Engineering Pipeline Foundation)
- Continue Sprint 2 docs: ARCHITECTURE.md (#82), ACADEMIC_REFERENCES.md (#83), ONBOARDING.md (#84)
- Address P1 audit issues (#64-#77) in parallel with Phase 3

---

## Session 003 — 2026-04-12

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Mission | Sprint 2 — Security & Config hardening (#66, #69, #71) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~1 hour |

### Decisions Made

1. Broker API keys (Alpaca, Binance), timescale_password, alert_smtp_password, twilio_sid/token, db_password all converted to SecretStr
2. Removed mypy ignore_errors for core.models.* — zero errors surfaced (models were already well-typed)
3. Kept float() in S05 RuleResult kwargs (serialization boundary: RuleResult accepts str|int|float|bool, not Decimal)
4. Kept float() in CircuitBreakerSnapshot.daily_loss_pct (model field is typed float)
5. Deferred S01 connector float→Decimal changes: MacroPoint.value and FundamentalPoint.value model fields are float by design (macro indicators/ratios, not financial prices/sizes/pnl)
6. Deferred S07, S09, S10 float→Decimal (as planned — stats, trade metrics, JSON serialization)

### Files Modified

- `core/config.py` — SecretStr for 8 secret fields, timescale_dsn uses .get_secret_value()
- `core/models/order.py` — TradeRecord.r_multiple returns Decimal instead of float
- `core/models/signal.py` — Signal.risk_reward returns Decimal instead of float
- `pyproject.toml` — removed core.models.* from mypy ignore_errors
- `services/s01_data_ingestion/service.py` — .get_secret_value() for alpaca keys
- `services/s01_data_ingestion/connectors/alpaca_historical.py` — .get_secret_value()
- `services/s06_execution/service.py` — .get_secret_value() for alpaca + binance keys
- `services/s10_monitor/alert_engine.py` — .get_secret_value() for smtp_password, twilio_sid/token
- `services/s05_risk_manager/position_rules.py` — Decimal computation (float only at kwargs)
- `services/s05_risk_manager/circuit_breaker.py` — Decimal computation in _evaluate_triggers
- `services/s05_risk_manager/exposure_monitor.py` — Decimal computation (float only at kwargs)
- `tests/unit/test_config.py` — updated assertions for SecretStr

### Files Deferred (with reason)

- S01 connectors (FRED, ECB, BoJ, EDGAR, SimFin): model fields MacroPoint.value and FundamentalPoint.value are typed float — changing requires model migration
- S07 quant_analytics: float() for statistical computations (Hurst, GARCH) — not financial
- S09 trade_analyzer: dedicated metrics sprint
- S10 command_api: 20+ float() for JSON serialization — not financial

### Quality Gates

- ruff check: clean
- ruff format: 317 files formatted
- mypy --strict: 319 files, 0 errors
- pytest: 1228 unit tests passed, 0 failures

### Next Steps

- Phase 3.1 implementation
- Sprint 3: remaining P1 audit issues
- S01 connector Decimal migration (requires MacroPoint/FundamentalPoint model changes)

---

## Session 004 — 2026-04-12

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Mission | Sprint 3 — CI hardening (#64, #65, #68, #70) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~30 minutes |

### Decisions Made

1. Coverage omit narrowed: removed `services/s01_data_ingestion/*.py` wildcard and `services/s10_monitor/*` wildcard, replaced with specific network/UI modules only
2. Coverage gate raised from 40% to 75% (baseline measured at 80% post-narrowing)
3. Backtest thresholds (Sharpe 0.5, DD 12%) retained — deferred to Phase 5 pending full_report() Sharpe bug fix
4. `continue-on-error: true` retained on backtest-gate — follow-up issue #102 created
5. 9 transitive deps pinned in requirements.txt to patch 19 CVEs
6. Removed `|| true` from backtest.yml Rust wheel builds (was swallowing failures)

### Files Modified

- `requirements.txt` — added 9 CVE-patched transitive dep pins
- `pyproject.toml` — narrowed coverage omit from wildcards to specific files
- `.github/workflows/ci.yml` — coverage gate 40%→75%, backtest TODO comments
- `.github/workflows/backtest.yml` — removed `|| true` on Rust builds, added threshold TODO

### Coverage Baseline

| Metric | Before | After |
|---|---|---|
| With omit config | 83% (6,550 LOC) | 80% (6,861 LOC) |
| Without any omit | 66% (9,277 LOC) | — |
| CI gate | 40% | 75% |

### Quality Gates

- ruff check: clean
- ruff format: 317 files unchanged
- mypy --strict: 319 files, 0 errors
- pytest: 1228 unit tests passed, coverage 79.60%
- pip-audit: 0 project CVEs (2 in pip itself, env-managed)

### Next Steps

- Phase 3.1 implementation
- Follow-up issue #102: fix full_report() Sharpe then enforce backtest-gate
- Continue raising coverage toward 85% with new test sprints

---

## Session 005 — 2026-04-12

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Mission | Sprint 4 — Architecture refactors S01-S05 (#74, #75, #76, #77) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~1.5 hours |

### Decisions Made

1. S03 local VolRegime/RiskMode enums aligned on core.models.regime (CRISIS→CRISIS, HIGH_VOL→HIGH, LOW_VOL→LOW, RISK_ON→NORMAL, RISK_OFF→REDUCED). TRENDING removed (never assigned by compute())
2. S04 StrategySelector: Registry pattern with StrategyProfile dataclass + STRATEGY_REGISTRY dict. Added `use_or_logic` flag for short_momentum's OR semantics (trend OR vol match)
3. StateStore: Added `.client` property (public API). Kept `_ensure_connected()` as deprecated delegate to `client` for backward compat
4. S01 layering: Connectors accept normalizer factory via DI (`bar_normalizer_factory: Callable[[BarSize], NormalizerStrategy]`). ConnectorFactory injects normalizers at registration time. Factory pattern needed because normalizers take `bar_size` at construction

### Files Modified

**#74 — S03 dead code + enum alignment:**

- `services/s03_regime_detector/service.py` — removed `_update_regime()` (50 LOC)
- `services/s03_regime_detector/regime_engine.py` — deleted local VolRegime/RiskMode, aligned Phase-2 API on core enums
- `tests/unit/s03/test_regime_engine.py` — updated assertions for core enum values
- `tests/unit/s03/test_regime_engine_legacy.py` — updated Phase-2 boundary assertions

**#75 — S04 StrategySelector registry:**

- `services/s04_fusion_engine/strategy.py` — StrategyProfile dataclass + STRATEGY_REGISTRY, registry-based lookup

**#76 — StateStore public API:**

- `core/state.py` — added `client` property, deprecated `_ensure_connected()`
- `services/s05_risk_manager/service.py` — `state.client` instead of `state._ensure_connected()`
- `services/s06_execution/order_manager.py` — same migration
- `services/s10_monitor/command_api.py` — same migration (2 occurrences)

**#77 — S01 layering:**

- `services/s01_data_ingestion/connectors/alpaca_historical.py` — DI normalizer factory
- `services/s01_data_ingestion/connectors/binance_historical.py` — DI normalizer factory
- `services/s01_data_ingestion/connectors/massive_historical.py` — DI normalizer factory
- `services/s01_data_ingestion/connectors/yahoo_historical.py` — DI normalizer factory
- `services/s01_data_ingestion/orchestrator/connector_factory.py` — injects normalizers
- `scripts/backfill_binance.py` — passes normalizer factory
- `scripts/backfill_equities.py` — passes normalizer factory
- `scripts/backfill_yahoo.py` — passes normalizer factory
- 4 test files updated for new constructor signatures

### Quality Gates

- ruff check: clean
- ruff format: 317 files
- mypy --strict: 319 files, 0 errors
- pytest: 1228 unit tests passed, coverage 79.47%
- Zero behavior regression

### Next Steps

- Phase 3.1 implementation
- Continue P1 audit issues (Sprint 5+)
- Follow-up issue #102: fix full_report() Sharpe then enforce backtest-gate

---

## Session 006 — 2026-04-12

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Mission | Sprint 5 — Architecture heavy refactors (#72, #73) |
| Agent Model | Claude Opus 4.6 |
| Duration | ~1.5 hours |

### Decisions Made

1. Broker ABC (`broker_base.py`): `place_order(ApprovedOrder) -> ExecutedOrder | None` unifies sync (paper=ExecutedOrder) and async (live=None) fill models (D008)
2. BrokerFactory with lazy singleton pattern: paper mode → PaperTrader, live crypto → BinanceBroker, live equity → AlpacaBroker
3. Raw venue methods renamed to `_submit_raw_order()` (Alpaca, Binance) to avoid ABC method name collision while preserving venue-specific access
4. PaperTrader accepts optional `StateStore` for tick fetching in `place_order()`; `PaperTrader()` (no args) remains backward compatible
5. SignalPipeline with PipelineState dataclass: 7 steps with explicit inter-step data flow (D009)
6. Pipeline constants (_OFI_THRESHOLD, _SL_ATR_MULT, etc.) moved from service.py to pipeline.py

### Files Created

- `services/s06_execution/broker_base.py` — Broker ABC + exceptions
- `services/s06_execution/broker_factory.py` — BrokerFactory
- `services/s02_signal_engine/pipeline.py` — SignalPipeline + PipelineState
- `tests/unit/s06/test_broker_base.py` — 15 tests (ABC, is_connected, factory)
- `tests/unit/s02/test_signal_pipeline.py` — 16 tests (all 7 pipeline steps)

### Files Modified

- `services/s06_execution/broker_alpaca.py` — inherits Broker, is_connected, place_order(ApprovedOrder)
- `services/s06_execution/broker_binance.py` — inherits Broker, is_connected, place_order(ApprovedOrder), _order_symbols tracking
- `services/s06_execution/paper_trader.py` — inherits Broker, connect/disconnect no-ops, place_order, _get_or_build_tick
- `services/s06_execution/service.py` — refactored to use BrokerFactory, _execute() simplified from 35 to 5 lines
- `services/s02_signal_engine/service.py` — _process_tick now 3 lines delegating to pipeline.run()

### Quality Gates

- ruff check: clean
- ruff format: 322 files
- mypy --strict: 324 files, 0 errors
- pytest: 1259 unit tests passed (+31 new), coverage 79.68%
- Integration tests: 21 passed, 27 skipped (no network/Docker), 7 TimescaleDB errors (pre-existing)
- Zero behavior regression

### Next Steps

- Phase 3.1 implementation
- Remaining P1 issue: #63 (S01 connector Decimal migration)
- Follow-up issue #102: fix full_report() Sharpe then enforce backtest-gate
