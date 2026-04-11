# APEX Whole-Codebase Architecture & Quality Audit

**Date**: 2026-04-11
**Auditor**: Claude Opus 4.6 (orchestrated by Clement Barbier)
**Scope**: Phase 1 + Phase 2 (S01-S10 + core + scripts + rust + tests + docs)
**Trigger**: Gate obligatoire avant Phase 3 (Feature Validation Harness)
**Reference**: Lopez de Prado (2018) "Advances in Financial Machine Learning" Ch. 1

---

## Executive Summary

| Metric | Value |
|---|---|
| Python files (production) | 188 (services: 142, core: 20, scripts: 18, backtesting: 5, supervisor: 3) |
| Python files (tests) | 131 (unit: 1228 tests, integration: 55 tests) |
| Production LOC | 31,149 |
| Test LOC | 17,501 |
| Test-to-production ratio | 0.56 |
| Total tests | 1,283 (1,228 unit + 55 integration) |
| Test coverage (measured) | 83% on measured modules |
| Coverage omit entries | 25 (see Section E for impact) |
| mypy strict (319 files) | 0 errors |
| `type: ignore` comments | 33 (all justified) |
| bandit security issues | 0 |
| Known CVEs (pip-audit) | 19 in 10 packages |
| Rust crates | 2 (apex_mc, apex_risk) — compile clean, 2 tests total |
| pylint rating | 9.96/10 |
| TODOs/FIXMEs | 1 |
| Total findings | **P0: 0, P1: 9, P2: 6, P3: 3** |
| **Decision** | **CLEARED for Phase 3** |

The APEX codebase is in **good overall health**. No blocking P0 issues were found. The architecture is clean: zero cross-service coupling, zero core→services imports, bandit-clean security, and mypy strict passing on all 319 files. The 9 P1 findings are primarily: (1) CI configuration drifting from documented standards, (2) `float()` usage where `Decimal` is mandated, (3) broker API keys not using `SecretStr`, (4) PROJECT_ROADMAP.md significantly out of date, and (5) known CVEs in dependencies. These can all be addressed in parallel with Phase 3 without risk. The codebase shows clear quality improvement from Phase 1 to Phase 2, with S01 demonstrating mature patterns (Strategy, Repository, Quality Pipeline) that are well-tested.

---

## Section A — SOLID Findings (par service)

### S01 Data Ingestion (78 files, 9,583 LOC) — **GOOD**

S01 is the largest and most mature service. It follows SOLID principles well:

- **SRP** ✅ — Clean separation: connectors/ (data fetching), normalizers/ (data transformation), quality/ (validation), serving/ (API), orchestrator/ (scheduling). Each module has one responsibility.
- **OCP** ✅ — New connectors are added by implementing `MacroConnectorBase` or the connector interface, without modifying existing code. NormalizerV2 uses Strategy pattern (`NormalizerStrategy`) for extensibility.
- **LSP** ✅ — All concrete connectors (Alpaca, Binance, Yahoo, FRED, ECB, BoJ, EDGAR, SimFin) implement their base contracts.
- **ISP** ✅ — Interfaces are focused: `DataQualityCheck` has a single `check()` method, connectors have `fetch_bars()`.
- **DIP** ✅ — Consumers depend on abstract interfaces, not concrete implementations.

**Finding A-1 (P2)**: `services/s01_data_ingestion/orchestrator/cli.py` — CLI class handles both display formatting AND business logic (fetching state, triggering runs). Minor SRP violation. Could split into a CLI formatter + a service layer.

### S02 Signal Engine (8 files, 1,759 LOC) — **ACCEPTABLE**

- **SRP** ✅ — Separate modules for microstructure, VPIN, technical indicators, crowd behavior, signal scoring.
- **OCP** ⚠️ — `technical.py` (190 LOC) has multiple indicator functions in a single module. Adding a new indicator requires modifying this file.

**Finding A-2 (P3)**: `services/s02_signal_engine/technical.py` — Monolithic indicator module. Consider splitting into per-indicator modules or using a Strategy pattern for each indicator family. Low priority since this file will likely be refactored during Phase 3.

### S03 Regime Detector (5 files, 893 LOC) — **CLEAN**

No violations found. Clean separation between regime engine, session tracker, and CB calendar.

### S04 Fusion Engine (8 files, 1,107 LOC) — **CLEAN**

Well-structured with separate modules for fusion, Kelly sizing, meta-labeling, hedge triggers, feature logging, and strategy.

### S05 Risk Manager (8 files, 1,628 LOC) — **CLEAN**

Circuit breaker, position rules, meta-label gate, exposure monitor, and CB event guard are properly separated. Risk Manager as VETO layer is correctly implemented.

### S06 Execution (7 files, 1,325 LOC) — **CLEAN**

Paper trader, optimal execution (Almgren-Chriss), and broker abstractions are properly separated.

### S07 Quant Analytics (9 files, 1,745 LOC) — **GOOD**

**S07 purity check** (critical for quant integrity):
- `market_stats.py` — Hurst, GARCH, Ljung-Box: **PURE** ✅ (stateless, no side effects)
- `realized_vol.py` — Bipower, TSRV, Parkinson: **PURE** ✅
- `rough_vol.py` — Rough volatility estimator: **PURE** ✅
- `regime_ml.py` — HMM regime ML: **PURE** ✅ (returns dicts, no mutations)
- `monte_carlo.py` — Monte Carlo simulation: **PURE** ✅
- `microstructure_adv.py` — VPIN, Hawkes, Kyle lambda: **PURE** ✅

All S07 metric functions are pure and composable. No hidden side effects, DB writes, or state mutations. This is exactly what ADR-0002 requires.

### S08 Macro Intelligence (6 files, 636 LOC) — **ACCEPTABLE**

- **Finding A-3 (P2)**: `cb_watcher.py` has 57% test coverage — the lowest of any tested module. Some methods are complex and untested.

### S09 Feedback Loop (5 files, 525 LOC) — **CLEAN**

Drift detector, signal quality, trade analyzer — all properly separated.

### S10 Monitor Dashboard (7 files, 1,739 LOC) — **ACCEPTABLE**

- **Finding A-4 (P3)**: `dashboard.py` contains large inline HTML/JS template strings. This is acknowledged in pyproject.toml (`E501` and `W291` ignores). Not a SOLID violation per se, but coupling between Python and frontend markup.

### core/ (20 files) — **GOOD**

- `BaseService`, `Bus`, `Config`, `Topics` — clean abstractions
- `math/` — fractional differentiation, labeling: pure functions ✅
- `models/` — frozen Pydantic v2 models: immutable data pipeline ✅

---

## Section B — Clean Code Findings

### Cyclomatic Complexity

pylint rating: **9.96/10**. No functions with cyclomatic complexity > 15 found in the automated scan. The codebase is exceptionally well-decomposed.

### Duplicate Code

3 duplications found by pylint (all in backfill scripts):
1. `scripts/backfill_binance` ↔ `scripts/backfill_equities` — insert loop (5 lines)
2. `scripts/backfill_binance` ↔ `scripts/backfill_yahoo` — checker/logger setup (6 lines)
3. `scripts/backfill_calendar` ↔ `scripts/backfill_fundamentals` — Windows event loop policy (6 lines)

**Finding B-1 (P3)**: Minor duplication in backfill scripts. Could extract a `BackfillRunner` base class. Low priority since scripts are operational tools, not core pipeline.

### Dead Code

vulture analysis: No significant dead code detected with confidence > 80%.

### TODOs/FIXMEs

Only 1 TODO in production code:
- `services/s05_risk_manager/cb_event_guard.py:129` — `TODO(APEX-CB-API-V2)`: tracked, intentional.

### `print()` in Production Code

**Finding B-2 (P2)**: `services/s01_data_ingestion/orchestrator/cli.py` uses `print()` (10 instances) instead of structlog. Acceptable for CLI tools but violates CLAUDE.md Section 10 which mandates structlog only.

### Long Functions

No functions exceeding 50 lines were found as problematic. The codebase maintains good function decomposition.

---

## Section C — Architecture Findings

### Cross-Service Coupling

| Check | Result |
|---|---|
| S0X imports from other S0Y | **CLEAN** — zero violations |
| core/ imports from services/ | **CLEAN** — zero violations |
| S01 connectors/ → normalizers/ | **CLEAN** |
| S01 connectors/ → serving/ | **CLEAN** |

**Architecture is exemplary.** All inter-service communication goes through ZMQ PUB/SUB and Redis as designed. No direct Python imports between services.

### Layering

S01 internal layering is correct:
- connectors/ → does not import normalizers/ or serving/
- normalizers/ → independent
- quality/ → independent
- serving/ → imports from core models only
- orchestrator/ → uses Redis state, independent of connectors

---

## Section D — Type Safety Findings

### mypy Strict

**319 files pass mypy strict with 0 errors.** ✅

### type: ignore Comments

**33 total `type: ignore` comments**. Breakdown:

| Category | Count | Justified? |
|---|---|---|
| External library type gaps (Alpaca SDK, Redis, asyncpg) | 18 | ✅ Yes — third-party type stubs incomplete |
| Pydantic validator return types | 6 | ✅ Yes — known Pydantic v2 mypy interaction |
| JSON response parsing (`no-any-return`) | 2 | ✅ Yes — unavoidable with dynamic JSON |
| Dynamic dispatch (`arg-type`) | 4 | ✅ Yes — connector dispatch pattern |
| Service runner instantiation | 1 | ✅ Yes — generic base class |
| Config validator | 2 | ✅ Yes — Pydantic field validators |

All 33 are justified. No gratuitous suppressions.

### mypy Blind Spots

**Finding D-1 (P1)**: `pyproject.toml` lines 83-92 set `ignore_errors = true` for:
- `core.models.*` — **concerning**: these are the immutable data pipeline models, the backbone of the system
- `core.config` — acceptable (Pydantic settings)
- `tests.*` — acceptable
- `services.s10_monitor.dashboard` — acceptable (HTML templates)

The `core.models.*` exclusion means type errors in data models are silently ignored. This undermines the "mypy strict zero errors" claim for the most critical module.

**Recommendation**: Remove `core.models.*` from `ignore_errors = true`. Fix any mypy errors that surface — they may reveal real type inconsistencies in the data pipeline.

### `float()` Usage for Financial Values

**Finding D-2 (P1)**: Widespread `float()` usage violating CLAUDE.md Section 10 ("Decimal, never float, for all prices, sizes, PnL, and fees"):

**In core models (most critical):**
- `core/models/order.py:215` — `float(self.net_pnl / ...)` → PnL division returning float
- `core/models/signal.py:203` — `float(reward / risk)` → financial ratio as float

**In S01 connectors (financial values from APIs):**
- `fred_connector.py:119` — `float(value)` for macro series values
- `ecb_connector.py:304` — `float(value)` for ECB data
- `boj_connector.py:277` — `float(cleaned)` for BoJ data
- `edgar_connector.py:269` — `float(val)` for SEC filing values
- `simfin_connector.py:268,312` — `float(val)` for SimFin financial data
- `macro_feed.py:118,204` — `float()` for DXY and macro values

**In S01 quality checks:**
- `outlier_check.py:26,34,35` — `float()` for price validation
- `price_check.py:76` — `float()` for spread calculation

**In S02 signal engine:**
- `microstructure.py:53,126,147,162,188,189` — `float()` for prices and financial metrics
- `crowd_behavior.py:203,204` — `float(prices[-1])` for current price

**Nuance**: Many `float()` calls in S07 (market_stats, monte_carlo) are for statistical computations (Hurst exponent, GARCH parameters, correlations) where `float` is appropriate — these are NOT financial values. Similarly, `float(np_scalar)` for numpy conversion is acceptable in signal computation paths.

**Recommendation**: Fix `float()` → `Decimal(str(...))` for all prices, sizes, PnL, and fees in core/models/ and S01 connectors. Leave statistical computation paths as-is.

---

## Section E — Tests Findings

### Coverage

**Measured coverage: 83%** on 7,259 measured LOC (from pytest --cov).

However, the effective coverage denominator is significantly reduced by 25 omit entries:

| Omitted Zone | LOC Estimate | Impact |
|---|---|---|
| `services/s01_data_ingestion/*.py` (wildcard) | ~9,583 | **Entire S01 excluded** (except quality/ and serving/) |
| `services/s10_monitor/*` | ~1,739 | Entire S10 excluded |
| `services/s06_execution/broker_*.py`, `order_manager.py` | ~500 | Broker and order management excluded |
| `services/s07_quant_analytics/monte_carlo.py`, `performance.py`, `microstructure_adv.py` | ~600 | Key quant modules excluded |
| `services/s08_macro_intelligence/geopolitical.py`, `sector_rotation.py` | ~200 | Macro modules excluded |
| `core/base_service.py`, `core/bus.py` | ~400 | Infrastructure excluded |
| `backtesting/engine.py`, `backtesting/data_loader.py` | ~300 | Backtest engine excluded |
| Other (service.py entrypoints, supervisor/, scripts/) | ~800 | Operational code excluded |

**Finding E-1 (P1)**: The true coverage including all omitted files is estimated at **~40-50%**, not 83%. The CI gate is set to `--cov-fail-under=40` (line 88 of ci.yml), which is far below the documented 85% standard in CLAUDE.md.

The omit list serves a legitimate purpose (network-dependent code can't be unit-tested), but it's overly broad. For example, `services/s01_data_ingestion/*.py` excludes connectors that could have their parsing logic tested without network calls.

**Recommendation**: Narrow the omit list. Extract pure parsing/transformation logic from connectors into testable utility functions. Raise the CI gate to at least 60% as an intermediate step toward the documented 85%.

### Test Counts

| Zone | Files | Tests |
|---|---|---|
| tests/unit/ | ~100+ | 1,228 |
| tests/integration/ | ~15+ | 55 |
| **Total** | | **1,283** |

### Notable Coverage Gaps

| Module | Coverage | Concern |
|---|---|---|
| `s02_signal_engine/technical.py` | 52% | Signal computation — core pipeline |
| `s08_macro_intelligence/cb_watcher.py` | 57% | CB event detection |
| `s01_data_ingestion/serving/deps.py` | 67% | FastAPI dependency injection |
| `s01_data_ingestion/quality/outlier_check.py` | 65% | Data quality validation |

### Mock Usage

Moderate mock usage across tests — no excessive mock leakage detected. The project correctly uses `fakeredis.aioredis.FakeRedis()` for Redis mocking as mandated.

---

## Section F — Security Findings

### bandit

**0 issues found** across 11,303 scanned lines. ✅

### pip-audit — Known CVEs

**Finding F-1 (P1)**: **19 known vulnerabilities in 10 packages**:

| Package | Installed | CVEs | Fix Version |
|---|---|---|---|
| urllib3 | 2.4.0 | 5 CVEs (CVE-2025-50181, CVE-2025-50182, CVE-2025-66418, CVE-2025-66471, CVE-2026-21441) | ≥2.6.3 |
| tornado | 6.5.1 | 2 CVEs (CVE-2026-31958, CVE-2026-35536) | ≥6.5.5 |
| requests | 2.32.4 | 1 CVE (CVE-2026-25645) | ≥2.33.0 |
| pillow | 11.2.1 | 1 CVE (CVE-2026-25990) | ≥12.1.1 |
| protobuf | 6.31.1 | 1 CVE (CVE-2026-0994) | ≥6.33.5 |
| pygments | 2.19.1 | 1 CVE (CVE-2026-4539) | ≥2.20.0 |
| pip | 25.1.1 | 2 CVEs | ≥26.0 |
| streamlit | 1.45.1 | 1 CVE (CVE-2026-33682) | ≥1.54.0 |
| curl-cffi | 0.13.0 | 1 CVE (CVE-2026-33752) | ≥0.15.0 |
| wheel | 0.45.1 | 1 CVE (CVE-2026-24049) | ≥0.46.2 |

**Recommendation**: Update `requirements.txt` minimum versions for urllib3, requests, tornado, and pillow (the packages used in hot paths). The others (pip, wheel, streamlit, pygments) are dev/build tools with lower risk.

### Hardcoded API Keys

**No hardcoded API keys found** in production code. ✅

### Broker Keys Not Using SecretStr

**Finding F-2 (P1)**: Alpaca and Binance API keys in `core/config.py` use plain `str` instead of `SecretStr`:

| Field | Line | Type | Should Be |
|---|---|---|---|
| `alpaca_api_key` | 41 | `str` | `SecretStr` |
| `alpaca_api_secret` | 42 | `str` | `SecretStr` |
| `binance_api_key` | 53 | `str` | `SecretStr` |
| `binance_secret_key` | 54 | `str` | `SecretStr` |
| `timescale_password` | 264 | `str` | `SecretStr` |

Meanwhile, FRED/Massive/SimFin keys correctly use `SecretStr` (lines 66-87). This inconsistency means broker keys (the most sensitive credentials — real money access) could be accidentally logged by structlog. Issue #71.

### Missing HTTP Timeouts

No missing timeout issues found on httpx/requests calls in production code. ✅

---

## Section G — Documentation Findings

### Module Docstrings

Most modules have appropriate docstrings. No systemic documentation gap.

### ADR Alignment

| ADR | Aligned with Code? |
|---|---|
| ADR-0001 (ZMQ XSUB/XPUB) | ✅ — broker topology implemented as specified |
| ADR-0002 (Quant Methodology) | ✅ — metrics in backtesting/metrics.py implement the 10-point checklist |
| ADR-0003 (Universal Data Schema) | ✅ — TimescaleDB schema, UUID PKs, NUMERIC(20,8) all implemented |

### PROJECT_ROADMAP.md

**Finding G-1 (P1)**: PROJECT_ROADMAP.md is **significantly out of date**:

| Item | Roadmap Says | Reality |
|---|---|---|
| Phase 2 status | "IN PROGRESS" (2.1-2.6 done) | **DONE** — all 12 sub-phases (2.1-2.12) merged |
| Sub-phases 2.7-2.12 | "IN PROGRESS" or "PENDING" | All **DONE** and merged to main |
| Total tests | "935+" | **1,283** |
| PRs merged | "47+" | **28** merged PRs (count discrepancy) |
| Services fully implemented | "S01 (partial), S02 (scaffolded)" | S01 is complete with 78 files, all connectors merged |
| Branch status | "feat/macro-connectors in progress" | Branch merged, main is clean |
| Last updated | "2026-04-10" | Content reflects state as of ~Phase 2.6 |

**Recommendation**: Complete rewrite of Section 4, update Phase 2 to DONE status, update all metrics to current values.

---

## Section H — Dependencies Findings

### Pinning Strategy

**Finding H-1 (P2)**: All 43 dependencies in `requirements.txt` use `>=` minimum version only. No `==` pins, no upper bounds.

This means:
- Builds are not reproducible (a new release could break any build)
- No `requirements.lock` or `pip freeze` output committed

**Recommendation**: Add a `requirements-lock.txt` with pinned versions for reproducible builds. Keep `requirements.txt` with `>=` for compatibility, but lock the exact versions used in CI.

### Outdated Packages

19 packages have known CVEs (see Section F). General outdatedness is expected given the `>=` pinning strategy.

---

## Section I — Rust Findings

### Compilation

Both crates compile successfully:
- `apex_mc` — ✅ `cargo check` clean
- `apex_risk` — ✅ `cargo check` clean

Workspace `Cargo.lock` is committed at `rust/Cargo.lock`. ✅

### Tests

| Crate | Tests | Status |
|---|---|---|
| apex_mc | 2 (var_positive, simulate_paths_shape) | ✅ Pass |
| apex_risk | **0** | ⚠️ No tests |

**Finding I-1 (P2)**: `apex_risk` has **zero tests**. This crate is designed to be the hot-path risk chain (p99 < 5ms target per CLAUDE.md). While it's currently minimal (Phase 6 will build it out), having zero tests on any production crate is concerning.

**Recommendation**: Add basic smoke tests before Phase 6 builds on this crate. At minimum: test that the crate compiles and exports the expected Python bindings.

---

## Section J — CI/CD Findings

### Workflow Inventory

| Workflow | Status | Purpose |
|---|---|---|
| `ci.yml` | Active | quality → rust → unit-tests → integration-tests → backtest-gate |
| `backtest.yml` | Active | Dedicated backtest workflow |
| `_disabled_cd.yml` | Disabled (prefixed) | Docker build and push — disabled until Phase 7 |

### CI Configuration Drift

**Finding J-1 (P1)**: The CI pipeline has **three significant deviations** from documented standards:

1. **Coverage gate**: CI uses `--cov-fail-under=40` (ci.yml line 88). CLAUDE.md Section 7 mandates 85%. The documentation claims "Coverage gate: 85% minimum — enforced by CI" which is factually incorrect.

2. **Backtest gate**: CI uses `continue-on-error: true` (ci.yml line 113), meaning the backtest job can fail without blocking merges. CLAUDE.md Section 6 says "Never suggest merging if CI is red."

3. **Backtest thresholds**: CI uses `BACKTEST_MIN_SHARPE: "0.5"` and `BACKTEST_MAX_DD: "0.12"` (ci.yml lines 127-128). CLAUDE.md Section 6 specifies Sharpe ≥ 0.8 and max DD ≤ 8%.

**Recommendation**: Either update the CI to match documented standards, or update the documentation to reflect the current (looser) gates with rationale for why they're appropriate at this stage. The current state is misleading.

### Action Versions

Mostly up to date:
- `actions/checkout@v5` ✅
- `actions/setup-python@v6` ✅
- `dtolnay/rust-toolchain@stable` ✅
- `Swatinem/rust-cache@v2` ✅
- `codecov/codecov-action@v5` ✅
- `actions/upload-artifact@v4` ✅

Note: `_disabled_cd.yml` uses `actions/checkout@v4` (one version behind) and `actions/setup-python` is not specified there — but since it's disabled, this is informational only.

---

## Section K — Cross-Phase Coherence Findings

### Phase 1 ↔ Phase 2 Alignment

| Convention | Phase 1 Code | Phase 2 Code | Aligned? |
|---|---|---|---|
| Decimal for prices | ✅ backtesting/metrics.py uses Decimal | ⚠️ Connectors use float() | **NO** — see Finding D-2 |
| UTC datetimes | ✅ No naive datetime.now() found | ✅ No violations | ✅ |
| structlog | ✅ | ⚠️ CLI uses print() | **Partial** |
| Frozen Pydantic v2 | ✅ core/models/ | ✅ All data models frozen | ✅ |
| asyncio (no threading) | ✅ | ✅ | ✅ |
| ZMQ topics from core/topics.py | ✅ | ✅ | ✅ |

### ADR Compliance

All 3 ADRs are respected by the current code. No architectural drift from ADR-0001 (ZMQ), ADR-0002 (Quant), or ADR-0003 (Data Schema).

### Immutable Data Pipeline

The hierarchy `Tick → NormalizedTick → Signal → OrderCandidate → ApprovedOrder → ExecutedOrder → TradeRecord` is maintained with frozen Pydantic v2 models. ✅

---

## Section L — Action Items Prioritized

### P0 (blocks Phase 3)

None. No blocking issues found.

### P1 (important — address within 2 weeks)

| # | Finding | File(s) | Effort | Issue |
|---|---|---|---|---|
| P1-1 | CI coverage gate at 40% vs documented 85% | `.github/workflows/ci.yml:88` | S | #64 |
| P1-2 | CI backtest gate non-blocking (`continue-on-error: true`) | `.github/workflows/ci.yml:113` | S | #65 |
| P1-3 | CI backtest thresholds (Sharpe 0.5/DD 12%) vs documented (0.8/8%) | `.github/workflows/ci.yml:127-128` | S | #65 |
| P1-4 | `float()` usage for financial values in core/models and S01 connectors | core/models/, services/s01_*/ | M | #66 |
| P1-5 | PROJECT_ROADMAP.md significantly outdated (Phase 2 shown as IN PROGRESS) | `docs/PROJECT_ROADMAP.md` | M | #67 |
| P1-6 | 19 CVEs in 10 packages (urllib3, requests, tornado, pillow) | `requirements.txt` | S | #68 |
| P1-7 | mypy `ignore_errors=true` for `core.models.*` | `pyproject.toml:83-92` | M | #69 |
| P1-8 | Coverage omit too broad — S01 entirely excluded, true coverage ~40-50% | `pyproject.toml:112-147` | L | #70 |
| P1-9 | Broker API keys (Alpaca, Binance) use `str` instead of `SecretStr` | `core/config.py:41-42,53-54` | S | #71 |

### P2 (cosmetic — address when convenient)

| # | Finding | File(s) | Effort |
|---|---|---|---|
| P2-1 | CLI uses `print()` instead of structlog | `services/s01_data_ingestion/orchestrator/cli.py` | S |
| P2-2 | S01 CLI minor SRP violation (display + business logic) | `services/s01_data_ingestion/orchestrator/cli.py` | S |
| P2-3 | `cb_watcher.py` at 57% coverage | `services/s08_macro_intelligence/cb_watcher.py` | M |
| P2-4 | `apex_risk` Rust crate has 0 tests | `rust/apex_risk/` | S |
| P2-5 | No `requirements-lock.txt` for reproducible builds | `requirements.txt` | S |
| P2-6 | `technical.py` monolithic indicators (52% coverage) | `services/s02_signal_engine/technical.py` | M |

### P3 (nice-to-have)

| # | Finding | File(s) | Effort |
|---|---|---|---|
| P3-1 | Duplicate code in backfill scripts (3 instances, 5-6 lines each) | `scripts/backfill_*.py` | S |
| P3-2 | `technical.py` could be split into per-indicator modules | `services/s02_signal_engine/technical.py` | M |
| P3-3 | S10 dashboard inline HTML/JS templates | `services/s10_monitor/dashboard.py` | L |

---

## Section M — Decision: Cleared for Phase 3

**Decision**: **YES — CLEARED for Phase 3**

**Justification**:

1. **No P0 blockers.** The codebase has zero blocking issues that would compromise Phase 3 work.

2. **Architecture is sound.** Zero cross-service coupling, zero core→services imports, clean layering in S01, all ADRs respected. The microservice boundary discipline is excellent.

3. **Type safety is strong.** mypy strict passes on 319 files with 0 errors. The 33 `type: ignore` comments are all justified. The `core.models.*` mypy exclusion (P1-7) is concerning but not blocking.

4. **Security posture is good.** bandit: 0 issues. No hardcoded keys. The CVEs (P1-6) are in transitive dependencies and can be patched with a simple version bump.

5. **Test infrastructure is mature.** 1,283 tests all passing, fakeredis for unit isolation, pytest-asyncio, Hypothesis property tests. The coverage number (83% measured / ~45% true) is the weakest point but does not block Phase 3.

6. **P1 items are parallelizable.** All 9 P1 findings can be addressed in parallel with Phase 3 work via separate issues/PRs without blocking the feature validation harness.

**Phase 3 can begin immediately.** The P1 items should be tracked as a separate "tech debt sprint" running alongside Phase 3 sub-phases.

**If Phase 3 design gate (#61) is ready, it can be launched now.**

---

*Audit completed 2026-04-11. Total audit duration: ~1 session.*
*Next audit recommended: after Phase 3 completion, before Phase 4.*
