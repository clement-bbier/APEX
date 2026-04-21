# ADR-0011 — Decoded Replication Validation Harness

> *This ADR is authored in the Phase B preparation window of [Phase 5 v3 Multi-Strat Aligned Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md). It proposes a new **quality-assurance harness** — not a trading strategy — that validates signal enhancements, strategy onboarding, and trend-shock robustness using a decoded replication pattern inspired by the Ai For Alpha March 2026 paper. The harness extends [ADR-0002](0002-quant-methodology-charter.md) with five new canonical references and introduces three new validation tools scheduled for Phase B Gate 3 and Phase C.*
>
> **Related**: Charter §5.5 (strategy_id discipline); ADR-0002 (quant methodology charter); ADR-0004 (feature validation); ADR-0005 (meta-labeling fusion); ADR-0007 (strategy as microservice); ADR-0009 (panel-builder discipline); ADR-0014 (TimescaleDB schema v2).

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-04-21 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Authors | Claude Code (Opus 4.7) under CIO direction |

---

## 1. Status

**Proposed** — awaiting CIO ratification alongside companion research note [`docs/research/DECODED_REPLICATION_HARNESS.md`](../research/DECODED_REPLICATION_HARNESS.md).

No code lands with this ADR. Implementation is scheduled per §11 below: `EnhancedComparator` in Phase B Gate 3, `TrendShockInjector` and `StrategyRedundancyMonitor` in Phase C, full integration into the strategy-onboarding gate in Phase D.

---

## 2. Context

### 2.1 The problem this harness solves

Phase B onboards Strategy #1 (Crypto Momentum); Phase C onboards the allocator and the 7-step VETO chain; Phase D onboards Strategy #2 (Trend Following). Strategies #3 through #6 follow over months 12–18 ([Roadmap §2](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)). Each promotion from Gate 2 (live microservice, paper-traded) to Gate 3 (8-week paper-trading minimum) to Gate 4 (60-day live-micro) requires evidence that the new strategy generates **diversifying alpha** — not a scaled replica of a live strategy, not pure beta to the existing book.

The current [ADR-0002](0002-quant-methodology-charter.md) methodology charter enforces a strong single-strategy evaluation regime: PSR with non-normality correction, DSR under multiple testing, PBO and CPCV, stress-cost sensitivity, regime-conditional Sharpe. This is world-class as a single-strategy gate — but it does **not** answer the multi-strategy question the Charter now requires: *given that strategies 1 through N are already live, does strategy N+1 add information the book doesn't already have?*

Answering that question by inspection — eyeballing a correlation matrix of realized PnL streams, say — fails when strategies are young (insufficient history), when correlations are regime-dependent (look fine in calm periods, blow up in stress), or when two strategies are *conditionally* similar (same exposure in one regime, different in another). The multi-strategy book needs a **structural diagnostic**, not a post-hoc correlation spot-check.

### 2.2 The Ai For Alpha March 2026 paper

The Ai For Alpha Team's note *"Strategy Spotlight: Decoding Alpha in Practice"* (March 2026) and the underlying academic work — Ohana, Benhamou, Saltiel & Guez (2022) *"Deep Decoding of Strategies"* (Université Paris-Dauphine WP 4128693); Benhamou, Ohana & Guez (2024) *"Generative AI: Crafting Portfolios Tailored to Investor Preferences"* (SSRN 4780034) — introduce a **state-space decoding** method that projects an opaque strategy's return stream onto a liquid universe of tradeable assets via a time-varying Bayesian regression:

```
r_target_t = x_t^T β_t + ε_t,        ε_t ~ N(0, σ²)
β_t = β_{t-1} + η_t,                 η_t ~ N(0, W_t)
```

with forward filtering under a discount factor δ ∈ (0, 1] per West & Harrison (1997, Ch. 4). The method produces a time series of weights `β̂_t` — the replicating portfolio — which approximates the target's returns in the span of the liquid universe.

The paper's **methodological innovation** (beyond a straight replication of prior work) is the **long-Enhanced / short-Baseline excess portfolio**:

- The **Baseline** decoder is fit with the raw target return stream as its left-hand side.
- The **Enhanced** decoder is fit with an artificially boosted target: `r̃_t = r_target_t + c`, where `c = X%/252` is a constant annualized trend added every day.
- The **excess portfolio** is `r_excess_t = r_Enhanced_t − r_Baseline_t = x_t^T (w_Enhanced_t − w_Baseline_t)`.

The excess isolates *where* and *how* the decoder shifts its weights to absorb an injected trend. The paper's headline finding on a large hedge-fund database: the Hedge Funds family excess achieves roughly 15% correlation to the S&P 500 total-return index, a 0.91 Sharpe, and the best return-to-drawdown of any family tested.

The paper further introduces a **trend-shock experiment**: bump one *feature input* (not the target) by +10%/year over a bounded window (e.g., EUR/USD over calendar year 2016) and re-run. The decoder responds by substituting correlated instruments — in their example, GBP/USD absorbs 21.8% of the hedge-ratio shift. This maps how the replicator reasons about cross-instrument substitution and detects over- or under-reaction.

### 2.3 Why this is relevant to APEX

APEX does **not** need to decode external opaque strategies — we own every strategy in the book. But the diagnostic pattern — *compare two variants on the same liquid universe, compute the excess, inspect the sleeve attribution* — applies directly to three internal QA questions:

1. **Signal-enhancement validation.** Before accepting a new feature into an existing signal (e.g., adding a regime-conditional term to HAR-RV), run the current pipeline and the proposed pipeline on the same universe, compute the excess, and check that the new feature contributes real, diversifying information — not a scaled version of what the baseline already captures.

2. **Strategy onboarding gate.** Before promoting a new strategy to capital allocation, decode it against a liquid universe, run the enhanced-vs-baseline excess, and check that its excess is (a) profitable in its own right and (b) **not already replicated** by any existing strategy's excess.

3. **Trend-shock robustness test.** Bump a single *feature input* (e.g., daily realized variance of SPY over Q1 2024) by a bounded annualized trend, re-run the strategy, and observe the weight trajectory. Detects two pathologies: **over-reaction** (a small input perturbation produces wildly different weights — brittleness) and **under-reaction** (a large input perturbation produces no weight response — dead features).

None of the three uses is a trading strategy. All three are **validation tools** consumed by engineers and the CIO at Gate 2 and Gate 3 reviews.

### 2.4 Why existing gates are insufficient

[ADR-0002](0002-quant-methodology-charter.md) §1–10 evaluate a strategy **in isolation** — against a cash benchmark, against itself under CPCV, against stressed costs, against regime conditioning. None of the ten items ask *how does this strategy relate to the other strategies in the book?* That question is answered today by an ad-hoc review of realized PnL correlation — which, per §2.1 above, is insufficient for young strategies, regime-dependent correlations, and conditionally-similar strategies.

[ADR-0004](ADR-0004-feature-validation-methodology.md) validates individual features (IC, rank-IC, MDA, stability across regimes) but operates on a feature stream in isolation, not on a strategy's end-to-end return stream against the rest of the book.

[ADR-0005](ADR-0005-meta-labeling-fusion-methodology.md) governs how signals are combined *within* a strategy, not how strategies combine *across* the portfolio.

The harness proposed here fills this gap. It is explicitly complementary to ADR-0002, ADR-0004, and ADR-0005; nothing in those ADRs is changed.

---

## 3. Decision

The APEX repository gains a new first-party **validation module** `validation/decoding/` (path indicative; final location TBD in Phase B Gate 3 design PR). The module provides three validation tools:

### D1 — `EnhancedComparator`: decoder-based comparison of two variants

Given two decoders fit on the same liquid universe — one fit on a *baseline* return stream, one fit on an *enhanced* return stream — compute the long-Enhanced / short-Baseline excess portfolio and its metrics. Use cases:

- Signal-variant comparison (current HAR-RV vs HAR-RV + regime term).
- Strategy-variant comparison (v1 crypto momentum vs v2 with intraday volume filter).
- Strategy-vs-strategy comparison during onboarding (new strategy as "enhanced", existing peer strategy as "baseline").

The output is a return stream, a metrics bundle, and a sleeve-attribution breakdown (§5).

### D2 — `TrendShockInjector`: bounded feature-input perturbation

Given a feature-input time series (e.g., SPY daily realized variance), inject an artificial annualized trend of +X%/year over a bounded window, re-run the downstream signal/strategy, and diff the weight trajectory against the unshocked run. The injector operates on **inputs to features**, never on **strategy outputs** (no injected PnL, no synthetic fills).

### D3 — `StrategyRedundancyMonitor`: rolling redundancy alerts

Given the set of live strategies' excess return streams (from D1 run historically at onboarding and re-run periodically), compute the rolling 60-day correlation matrix of excess returns. When any pairwise correlation exceeds a configurable threshold (default 0.85), emit a `RedundancyAlert` consumable by the telemetry dashboard and the CIO review queue.

### D4 — Onboarding gate extension

The strategy-onboarding gate in [Phase 5 v3 Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) §6 (Gate 2 smoke, Gate 3 paper) gains the mandatory checks enumerated in §7.4 below, to be run as part of the Gate 2 PR review and re-validated at Gate 3 exit.

### D5 — ADR-0002 reference-list extension

Five canonical references are added to ADR-0002's "Mandatory references" table, covering the decoding and state-space literature this harness builds on (§9).

### D6 — No hot-path impact

All three tools run **offline** against stored histories (TimescaleDB per [ADR-0014](ADR-0014-timescaledb-schema-v2.md), Redis per-strategy keys per Charter §5.5). Zero footprint in the live tick-to-order path.

---

## 4. Mathematical framework

This section summarizes the state-space decoder and excess-portfolio definitions. Full derivations are deferred to the cited sources (West & Harrison 1997, Ch. 4; Kim & Nelson 1999, Ch. 3; Ohana et al. 2022 §2–3; Ai For Alpha 2026 §2).

### 4.1 Sequential state-space regression

Let `r_target_t ∈ ℝ` be the target return at time `t`, and `x_t ∈ ℝ^p` the row-vector of returns of `p` liquid universe instruments (equities, bonds, credit, FX, commodities — see §6). The decoder is:

```
(obs)    r_target_t = x_t^T β_t + ε_t,     ε_t ~ N(0, σ²)
(state)  β_t = β_{t-1} + η_t,               η_t ~ N(0, W_t)
```

This is a **dynamic linear model** (DLM) with a random walk on the coefficient vector β. West & Harrison (1997, Ch. 4) develops the conjugate forward-filtering update using a **discount factor** δ ∈ (0, 1] that controls how quickly old observations are down-weighted:

```
β̂_t = argmin_β [ Σ_{τ ≤ t} δ^{t-τ} (r_target_τ − x_τ^T β)² ]
                + penalization (β − β_{t-1})^T W_t^{-1} (β − β_{t-1})
```

In practice, the forward filter carries forward a posterior mean `β̂_t` and a posterior covariance `C_t`; the prior for `β_{t+1}` has mean `β̂_t` and inflated covariance `C_t / δ`; on observing `(x_{t+1}, r_target_{t+1})`, Kalman-update to get `β̂_{t+1}` and `C_{t+1}`. Pseudocode is provided in the companion research note §4 for illustration only.

### 4.2 Baseline and enhanced targets

Following Ai For Alpha (2026) §2, the decoder is fit twice on **the same universe** with **two different targets**:

- **Baseline target**: `r_target_t` unchanged — the raw return stream of the strategy or signal under test.
- **Enhanced target**: `r̃_t = r_target_t + c`, where `c = X% / 252` is a constant daily increment corresponding to an annualized trend of `X%` (paper uses `X = 10`; APEX will select per-strategy, see §7.1).

Two fits yield two weight trajectories: `β̂^{Baseline}_t` and `β̂^{Enhanced}_t`.

### 4.3 Excess portfolio

The long-Enhanced / short-Baseline **excess portfolio** isolates the effect of the injected trend:

```
r_excess_t = x_t^T (β̂^{Enhanced}_t − β̂^{Baseline}_t)
           = r^{Enhanced}_t − r^{Baseline}_t
```

where `r^{Enhanced}_t = x_t^T β̂^{Enhanced}_t` and similarly for Baseline. The excess return stream is the primary diagnostic input for `EnhancedComparator` (§5.1, D1).

### 4.4 Trend-shock on a feature input

For `TrendShockInjector` (D2), the perturbation is applied to a **feature input** — not the target. Let `f_t` be a feature-input time series (e.g., realized variance of an asset, a macro index level). Define:

```
f̃_t = f_t + 10% / 252     for t ∈ [bump_start, bump_end]
f̃_t = f_t                  otherwise
```

The downstream signal/strategy is re-run with `f̃` substituted for `f`, producing a shocked weight trajectory `β̂^{shocked}_t`. The diagnostic compares `β̂^{shocked}_t` against `β̂^{unshocked}_t` and reports:

- **Substitution pattern**: which instruments absorb the largest weight shifts during the bump window.
- **Elasticity**: magnitude of weight change per unit of input perturbation.
- **Hysteresis**: persistence of weight changes after `bump_end`.

A well-behaved signal exhibits bounded, smooth substitution. Pathologies include collapsing onto a single substitute, flipping sign, or showing no response at all (feature is effectively dead).

### 4.5 Discount factor choice

Per Ai For Alpha 2026 §2 and West & Harrison 1997 §4.3, `δ ∈ [0.95, 1.0]` is the practical range. `δ = 1` gives equal weight to all history (no adaptation — fully recursive OLS). `δ = 0.98` gives an effective window of ~50 observations. APEX harness default is `δ = 0.98` for daily-resampled returns; per-strategy override is allowed in the strategy's Gate 2 PR.

---

## 5. Interface specification

The following are **type sketches** (Python `Protocol` declarations) — not implementations. Implementation lives in Phase B Gate 3 and Phase C per §11. Signatures are provisional and may tighten during implementation design review.

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


class StrategyDecoder(Protocol):
    """
    Bayesian state-space decoder for a strategy or signal return stream.

    Fits r_target_t = x_t^T β_t + ε_t with β_t = β_{t-1} + η_t per
    West & Harrison (1997, Ch. 4). Forward-filter implementation uses
    a discount factor δ in (0, 1]; see ADR-0011 §4.1.
    """

    async def fit(
        self,
        target_returns: "pd.Series",
        universe_returns: "pd.DataFrame",
        discount_factor: float = 0.98,
    ) -> None: ...

    async def predict_weights(self, t: datetime) -> "pd.Series":
        """Weights at time t — β̂_t in the notation of §4.1."""
        ...

    async def filter(self) -> "pd.DataFrame":
        """Full time series of inferred weights over the fit window."""
        ...


class EnhancedComparator(Protocol):
    """
    Decoder-based comparison of two strategy/signal variants on the
    same liquid universe. Implements ADR-0011 D1 (§3).
    """

    def __init__(
        self,
        baseline: StrategyDecoder,
        enhanced: StrategyDecoder,
    ) -> None: ...

    def excess_portfolio(self) -> "pd.DataFrame":
        """
        Returns a dataframe with columns:
          r_baseline: x_t^T β̂^{Baseline}_t
          r_enhanced: x_t^T β̂^{Enhanced}_t
          r_excess:   r_enhanced − r_baseline
        """
        ...

    def metrics(self) -> "ExcessMetrics": ...

    def attribution_by_sleeve(self) -> dict[str, Decimal]:
        """
        Average weight shift |β̂^{Enhanced} − β̂^{Baseline}| aggregated
        by sleeve (equity, bond, credit, fx, commodity). Unit: fraction
        of total weight-shift magnitude across all sleeves.
        """
        ...


@dataclass(frozen=True)
class ExcessMetrics:
    cumulative_return: Decimal
    annual_return: Decimal
    volatility: Decimal
    sharpe: Decimal
    max_drawdown: Decimal
    return_to_drawdown: Decimal
    correlation_to_market: Decimal   # vs SPY total return or strategy-specific benchmark
    correlation_to_baseline: Decimal  # vs r_baseline


class TrendShockInjector(Protocol):
    """
    Bounded-window trend shock on a single feature input. Implements
    ADR-0011 D2 (§3).
    """

    async def inject(
        self,
        input_series: "pd.DataFrame",
        target_column: str,
        bump_bps_annual: int,
        start: datetime,
        end: datetime,
    ) -> "pd.DataFrame":
        """
        Returns a copy of input_series with `target_column` bumped by
        bump_bps_annual / 252 per bar over [start, end]. Other columns
        are unchanged.
        """
        ...


class StrategyRedundancyMonitor(Protocol):
    """
    Rolling redundancy alerts across live strategies' excess return
    streams. Implements ADR-0011 D3 (§3).
    """

    async def rolling_correlation_matrix(
        self,
        strategy_ids: list[str],
        window_days: int = 60,
    ) -> "pd.DataFrame": ...

    async def redundancy_alerts(
        self,
        threshold: float = 0.85,
    ) -> list["RedundancyAlert"]: ...


@dataclass(frozen=True)
class RedundancyAlert:
    strategy_a: str
    strategy_b: str
    window_end: datetime
    correlation: Decimal
    threshold: Decimal
```

Notes on the interface:

- All floating-point metric fields are typed as `Decimal` per [CLAUDE.md §2](../../CLAUDE.md) forbidden patterns. The underlying numeric library (numpy, scipy, `apex_risk` Rust crate) operates in `f64` internally; the surface of the harness quantizes to `Decimal` before persisting.
- All `datetime` inputs are required to carry `tzinfo=UTC` per [CLAUDE.md §2](../../CLAUDE.md).
- The harness is **async-only** for I/O points (Redis, TimescaleDB reads) consistent with [CLAUDE.md §2](../../CLAUDE.md); the CPU-bound Kalman filter itself is synchronous but wrapped in `asyncio.to_thread` (or delegated to a Rust crate under `apex_*`) to avoid blocking the event loop.
- `strategy_id` is threaded through every call per [Charter §5.5](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) — the harness reads `trades:{strategy_id}:all` and writes `apex_strategy_metrics` rows keyed by `strategy_id`.

---

## 6. Data requirements

### 6.1 Liquid universe for decoding

The universe against which a strategy is decoded must (a) span the asset classes the strategy trades or is plausibly exposed to, (b) be deeply liquid so that the replicating portfolio is realistically tradeable in principle, and (c) be available at daily frequency over at least a 10-year window for the `EnhancedComparator` fit.

The default cross-asset universe mirrors the Ai For Alpha 2026 paper's universe for comparability:

| Sleeve | Instruments (indicative tickers) |
|---|---|
| Equities | US broad (SPY), US small-cap (IWM), US tech (QQQ), Japan (EWJ), Euro area (VGK), UK (EWU), emerging markets (EEM) |
| Bonds | US 10Y (IEF), Japan 10Y (futures proxy), Germany 10Y (Bund futures proxy), UK 10Y (Gilt futures proxy), Canada 10Y |
| Credit | CDX North America High Yield 5Y, iTraxx Crossover 5Y |
| FX | AUD/USD, CAD/USD, CHF/USD, EUR/USD, GBP/USD, JPY/USD |
| Commodities | Gold (GLD), Brent (BNO or front futures), Copper, Natural Gas (UNG or futures) |

Strategy-specific variants of this universe are permitted — e.g., a crypto-only strategy decodes against a crypto universe (BTC, ETH, top-20 USDT pairs by ADV) supplemented by equity-sleeve proxies to quantify equity beta. The chosen universe for each strategy is **declared in its per-strategy Charter** (`docs/strategy/per_strategy/<strategy_id>.md`) and is not permitted to change silently.

### 6.2 Data source

The free-tier Alpaca integration that serves S01 Ingestion does **not** cover all sleeves above — in particular, credit indices, non-US sovereigns, and several FX crosses. The harness requires a vendor that covers all sleeves at daily frequency with 10+ years of history.

Candidate providers:

- **Databento** — broad coverage, T+1 daily bars, extensive historical depth. Preferred if the Terminal 10 connector audit (parallel work) confirms pricing and quota fit.
- **Polygon.io** — US equities, US options, FX, crypto; adequate for most sleeves but credit-index coverage is absent.
- **Refinitiv / Bloomberg** — comprehensive but institutional pricing; out of scope for a solo-operator budget per [Charter §1.1](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md).

The Phase B Gate 3 design PR that implements `EnhancedComparator` must select the vendor, sign off the data-quality audit, and backfill the TimescaleDB `apex_market_daily` table with the chosen universe. Until that PR lands, the harness is **blocked on data**.

### 6.3 Target-return stream

The target-return stream `r_target_t` is the **per-strategy daily return** computed from `trades:{strategy_id}:all` (Charter §5.5) marked to market and resampled to daily frequency in UTC. The ADR-0002 discipline of "returns basis: daily-resampled equity-curve returns, never per-trade returns" (item 1 of its mandatory checklist) applies unchanged.

### 6.4 Storage

Three persistent artifacts per strategy per harness run:

- **Daily universe bar panel** (shared across strategies) — TimescaleDB hypertable `apex_market_daily` keyed by `(symbol, ts)`. One-time backfill at vendor onboarding, incremental append daily.
- **Strategy decoder snapshot** — TimescaleDB table `apex_decoder_snapshot` keyed by `(strategy_id, universe_id, as_of_ts)`; columns include `beta_vector JSONB`, `variant ENUM('baseline', 'enhanced')`, `discount_factor NUMERIC(6,4)`.
- **Excess metrics row** — TimescaleDB table `apex_strategy_metrics` gains three new columns via a follow-up migration (§7.2): `excess_sharpe`, `excess_correlation_to_market`, `attribution_by_sleeve JSONB`.

Schema DDL for these additions is out of scope for this ADR — it is authored in the Phase B Gate 3 design PR that implements `EnhancedComparator`, subject to [ADR-0014](ADR-0014-timescaledb-schema-v2.md) conventions.

---

## 7. Integration points with APEX

### 7.1 Per-strategy baselines declared in the strategy Charter

Every strategy's per-strategy Charter (`docs/strategy/per_strategy/<strategy_id>.md`, Charter §5.5) gains a new mandatory section **"Decoded Replication Baseline"** that declares:

- The liquid universe for this strategy (subset of §6.1 or a custom superset, justified).
- The baseline definition — which variant of the signal/strategy counts as "baseline" in the EnhancedComparator.
- The trend-shock parameters — which feature inputs are candidates for `TrendShockInjector`, with plausible bump magnitudes (annualized bps).
- The redundancy threshold — default 0.85 per D3 is usable; strategies with structurally-similar peers may tighten or loosen with justification.

Without this section, a strategy cannot open a Gate 2 PR.

### 7.2 TimescaleDB schema extension

A follow-up migration (`db/migrations/002_decoded_replication_metrics.sql`, not authored in this ADR) adds three columns to `apex_strategy_metrics`:

```
excess_sharpe                  NUMERIC(10, 6)   NULL,
excess_correlation_to_market   NUMERIC(5, 4)    NULL,
attribution_by_sleeve          JSONB            NULL
```

and two new tables:

```
apex_decoder_snapshot          -- time series of β̂_t per strategy / variant
apex_redundancy_alert          -- alerts emitted by StrategyRedundancyMonitor
```

Full DDL, index choices, and compression policies are specified in the Phase B Gate 3 implementation PR per [ADR-0014](ADR-0014-timescaledb-schema-v2.md).

### 7.3 Telemetry dashboard

A new **"Decoded Replication"** tab is added to `services/ops/monitor_dashboard/` (Charter §5.4 target topology). Per strategy, the tab renders:

- Excess cumulative-return curve.
- Excess drawdown curve.
- Sleeve-attribution stacked area over time.
- Rolling correlation-to-market (60-day window).
- Pairwise redundancy heatmap across live strategies.
- Most recent `RedundancyAlert` list.

This is a **read-only** dashboard per [CLAUDE.md §11](../../CLAUDE.md) — no orders can be triggered from it.

### 7.4 Strategy onboarding gate (Gate 2 and Gate 3)

The [Playbook](../strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) Gate 2 checklist is extended with the following mandatory items, to be evidenced in the Gate 2 PR body:

**Mandatory — excess profile thresholds:**

1. `excess_sharpe > 0.3` over the CPCV-purged out-of-sample window (per [ADR-0002](0002-quant-methodology-charter.md) item 5).
2. `|excess_correlation_to_market| < avg(|excess_correlation_to_market|) across existing live strategies`. *This threshold is a relative bar, not an absolute one — it tightens as the book accumulates market-uncorrelated alpha, which is the intended ratchet.*
3. `attribution_by_sleeve` exhibits no single-sleeve concentration above 70% — the strategy's enhancement must spread across sleeves, not ride a single beta.
4. Rolling 60-day correlation to each existing live strategy's excess returns remains below 0.85 across all windows in the evaluation history.

**Mandatory — trend-shock robustness:**

5. For each feature input declared in the strategy's per-strategy Charter "Decoded Replication Baseline" section (§7.1 above), a `TrendShockInjector` run of `+10%/year over a 3-month window` produces:
   - Non-zero weight response (elasticity above a strategy-specific floor).
   - Bounded weight response (no single instrument absorbs more than 80% of the shift — detects over-concentration).
   - Sign-consistent response (no unexpected sign flips — detects fragile features).

**Failure handling.** A Gate 2 PR that fails any of items 1–5 above is **rejected at review**. Remediation options: rescope the universe, refine the feature set, widen the discount factor, or withdraw the strategy for further Gate 1 iteration. Waivers are permitted only with a documented per-strategy exception in the strategy Charter and explicit CIO sign-off.

**Gate 3 re-validation.** After the Gate 3 8-week paper trading minimum, all five items are re-run against the paper-trading return stream. Drift in any item beyond ±30% of its Gate 2 value requires a documented explanation in the Gate 3 exit PR.

### 7.5 Periodic re-validation in production

After Gate 4 promotion to live, the harness runs weekly for each live strategy on a cron schedule (`services/ops/scheduler/` or the Phase D ops-runner, exact location TBD). Outputs are persisted to `apex_strategy_metrics`. `StrategyRedundancyMonitor` emits `RedundancyAlert` rows that:

- Surface in the Decoded Replication dashboard tab (§7.3).
- Page the CIO only at a secondary threshold (default 0.90) — the primary 0.85 threshold triggers a review ticket, not a page, to avoid alert fatigue.

---

## 8. Limitations and caveats

1. **Not a trading strategy.** The excess portfolio and the shocked weight trajectories are diagnostic artifacts. They are **not** to be deployed as independent trading strategies, and the capital allocator ([Charter §6](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md), [ADR-0008](ADR-0008-capital-allocator-topology.md)) never allocates capital to a "decoded replication" sleeve. This constraint is protected by the fact that the harness lives under `validation/` and does not implement the `StrategyRunner` ABC.

2. **Baselines must be explicit.** "Enhanced" is only meaningful against a specific baseline. Each per-strategy Charter declares the baseline; changing the baseline between two harness runs is a protocol violation and triggers re-validation of the entire gate. There is no implicit global baseline.

3. **Feature decoding is projection, not fact-extraction.** The decoder projects a return stream onto a chosen basis (the liquid universe). A non-trivial `β̂_t` does **not** prove the strategy causally trades those instruments. It proves the return stream is representable (in the span of the basis) as a dynamic mixture of those instruments. Over-interpretation of `β̂_t` as "what the strategy is really doing" is an error mode the companion research note addresses explicitly.

4. **Computational cost is non-trivial.** The Kalman forward filter is `O(T · p³)` per fit; two fits per comparison; one comparison per strategy per re-validation. For `T = 10 years × 252 days = 2520` daily bars, `p ≈ 25` universe instruments, and `N = 6` strategies, the weekly cron workload is on the order of `6 × 2 × 2520 × 25³ ≈ 2.4B` floating-point ops — comfortably on the order of seconds per strategy in compiled code (numpy BLAS or `apex_risk` Rust crate). This rules out running the harness inline with tick processing ([CLAUDE.md §5](../../CLAUDE.md)) but poses no problem offline.

5. **Universe choice is the main researcher degree of freedom.** Different universes produce different decodings. This is a feature, not a bug — the universe defines the question being asked — but it means the gate numbers (excess_sharpe, correlation_to_market) are **not comparable across strategies with different universes**. The onboarding gate's redundancy check (item 4 of §7.4) requires that all strategies be decoded on a **common** universe for fair comparison; per-strategy extended universes are allowed for sleeve-attribution analysis only.

6. **Non-stationarity of β_t.** The DLM assumes a random walk in β. Structural breaks (e.g., regime shifts) may produce implausible jumps in β̂_t. Kim & Nelson (1999) extend the framework to regime-switching state-space models; APEX harness v1 does **not** adopt that extension — structural-break handling is deferred to a future ADR if empirical evidence motivates it.

7. **Look-ahead risk in the discount factor.** Choosing `δ` post-hoc to maximize excess_sharpe on a specific strategy is a form of backtest overfitting per [ADR-0002](0002-quant-methodology-charter.md) item 4. The default `δ = 0.98` is fixed across all Phase B and Phase C strategies; per-strategy overrides require explicit justification in the per-strategy Charter and are subject to the DSR correction for multiple testing across strategies.

8. **Excess portfolio can be gamed by trivial enhancements.** Injecting a constant trend `c` into the target will always produce a non-zero excess that correlates with whatever instruments the decoder uses to "finance" that trend. The gate thresholds in §7.4 are calibrated to reject trivial excesses — the excess must be **profitable on its own** (Sharpe > 0.3), **cross-sleeve diversified** (no >70% concentration), and **uncorrelated with existing strategies' excesses** (pairwise correlation < 0.85). A strategy whose only "enhancement" is a constant upward drift will fail the diversification and redundancy checks.

---

## 9. References

Full bibliographic citations for all sources relied on by this ADR. The **Ai For Alpha Team (2026)** and the four supporting academic references marked with ★ are proposed additions to the [ADR-0002](0002-quant-methodology-charter.md) canonical reference list (see D5 of §3).

1. ★ **Ai For Alpha Team** (March 2026). *"Strategy Spotlight: Decoding Alpha in Practice"*. Ai For Alpha white paper series. Research note introducing the long-Enhanced / short-Baseline diagnostic and the trend-shock robustness test.

2. ★ **Benhamou, E., Ohana, J. & Guez, B.** (2024). *"Generative AI: Crafting Portfolios Tailored to Investor Preferences"*. SSRN working paper 4780034. Extends the state-space decoding framework to preference-conditioned portfolio construction.

3. ★ **Ohana, J., Benhamou, E., Saltiel, D. & Guez, B.** (2022). *"Deep Decoding of Strategies"*. Université Paris-Dauphine Research Paper 4128693 (SSRN). Deep-learning extension of the Bayesian decoder; foundational reference for the decoding methodology.

4. ★ **West, M. & Harrison, J.** (1997). *Bayesian Forecasting and Dynamic Models* (2nd ed.). Springer-Verlag. Canonical reference for dynamic linear models, discount factors, forward filtering, and retrospective smoothing.

5. ★ **Kim, C.-J. & Nelson, C. R.** (1999). *State-Space Models with Regime Switching: Classical and Gibbs-Sampling Approaches with Applications*. MIT Press. Canonical reference for extending state-space models to regime-switching contexts — relevant for the future ADR on structural-break handling (§8 item 6).

6. **López de Prado, M.** (2018). *Advances in Financial Machine Learning*. Wiley. Cited per [ADR-0002](0002-quant-methodology-charter.md) for CPCV, PBO, and meta-labeling — the backdrop against which this harness is complementary, not substitutive.

7. **Harvey, C. R., Liu, Y. & Zhu, H.** (2016). *"…and the Cross-Section of Expected Returns"*. *Review of Financial Studies* 29(1), 5–68. Cited per [ADR-0002](0002-quant-methodology-charter.md) for multiple-testing discipline in quant research.

8. **Politis, D. N. & Romano, J. P.** (1994). *"The Stationary Bootstrap"*. *JASA* 89(428), 1303–1313. Cited per [ADR-0002](0002-quant-methodology-charter.md) for bootstrap CIs on excess metrics — the harness defers to the existing ADR-0002 bootstrap discipline for its own CI construction.

---

## 10. Consequences

### 10.1 On strategy onboarding

Gate 2 and Gate 3 become materially stricter. Strategies that previously could pass by demonstrating standalone Sharpe now additionally must demonstrate that their contribution to the book is structurally novel. Historically this is the hardest gate in a multi-strategy firm — and its absence is a well-documented failure mode of systematic multi-strat platforms when crowded trades unwind. This ADR codifies the gate that closes that failure mode.

### 10.2 On existing strategies

The single "default" strategy (the legacy `LegacyConfluenceStrategy` per [Charter §5.10](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)) has no book to diversify against. It is exempt from the redundancy check (item 4 of §7.4). All strategies onboarded from Strategy #1 onwards are subject to the full gate.

Strategy #1 (Crypto Momentum) is the first strategy to exercise this harness. Its Gate 2 PR is thus both a strategy-onboarding PR **and** a harness-commissioning PR — the first `EnhancedComparator` run establishes the protocol.

### 10.3 On infrastructure

New first-party code lives under `validation/decoding/`. New TimescaleDB tables and columns per §7.2. New dashboard tab per §7.3. Zero code in the hot path — the harness is strictly offline and per-strategy.

### 10.4 On the quant methodology charter

[ADR-0002](0002-quant-methodology-charter.md)'s canonical reference list grows by five entries per D5 / §9. A follow-up PR against ADR-0002 appends these to the "Mandatory references" table with brief use-case descriptions. No changes to ADR-0002's ten-item mandatory evaluation checklist — the harness is additive.

### 10.5 On CIO time

The harness produces **human-read output**. Weekly review of redundancy alerts, quarterly review of cross-strategy sleeve attribution, ad-hoc review on trend-shock events — this is material CIO load per strategy per year. The automation in §7.3 dashboards is designed to make this reviewable in under an hour per strategy per week; without that automation, the harness would scale poorly beyond three strategies.

---

## 11. Implementation phases

Implementation is deliberately staged so that each tool proves its value on real APEX data before the next tool is funded.

### Phase B Gate 3 — `EnhancedComparator` for HAR-RV signal variants

**Window**: weeks 10–14 of Phase B (per [Roadmap §3](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)).
**Scope**:

- Design PR ratifies the `validation/decoding/` module structure, data-vendor choice, and schema DDL.
- Implementation PR delivers `StrategyDecoder`, `EnhancedComparator`, and `ExcessMetrics` per the §5 type sketches.
- First real use case: comparing two HAR-RV variants (baseline: 3-component daily/weekly/monthly realized variance; enhanced: same + regime-conditional term). Proves the pattern on a well-understood APEX signal before applying it to a full strategy.

**Exit criteria**: an `EnhancedComparator` run on HAR-RV variants produces a signed `ExcessMetrics` artifact, a sleeve-attribution breakdown, and a dashboard tab preview — all consumed by the CIO in a dedicated review.

### Phase C — `TrendShockInjector` and `StrategyRedundancyMonitor`

**Window**: weeks 14–22 (overlapping with Strategy #1 Gate 2 work, per [Roadmap §4](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)).
**Scope**:

- `TrendShockInjector` with feature-input bumping, plus the diff-and-report layer that renders substitution / elasticity / hysteresis metrics.
- `StrategyRedundancyMonitor` with rolling 60-day correlation matrix and `RedundancyAlert` emission.
- Strategy #1 Crypto Momentum Gate 2 PR is the first gate to enforce the full §7.4 checklist.

**Exit criteria**: Strategy #1 passes all five §7.4 items (or a documented waiver is approved); the Decoded Replication dashboard tab is live; `RedundancyAlert` rows land in TimescaleDB.

### Phase D — Full integration into the promotion pipeline

**Window**: weeks 22–28 (per [Roadmap §5](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)).
**Scope**:

- Weekly-cron re-validation (§7.5).
- Gate 3 re-validation hook at paper-exit.
- Per-strategy Charter template updated with the mandatory "Decoded Replication Baseline" section (§7.1).
- Second strategy (Trend Following) onboarded through the full harness — first cross-strategy redundancy check with a non-trivial book.

**Exit criteria**: harness runs on two live strategies weekly without manual intervention; redundancy alerts have surfaced at least one real (or correctly-absent) signal; Gate 3 exit PRs include the drift report.

### Post-Phase D — Extensions deferred to future ADRs

- Regime-switching decoder per Kim & Nelson (1999) — addresses structural breaks (§8 item 6).
- Non-linear decoders (GPR, deep kernel) per Ohana et al. (2022) — addresses non-linear strategy responses.
- Per-feature attribution beyond sleeve-level (per-instrument attribution over long windows).
- Harness vs. vendor-provided peer decoding (compare APEX strategies' excess to published hedge-fund-family excesses).

None of the extensions are in the Phase B–D scope.

---

## 12. Alternatives considered and rejected

- **Ad-hoc realized-PnL correlation matrix across strategies.** Rejected — see §2.1. Fails for young strategies (insufficient history), regime-dependent correlations, and conditionally-similar strategies.
- **Factor-model decomposition (Fama-French / Barra).** Rejected as sole gate — factor models are static-basis decompositions that miss time-varying exposures, which are the dominant feature of multi-strategy books. The state-space decoder is a generalization of factor decomposition (factor loadings = β̂_t with high δ).
- **Sharpe-only diversification check (correlation of excess Sharpes across strategies).** Rejected — Sharpe is a scalar per strategy and loses the temporal structure necessary to detect conditional redundancy.
- **Implementing decoding on live PnL streams only (no enhancement).** Rejected — without the long-Enhanced / short-Baseline construction, the decoder produces a replicating portfolio but not the diagnostic excess that isolates incremental alpha. Enhancement is load-bearing.
- **Decoding external opaque strategies (copycat alpha from hedge-fund return streams).** Rejected. The Ai For Alpha paper's external-strategy use case does not apply to APEX — we own every strategy in our book, so external decoding adds no information. Internal decoding as a QA tool does.

---

## 13. Change log

- **2026-04-21** — ADR drafted by Claude Code (Opus 4.7) under CIO direction; proposed for ratification alongside companion research note [`docs/research/DECODED_REPLICATION_HARNESS.md`](../research/DECODED_REPLICATION_HARNESS.md).
