# Changelog

All notable changes to the APEX Trading System are documented here.
Format: [Semantic Versioning](https://semver.org/)

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
