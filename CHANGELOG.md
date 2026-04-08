# Changelog

All notable changes to the APEX Trading System are documented here.
Format: [Semantic Versioning](https://semver.org/)

---

## [Unreleased] — SRE-001 Foundation merged

### Added
- Multi-agent governance: AI_RULES.md, CODEOWNERS, 4 agent prompts
- Hardened CI: split coverage gates, Node24-ready actions, preflight Makefile
- ADR-0001 documenting the ZMQ XSUB/XPUB broker topology
- Issue template `agent-task.yml` for structured agent dispatch

### Fixed
- Dockerfile groupadd exit 127 (passwd package + slim-bookworm pin)
- 61 ruff errors cleared
- CircuitBreaker / CBEventGuard legacy sync API shims for v1 integration tests
- backtest-gate fixture schema aligned with data_loader contract

### Known issues
- backtest-gate is marked `continue-on-error: true` pending APEX-METRICS-V2
- rust/Cargo.lock not yet committed (tracked by infra issue)

---

## [0.3.0] — Phase 4: Academic Alpha & Command Center

### Added
- **HAR-RV model** (`services/s07_quant_analytics/realized_vol.py`): Corsi (2009) heterogeneous
  autoregressive realized variance with daily/weekly/monthly lags and OLS fitting.
- **Bipower Variation** (Barndorff-Nielsen & Shephard 2004): jump-robust volatility estimator
  and `jump_detection()` with configurable threshold.
- **Rough Volatility** (`services/s07_quant_analytics/rough_vol.py`): Hurst exponent estimation
  via log-log regression on volatility lags; Gatheral et al. (2018) H≈0.1 regime classification.
- **Variance Ratio Test** (Lo & MacKinlay 1988): momentum/mean-reversion diagnostic integrated
  into `RoughVolAnalyzer.variance_ratio_test()`.
- **Optimal Execution** (`services/s06_execution/optimal_execution.py`): Almgren-Chriss (2001)
  liquidation schedule and Bouchaud et al. (2018) square-root market impact law.
- **Command Center REST API** (`services/s10_monitor/command_api.py`): 11 plain async functions
  exposing system status, PnL, regime, signals, positions, performance, CB events, and config.
  Confirmation guard (`_require_confirmation`) on destructive actions.
- **Enhanced dashboard** (`services/s10_monitor/dashboard.py`): Chart.js equity curve, service
  health grid, CB event panel, live regime and signal feed, WebSocket broadcast loop.
- S07 `QuantAnalyticsService` wired to `RealizedVolEstimator` and `RoughVolAnalyzer`: jump
  detection and rough vol Hurst written to Redis on every fast loop cycle.
- S06 `PaperTrader` wired to `MarketImpactModel`: `compute_slippage()` uses square-root law
  when ADV is available, falls back to Kyle linear model otherwise.
- 128 new unit tests across S01, S04, S05, S06, S07, S09, S10 — coverage raised from ~75% to 85.65%.

### Changed
- `pyproject.toml`: coverage gate raised from 75% to 85%.
- `.gitignore`: added `.env`, `prompt_phase*.md`, and `repomix-output*.xml` glob.
- `supervisor/orchestrator.py`: suppressed `no-untyped-call` mypy false positive on `aioredis.from_url`.

### Fixed
- All ruff violations (F401, I001, E501, B904, S112, B905, PT018, N806) across new modules.
- mypy strict: zero errors on all 147 source files.

---

## [Unreleased] — Phase 3 Integration & Hardening

### Added
- Full integration test suite (tests/integration/) — 20 tests covering full pipeline
- Walk-forward validation with purged cross-validation (Lopez de Prado method)
- Session tracker rewritten with complete DST support (America/New_York via ZoneInfo)
- DriftDetector with DriftAlert dataclass and check_drift() for S09 signal quality
- Property-based tests for core safety invariants (Hypothesis: Kelly, Signal, Risk)
- Latency measurement tests (tick -> signal < 50ms verified)
- CHANGELOG.md and PR template
- CircuitBreaker convenience API: allows_new_orders(), reset(), update_daily_pnl(), etc.
- check_max_risk_per_trade() standalone function with RuleResult return type
- CBEventGuard.is_blocked() synchronous method for fast-path checks
- PaperTrader.compute_slippage() extracted for testability
- GitHub Actions nightly backtest CI workflow

### Changed
- session_tracker.py: rewritten with new DST-aware datetime API (Session StrEnum)
- walk_forward.py: new pandas/datetime-based WalkForwardValidator (keeps tick-based as TickBasedWalkForwardValidator)
- drift_detector.py: new check_drift() method with DriftAlert dataclass
- pyproject.toml: fixed mypy override config (removed unsupported disable_error_codes)
- backtesting/engine.py, services/s02_signal_engine/: line-length and lint fixes

---

## [0.2.0] — Phase 2: Intelligence Engine

### Added
- SignalScorer: multi-dimensional confluence matrix (OFI 35% + BB 25% + EMA 20% + RSI 15% + VWAP 5%)
- RegimeEngine: dynamic VIX/DXY/yield curve classification with macro_mult
- CBWatcher: FOMC 2024-2025 calendar with 45min pre-event block windows
- Cross-asset correlation: BTC/SPY protection logic
- Kelly dynamic sizing connected to S09 rolling win rate stats
- Backtest macro event injection (FOMC dates in historical replay)
- Sector exposure limits (25% max per sector, S05)

---

## [0.1.0] — Phase 1: Stabilization

### Added
- Zero mypy strict errors (143 -> 0)
- Docker Windows compatibility
- Real Binance historical data download (no API key required)
- core/topics.py: centralized ZMQ topic constants
- Initial test suite (13% -> 40% coverage)
- Rust warning cleanup (zero warnings policy)
- README.md with setup and quickstart
- MANIFEST.md committed to repository
- CLAUDE.md: development contract for Claude Code
