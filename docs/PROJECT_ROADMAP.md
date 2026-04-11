# APEX / CashMachine — Project Roadmap

**Source of truth for project state, planning, and execution.**

| Field | Value |
|---|---|
| Maintainer | Clement Barbier |
| Created | 2026-04-10 |
| Last updated | 2026-04-10 |
| Update frequency | After each sub-phase merge |

---

## Table of Contents

1. [Vision and Strategic Objectives](#1-vision-and-strategic-objectives)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Code Conventions and Quality Standards](#3-code-conventions-and-quality-standards)
4. [Current State (Snapshot)](#4-current-state-snapshot)
5. [Roadmap by Phase](#5-roadmap-by-phase)
6. [Planning Methodology](#6-planning-methodology)
7. [Academic Standards](#7-academic-standards)
8. [ADR Index](#8-adr-index)
9. [Identified Risks and Mitigations](#9-identified-risks-and-mitigations)
10. [Appendices](#10-appendices)
11. [Document Changelog](#11-document-changelog)
12. [Governance & Methodology](#12-governance--methodology)

---

## 1. Vision and Strategic Objectives

### Long-term vision

APEX is an autonomous quantitative trading engine designed for personal use by a single
operator (Clement Barbier). The system targets maximum alpha generation on US equities
(NYSE/Nasdaq via Alpaca) and cryptocurrency (BTC/ETH via Binance), with potential
expansion to additional asset classes and brokers (IBKR) as the system matures.

The end state is a continuously adaptive, multi-strategy pipeline that:

- Ingests real-time market data, macro signals, central bank announcements, and
  alternative data across multiple asset classes and geographies.
- Computes signals on every tick using academically validated features with
  institutional-grade statistical testing (PSR, DSR, PBO, CPCV).
- Detects regime changes in real-time (HMM, Markov-switching) and adjusts capital
  allocation, position sizing, and strategy weights dynamically.
- Enforces risk rules as a non-bypassable veto layer with sub-5ms latency (Rust).
- Executes orders through multiple brokers with slippage-aware routing.
- Monitors its own signal quality drift, adjusts, and reports degradation as it happens.
- Provides a personal dashboard for deployment monitoring and performance tracking.

### Target audience

Personal trading only. No external clients. No SaaS. No fund management.
The system is built to institutional standards for one reason: to avoid the amateur
pitfalls (overfitting, selection bias, transaction cost blindness) that cause 95% of
retail quant strategies to fail (Harvey, Liu & Zhu, 2016).

### Quality benchmarks

The project holds itself to the standards of institutional quant shops:

- **Two Sigma** — systematic signal generation, rigorous statistical testing
- **AQR Capital Management** — factor-based approach, academic rigor in research
- **Man AHL** — machine learning applied to systematic trading with scientific discipline
- **Renaissance Technologies** — relentless empiricism, no ad hoc proxies

These are aspirational benchmarks, not claims of equivalence.

### Guiding principles

1. **Academic rigor over shortcuts.** Every signal, metric, and model must have a
   published academic reference. No ad hoc proxies.
2. **Mathematical consistency.** Decimal arithmetic for all financial quantities.
   UTC timestamps everywhere. Immutable data pipeline.
3. **Continuous adaptation.** Every service that consumes external data must update
   its state continuously. Static services are regressions.
4. **Risk as veto.** The Risk Manager (S05) cannot be bypassed under any circumstance.
   Circuit breaker state machine validated on every startup.
5. **Measure before optimizing.** Profile hot paths. Benchmark before and after.
   No premature optimization.

---

## 2. High-Level Architecture

### Service topology

```
                           ┌──────────────────────────────────────────────────┐
                           │              ZMQ XSUB/XPUB Broker               │
                           │          (core/zmq_broker.py — BINDS)           │
                           └──────────┬───────────────────────┬──────────────┘
                                      │  All services CONNECT │
         ┌────────────────────────────┼───────────────────────┼──────────────────────┐
         │                            │                       │                      │
   ┌─────▼─────┐  tick.*       ┌─────▼─────┐  signal.*  ┌───▼──────┐  regime.*     │
   │    S01     │──────────────►│    S02     │──────────►│   S03    │──────────┐    │
   │   Data     │               │  Signal    │           │  Regime  │          │    │
   │ Ingestion  │               │  Engine    │           │ Detector │          │    │
   └────────────┘               └────────────┘           └──────────┘          │    │
         │                            │                       │                │    │
         │                            │                       │          ┌─────▼────▼──┐
         │                            │                       └─────────►│     S04     │
         │                            │                                  │   Fusion    │
         │                            │                                  │   Engine    │
         │                            │                                  └──────┬──────┘
         │                            │                                         │
         │                            │                              order.*    │
         │                            │                                  ┌──────▼──────┐
         │                            │                                  │     S05     │
         │                            │                                  │    Risk     │
         │                            │                                  │  Manager    │
         │                            │                                  │  (VETO)     │
         │                            │                                  └──────┬──────┘
         │                            │                                         │
         │                            │                              approved.* │
         │                            │                                  ┌──────▼──────┐
         │                            │                                  │     S06     │
         │                            │                                  │  Execution  │
         │                            │                                  │   Engine    │
         │                            │                                  └─────────────┘
         │                            │
   ┌─────┴──────────────────────┬─────┴─────────────────────────────────────────┐
   │  Support Services          │                                               │
   │                            │                                               │
   │  ┌────────────┐  ┌────────┴───┐  ┌────────────┐  ┌────────────┐          │
   │  │    S07     │  │    S08     │  │    S09     │  │    S10     │          │
   │  │   Quant    │  │   Macro    │  │  Feedback  │  │  Monitor   │          │
   │  │ Analytics  │  │   Intel    │  │    Loop    │  │ Dashboard  │          │
   │  └────────────┘  └────────────┘  └────────────┘  └────────────┘          │
   └──────────────────────────────────────────────────────────────────────────┘

                           ┌────────────────────┐
                           │       Redis        │
                           │  (state + cache)   │
                           └────────────────────┘

                           ┌────────────────────┐
                           │    TimescaleDB     │
                           │ (bars, ticks, etc) │
                           └────────────────────┘
```

### Immutable data pipeline

```
Tick → NormalizedTick → Signal → OrderCandidate → ApprovedOrder → ExecutedOrder → TradeRecord
```

Each stage produces a new frozen Pydantic v2 object. No mutations.

### Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 (services), Rust/PyO3 (CPU-bound math) |
| Messaging | ZeroMQ XSUB/XPUB broker (core/zmq_broker.py) |
| State / Cache | Redis |
| Time-series DB | TimescaleDB (PostgreSQL + hypertables) |
| Data models | Pydantic v2 (frozen) |
| Containerization | Docker + docker-compose |
| API (internal) | FastAPI (S10 dashboard, future serving layer) |
| Data processing | Polars (bulk), NumPy (vectorized signals) |
| Rust crates | apex_mc (Monte Carlo), apex_risk (risk chain) |
| CI/CD | GitHub Actions (quality → rust → unit → integration → backtest-gate) |

---

## 3. Code Conventions and Quality Standards

These are non-negotiable. Enforced on every commit via CI.

### Arithmetic and types

- `Decimal` for all prices, sizes, PnL, fees. Never `float`.
- `datetime.now(timezone.utc)` for all timestamps. Never naive datetimes.
- Complete type annotations on every function. `mypy --strict` zero errors.
- No bare generics: `dict[str, Any]`, `list[T]`, not `dict`, `list`.

### Logging and concurrency

- `structlog` only. Never `print()`, never `logging.basicConfig()`.
- `asyncio` only. Never `threading.Thread` inside a service.
- `await asyncio.sleep(x)`. Never `time.sleep(x)`.

### Testing

- `fakeredis.aioredis.FakeRedis()` for Redis in unit tests.
- Hypothesis property tests (1000 examples) for mathematical functions.
- Coverage gate: 85% minimum, enforced by CI.
- Tests in `tests/unit/` (no external deps) and `tests/integration/` (full pipeline).

### Linting and formatting

- `ruff check` + `ruff format` (line-length 100, target py312).
- `bandit` for security scanning.
- `mypy --strict` for type checking.

### Performance targets

- Hot path latency: < 5ms per tick for signal computation.
- Risk chain (S05): p99 < 5ms (Rust apex_risk).
- Polars over pandas for all bulk data transformations.
- NumPy vectorized ops — never Python loops over arrays in signal computation.

---

## 4. Current State (Snapshot)

*Last updated: 2026-04-11 (post Phase 3 design gate)*

### Phase summary

| Phase | Status | Sub-phases merged | Tests | Last merge date |
|---|---|---|---|---|
| Phase 1 | DONE | All (ADR-0002 + quant metrics + validation) | ~400 | 2026-04-10 |
| Phase 2 | **DONE** | All 12 (2.1–2.12) | 1,283 | 2026-04-11 |
| Phase 3 | **DESIGN COMPLETE** | 0/13 (spec ready) | — | — |
| Phase 4 | PENDING | — | — | — |
| Phase 5 | PENDING | — | — | — |
| Phase 6 | PENDING | — | — | — |
| Phase 7 | PENDING | — | — | — |
| Phase 8 | PENDING | — | — | — |
| Phase 9 | PENDING | — | — | — |
| Phase 10 | PENDING | — | — | — |
| Phase 11 | PENDING | — | — | — |
| Phase 12 | PENDING | — | — | — |

**Estimated overall completion: ~20-25% of total project scope.**

### Whole-codebase audit (2026-04-11)

Conducted as gate before Phase 3 (refs #55). Full report:
`docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md`

| Metric | Value |
|---|---|
| Findings | P0: 0, P1: 15, P2: 13, P3: 6 |
| Decision | **CLEARED for Phase 3** |
| Issues created | #64–#77 (14 issues) |

Top P1 findings: CI gates drifted from standards (#64,#65), float→Decimal (#66),
SecretStr for broker keys (#71), SOLID violations in S02-S06 (#72–#76),
19 CVEs (#68). All addressable in parallel with Phase 3.

### Key metrics

- **Total tests**: 1,283 (1,228 unit + 55 integration, all green)
- **mypy strict**: zero errors (319 files)
- **ruff**: clean (zero warnings)
- **pylint**: 9.96/10
- **bandit**: zero security issues
- **Coverage**: 83% on measured modules (~45% including omitted files)
- **ADRs accepted**: 3 (ZMQ topology, Quant Methodology Charter, Universal Data Schema)
- **PRs merged**: 28
- **Services scaffolded**: 10/10 (S01-S10)
- **S01 Data Ingestion**: fully implemented (78 files, 9,583 LOC, all connectors merged)
- **Production LOC**: 31,149 | **Test LOC**: 17,501

### Branch status

- `main` is the integration branch. All sub-phases merge to `main` via PR.
- No active feature branches. Working tree clean.

---

## 5. Roadmap by Phase

---

### Phase 1 — Quant Methodology Foundation

| Field | Value |
|---|---|
| Status | **DONE** |
| Services concerned | S02 (Signal Engine), S05 (Risk Manager), S09 (Feedback Loop) |
| Duration | ~1 week |
| Dependencies | Initial repo scaffolding |
| Roadmap weight | ~5% |

#### Objective

Establish the quantitative methodology charter that governs all future signal, strategy,
and backtest development. Ensure the project cannot regress to amateur-grade evaluation
practices (Sharpe-only, no OOS, no multiple-testing correction).

#### Sub-phases (all DONE)

- **1.1** ADR-0002: Quant Methodology Charter — 15 canonical references, 10-point
  mandatory evaluation checklist, anti-pattern rejection criteria.
- **1.2** Quant scaffolding audit — inventory of existing PSR/DSR/CPCV/fractional-diff/
  meta-labeling scaffolding vs. ADR-0002 requirements.
- **1.3** PSR + DSR + bootstrap Sharpe CI wired into `full_report()`.
- **1.4** Rank-PBO via CPCV integrated, scalar proxy deprecated.
- **1.5** Ulcer Index, Calmar, Sortino, Martin ratio + distribution stats.
- **1.6** Cost sensitivity report (zero / realistic / stress scenarios).
- **1.7** Regime-conditional Sharpe/DD/Ulcer + HHI concentration index.
- **1.8** OOS walk-forward gate with embargo.
- **1.9** Turnover ratio, alpha decay half-life, capacity estimate.
- **1.10** Almgren-Chriss market impact model + avg_slippage_bps.
- **1.11** Async circuit breaker integration tests (S05 v2 API).

#### Deliverables

- [x] ADR-0002 accepted and binding on all future quant PRs
- [x] `backtesting/metrics.py` — `full_report()` with all 10 ADR-0002 evaluation points
- [x] PR template `.github/PULL_REQUEST_TEMPLATE/quant.md` enforcing ADR-0002 checklist
- [x] Quant agent prompt `.github/agents/apex-quant.agent.md` referencing ADR-0002
- [x] Scaffolding audit document `docs/audits/`

#### Success metrics

- Every quant PR template includes ADR-0002 compliance section.
- `full_report()` computes PSR, DSR, PBO, CPCV, Ulcer, Calmar, Sortino, cost sensitivity,
  regime decomposition, OOS gate, turnover, capacity, and Almgren-Chriss slippage.
- Integration tests for S05 circuit breaker pass on async v2 API.

#### Canonical references

1. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
2. Bailey, D. H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio".
   *Journal of Portfolio Management*, 40(5), 94-107.
3. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2014).
   "The Probability of Backtest Overfitting". *Journal of Computational Finance*.
4. Harvey, C. R. & Liu, Y. (2015). "Backtesting". *Journal of Portfolio Management*,
   42(1), 13-28.
5. Almgren, R. & Chriss, N. (2001). "Optimal execution of portfolio transactions".
   *Journal of Risk*, 3(2), 5-40.
6. Kelly, J. L. (1956). "A New Interpretation of Information Rate".
   *Bell System Technical Journal*, 35(4), 917-926.
7. Politis, D. N. & Romano, J. P. (1994). "The Stationary Bootstrap". *JASA*, 89(428),
   1303-1313.

#### Open questions

- None. Phase 1 is complete and serves as the foundation for all future phases.

#### ADRs

- **ADR-0002**: Quant Methodology Charter — ACCEPTED (2026-04-08)

---

### Phase 2 — Universal Data Infrastructure

| Field | Value |
|---|---|
| Status | **DONE** |
| Services concerned | S01 (Data Ingestion) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 1 merged (methodology charter in place) |
| Roadmap weight | ~15% |

#### Objective

Build a universal, asset-agnostic data ingestion pipeline that can ingest, normalize,
validate, and serve market data (micro), macro-economic data, fundamental data, and
calendar events from any source. The pipeline must handle equities, crypto, FX, indices,
ETFs, and fixed-income data through a single unified schema stored in TimescaleDB.

#### Sub-phases (detailed)

| Sub-phase | Title | Status | PR | Merge date |
|---|---|---|---|---|
| 2.1 | Universal TimescaleDB schema + asset registry | DONE | #37 | 2026-04-10 |
| 2.2 | NormalizerV2 — asset-agnostic Strategy pattern | DONE | #39 | 2026-04-10 |
| 2.3 | Data Quality Pipeline — composable validation | DONE | #41 | 2026-04-10 |
| 2.4 | Binance historical + live connector | DONE | #43 | 2026-04-10 |
| 2.5 | Alpaca + Massive equities connectors | DONE | #45 | 2026-04-10 |
| 2.6 | Yahoo Finance — indices, FX, ETFs | DONE | #47 | 2026-04-10 |
| 2.7 | Macro connectors — FRED + ECB + BoJ | DONE | #49 | 2026-04-10 |
| 2.8 | Calendar events (FOMC, ECB, CPI, NFP) | DONE | #51 | 2026-04-10 |
| 2.9 | Fundamentals (SEC EDGAR + SimFin) | DONE | #53 | 2026-04-10 |
| 2.10 | Internal serving layer (REST) | DONE | #56 | 2026-04-10 |
| 2.11 | Backfill orchestrator | DONE | #58 | 2026-04-11 |
| 2.12 | Observability (metrics, tracing, healthchecks) | DONE | #62 | 2026-04-11 |

#### Sub-phase details

**2.1 — Universal TimescaleDB schema + asset registry (DONE)**
- Universal `bars` table with composite PK `(asset_id, bar_type, bar_size, timestamp)`.
- `assets` table with UUID PKs for decentralized ID generation.
- TimescaleDB hypertable with `compress_segmentby = 'asset_id, bar_type, bar_size'`.
- AsyncPG repository pattern for all DB operations.
- ADR-0003 documenting all schema design decisions.

**2.2 — NormalizerV2 asset-agnostic (DONE)**
- Strategy pattern: `NormalizerStrategy` interface with per-source implementations.
- `NormalizerRouter` dispatches to the correct strategy based on source/asset class.
- All normalizers produce the same `NormalizedBar` / `NormalizedTick` output.
- Cache-aware deduplication via Redis.

**2.3 — Data Quality Pipeline (DONE)**
- Composable `DataQualityChecker` with pluggable validation rules.
- Checks: timestamp monotonicity, price positivity, OHLC consistency, volume sanity,
  gap detection, staleness detection.
- Quality scores published to Redis for S09 Feedback Loop visibility.

**2.4 — Binance connector (DONE)**
- Historical klines via REST API with pagination and rate limiting.
- Live WebSocket stream for real-time ticks.
- Support for BTC/USDT, ETH/USDT, and configurable symbol list.
- Testnet mode for paper trading.

**2.5 — Alpaca + Massive equities connectors (DONE)**
- Alpaca: historical bars via REST, real-time via WebSocket (IEX feed).
- Massive (ex-Polygon): S3 flatfile bulk download for historical equity data.
- Covers NYSE + Nasdaq listed equities.

**2.6 — Yahoo Finance indices/FX/ETFs (DONE)**
- Indices: ^GSPC (S&P 500), ^DJI (Dow Jones), ^IXIC (Nasdaq), ^VIX, ^RUT.
- FX: EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD.
- ETFs: SPY, QQQ, IWM, TLT, GLD, USO, HYG, LQD, EEM, VXX.
- Daily resolution via yfinance with DataQualityChecker integration.

**2.7 — Macro connectors FRED + ECB + BoJ (IN PROGRESS)**
- FRED: US macro series (GDP, CPI, NFP, unemployment, Fed Funds, yield curve,
  credit spreads, consumer sentiment, ISM PMI, housing starts).
- ECB Statistical Data Warehouse: Euro area rates, M3 money supply, HICP inflation.
- Bank of Japan: policy rate, monetary base, Tankan survey.
- All connectors inherit from `MacroConnectorBase` with unified `fetch()` interface.

**2.8 — Calendar events (PENDING)**
- Central bank meeting dates: FOMC, ECB Governing Council, BoJ, BoE.
- Economic releases: CPI, NFP, ISM PMI, retail sales, GDP.
- Structured event objects with expected impact level (HIGH/MEDIUM/LOW).
- Integration with S08 Macro Intelligence for pre-event blocking.

**2.9 — Fundamentals (PENDING)**
- SEC EDGAR: quarterly filings (10-Q, 10-K), insider transactions (Form 4).
- SimFin: standardized financial statements, ratios.
- Earnings calendar integration.

**2.10 — Internal serving layer (PENDING)**
- FastAPI or gRPC internal API for services to query historical data.
- Replaces direct DB queries from individual services.
- Caching layer with Redis.

**2.11 — Backfill orchestrator (PENDING)**
- CLI tool to backfill historical data for any connector/date range.
- Resume-capable (tracks last successful timestamp per asset/source).
- Rate-limit aware with exponential backoff.

**2.12 — Observability (PENDING)**
- Prometheus metrics for each connector (latency, error rate, throughput).
- Structured tracing for data pipeline (ingest → normalize → validate → store).
- Health check endpoints for Docker orchestration.

#### Deliverables

- [x] Universal TimescaleDB schema with asset registry — DONE (2.1)
- [x] Asset-agnostic normalizer (Strategy pattern) — DONE (2.2)
- [x] Data quality pipeline with composable checks — DONE (2.3)
- [x] Connectors: Binance, Alpaca, Massive, Yahoo Finance — DONE (2.4, 2.5, 2.6)
- [x] Connectors: FRED, ECB, BoJ — DONE (2.7)
- [x] Calendar event ingestion and structured event model — DONE (2.8)
- [x] Fundamentals pipeline (SEC EDGAR + SimFin) — DONE (2.9)
- [x] Internal data serving API (REST) — DONE (2.10)
- [x] Backfill orchestrator CLI — DONE (2.11)
- [x] Observability stack (metrics, tracing, healthchecks) — DONE (2.12)

#### Success metrics

- Any new data source can be added by implementing a single connector class.
- All connectors produce `NormalizedBar` / `NormalizedTick` through the same pipeline.
- Data quality scores are published to Redis and visible to S09 Feedback Loop.
- TimescaleDB stores all asset classes in a single unified schema.
- Zero data type inconsistencies (Decimal prices, UTC timestamps) across all sources.

#### Canonical references

1. Kleppmann, M. (2017). *Designing Data-Intensive Applications*. O'Reilly.
2. Makarov, I. & Schoar, A. (2020). "Trading and Arbitrage in Cryptocurrency Markets".
   *Journal of Financial Economics*, 135(2), 293-319.
3. Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018). *Trades, Quotes and
   Prices: Financial Markets Under the Microscope*. Cambridge University Press.
4. Cochrane, J. H. (2005). *Asset Pricing* (Revised Edition). Princeton University Press.
5. Lucca, D. O. & Moench, E. (2015). "The Pre-FOMC Announcement Drift".
   *Journal of Finance*, 70(1), 329-371.

#### Open questions

- **2.8**: Which calendar source? Investing.com scraping vs. paid API (FedWatch, Econ
  Calendar API). Need to evaluate reliability and latency.
- **2.9**: SEC EDGAR rate limits (10 req/s) — is that sufficient for real-time
  monitoring of insider transactions?
- **2.10**: REST vs. gRPC for internal serving. REST is simpler; gRPC is faster for
  inter-service communication. Decision needed before implementation.
- **2.11**: Should backfill run as a standalone script or as a service (S01 mode)?

#### ADRs

- **ADR-0003**: Universal Data Schema Design Decisions — ACCEPTED (2026-04-10)

---

### Phase 3 — Feature Validation Harness

| Field | Value |
|---|---|
| Status | **DESIGN COMPLETE** (2026-04-11) |
| Services concerned | S02 (Signal Engine), S07 (Quant Analytics), S09 (Feedback Loop) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 2 merged (all data sources available) |
| Roadmap weight | ~10% |
| Design spec | `docs/phases/PHASE_3_SPEC.md` (complete, 13 sub-phases) |

#### Objective

Build a rigorous feature validation pipeline that measures the predictive power of every
signal and feature before it enters the live trading pipeline. No feature is accepted
without passing IC measurement, stability testing, multicollinearity checks, CPCV with
purging, and multiple hypothesis testing (DSR, PBO). This phase operationalizes ADR-0002
at the feature level.

**Full specification**: See `docs/phases/PHASE_3_SPEC.md` for detailed sub-phase
breakdowns with academic justification, technical deliverables, success metrics, risks,
and 60 Tier-1 academic references.

#### Sub-phases (detailed in PHASE_3_SPEC.md)

| Sub-phase | Title | Status |
|---|---|---|
| 3.1 | Feature Engineering Pipeline Foundation | PENDING |
| 3.2 | Feature Store Architecture | PENDING |
| 3.3 | Information Coefficient Measurement | PENDING |
| 3.4 | HAR-RV Validation (Corsi 2009) | PENDING |
| 3.5 | Rough Volatility Validation (Gatheral et al. 2018) | PENDING |
| 3.6 | Order Flow Imbalance Validation (Cont et al. 2014) | PENDING |
| 3.7 | CVD + Kyle Lambda Validation (Kyle 1985) | PENDING |
| 3.8 | GEX Validation (Barbon & Buraschi 2020) | PENDING |
| 3.9 | Multicollinearity and Orthogonalization | PENDING |
| 3.10 | CPCV with Purging (Bailey & Lopez de Prado 2017) | PENDING |
| 3.11 | Multiple Hypothesis Testing (DSR, PBO) | PENDING |
| 3.12 | Feature Selection Report | PENDING |
| 3.13 | Integration with S02 Signal Engine | PENDING |

#### Deliverables

- Feature engineering pipeline (`features/` package) with `FeatureCalculator` ABC.
- Versioned Feature Store with point-in-time queries (custom on TimescaleDB).
- IC measurement framework (Spearman rank IC, IC_IR, turnover-adjusted IC, IC decay).
- Per-feature validation reports for HAR-RV, Rough Vol, OFI, CVD, Kyle lambda, GEX.
- Multicollinearity matrix, VIF scores, and orthogonalization.
- CPCV with purging and embargo (C(6,2) = 15 folds).
- DSR and PBO corrections for multiple hypothesis testing.
- Final approved feature list with documented keep/reject rationale.
- S02 Feature Adapter (Adapter pattern) for Phase 4 integration.

#### Success metrics

- Every feature in S02 has a measured IC with confidence interval.
- IC threshold: |IC| > 0.02, IC_IR > 0.50 for feature acceptance.
- Multicollinearity check: no pair of active features with |correlation| > 0.7.
- CPCV OOS IC consistent across folds (low variance).
- PBO < 0.50 for the retained feature set.
- DSR > 0.95 for all retained features.
- 85% test coverage on `features/` package.

#### Canonical references

See `docs/phases/PHASE_3_SPEC.md` Section 11 for complete bibliography (60 references).

#### Open questions

- What IC threshold to use for feature inclusion? Spec proposes |IC| > 0.02 and IC_IR > 0.50.
- GEX data availability: options OI + gamma data source TBD (may need paid API).
- If all features fail IC threshold, Phase 4 must re-scope features.

#### ADRs

- ADR-XXXX (to create): Feature validation methodology and IC thresholds.

---

### Phase 4 — Regime Detector + Capital Allocator

| Field | Value |
|---|---|
| Status | **PENDING** |
| Services concerned | S03 (Regime Detector), S04 (Fusion Engine / Capital Allocator) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 3 merged (validated features available) |
| Roadmap weight | ~10% |

#### Objective

Implement real-time regime detection (S03) and dynamic capital allocation (S04). The
regime detector identifies market states (trending/ranging, low-vol/high-vol, risk-on/
risk-off) and the capital allocator adjusts position sizing and strategy weights
accordingly. This is the core adaptive intelligence of the system.

#### Sub-phases (indicative)

| Sub-phase | Title | Status |
|---|---|---|
| 4.1 | HMM-based regime detector (2-state and 3-state models) | PENDING |
| 4.2 | Markov-switching model with macro inputs | PENDING |
| 4.3 | Regime-aware macro multiplier (continuous, not discrete) | PENDING |
| 4.4 | Capital allocator: Risk Parity baseline | PENDING |
| 4.5 | Black-Litterman overlay with signal-derived views | PENDING |
| 4.6 | Kelly multivariate sizing integration | PENDING |
| 4.7 | Session-aware allocation (US/EU/Asia session weights) | PENDING |

#### Deliverables

- S03 publishes `regime.*` events on every regime change via ZMQ.
- S04 recomputes allocation weights on every regime change and every signal update.
- Regime states stored in Redis with transition probabilities.
- Capital allocation weights published to S05 for position sizing.

#### Success metrics

- Regime detection latency < 100ms from market state change to published event.
- Capital allocation adapts within one tick cycle of regime change.
- Out-of-sample regime classification accuracy > 60% (measured via walk-forward).
- Portfolio Sharpe improves vs. static allocation baseline (measured in Phase 5 backtest).

#### Canonical references

1. Hamilton, J. D. (1989). "A New Approach to the Economic Analysis of Nonstationary
   Time Series and the Business Cycle". *Econometrica*, 57(2), 357-384.
2. Black, F. & Litterman, R. (1992). "Global Portfolio Optimization". *Financial
   Analysts Journal*, 48(5), 28-43.
3. Maillard, S., Roncalli, T. & Teiletche, J. (2010). "The Properties of Equally
   Weighted Risk Contribution Portfolios". *Journal of Portfolio Management*, 36(4),
   60-70.
4. Ang, A. & Bekaert, G. (2002). "International Asset Allocation With Regime Shifts".
   *Review of Financial Studies*, 15(4), 1137-1187.
5. Kelly, J. L. (1956). "A New Interpretation of Information Rate".
   *Bell System Technical Journal*, 35(4), 917-926.

#### Open questions

- Which HMM library? hmmlearn vs. pomegranate vs. custom implementation.
  Need ADR to evaluate trade-offs (API stability, GPU support, testing).
- How many regime states? 2 (bull/bear) vs. 3 (bull/bear/sideways) vs.
  continuous regime probability.
- Black-Litterman vs. Risk Parity vs. Kelly multivariate: which as primary allocator?
  Possibly layered: Risk Parity as base, B-L as overlay, Kelly for sizing.

#### ADRs

- ADR-XXXX (to create): HMM library selection for S03 Regime Detector.
- ADR-XXXX (to create): Capital allocation methodology (Risk Parity vs. B-L vs. Kelly).

---

### Phase 5 — Backtesting Engine (Institutional Grade)

| Field | Value |
|---|---|
| Status | **PENDING** |
| Services concerned | `backtesting/` module |
| Duration | ~4-5 weeks |
| Dependencies | Phase 4 merged (regime + allocation logic available to backtest) |
| Roadmap weight | ~10% |

#### Objective

Build an event-driven backtesting engine that applies all ADR-0002 methodology
requirements: walk-forward with purging and embargo, CPCV, PSR/DSR/PBO, realistic
slippage (Almgren-Chriss), and multiple-testing correction. The engine must be capable
of testing the full pipeline (S01 → S06) on historical data with institutional rigor.

#### Sub-phases (indicative)

| Sub-phase | Title | Status |
|---|---|---|
| 5.1 | Event-driven engine architecture (tick replay + order book simulation) | PENDING |
| 5.2 | Walk-forward analysis with purging and embargo (CPCV) | PENDING |
| 5.3 | Slippage modeling (Almgren-Chriss temporary + permanent impact) | PENDING |
| 5.4 | Multiple hypothesis testing gate (DSR, PSR, PBO on all variants) | PENDING |
| 5.5 | Backtest report generation (full ADR-0002 compliance) | PENDING |
| 5.6 | Performance benchmarking (backtest speed, memory) | PENDING |

#### Deliverables

- Event-driven backtest engine that replays historical ticks through S02 → S05.
- Walk-forward optimizer with configurable train/test/embargo windows.
- CPCV implementation with rank-PBO output.
- Slippage model calibrated per asset class.
- Automated backtest report satisfying all 10 ADR-0002 evaluation points.

#### Success metrics

- Backtest engine processes 1 year of 1-minute data in < 5 minutes.
- CI backtest gate: Sharpe ≥ 0.8, max DD ≤ 8% on 30-day fixture.
- All backtest reports include PSR confidence interval and DSR correction.
- PBO < 0.5 (less than 50% probability of overfitting) on accepted strategies.

#### Canonical references

1. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 11-13. Wiley.
2. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2017).
   "The Probability of Backtest Overfitting". *Journal of Computational Finance*, 20(4).
3. Harvey, C. R. & Liu, Y. (2015). "Backtesting". *Journal of Portfolio Management*,
   42(1), 13-28.
4. Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies* (2nd ed.).
   Wiley.
5. Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected
   Returns". *Review of Financial Studies*, 29(1), 5-68.

#### Open questions

- Build custom engine vs. extend vectorbt vs. use Lean/QuantConnect?
  Custom gives full control but higher development cost. Need ADR.
- Order book simulation: L1 (top of book) vs. L2 (depth) — L2 is more realistic but
  requires order book data we may not have for all asset classes.
- How to model crypto slippage? Almgren-Chriss was designed for equities. Need to
  adapt or find crypto-specific models.

#### ADRs

- ADR-XXXX (to create): Backtesting engine architecture (build vs. vectorbt vs. lean).
- ADR-XXXX (to create): Slippage model specification per asset class.

---

### Phase 6 — Risk Manager Full Implementation

| Field | Value |
|---|---|
| Status | **PENDING** |
| Services concerned | S05 (Risk Manager) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 5 merged (backtested strategies available for risk calibration) |
| Roadmap weight | ~10% |

#### Objective

Complete the Risk Manager (S05) with full circuit breaker state machine, Bayesian Kelly
shrinkage, meta-label gate, position rules, portfolio exposure monitoring, and central
bank event guard. The risk chain must execute in < 5ms p99 via Rust (apex_risk crate).

#### Sub-phases (indicative)

| Sub-phase | Title | Status |
|---|---|---|
| 6.1 | Circuit breaker state machine — Redis-persisted, multi-trigger | PENDING |
| 6.2 | Bayesian Kelly shrinkage (posterior updates on rolling window) | PENDING |
| 6.3 | Meta-Label gate (Lopez de Prado meta-labeling for entry filtering) | PENDING |
| 6.4 | Position rules: max size, max correlated, max per asset class | PENDING |
| 6.5 | Portfolio exposure monitor (real-time, published to S10) | PENDING |
| 6.6 | Central bank event guard (pre-FOMC blackout, post-event scalp window) | PENDING |
| 6.7 | Rust apex_risk parallelization (p99 < 5ms target) | PENDING |

#### Deliverables

- S05 circuit breaker with CLOSED → OPEN → HALF_OPEN state machine persisted in Redis.
- Bayesian Kelly sizer with shrinkage toward conservative prior.
- Meta-label binary classifier gate integrated before order approval.
- Real-time exposure dashboard data published to S10.
- Rust implementation of hot-path risk checks (apex_risk crate).

#### Success metrics

- Risk chain latency: p99 < 5ms (measured via benchmark suite).
- Circuit breaker correctly blocks trading on: daily DD > 3%, rapid loss in 30min window,
  VIX spike > 20% in 1h, data feed silence > 60s, price gap > 5%.
- Bayesian Kelly fraction converges to true Kelly within 200 trades on synthetic data.
- Meta-label gate rejects at least 30% of low-confidence entries on historical data.

#### Canonical references

1. Kelly, J. L. (1956). "A New Interpretation of Information Rate".
   *Bell System Technical Journal*, 35(4), 917-926.
2. Vince, R. (1992). *The Mathematics of Money Management*. Wiley.
3. Lucca, D. O. & Moench, E. (2015). "The Pre-FOMC Announcement Drift".
   *Journal of Finance*, 70(1), 329-371.
4. Jorion, P. (2007). *Value at Risk: The New Benchmark for Managing Financial Risk*
   (3rd ed.). McGraw-Hill.
5. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 3
   (Meta-Labeling). Wiley.

#### Open questions

- Bayesian Kelly: which prior? Uniform (non-informative) vs. empirical Bayes from
  backtest results? Need ADR.
- Circuit breaker: how long in OPEN state before transitioning to HALF_OPEN?
  Fixed timeout vs. condition-based (e.g., VIX returning below threshold)?
- Meta-label model: logistic regression vs. gradient boosting? Simpler is better
  for interpretability, but GBM may capture non-linear patterns.

#### ADRs

- ADR-XXXX (to create): Bayesian Kelly shrinkage formulation.
- ADR-XXXX (to create): Circuit breaker state machine specification.

---

### Phase 7 — Order Manager + Execution (Paper)

| Field | Value |
|---|---|
| Status | **PENDING** |
| Services concerned | S06 (Execution Engine) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 6 merged (risk manager fully functional) |
| Roadmap weight | ~10% |

#### Objective

Implement the order management state machine and execution engine for paper trading.
Orders flow through a defined lifecycle (NEW → SUBMITTED → PARTIAL → FILLED / CANCELLED /
REJECTED). Multi-broker routing sends equity orders to Alpaca and crypto orders to Binance.
WebSocket fills with slippage tracking. No real money at this stage.

#### Sub-phases (indicative)

| Sub-phase | Title | Status |
|---|---|---|
| 7.1 | Order state machine (lifecycle, persistence, audit trail) | PENDING |
| 7.2 | Multi-broker router (Alpaca equities, Binance crypto) | PENDING |
| 7.3 | WebSocket fill listener + slippage tracker | PENDING |
| 7.4 | Paper trading integration test (full pipeline S01 → S06) | PENDING |
| 7.5 | Order audit log (every state transition persisted) | PENDING |

#### Deliverables

- S06 order manager with full state machine and Redis persistence.
- Broker abstraction layer (Strategy pattern) for Alpaca and Binance.
- WebSocket fill listener with real-time slippage measurement.
- Full pipeline integration test: tick → signal → regime → fusion → risk → paper order.

#### Success metrics

- Order lifecycle is fully auditable (every state transition logged and persisted).
- Paper trading runs 24/7 for at least 1 week without crashes.
- Slippage measurements match Almgren-Chriss model predictions within 2x.
- Multi-broker routing correctly dispatches by asset class.

#### Canonical references

1. Almgren, R. & Chriss, N. (2000). "Optimal Execution of Portfolio Transactions".
   *Journal of Risk*, 3(2), 5-39.
2. Bertsimas, D. & Lo, A. W. (1998). "Optimal Control of Execution Costs".
   *Journal of Financial Markets*, 1(1), 1-50.
3. Cartea, A., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency
   Trading*. Cambridge University Press.

#### Open questions

- Order routing strategy: smart order routing (SOR) or simple asset-class dispatch?
  SOR adds complexity but could improve fills. Need ADR.
- How to handle partial fills? Especially for crypto where fill granularity can be
  very fine.
- Paper trading fill simulation: use broker paper API or self-simulate from live
  order book data?

#### ADRs

- ADR-XXXX (to create): Order routing strategy.

---

### Phase 8 — Live Trading

| Field | Value |
|---|---|
| Status | **PENDING** |
| Services concerned | S06 (Execution), S09 (P&L Tracker), S10 (Monitor) |
| Duration | ~3-4 weeks |
| Dependencies | Phase 7 paper trading stable for ≥ 1 week |
| Roadmap weight | ~10% |

#### Objective

Transition from paper to live trading. Deploy with real broker API keys (Alpaca + Binance,
potentially IBKR). Implement real-time P&L tracking (S09) and full monitoring dashboard
(S10). Establish 24/7 watchdog and alerting. This is the phase where real capital is at
risk — every safety mechanism must be verified.

#### Sub-phases (indicative)

| Sub-phase | Title | Status |
|---|---|---|
| 8.1 | Paper → live switch (config-driven, no code changes) | PENDING |
| 8.2 | Real broker API keys (Alpaca live, Binance mainnet) | PENDING |
| 8.3 | S09 real-time P&L tracker (unrealized + realized, per-trade + portfolio) | PENDING |
| 8.4 | S10 full monitoring dashboard (positions, P&L, risk state, signals) | PENDING |
| 8.5 | 24/7 watchdog + alerting (email/SMS on circuit breaker, fill, error) | PENDING |
| 8.6 | Graceful shutdown protocol (close all positions on system halt) | PENDING |

#### Go-live criteria (must ALL be met)

- 3 months profitable on paper trading.
- Sharpe > 1.5 on paper equity curve.
- Maximum drawdown < 5% on paper.
- All circuit breaker triggers tested and verified.
- Graceful shutdown tested under all failure scenarios.

#### Deliverables

- Live trading mode activated via `TRADING_MODE=live` environment variable.
- Real-time P&L tracking with per-trade and portfolio-level attribution.
- Dashboard showing positions, P&L curve, risk state, active signals.
- Alerting via email (SMTP) and SMS (Twilio) on critical events.
- Graceful shutdown: close all positions if system detects unrecoverable state.

#### Success metrics

- System runs 24/7 for 1 month without unplanned downtime.
- P&L tracking matches broker statements to the cent.
- Alert latency < 30 seconds from trigger to notification.
- No position left open after graceful shutdown.

#### Canonical references

1. Harris, L. (2003). *Trading and Exchanges: Market Microstructure for Practitioners*.
   Oxford University Press.
2. O'Hara, M. (1995). *Market Microstructure Theory*. Blackwell.
3. Hasbrouck, J. (2007). *Empirical Market Microstructure*. Oxford University Press.

#### Open questions

- IBKR integration: needed at launch or Phase 9? IBKR offers better fills for equities
  but API is more complex.
- Watchdog architecture: separate process or Managed Agent (see MANAGED_AGENTS_PLAYBOOK.md)?
- How to handle overnight risk for equities? Close all equity positions before market
  close or hold overnight with stop-losses?

#### ADRs

- None planned. Phase 8 is primarily operational, not architectural.

---

### Phase 9 — Strategy Multiplication

| Field | Value |
|---|---|
| Status | **PENDING** (long-term) |
| Services concerned | S02, S03, S04, S05 |
| Duration | Ongoing (months) |
| Dependencies | Phase 8 live trading stable |
| Roadmap weight | ~8% |

#### Objective

Add new trading strategies one by one, each independently validated through the Phase 3
feature validation process and Phase 5 backtesting engine. Achieve genuine portfolio
diversification through uncorrelated strategy returns.

#### Indicative strategies to evaluate

- Mean reversion (pairs trading, statistical arbitrage).
- Momentum (cross-sectional and time-series).
- Carry (yield curve, FX carry).
- Volatility (vol surface arbitrage, vol-of-vol).
- Event-driven (earnings, central bank, macro surprises).
- Machine learning (supervised alpha signals, reinforcement learning for execution).

Each strategy must pass:

1. Phase 3 IC measurement (|IC| > threshold).
2. Phase 5 backtest (Sharpe ≥ 0.8, PSR > 95%, PBO < 0.5).
3. Correlation with existing strategies < 0.5 (diversification requirement).
4. Phase 6 risk approval (within portfolio risk budget).

#### Canonical references

1. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
2. Kakushadze, Z. & Serur, J. A. (2018). *151 Trading Strategies*. Palgrave Macmillan.
3. Jansen, S. (2020). *Machine Learning for Algorithmic Trading* (2nd ed.). Packt.

#### Open questions

- How many simultaneous strategies before correlation management becomes the bottleneck?
- ML strategies: how to prevent overfitting without the statistical testing infrastructure
  becoming more complex than the strategies themselves?

#### ADRs

- None planned. Each strategy may generate its own ADR if it introduces novel methodology.

---

### Phase 10 — User Interface

| Field | Value |
|---|---|
| Status | **PENDING** (long-term) |
| Services concerned | S10 (Monitor Dashboard) |
| Duration | ~2-3 weeks |
| Dependencies | Phase 8 live trading stable |
| Roadmap weight | ~5% |

#### Objective

Build a personal frontend for deployment monitoring, performance tracking, and system
control. Read-only for trading (no UI-triggered orders). The interface is for the
operator (Clement Barbier) only — no multi-user requirements.

#### Indicative features

- Real-time P&L curve and position table.
- Signal strength heatmap across all active features.
- Regime state visualization (current + historical).
- Risk dashboard: circuit breaker state, exposure, Kelly fraction.
- System health: service heartbeats, data feed status, latency metrics.
- Backtest comparison view.

#### Canonical references

- No specific academic references. Standard frontend engineering.

#### Open questions

- Technology: React, Svelte, or plain HTML/JS with HTMX?
  S10 already has a basic HTML/JS dashboard — extend or rewrite?
- Hosting: local-only or accessible via VPN?

#### ADRs

- None planned.

---

### Phase 11 — Advanced Analytics and Research Tools

| Field | Value |
|---|---|
| Status | **PENDING** (long-term) |
| Services concerned | S07 (Quant Analytics), research notebooks |
| Duration | ~3-4 weeks |
| Dependencies | Phase 8 live trading stable |
| Roadmap weight | ~4% |

#### Objective

Build advanced analytical tools for ongoing research: interactive notebooks, factor
decomposition, alpha attribution, and automated research pipelines. These tools support
the continuous improvement cycle — finding new alpha, validating it, and deploying it.

#### Indicative features

- Factor decomposition (Fama-French 5-factor, Carhart 4-factor).
- Alpha attribution by signal, regime, and asset class.
- Automated research pipeline (signal idea → IC test → backtest → report).
- Jupyter notebook templates for ad hoc research.

#### Canonical references

1. Fama, E. F. & French, K. R. (2015). "A Five-Factor Asset Pricing Model".
   *Journal of Financial Economics*, 116(1), 1-22.
2. Carhart, M. M. (1997). "On Persistence in Mutual Fund Performance".
   *Journal of Finance*, 52(1), 57-82.

#### Open questions

- How much automation? Fully automated research pipeline vs. notebook-first approach?

#### ADRs

- None planned.

---

### Phase 12 — Infrastructure Hardening and Scaling

| Field | Value |
|---|---|
| Status | **PENDING** (long-term) |
| Services concerned | All (S01-S10), infrastructure |
| Duration | ~3-4 weeks |
| Dependencies | Phase 8 live trading stable |
| Roadmap weight | ~3% |

#### Objective

Harden the infrastructure for long-term reliability. Implement redundancy, disaster
recovery, and scaling capabilities. This is operational maturity — the system should
survive hardware failures, network outages, and broker API changes without manual
intervention.

#### Indicative features

- Multi-region deployment (primary + failover).
- Automated database backups with point-in-time recovery.
- Broker failover (Alpaca → IBKR, Binance → alternate exchange).
- Log aggregation and long-term storage.
- Configuration management (versioned configs, rollback capability).
- Load testing and capacity planning.

#### Canonical references

- No specific academic references. Standard infrastructure engineering.

#### Open questions

- Cloud vs. bare metal? Cost optimization for 24/7 operation.
- How much redundancy is justified for a personal trading system?

#### ADRs

- None planned.

---

## 6. Planning Methodology

### Rolling wave planning

This project follows **rolling wave planning** (PMBOK):

- **Current phase (N)**: fully detailed with sub-phase breakdown, specific deliverables,
  acceptance criteria, and assigned work.
- **Next phase (N+1)**: sub-phases identified with indicative scope, dependencies
  clarified, open questions documented.
- **Future phases (N+2 and beyond)**: high-level objectives and indicative scope only.
  Detail is added as the project approaches each phase.

This prevents over-specification of distant work while ensuring near-term work is
well-defined.

### Specification documents

For each major phase (3+), a specification document must be created before implementation:

- **Location**: `docs/phases/PHASE_N_SPEC.md`
- **Content**: detailed requirements, design decisions, data flow diagrams, API contracts,
  test plan.
- **Timing**: created and reviewed before the first sub-phase PR of the phase.

### Retrospective documents

For each major phase, a retrospective must be created after completion:

- **Location**: `docs/phases/PHASE_N_RETROSPECTIVE.md`
- **Content**: what went well, what went poorly, what was learned, what would change,
  metrics achieved vs. targets.
- **Timing**: created within 1 week of the final sub-phase merge.

### PR workflow

1. Each sub-phase is developed on a feature branch (`feat/`, `quant/`, `sre/`).
2. PR is opened against `main` with the appropriate template (quant, feature, bugfix).
3. GitHub Copilot review + manual review.
4. CI must be green (quality → rust → unit → integration → backtest-gate).
5. Merge to `main`.
6. This roadmap is updated to reflect the new state.

### Hotfix protocol

After each PR merge, a hotfix pass is performed:

1. Review CI results for any new warnings or regressions.
2. Check test coverage delta — must not decrease.
3. Address any review feedback that was deferred.
4. Update this roadmap if the phase state changed.

### References (methodology)

1. Highsmith, J. (2009). *Agile Project Management: Creating Innovative Products*
   (2nd ed.). Addison-Wesley.
2. Project Management Institute (2017). *PMBOK Guide* (6th ed.). PMI.
   (Rolling wave planning, progressive elaboration.)
3. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 1. Wiley.
   (Failure modes of quant projects: overfitting, selection bias, data snooping.)

---

## 7. Academic Standards

The following table lists canonical researchers and institutions by domain. All APEX
implementations must reference the appropriate authorities when implementing features
in their domain.

| Domain | Researchers / Institutions |
|---|---|
| Market microstructure | Maureen O'Hara (Cornell), Albert "Pete" Kyle (Maryland), Larry Harris (USC), Bouchaud-Farmer-Lillo |
| Volatility modeling | Bollerslev (Duke), Engle (NYU Stern, Nobel 2003), Hansen (UNC), Corsi (HAR-RV) |
| Asset pricing | Cochrane (Hoover Stanford), Fama (Chicago, Nobel 2013), French (Dartmouth), Lo (MIT Sloan) |
| Risk management | Jorion (UC Irvine), Alexander (Sussex), Lopez de Prado (Cornell + ADIA) |
| Portfolio theory | Markowitz (Nobel 1990), Ross (MIT, APT), Black + Litterman (Goldman), Sharpe (Stanford, Nobel 1990) |
| Behavioral finance | Kahneman (Princeton, Nobel 2002), Shiller (Yale, Nobel 2013), Thaler (Chicago, Nobel 2017) |
| ML in finance | Lopez de Prado (Cornell), Stefan Jansen (ML4T) |
| HFT | O'Hara, Hatheway (NASDAQ), Jones (Columbia), Hasbrouck (NYU) |
| Macro-finance | Lars Peter Hansen (Chicago, Nobel 2013), Campbell (Harvard), Piazzesi (Stanford) |
| Crypto microstructure | Makarov (LSE) + Schoar (MIT), Urquhart (Birmingham), Liu + Tsyvinski (Yale) |

---

## 8. ADR Index

### Existing ADRs

| ADR | Title | Status | Date | Phase |
|---|---|---|---|---|
| ADR-0001 | ZMQ Broker (XSUB/XPUB) Topology | ACCEPTED | 2026-04-08 | Infrastructure |
| ADR-0002 | Quant Methodology Charter | ACCEPTED | 2026-04-08 | Phase 1 |
| ADR-0003 | Universal Data Schema Design Decisions | ACCEPTED | 2026-04-10 | Phase 2 |

### Planned ADRs

| ADR | Title | Phase | Status |
|---|---|---|---|
| ADR-0004 | HMM library selection for S03 Regime Detector | Phase 4 | PENDING |
| ADR-0005 | Capital allocation methodology (Risk Parity vs. B-L vs. Kelly) | Phase 4 | PENDING |
| ADR-0006 | Backtesting engine architecture (build vs. vectorbt vs. lean) | Phase 5 | PENDING |
| ADR-0007 | Slippage model specification per asset class | Phase 5 | PENDING |
| ADR-0008 | Bayesian Kelly shrinkage formulation | Phase 6 | PENDING |
| ADR-0009 | Circuit breaker state machine specification | Phase 6 | PENDING |
| ADR-0010 | Order routing strategy | Phase 7 | PENDING |

ADR numbers for planned items are provisional and may change.

---

## 9. Identified Risks and Mitigations

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Planning drift between phases | Medium | High | This roadmap + spec/retrospective documents per phase. Updated after every sub-phase merge. |
| R2 | Signals fail out-of-sample | High | High | Phase 3 validation harness with IC measurement, CPCV, and PBO. No signal accepted without OOS validation. |
| R3 | Risk Manager latency > 5ms | High | Medium | Rust apex_risk crate. Benchmark suite in Phase 6. Profile before and after every change. |
| R4 | Silent data quality degradation | High | Medium | DataQualityChecker (Phase 2.3) with composable validation. Quality scores in Redis. S09 monitors for drift. |
| R5 | Backtest overfitting | Critical | High | PSR/DSR/PBO/CPCV (ADR-0002). Multiple-testing correction mandatory. Walk-forward with embargo. |
| R6 | Single point of failure (broker) | Medium | Medium | Redundant data sources (Alpaca + Massive for equities, Phase 2.5). Multi-broker execution planned (Phase 7). |
| R7 | API key compromise | Critical | Low | Keys in .env only. Never in source code or logs. SecretStr for sensitive fields. IP whitelisting on broker accounts. |
| R8 | TimescaleDB data loss | High | Low | Automated backups with PITR (Phase 12). Backfill orchestrator can rebuild from source APIs (Phase 2.11). |
| R9 | Regime detector false positives | Medium | Medium | Walk-forward validation of regime classification accuracy (Phase 4). Minimum confidence threshold for regime changes. |
| R10 | Circuit breaker opens too frequently | Medium | Medium | Calibrate thresholds from paper trading data (Phase 8). Avoid overly sensitive triggers. |
| R11 | Dependency on free data APIs | Medium | High | Multiple sources per data type. Yahoo Finance as fallback for indices/FX. FRED is public and stable. |
| R12 | Solo developer bus factor | High | — | Comprehensive documentation (this roadmap, ADRs, CLAUDE.md). Code quality enforced by CI. Managed Agents playbook for operational continuity. |
| R13 | CI gates drifted from documented standards | Medium | **Confirmed** | Audit 2026-04-11 found coverage gate at 40% (not 85%), backtest gate non-blocking, thresholds relaxed. Issues #64, #65. Fix before Phase 3 completion. |
| R14 | `float()` for financial values in connectors and core models | Medium | **Confirmed** | ~20+ instances of `float()` where `Decimal` is required by CLAUDE.md. Issue #66. Fix incrementally during Phase 3. |
| R15 | Dependency CVEs (19 known vulnerabilities) | Medium | **Confirmed** | urllib3, requests, tornado, pillow have known CVEs. Issue #68. Requires version bumps in requirements.txt. |
| R16 | Coverage denominator inflation | Medium | **Confirmed** | 25 omit entries in pyproject.toml exclude ~14,000 LOC from coverage measurement. True coverage ~45%. Issue #70. |

---

## 10. Appendices

---

### Appendix A — Data Coverage at End of Phase 2

#### Micro data (market data)

| Asset class | Source | Resolution | Status |
|---|---|---|---|
| US equities (NYSE, Nasdaq) | Alpaca REST + WebSocket | 1m, 5m, 15m, 1h, 1d; real-time ticks | DONE (2.5) |
| US equities (historical bulk) | Massive (ex-Polygon) S3 flatfiles | 1m, 1d | DONE (2.5) |
| Crypto (BTC/USDT, ETH/USDT) | Binance REST + WebSocket | 1m, 5m, 15m, 1h, 1d; real-time ticks | DONE (2.4) |
| Indices (S&P 500, Dow, Nasdaq, VIX, Russell 2000) | Yahoo Finance | 1d | DONE (2.6) |
| FX (EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD) | Yahoo Finance | 1d | DONE (2.6) |
| ETFs (SPY, QQQ, IWM, TLT, GLD, USO, HYG, LQD, EEM, VXX) | Yahoo Finance | 1d | DONE (2.6) |

#### Macro data

| Series | Source | Frequency | Status |
|---|---|---|---|
| US GDP, CPI, NFP, unemployment, Fed Funds rate | FRED | Monthly/Quarterly | IN PROGRESS (2.7) |
| US yield curve (2Y, 5Y, 10Y, 30Y spreads) | FRED | Daily | IN PROGRESS (2.7) |
| US credit spreads (BAA-AAA, HY-IG) | FRED | Daily | IN PROGRESS (2.7) |
| US consumer sentiment (Michigan) | FRED | Monthly | IN PROGRESS (2.7) |
| US ISM PMI, housing starts | FRED | Monthly | IN PROGRESS (2.7) |
| Euro area policy rate, M3, HICP | ECB SDW | Monthly/Quarterly | IN PROGRESS (2.7) |
| Japan policy rate, monetary base, Tankan | Bank of Japan | Quarterly | IN PROGRESS (2.7) |
| Central bank meeting dates (FOMC, ECB, BoJ, BoE) | TBD | Event-driven | PENDING (2.8) |
| Economic releases (CPI, NFP, ISM, retail, GDP) | TBD | Event-driven | PENDING (2.8) |

#### Fundamental data

| Data type | Source | Frequency | Status |
|---|---|---|---|
| Quarterly filings (10-Q, 10-K) | SEC EDGAR | Quarterly | PENDING (2.9) |
| Insider transactions (Form 4) | SEC EDGAR | Event-driven | PENDING (2.9) |
| Standardized financials + ratios | SimFin | Quarterly | PENDING (2.9) |
| Earnings calendar | TBD | Event-driven | PENDING (2.9) |

---

### Appendix B — Data NOT Covered (Perspectives for Phase 2bis or Future)

These data sources are not in scope for the current roadmap but may be evaluated
in future phases if they provide demonstrable alpha after Phase 3 validation:

| Data type | Potential sources | Notes |
|---|---|---|
| Social sentiment | Twitter/X API, Reddit (pushshift), StockTwits | Noisy. Requires NLP pipeline. Alpha decays fast. |
| Financial news | Bloomberg Terminal, Refinitiv Eikon, Benzinga | Expensive. Bloomberg requires Terminal subscription. |
| Options chains (OI, IV, gamma surface) | CBOE, Polygon Options, IBKR | Required for GEX validation (Phase 3.4). May move to Phase 2 if needed earlier. |
| On-chain crypto data | Glassnode, CryptoQuant, Nansen | Useful for crypto-specific signals. Freemium tiers available. |
| Alternative data (satellite, credit card, web traffic) | Quandl, Thinknum, SimilarWeb | Premium pricing. Institutional-grade. Not justified at current AUM. |
| Intraday indices / FX | Dukascopy, TrueFX, IEX Cloud | Yahoo Finance only provides daily. May need higher resolution for FX signals. |

---

### Appendix C — Glossary of APEX Acronyms

#### Services

| Acronym | Full name | Description |
|---|---|---|
| S01 | Data Ingestion | Real-time and historical data ingestion from all sources |
| S02 | Signal Engine | Computes trading signals from normalized data |
| S03 | Regime Detector | Identifies market regimes (trending/ranging, vol state) |
| S04 | Fusion Engine | Combines signals with regime and allocates capital |
| S05 | Risk Manager | Veto layer — enforces all risk rules, circuit breaker |
| S06 | Execution Engine | Order management, broker routing, fill tracking |
| S07 | Quant Analytics | Statistical models (Hurst, GARCH, Hawkes, Monte Carlo) |
| S08 | Macro Intelligence | Central bank calendars, geopolitical events, sessions |
| S09 | Feedback Loop | Signal quality tracking, Kelly stats, drift detection |
| S10 | Monitor Dashboard | Read-only web dashboard for system monitoring |

#### Statistical metrics

| Acronym | Full name | Reference |
|---|---|---|
| PSR | Probabilistic Sharpe Ratio | Bailey & Lopez de Prado (2012) |
| DSR | Deflated Sharpe Ratio | Bailey & Lopez de Prado (2014) |
| PBO | Probability of Backtest Overfitting | Bailey, Borwein, Lopez de Prado & Zhu (2014) |
| CPCV | Combinatorial Purged Cross-Validation | Lopez de Prado (2018) |
| IC | Information Coefficient | Grinold & Kahn (1999) |
| IC_IR | Information Coefficient Information Ratio | Grinold & Kahn (1999) |

#### Market features

| Acronym | Full name | Reference |
|---|---|---|
| HAR-RV | Heterogeneous Autoregressive Realized Volatility | Corsi (2009) |
| OFI | Order Flow Imbalance | Cont, Kukanov & Stoikov (2014) |
| CVD | Cumulative Volume Delta | Market microstructure literature |
| GEX | Gamma Exposure | Options market-making literature |
| VPIN | Volume-synchronized Probability of Informed Trading | Easley, Lopez de Prado & O'Hara (2012) |

#### Risk and portfolio

| Acronym | Full name | Reference |
|---|---|---|
| HMM | Hidden Markov Model | Hamilton (1989) |
| B-L | Black-Litterman model | Black & Litterman (1992) |
| VaR | Value at Risk | Jorion (2007) |
| DD | Drawdown | Standard |
| GARCH | Generalized Autoregressive Conditional Heteroskedasticity | Bollerslev (1986) |

#### Infrastructure

| Acronym | Full name |
|---|---|
| ZMQ | ZeroMQ (messaging library) |
| XSUB/XPUB | ZeroMQ Extended Subscriber/Publisher sockets |
| PyO3 | Python bindings for Rust |
| PITR | Point-in-Time Recovery |

---

### Appendix D — Useful Links

| Resource | Location |
|---|---|
| Repository | github.com/clement-bbier/CashMachine |
| Development conventions | `./CLAUDE.md` |
| Architecture specification | `./MANIFEST.md` |
| ADRs | `./docs/adr/` |
| Managed Agents Playbook | `./MANAGED_AGENTS_PLAYBOOK.md` |
| Phase specifications (future) | `./docs/phases/PHASE_N_SPEC.md` |
| Phase retrospectives (future) | `./docs/phases/PHASE_N_RETROSPECTIVE.md` |
| Quant scaffolding audit | `./docs/audits/` |
| Orchestrator playbook | `./docs/ORCHESTRATOR_PLAYBOOK.md` |
| CI pipeline | `.github/workflows/` |
| PR templates | `.github/PULL_REQUEST_TEMPLATE/` |

---

## 12. Governance & Methodology

*Added 2026-04-11 by meta-governance audit (#59).*

### Non-code artifact inventory

| Category | Count | Status |
|---|---|---|
| Root-level docs (CLAUDE.md, README, AI_RULES, etc.) | 8 | 7 current, 1 stale (CHANGELOG.md) |
| docs/ directory | 8 | 6 current, 2 stale (roadmap sub-phases, copilot-instructions) |
| ADRs | 3 accepted | All current and aligned with code |
| Agent prompts | 5 | 3 current, 2 stale (apex-sre, copilot-instructions contradict ADR-0001) |
| PR/issue templates | 3 | All current |
| CI workflows | 3 | Functional but drifted from documented standards (tracked by #64-#65) |
| Service READMEs | 2 (S01 observability, S01 orchestrator) | Current |

### Artifacts to create

| Priority | Artifact | Issue | Status |
|---|---|---|---|
| **P0** | `docs/GLOSSARY.md` | #78 | PENDING |
| **P0** | Fix roadmap Phase 2 stale sub-phase descriptions | #79 | PENDING |
| **P0** | `docs/CONVENTIONS/COMMIT_MESSAGES.md` | #80 | PENDING |
| P1 | ADR-0004: Feature validation methodology | #81 | PENDING |
| P1 | `docs/ARCHITECTURE.md` | #82 | PENDING |
| P1 | `docs/ACADEMIC_REFERENCES.md` | #83 | PENDING |
| P1 | `docs/ONBOARDING.md` | #84 | PENDING |
| P1 | `.pre-commit-config.yaml` | #85 | PENDING |
| P1 | Fix stale agent prompts (SRE, copilot-instructions) | #86 | PENDING |

### Managed Agents status

| Agent | Phase | Est. cost/month | Status |
|---|---|---|---|
| `apex-veille-quant` | Now | $2-4 | Template ready (MANAGED_AGENTS_PLAYBOOK.md) |
| `apex-dep-auditor` | Now | $1 | Proposed |
| `apex-convention-checker` | Phase 3 | $1-2 | Proposed |
| `apex-nightly-backtest` | Phase 5 | $5 | Template ready |
| `apex-watchdog-circuit-breaker` | Phase 8 | $15-25 | Template ready |
| `apex-paper-summarizer` | On demand | $0.50/paper | Proposed |

### Audit trail

| Audit | Date | Scope | Decision | Report |
|---|---|---|---|---|
| Whole-codebase (#55) | 2026-04-11 | Code quality, architecture, SOLID, tests, security | CLEARED for Phase 3 | `docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md` |
| Meta-governance (#59) | 2026-04-11 | Docs, ADRs, conventions, workflows, knowledge base, agents | CLEARED for Phase 3 | `docs/audits/META_AUDIT_2026_04_11_GOVERNANCE.md` |

---

## 11. Document Changelog

| Date | Version | Change | Author |
|---|---|---|---|
| 2026-04-10 | 1.0 | Initial document — vision, architecture, Phases 1-12, references, ADR index, risks, appendices | Claude Code (orchestrated by C. Barbier) |
| 2026-04-11 | 1.1 | Section 4 updated with audit #55 results. Risks R13-R16 added. | Claude Code (audit #55) |
| 2026-04-11 | 1.2 | Section 12 (Governance & Methodology) added from meta-governance audit #59. | Claude Code (audit #59) |
