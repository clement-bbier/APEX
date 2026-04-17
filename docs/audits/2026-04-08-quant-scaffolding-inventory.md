> **📦 ARCHIVED — 2026-04-17**
>
> Historical Phase 3 scaffolding snapshot (2026-04-08). The definitive post-merge record is
> [`docs/phase_3_closure_report.md`](../phase_3_closure_report.md); reconcile against that
> report before citing anything here. Kept for audit-trail purposes only.

---

# Quant Scaffolding Inventory — Audit vs ADR-0002

- **Date:** 2026-04-08
- **Author:** Quant Agent
- **Branch:** `quant/audit-scaffolding-inventory`
- **Main commit at audit time:** `5c389b4`
- **Scope:** Read-only inventory of every quant / academic component in the
  repo, evaluated against the ADR-0002 Quant Methodology Charter.
- **Outcome:** one new file (this report). Zero source / test / config
  modifications.

---

## Executive summary

1. **The math library is in surprisingly good shape.** PSR, DSR, PBO,
   CPCV, fractional differentiation, triple-barrier labeling,
   Almgren–Chriss / sqrt impact, HAR-RV, bipower variation, rough vol,
   HMM regime detection — all are implemented as **non-stub, tested
   modules with proper academic citations**. The repo is closer to
   ADR-0002 than the charter implies.
2. **The wiring is the bottleneck.** PSR / DSR / PBO / CPCV exist in
   `backtesting/metrics.py` and `backtesting/walk_forward.py` but
   **none are called from `full_report()` or `BacktestEngine.run()`**.
   The headline backtest report is therefore Sharpe/Sortino/Calmar
   only — exactly the gap ADR-0002 was written to close.
3. **Two production-grade modules are completely orphaned.**
   `core/math/fractional_diff.py` and `core/math/labeling.py` are
   tested but **no service in `services/` imports them**. The
   triple-barrier label column exists in the meta-feature DB schema
   but is never populated.
4. **Six ADR-0002 mandatory items have zero implementation:** Ulcer
   Index, return-distribution stats (skew/kurt/tail ratio in the
   report), stationary-bootstrap CI on Sharpe, transaction-cost
   sensitivity (3 scenarios), turnover/alpha-decay/capacity, and
   regime-conditional Sharpe/DD breakdown. Per-regime / per-session
   *PnL* breakdowns exist, but per-regime *Sharpe / DD* do not.
5. **Biggest alpha lifts are wiring, not new code.** Issues are
   ordered to ship the most ADR-0002 compliance per LOC: wire
   PSR/DSR/PBO/CPCV into `full_report()` (P0), then wire fractional
   diff and triple-barrier into S02/S04/S09 (P1).

---

## Section A — Component inventory

Legend for **Verdict**: `KEEP` working & wired · `WIRE` working but
unconnected · `FIX` math/spec deviation · `TEST` no test coverage ·
`COMPLETE` stub needs implementation · `DROP` obsolete.

### A.1 Backtesting metrics layer

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into `full_report` / prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `backtesting/metrics.py::sharpe_ratio` | Sharpe (1966); LdP 2018 Ch.14 | partial (Sharpe baseline, not in 15-table) | complete | matches reference; computed on daily-resampled equity (per PR #15) | `tests/unit/backtesting/test_metrics.py` + `tests/unit/test_backtest_metrics.py` | yes (full_report) | KEEP | — | — |
| 2 | `metrics.py::sortino_ratio` | Sortino & van der Meer (1991) | no | complete | matches reference; **but called on per-trade `period_returns`, not daily** | yes (test_metrics) | yes | FIX | P0 | `[alpha] compute Sortino on daily-resampled equity-curve returns (consistency with Sharpe / SRE-001d)` |
| 3 | `metrics.py::calmar_ratio` | Young (1991) | no | complete | matches reference | yes | yes | KEEP | — | — |
| 4 | `metrics.py::max_drawdown` | standard | n/a | complete | matches reference | yes | yes | KEEP | — | — |
| 5 | `metrics.py::probabilistic_sharpe_ratio` | Bailey & LdP (2012) | **yes (#2)** | complete | matches Prop. 1–2 | `tests/unit/backtesting/test_psr_dsr.py` | **NO — not called by `full_report()`** | WIRE | **P0** | `[alpha] wire PSR into full_report() with non-normality correction surfaced in report dict` |
| 6 | `metrics.py::deflated_sharpe_ratio` | Bailey & LdP (2014) | **yes (#3)** | complete | matches Eq. 2 | `test_psr_dsr.py` | **NO** | WIRE | **P0** | `[alpha] wire DSR into full_report() with n_trials threaded from caller` |
| 7 | `metrics.py::minimum_track_record_length` | Bailey & LdP (2012) Prop. 3 | yes (#2) | complete | matches reference | `test_psr_dsr.py` | NO | WIRE | P1 | `[alpha] expose MinTRL in full_report() to surface evidence-sufficiency` |
| 8 | `metrics.py::backtest_overfitting_probability` | Bailey, Borwein, LdP, Zhu (2015) | **yes (#4)** | partial — uses a closed-form proxy `0.5*(1+d)*(0.5+0.5*log(N))`, not the rank-based combinatorial PBO from Eq. 11 | deviates: scalar IS/OOS pair instead of CPCV-derived OOS distribution | `test_psr_dsr.py` (smoke) | NO | FIX + WIRE | **P0** | `[alpha] replace scalar PBO proxy with CPCV-derived rank-based PBO (Bailey 2015 Eq.11) and wire into full_report` |
| 9 | `metrics.py::full_report` | aggregator | n/a | complete in scope, but missing PSR/DSR/PBO/Ulcer/skew/kurt/tail-ratio/bootstrap-CI/turnover | n/a | yes | yes (engine.run + scripts) | FIX | **P0** | covered by issues #1, #2, #3, #5 below |
| 10 | `walk_forward.py::WalkForwardValidator` (datetime API) | LdP 2018 Ch.7 (Pardo 2008) | yes (#1, #12) | complete | matches reference (purge + embargo) | `tests/unit/backtesting/test_walk_forward.py` | partial — only used from CPCV-style helpers, not from engine's primary path | KEEP / WIRE | P2 | `[alpha] make engine.validate() route through datetime WalkForwardValidator for OOS gating` |
| 11 | `walk_forward.py::TickBasedWalkForwardValidator` | LdP 2018 Ch.7 | yes (#1) | complete | matches reference | covered indirectly | yes (engine.validate) | KEEP | — | — |
| 12 | `walk_forward.py::CombinatorialPurgedCV` | LdP 2018 Ch.12; Bailey 2015 | **yes (#1, #4)** | complete; produces full OOS distribution + scalar PBO | matches reference | `tests/unit/backtesting/test_cpcv.py` | **NO — never invoked from engine or full_report** | WIRE | **P0** | `[alpha] wire CPCV into BacktestEngine.validate() and surface oos_sharpe_distribution + PBO in the report` |
| 13 | `backtesting/data_loader.py` | n/a | n/a | contract only (not audited deeply per scope) | cannot verify without running | none flagged | partial | KEEP | — | — |
| 14 | `backtesting/engine.py::BacktestEngine.run / validate` | n/a | n/a | complete | n/a | indirectly (integration tests) | yes | KEEP | — | — |

### A.2 Core math primitives

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 15 | `core/math/fractional_diff.py::FractionalDifferentiator` (batch FFD) | LdP 2018 Ch.5 Snippet 5.3; Hosking 1981; Granger & Joyeux 1980 | yes (#1) | complete (ω weights, find_minimum_d, ADF, memory_retained) | matches reference | `tests/unit/core/test_fractional_diff.py` | **NO — no service imports it** | WIRE | **P1** | `[alpha] use FractionalDifferentiator to derive stationary log-price features feeding S07 / meta-labeler` |
| 16 | `core/math/fractional_diff.py::IncrementalFracDiff` | LdP 2018 Ch.5 | yes (#1) | complete (deque-based O(K)/tick) | matches reference; near-equivalence to batch verified in tests | yes | NO | WIRE | P1 | (covered above; same issue) |
| 17 | `core/math/labeling.py::TripleBarrierLabeler` | LdP 2018 Ch.3 §3.1–3.4 | yes (#1) | complete (upper/lower/vertical, vol-adaptive barriers, long+short) | matches reference | `tests/unit/core/test_labeling.py` | **NO — `triple_barrier_label` column in feature_logger schema is always written `None`** | WIRE | **P1** | `[alpha] populate triple_barrier_label in S09 FeedbackLoop using TripleBarrierLabeler over closed-trade tick history` |

### A.3 Signal engine (alpha layer)

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | `s02/microstructure.py::MicrostructureAnalyzer` (OFI, CVD, Kyle λ, spread, intensity, absorption) | Hasbrouck 2007; Kyle 1985 | yes (#11) | complete; **OFI uses bid/ask *prices* as a proxy for queue volumes** (documented limitation) | deviates: classical OFI requires L2 quote sizes, not best-bid/ask price diffs — flagged in code comment | `tests/unit/s02/test_microstructure_analyzer.py`, `test_ofi_calculator.py` | yes (s02 service.py) | FIX | P1 | `[alpha] upgrade OFI to use L2 queue sizes once feed exposes them; document proxy decay in docstring` |
| 19 | `s02/vpin.py::VPINCalculator` | Easley, LdP, O'Hara (2011, 2012) | yes (#11 Hasbrouck domain; #1 LdP) | complete; ADV-calibrated dynamic bucket sizing | matches Easley et al. 2012 | `tests/unit/s02/test_vpin.py` | yes (s02 service + meta_labeler) | KEEP | — | — |
| 20 | `s02/technical.py::TechnicalAnalyzer` (RSI/Bollinger/EMA/VWAP/ATR) | standard TA (Wilder 1978 etc.) | no | complete | matches references | `tests/unit/s02/test_technical_analyzer.py` | yes | KEEP | — | — |
| 21 | `s02/signal_scorer.py::SignalScorer` | confluence aggregator (no academic claim) | no | complete | n/a (heuristic) | `tests/unit/s02/test_signal_scorer.py` | yes | KEEP | — | — |

### A.4 Fusion / sizing

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 22 | `s04/meta_labeler.py::MetaLabeler` | LdP 2018 §3.6; LdP 2019 JFDS | yes (#1) | complete (deterministic Phase-5 rules, hard blocks, soft score, size_mult); Phase-6 ML upgrade path documented | matches LdP §3.6 architecturally; classifier not yet trained | `tests/unit/s04/test_meta_labeler.py` | yes (s05 meta_label_gate, s04 service) | KEEP | — | — |
| 23 | `s04/kelly_sizer.py::KellySizer` | Kelly (1956); Thorp (1969) | yes (#15) | complete; quarter-Kelly default + sanity clamps + Redis stats from S09 | matches Kelly formula `(p·b−q)/b` divided by `kelly_divisor`, capped 0.25 | `tests/unit/s04/test_kelly_redis.py` | yes | KEEP | — | — |
| 24 | `s04/fusion.py::FusionEngine` | composite scorer | no | complete | heuristic, no claim | `tests/unit/s04/test_fusion_engine.py` | yes | KEEP | — | — |

### A.5 Quant analytics (S07)

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 25 | `s07/realized_vol.py::RealizedVolEstimator` (RV, BV, jump detection, HAR-RV, vol-adjusted Kelly) | Corsi 2009; Barndorff-Nielsen & Shephard 2004; Andersen et al. 2003 | partial (HAR-RV not in 15 table; aligns with #1 family) | complete | matches BV `μ₁⁻²·Σ|r_t||r_{t-1}|`, HAR-RV daily/weekly/monthly OLS | `tests/unit/s07/test_realized_vol.py` | yes (s07 service publishes vol features consumed by meta_labeler) | KEEP | — | — |
| 26 | `s07/rough_vol.py::RoughVolAnalyzer` (Hurst from log-vol autocorrelation, Variance Ratio test) | Gatheral, Jaisson, Rosenbaum 2018; Lo & MacKinlay 1988 | partial (not in 15-table) | complete | matches reference (R/S-adjacent log-vol regression) | `tests/unit/s07/test_rough_vol.py` | yes (Hurst feeds meta_labeler) | KEEP | — | — |
| 27 | `s07/regime_ml.py::RegimeML` (Gaussian HMM via Baum-Welch, PELT breakpoints, Engle-Granger cointegration) | Baum 1970; Killick 2012; Engle & Granger 1987 | no | complete (~450 LOC, pure numpy) | matches reference (manual EM + Viterbi); cannot fully verify without running | `tests/unit/s07/test_regime_ml.py` | partial — surfaced via s07 service but not currently routed into S03 macro_mult | WIRE | P2 | `[alpha] route HMM state probabilities into S03 RegimeDetector as a 4-state regime feature` |
| 28 | `s07/market_stats.py::MarketStats` (Ljung-Box, Hurst R/S, GARCH(1,1), realized/implied ratio, rolling correlation, cross-asset block) | standard econometrics | no | partial — Ljung-Box uses **`lags*1.5` as a critical-value approximation** instead of chi-squared quantile; GARCH(1,1) is recursive only (no MLE fitting of ω/α/β) | deviates: see above | `tests/unit/s07/test_market_stats.py`, `test_correlation.py` | yes (Hurst published) | FIX | P2 | `[alpha] replace Ljung-Box critical-value heuristic with scipy.stats.chi2.ppf and add MLE fit for GARCH(1,1)` |

### A.6 Execution layer (audited per Phase 3 ADR-0002 item #8)

| # | Component | Academic ref | In ADR-0002 refs | State | Math correctness | Unit test | Wired into prod | Verdict | Pri | Proposed issue |
|---|---|---|---|---|---|---|---|---|---|---|
| 29 | `s06/optimal_execution.py::MarketImpactModel` (sqrt impact + Kyle linear + Almgren-Chriss schedule) | Almgren & Chriss 2001; Bouchaud, Farmer, Lillo 2009; Gatheral 2010 | **yes (#10)** | complete | matches Almgren-Chriss closed-form + sqrt-law `σ·√(Q/V)·η` | `tests/unit/s06/test_optimal_execution.py` | yes (paper_trader uses `MarketImpactModel`) | KEEP | — | — |

> **Note:** While `MarketImpactModel` is wired into `paper_trader.py`, the
> backtest engine itself does not appear to vary execution cost across
> the three scenarios mandated by ADR-0002 §7. See gap analysis row
> "Transaction-cost sensitivity".

---

## Section B — ADR-0002 gap analysis

| # | ADR-0002 mandatory item | Status | Evidence | What's missing |
|---|---|---|---|---|
| 1 | Daily-resampled equity-curve Sharpe | ✅ | `metrics.py:566-579` (PR #15, issue #8) | — |
| 2 | Sortino on daily returns | ⚠️ partial | `full_report` calls `sortino_ratio(period_returns,...)` (per-trade) | Switch input to `daily_returns` for consistency with Sharpe |
| 3 | Calmar ratio | ✅ | `metrics.py:103, full_report:581` | — |
| 4 | Max DD (absolute and relative) | ✅ partial | `max_drawdown()` returns one DD fraction + duration | Add absolute (currency) DD alongside relative |
| 5 | Ulcer Index | ❌ | grep: zero hits | Implement `ulcer_index(equity_curve)` (Martin & McCann 1989) and surface in full_report |
| 6 | Return distribution: skew, kurt, tail ratio | ⚠️ partial | scipy.skew/kurtosis used inside PSR but not exported | Surface skew, excess kurtosis, P95/P5 absolute tail ratio in full_report |
| 7 | OOS split with embargo | ✅ | `WalkForwardValidator` (datetime + tick variants) | — |
| 8 | Stationary bootstrap CI on Sharpe | ❌ | grep "bootstrap": zero hits in metrics | Implement Politis-Romano (1994) stationary bootstrap; return 95 % CI on Sharpe in full_report |
| 9 | Probabilistic Sharpe Ratio | ⚠️ exists but unwired | `metrics.py:347` | Call from `full_report`; output `psr` field |
| 10 | Deflated Sharpe Ratio | ⚠️ exists but unwired | `metrics.py:396` | Call from `full_report` with caller-provided `n_trials`; output `dsr` field |
| 11 | CPCV | ⚠️ exists but unwired | `walk_forward.py:374` | Add `engine.validate_cpcv()` entry point and report `oos_sharpe_distribution`, `pbo` |
| 12 | Probability of Backtest Overfitting | ⚠️ exists, math deviates | `metrics.py:499` is a scalar proxy, not Eq. 11 rank-based PBO | Replace with CPCV-derived rank PBO; surface in full_report |
| 13 | Transaction-cost sensitivity (3 scenarios: zero / realistic / 2x) | ❌ | grep: no cost sweep harness | Add `engine.run_cost_sensitivity()` running 3 cost configs and reporting Sharpe degradation curve |
| 14 | Almgren-Chriss-style slippage | ✅ | `s06/optimal_execution.py` wired in paper_trader | Ensure backtest engine routes fills through `MarketImpactModel` (already partially true, verify in WIRE issue) |
| 15 | Annualized turnover | ❌ | grep: zero hits | Implement `turnover_ratio(trades, equity)` and add to full_report |
| 16 | Alpha decay half-life | ❌ | grep: zero hits | Implement `alpha_decay_halflife(daily_returns)` via exponential fit on cumulative PnL slope |
| 17 | Capacity estimate | ❌ | grep: zero hits | Implement `capacity_at_25pct_edge(impact_model, gross_edge_bps, adv)` per Perold (1988) |
| 18 | Regime-conditional Sharpe / DD / hit rate | ⚠️ partial | `by_regime_breakdown` exists but reports only PnL stats, not Sharpe / DD per regime | Extend to compute Sharpe + DD per regime/session bucket |
| 19 | Haircut Sharpe (alternative to DSR) | ❌ | grep: zero hits | Optional — DSR satisfies the requirement; track as P2 follow-up |

---

## Section C — Proposed backlog (next Quant missions)

Ordered by priority. Each issue is independent unless an explicit
dependency is noted. Labels assume the canonical 13-label set
(`alpha`, `quant`, `backtest`, `metrics`, `methodology`, `s02`, `s04`,
`s06`, `s07`, `tests`, `docs`, `P0`, `P1`).

---

### Issue 1 — `[alpha] wire PSR + DSR + bootstrap CI into full_report()`

- **Labels:** `alpha`, `quant`, `metrics`, `backtest`, `methodology`, `P0`
- **Scope:** `full_report()` currently outputs Sharpe/Sortino/Calmar
  only. PSR and DSR already exist as tested functions in
  `metrics.py:347-456`. This issue calls them on the daily-resampled
  return series and adds a Politis–Romano (1994) stationary-bootstrap
  95 % CI for the headline Sharpe. `n_trials` is passed in by the
  caller (defaults to 1).
- **Acceptance criteria:**
  - `full_report()` returns `psr`, `dsr`, `sharpe_ci_low`,
    `sharpe_ci_high`, `skew`, `excess_kurtosis`, `tail_ratio`
    (ADR-0002 items #6, #8, #9, #10).
  - New `bootstrap_sharpe_ci(returns, n_resamples, block_size)` in
    `metrics.py` with unit tests vs known fixtures.
  - Property test: PSR ≤ 1, DSR ≤ PSR for the same returns.
  - `backtesting/engine.py` exposes `n_trials` kwarg on
    `BacktestEngine.run()` and threads it to `full_report`.
  - All existing tests still green (no regressions on Sharpe value).
- **References:** Bailey & López de Prado (2012, 2014); Politis &
  Romano (1994).
- **Effort:** M
- **Dependencies:** none.

---

### Issue 2 — `[alpha] replace scalar PBO with CPCV-rank PBO and wire into full_report`

- **Labels:** `alpha`, `quant`, `methodology`, `backtest`, `P0`
- **Scope:** `metrics.py::backtest_overfitting_probability` is a
  closed-form proxy that takes `(IS_sharpe, OOS_sharpe, n_trials)`
  scalars. ADR-0002 #12 + Bailey 2015 Eq. 11 require the rank-based
  PBO computed over a CPCV OOS distribution. CPCV already exists in
  `walk_forward.py:374` but is not invoked anywhere outside its unit
  test. This issue:
  1. Adds `BacktestEngine.validate_cpcv(n_splits=6, n_test_splits=2)`.
  2. Implements `pbo_from_cpcv(cpcv_result)` returning the
     rank-based PBO (Eq. 11).
  3. Deprecates the scalar `backtest_overfitting_probability` (keep
     for one release as a thin wrapper that emits a DeprecationWarning).
  4. Surfaces `oos_sharpe_distribution`, `pbo`, `cpcv_recommendation`
     in `full_report` when called from `validate_cpcv`.
- **Acceptance criteria:**
  - CPCV rank-PBO matches Eq. 11 on a known fixture (test).
  - On a deliberately overfit synthetic strategy, PBO > 0.5.
  - On a clean trending fixture, PBO < 0.25 → DEPLOY.
  - Engine integration test runs CPCV end-to-end with the existing
    1-day fixture.
- **References:** Bailey, Borwein, López de Prado, Zhu (2015) Eq. 11;
  López de Prado (2018) Ch. 12.
- **Effort:** L
- **Dependencies:** Issue 1 (shared `full_report` schema additions).

---

### Issue 3 — `[alpha] add Ulcer Index, MAR, and per-regime Sharpe/DD breakdown`

- **Labels:** `alpha`, `metrics`, `backtest`, `methodology`, `P0`
- **Scope:** Closes ADR-0002 items #5 (Ulcer), #4 (absolute DD), and
  #18 (per-regime Sharpe / DD). `by_regime_breakdown` currently
  reports only PnL aggregates; this issue extends it to compute
  Sharpe, max DD, and hit rate per regime / per session, and adds
  Ulcer Index + absolute drawdown to the headline report.
- **Acceptance criteria:**
  - `ulcer_index(equity_curve)` implemented per Martin & McCann
    (1989) with unit test.
  - `full_report` returns `ulcer_index`, `max_drawdown_abs`,
    `mar_ratio` (annual return / Ulcer).
  - `by_regime_breakdown` rows include `sharpe`, `max_dd`,
    `n_winning_trades`.
  - Sortino in `full_report` is recomputed on `daily_returns` (fixes
    component #2 in Section A).
- **References:** Martin & McCann (1989); ADR-0002 §6.
- **Effort:** M
- **Dependencies:** Issue 1 (new `full_report` schema fields).

---

### Issue 4 — `[alpha] add transaction-cost sensitivity sweep (zero / realistic / 2x stress)`

- **Labels:** `alpha`, `backtest`, `methodology`, `s06`, `P0`
- **Scope:** ADR-0002 §7 mandates that every Quant PR show the
  Sharpe-degradation curve under three cost regimes. Today the
  backtest is a single scenario. Add
  `BacktestEngine.run_cost_sensitivity(ticks)` that runs the same
  strategy under three cost configurations using
  `MarketImpactModel` (already wired into `paper_trader.py`):
  zero cost, realistic (sqrt impact + commissions + spread), and 2x
  realistic. Returns three reports + a degradation summary.
- **Acceptance criteria:**
  - New entry point + CLI flag `--cost-sensitivity`.
  - Report contains `sharpe_zero`, `sharpe_realistic`,
    `sharpe_stress`, and `degradation_pct`.
  - Strategy is **rejected** at the backtest gate if
    `sharpe_realistic < 0.8` (matching the existing CI gate).
  - Integration test on the existing 30-day fixture.
- **References:** Almgren & Chriss (2001); Bouchaud, Farmer, Lillo
  (2009); ADR-0002 §7–§8.
- **Effort:** M
- **Dependencies:** none (parallel-safe with Issues 1–3).

---

### Issue 5 — `[alpha] populate triple_barrier_label in S09 FeedbackLoop`

- **Labels:** `alpha`, `s04`, `quant`, `methodology`, `P1`
- **Scope:** `core/math/labeling.py::TripleBarrierLabeler` is fully
  implemented and unit tested but is not imported by any service.
  The `triple_barrier_label` column already exists in
  `feature_logger.py` and is hard-coded to `None`. This issue wires
  S09 to compute the triple-barrier label for every closed trade
  using its tick history and updates the meta-feature row, unlocking
  Phase-6 supervised meta-labeling.
- **Acceptance criteria:**
  - On every `trade.closed` event, S09 computes
    `BarrierLabel(+1/0/-1)` from the trade's entry tick + N
    subsequent ticks (configurable horizon).
  - Vol-adaptive barriers use S07's published HAR-RV forecast (no
    hard-coded sigma).
  - Integration test confirms ≥ 95 % of closed trades in the 30-day
    fixture have a non-null label.
  - New unit test on a synthetic OHLC fixture.
- **References:** López de Prado (2018) Ch. 3 §3.1–3.6.
- **Effort:** M
- **Dependencies:** none.

---

### Issue 6 — `[alpha] use FractionalDifferentiator to derive stationary log-price features`

- **Labels:** `alpha`, `s07`, `s04`, `quant`, `P1`
- **Scope:** `core/math/fractional_diff.py` (batch + incremental) is
  complete and tested but no service consumes it. This issue:
  1. Adds an offline calibration job that finds `d_opt` per symbol
     using `find_minimum_d()` on a 90-day price history and stores
     it in Redis (`fracdiff:d_opt:{symbol}`).
  2. Adds `IncrementalFracDiff` to S07's per-tick pipeline so the
     stationary log-price series is published as a feature.
  3. Adds the new feature to `MetaFeatures` so the meta-labeler
     classifier (Phase-6) can consume it.
- **Acceptance criteria:**
  - Calibration produces `d_opt ∈ (0.2, 0.6)` for BTC fixture.
  - ADF p-value < 0.05 on the differentiated series.
  - Per-tick CPU cost < 0.05 ms (existing perf gate).
  - Unit test compares incremental output to batch on shared input.
- **References:** López de Prado (2018) Ch. 5; Hosking (1981).
- **Effort:** L
- **Dependencies:** Issue 5 (so that meta-labeler row schema changes
  are batched).

---

### Issue 7 — `[alpha] add turnover, alpha-decay half-life, and capacity estimate to full_report`

- **Labels:** `alpha`, `metrics`, `methodology`, `s06`, `P1`
- **Scope:** Closes ADR-0002 items #15, #16, #17. Implements three
  pure functions in `metrics.py` and surfaces them in `full_report`.
  Capacity uses `MarketImpactModel.sqrt_impact` to find the AUM at
  which expected impact > 25 % of gross edge.
- **Acceptance criteria:**
  - `turnover_ratio(trades, daily_equity)` matches a manual
    calculation on a 3-trade fixture.
  - `alpha_decay_halflife(daily_returns)` returns finite values on
    the 30-day fixture.
  - `capacity_estimate(impact_model, gross_edge_bps, adv)` returns
    a positive AUM and degrades monotonically as `gross_edge_bps`
    falls.
  - Three new unit tests + property tests.
- **References:** Perold (1988); Grinold & Kahn (1999); Almgren &
  Chriss (2001).
- **Effort:** M
- **Dependencies:** Issue 4 (shares the cost-sensitivity harness).

---

### Issue 8 — `[alpha] route HMM regime probabilities into S03 RegimeDetector`

- **Labels:** `alpha`, `s07`, `s03`, `quant`, `P2`
- **Scope:** `RegimeML.fit_hmm` is complete but the 4-state output
  is not consumed downstream. This issue publishes the smoothed
  state probabilities to Redis and lets S03 use them as a fourth
  input to `macro_mult` alongside vol regime, trend regime, and
  macro catalysts.
- **Acceptance criteria:**
  - S07 publishes `hmm:state_probs:{symbol}` every 5 minutes.
  - S03 RegimeDetector consumes the channel and exposes the new
    feature in `Regime` (additive, no breaking change).
  - Integration test verifies state assignment on a synthetic
    two-regime series.
  - Per-regime Sharpe (Issue 3) decomposition gains a fourth axis.
- **References:** Baum et al. (1970); López de Prado (2018) §4.7.
- **Effort:** L
- **Dependencies:** Issues 1, 3 (regime breakdown infrastructure).

---

## Appendix — Evidence excerpts

### Evidence E-1 — PSR/DSR/PBO/CPCV exist but are not called from `full_report()`

`backtesting/metrics.py:574-595` (full body of `full_report` returns
dict):

```python
return {
    "sharpe": sharpe_ratio(daily_returns, ...),
    "sortino": sortino_ratio(period_returns, ...),
    "calmar": calmar_ratio(annual_return, dd),
    "max_drawdown": dd,
    ...
    "by_session": by_session_breakdown(trades),
    "by_regime": by_regime_breakdown(trades),
    "by_signal": by_signal_breakdown(trades),
    "equity_curve": curve,
}
```

No `psr`, `dsr`, `pbo`, or `cpcv` keys. Cross-check via grep:
`probabilistic_sharpe_ratio`, `deflated_sharpe_ratio`,
`backtest_overfitting_probability`, `CombinatorialPurgedCV` appear
only in their definition file, in `walk_forward.py`, and in their
own unit tests. Zero references from `engine.py`, `service`
modules, or `scripts/`.

### Evidence E-2 — Sortino fed per-trade returns

`backtesting/metrics.py:580`:

```python
"sortino": sortino_ratio(period_returns, risk_free_rate),
```

`period_returns` is the per-trade equity-curve diff (line 558),
not the daily-resampled series. Sharpe was migrated to daily by
PR #15 (commit 4e62a95) but Sortino was missed.

### Evidence E-3 — Triple-barrier label column always None

`services/s04_fusion_engine/feature_logger.py:30, 122`:

```text
triple_barrier_label SMALLINT DEFAULT NULL  -- filled later by S09
...
"triple_barrier_label": None,
```

And `grep TripleBarrierLabeler services/` returns zero matches.

### Evidence E-4 — `core/math/fractional_diff.py` has zero callers in `services/`

`grep -r "FractionalDifferentiator\|IncrementalFracDiff" services/`
returns no results. Tests exist (`tests/unit/core/test_fractional_diff.py`)
but production wiring is absent.

### Evidence E-5 — Scalar PBO uses a closed-form proxy, not Eq. 11

`backtesting/metrics.py:527-534`:

```python
if n_trials <= 1:
    return 0.0
if in_sample_sharpe <= 0:
    return 1.0
d = (in_sample_sharpe - out_of_sample_sharpe) / abs(in_sample_sharpe)
d = max(-1.0, min(1.0, d))
log_f = math.log(max(1, n_trials)) / math.log(100)
return max(0.0, min(1.0, 0.5 * (1 + d) * (0.5 + 0.5 * log_f)))
```

Bailey et al. (2015) Eq. 11 defines PBO as the rank-based fraction
of CPCV OOS paths whose Sharpe falls below the IS median — a
distribution statistic, not a scalar transform of two Sharpes.

### Evidence E-6 — OFI proxy limitation acknowledged in code

`services/s02_signal_engine/microstructure.py:37-40`:

```text
# bid_vols / ask_vols store best-bid and best-ask *prices* as the
# closest available proxy for queue-level volumes in NormalizedTick.
```

Classical OFI (Cont, Kukanov, Stoikov 2014) requires L2 size
deltas. The current implementation is a directional proxy and is
documented as such, hence the FIX verdict.

### Evidence E-7 — Ljung-Box critical-value heuristic

`services/s07_quant_analytics/market_stats.py:43-44`:

```python
# Approximate 5% critical value for chi-squared with `lags` degrees of freedom
critical_value = lags * 1.5
```

Should be `scipy.stats.chi2.ppf(0.95, df=lags)`. Hence FIX P2.

### Evidence E-8 — ADR-0002-mandatory metrics that are entirely absent

`grep -i "ulcer\|tail_ratio\|bootstrap\|haircut\|turnover\|capacity\|alpha_decay" backtesting/`
returns zero hits in `backtesting/`. These are the six items driving
Issues 3, 4, and 7.
