# APEX Trading System — Project Manifesto

> **Primary Objective: Maximize PnL through systematic alpha generation**
> Multi-asset | Microstructure-first | Regime-adaptive | Hedge Fund-grade

---

> **STATUS: CURRENT-STATE ARCHITECTURE** (as of 2026-04-19)
>
> This document describes the **current** technical architecture of the APEX codebase in its present S01-S10 topology. It is the source of truth for code that exists today on disk.
>
> **Target-state architecture is defined in [docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md](docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)** (Charter v1.0, ratified 2026-04-18).
>
> Key deltas current → target:
>
> | Current (this document) | Target (Charter) |
> |---|---|
> | 10 services numbered S01–S10 | Services classified by domain: `data/`, `signal/`, `portfolio/`, `execution/`, `research/`, `ops/`, `strategies/` (Charter §5.4) |
> | Single-strategy signal path in S02 | Multi-strategy microservices under `services/strategies/` (Charter §5.1); legacy S02 wrapped as `LegacyConfluenceStrategy` |
> | No capital allocator (Fusion Engine does per-signal fusion only) | New `services/portfolio/strategy_allocator/` microservice (Charter §5.2, §6) |
> | No panel builder (strategies subscribe directly to tick topics) | New `services/data/panels/` microservice; all strategies consume panels (Charter §5.3) |
> | Pydantic models without `strategy_id` | `strategy_id` added to `Signal`, `OrderCandidate`, `ApprovedOrder`, `ExecutedOrder`, `TradeRecord` (Charter §5.5) |
> | 6-step VETO chain in S05 | 7-step Chain of Responsibility (Charter §8.2) |
> | Global Redis keys (`kelly:{symbol}`, `trades:all`, etc.) | Per-strategy partitioning (`kelly:{strategy_id}:{symbol}`, `trades:{strategy_id}:all`) for strategy-specific keys (Charter §5.5) |
>
> **This document remains binding for current code** until the multi-strat infrastructure lift (Phases A-B-C-D from MULTI_STRAT_READINESS_AUDIT_2026-04-18.md §6, scheduled in Document 3) progressively updates the codebase. Each phase of the lift will update this MANIFEST.md in the same PR as the code change, so current-state and code remain aligned.
>
> Migration tracking: [`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (Document 3, v3.0, ratified 2026-04-20 via PR #188 + post-merge fixups PR #189). The Roadmap schedules Phase A (weeks 1–8, ready to begin), Phase B (weeks 6–14), Phase C (weeks 12–22), Phase D (weeks 18–28) + Phase D.5 topology migration (weeks 26–28); sequences the six boot strategies' gate windows; and codifies the three portfolio-level benchmarks (Survival at month 9 / Legitimacy at month 15 / Institutional at month 24).
>
> **Four new ADRs** formalize Charter §5.1–§5.4 alongside Document 3: [ADR-0007 Strategy as Microservice](docs/adr/ADR-0007-strategy-as-microservice.md), [ADR-0008 Capital Allocator Topology](docs/adr/ADR-0008-capital-allocator-topology.md), [ADR-0009 Panel Builder Discipline](docs/adr/ADR-0009-panel-builder-discipline.md), [ADR-0010 Target Topology Reorganization](docs/adr/ADR-0010-target-topology-reorganization.md). With Document 3 ratified, the **Charter-Playbook-Roadmap trilogy is fully canonical on main**.
>
> **Operational procedures** for strategy development, validation, deployment, circuit-breaker response, decommissioning, reactivation, and category reassignment are specified in the **Lifecycle Playbook** (v1.0, ratified 2026-04-20): [`docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`](docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md). The Playbook references the technical architecture described here; conversely, this MANIFEST references back to the Playbook for any procedure involving strategy microservices at `services/strategies/<strategy_id>/`.

---

## Table of Contents

1. [Vision & Philosophy](#1-vision--philosophy)
2. [Theory of Alpha — Where the Real Edge Lives](#2-theory-of-alpha)
3. [Market Catalysts & Session Patterns](#3-market-catalysts--session-patterns)
4. [Multi-Timeframe Cascade Strategy](#4-multi-timeframe-cascade-strategy)
5. [Long/Short Dynamic Hedging](#5-longshort-dynamic-hedging)
6. [Regime-Adaptive Strategies](#6-regime-adaptive-strategies)
7. [Asset Universe & Dynamic Selection](#7-asset-universe--dynamic-selection)
8. [Microservices Architecture](#8-microservices-architecture)
9. [Service Specifications](#9-service-specifications)
10. [Mathematical & Quantitative Engine](#10-mathematical--quantitative-engine)
11. [Design Patterns](#11-design-patterns)
12. [Technology Stack](#12-technology-stack)
13. [Repository Structure](#13-repository-structure)
14. [Security & Capital Protection](#14-security--capital-protection)
15. [Economics & Profitability](#15-economics--profitability)
16. [Roadmap](#16-roadmap)
17. [Out of Scope — Phase 1](#17-out-of-scope--phase-1)
18. [Academic References](#18-academic-references)

---

## 1. Vision & Philosophy

APEX Trading System is an autonomous quantitative trading engine designed to generate alpha systematically and reproducibly across US equities and cryptocurrency markets. It draws direct inspiration from the approaches of leading quantitative institutions — **Renaissance Technologies (James Simons)**, Two Sigma, Citadel, DE Shaw — adapted for a high-performance personal infrastructure.

### Core Conviction

Markets are complex adaptive systems, partially predictable, in which statistically robust patterns can be extracted through rigorous mathematical methods. The informational advantage does not come from consuming public macro information — already priced in — but from precise reading of **microstructure**, **crowd behavior**, **order flow dynamics**, **session patterns**, and **central bank catalysts**.

### What this system IS NOT

- ❌ A bot following simple mechanical rules ("RSI < 30 → buy")
- ❌ A macro-news-driven system (public information is already priced)
- ❌ A HFT system (co-location infrastructure not required)
- ❌ A discretionary system (zero human intervention during trading hours)
- ❌ An absolute price predictor (we predict probabilities, not prices)

### What this system IS

- ✅ A **microstructure-first** statistical engine grounded in peer-reviewed mathematics
- ✅ A **multi-asset, regime-adaptive** system that allocates capital where edge is maximal
- ✅ A **multi-timeframe** system: swing context + short-term execution = compound alpha
- ✅ A **long/short hedging** engine: profitable in both directions simultaneously
- ✅ A **professional microservices** architecture: each component independently testable
- ✅ A system with **integrated quantitative risk management** — catastrophic behavior is architecturally impossible

### Performance Target — Hedge Fund Grade

| Metric | Target |
|---|---|
| Annual return | 20–40% |
| Sharpe Ratio | > 1.5 |
| Max Drawdown | < 10% |
| Win Rate | > 52% |
| Profit Factor | > 1.4 |

> Renaissance Technologies' Medallion Fund achieved +66% gross annually. The edge was pure mathematics, not trading intuition.

---

## 2. Theory of Alpha

Alpha is excess return unexplained by systematic risk. This system generates it through **five independent sources**, each grounded in published academic research.

### Edge #1 — Microstructure & Order Flow

Microstructure studies price formation mechanisms at very short timescales. This is the most robust edge because it rests on measurable mechanical imbalances.

#### Order Flow Imbalance (OFI)
*Cont, Kukanov & Stoikov (2014)*

```
OFI_t = ΔBid_vol_t - ΔAsk_vol_t
where ΔBid_vol = max(0, Bid_vol_t - Bid_vol_(t-1))
```

A strongly positive OFI predicts short-term price increases with high statistical significance (R² ~ 0.6 over 10 seconds).

#### Cumulative Volume Delta (CVD)

```
CVD_t = Σ(buy_volume_i - sell_volume_i)  for i ∈ [session_open, t]
```

Divergence between CVD and price (price rises, CVD falls) is a strong reversal signal — smart money selling into the rally.

#### Kyle's Lambda — Market Illiquidity
*Kyle (1985)*

```
ΔP_t = λ × OFI_t + ε_t
λ = Cov(ΔP, OFI) / Var(OFI)
```

High lambda indicates illiquidity — a large order will significantly move price. Used for position sizing and liquidity trap avoidance.

#### Absorption Detection

When a large buy order arrives and price does not move, it signals institutional absorption by a seller. This pattern statistically precedes price drops.

---

### Edge #2 — Crowd Behavior & Behavioral Finance

Markets are not efficient in the short term because they are composed of human agents with predictable cognitive biases.

#### Self-fulfilling Momentum
*Jegadeesh & Titman (1993)*

```
MOM_t = P_t / P_(t-n) - 1
```

Assets that outperformed over 3–12 months continue outperforming. The mechanism: investors under-react to initial information, then over-react.

#### Stop Hunting & Liquidation Cascades

Institutional participants know where retail stops cluster (below round numbers, below recent lows). The system maps these zones and anticipates forced liquidations as a source of brutal momentum.

#### Gamma Exposure (GEX) — Price Magnets

```
GEX = Σ(Gamma_i × OpenInterest_i × ContractSize)  per strike
```

Strikes with high GEX act as gravitational attractors — market makers hedge by buying/selling the underlying, creating pinning effects exploitable for mean-reversion.

#### Disposition Effect
*Shefrin & Statman (1985)*

Investors sell winners too early and hold losers too long. Creates systematic resistance at old highs and support at old lows.

---

### Edge #3 — Quantitative Technical Signals

Technical indicators are only useful in a statistical framework: certain configurations produce exploitable conditional probabilities, measurable over sufficient historical data.

| Indicator | Mathematical Foundation | Signal | Timeframes |
|---|---|---|---|
| RSI Divergence | `RSI = 100 - 100/(1+RS)`, RS = avg_gain/avg_loss | Bullish/bearish divergence price vs oscillator | 1m, 5m, 15m |
| Bollinger Bands | `Bands = SMA(n) ± k×σ(n)`, k=2 → 95% price inclusion | Close outside band → reversion; Squeeze → breakout | 5m, 15m |
| EMA Crossovers | `EMA(n) = P_t×α + EMA_(t-1)×(1-α)`, α=2/(n+1) | EMA(8)/EMA(21) crossover in trend direction | 1m, 3m, 5m |
| VWAP | `VWAP = Σ(P_i×V_i) / Σ(V_i)` — institutional intraday reference | Price/VWAP deviation → mean reversion | Daily |
| ATR | `ATR = EMA(TrueRange, 14)`, `TR = max(H-L, \|H-Cp\|, \|L-Cp\|)` | Dynamic sizing, adaptive stop loss | 5m, 15m |
| Volume Profile | Volume distribution by price level; POC = most traded price | Structural support/resistance, VAH/VAL targets | Daily |

---

### Edge #4 — Session & Temporal Patterns

Intraday volatility is statistically non-uniform. Session patterns are reproducible, measurable, and exploitable.

| Time (ET) | Session Event | Volatility | Strategy |
|---|---|---|---|
| 09:30–10:30 | **US Open ★ PRIME** | Very High | Directional scalping |
| 10:30–11:30 | Digestion | Declining | Mean reversion |
| 12:00–13:30 | Lunch dip | Low | Avoid or range plays |
| 13:30–15:00 | Afternoon momentum | Medium-High | Momentum/trend |
| 15:00–16:00 | **US Close ★ PRIME** | High | Scalping + hedges |
| Pre/Post-market | Earnings reactions | Very High | Event-driven scalping |

**Crypto sessions (UTC):**
- 00:00–02:00: Asian liquidations
- 08:00–10:00: London open
- 13:30: US open spike (cross-asset contagion)

---

### Edge #5 — Macro as Context Filter

> **Macro does NOT generate trading signals. Public macro information is already priced in.**

The macro filter determines whether the context is favorable or unfavorable for micro signal expression. It modulates system aggressiveness.

**Central Bank Watch** — highest-impact macro catalyst:

| Institution | Frequency | Impact | Protocol |
|---|---|---|---|
| Fed (FOMC) | 8×/year | SPY ±1–3% in minutes | Block trades 45min before, scalp post-announcement |
| ECB | 8×/year | EUR/USD, European equities | Same protocol |
| BOJ | 8×/year | Yen carry trade → crypto/equities | Same protocol |
| BOE, SNB | 8×/year | Secondary but tracked | Same protocol |

**Central bank announcement protocol:**
```
T-45min : Block all new entries
T-0     : Read direction + amplitude of first move
T+5min  : If move > 1.5σ of historical vol → scalp directional momentum
T+60min : Return to standard regime
```

---

## 3. Market Catalysts & Session Patterns

### Recurring High-Impact Calendar Events

```
WEEKLY
├── Monday    : Week open positioning, gaps from weekend
├── Wednesday : FOMC minutes (alternating weeks), EIA crude oil inventory
├── Thursday  : Weekly jobless claims, ECB press conferences
└── Friday    : NFP (first Friday/month), options expiry (OpEx)

MONTHLY
├── First Friday : NFP — Non-Farm Payrolls → strongest monthly move
├── Mid-month    : CPI, PPI → inflation data → rate expectation repricing
├── Last Friday  : Monthly OpEx → GEX reset → high volatility
└── Variable     : FOMC, Fed speeches (Jackson Hole = annual)

QUARTERLY
├── Earnings season (Jan/Apr/Jul/Oct) : individual stock volatility
├── FOMC projections (dot plot)        : regime-changing
└── Quarterly OpEx (3rd Friday Mar/Jun/Sep/Dec) : "quad witching"
```

### Volatility Patterns by Day of Week

```
Monday    : Moderate — week positioning
Tuesday   : Often trending — follow Monday's direction
Wednesday : Choppy — mid-week indecision, FOMC risk
Thursday  : Often strong momentum (post-FOMC, claims data)
Friday    : Fade into close — risk reduction before weekend
```

---

## 4. Multi-Timeframe Cascade Strategy

The most powerful structural insight: **use higher timeframes for direction and targets, lower timeframes for precision entries and short-term profits within the larger move.**

### Timeframe Hierarchy

| Timeframe | Role | Horizon |
|---|---|---|
| Weekly (1W) | Macro structural trend | Context only |
| Daily (1D) | Swing trend direction | Medium-term target |
| 4H | Intermediate structure | Zone of interest |
| 1H | Swing entry timing | Swing entry point |
| 15min | Signal confirmation | Refinement |
| 5min | Scalp execution | Precise entry |
| 1min | Microstructure | Stop placement |

### Cascade Logic — Example

```
1D  → Bullish trend intact, above 200 EMA, bias: LONG
 └─► 4H  → Pullback to support zone / VWAP → opportunity
      └─► 1H  → RSI divergence forming → confirmation
           └─► 15min → OFI turning positive, EMA(8) crossing EMA(21)
                └─► 5min → Entry LONG
                     ├── Short-term target: 15min resistance → scalp profit
                     ├── Medium-term target: 4H resistance → swing profit  
                     └── Stop: below 5min structure (ATR-based)
```

### Dual-Profit Architecture

```
SAME POSITION, TWO PROFIT OBJECTIVES:

Partial exit 1 (30–40% of position) → short-term target (5min/15min)
  → Captures guaranteed scalp profit, reduces risk immediately

Partial exit 2 (remaining 60–70%) → medium-term target (4H/1D)  
  → Rides the larger move, maximizes position's full potential

Result: Profitable on both scalp AND swing timeframe simultaneously
```

---

## 5. Long/Short Dynamic Hedging

This is what separates hedge funds from retail: **the ability to be simultaneously long AND short, making money in both directions, reducing net risk.**

### Core Concept

```
SETUP: Strong 1D uptrend, but 15min extremely overbought

MAIN POSITION (Swing LONG, 100% size):
  Direction: Long
  Timeframe: 4H/1D
  Target: +5% over 2–3 days
  
HEDGE POSITION (Scalp SHORT, 30% size):
  Direction: Short
  Timeframe: 15min
  Target: +0.8% over 30 minutes
  Expiry: Closes when 15min signals reversal back up

OUTCOMES:
├── Market rises immediately: +5% (long) - 0.3% (hedge cost) = +4.7% net ✅
├── Market dips first:        -1.5% (long open) + 0.8% (hedge) = -0.7% net ✅
└── Without hedge:            -1.5% drawdown → psychological pressure → mistakes
```

### When to Hedge

| Signal | Hedge Trigger | Hedge Size |
|---|---|---|
| RSI divergence on lower TF | Counter-trend scalp | 20–35% of main |
| Bollinger Band extreme on 5min | Mean reversion short | 20–30% |
| GEX pinning level reached | Range hedge | 15–25% |
| Pre-FOMC / pre-NFP | Straddle (if options available) | 25–40% |
| Vol spike (VIX +15% in 1h) | Reduce main + add hedge | 30–50% |

### Pair Trading Extension (Phase 2)

```
Long: Strong sector leader (e.g., NVDA)
Short: Weak sector laggard (e.g., AMD)
Net: Market-neutral, pure relative performance capture
Mathematical basis: Cointegration (Engle-Granger test)
```

---

## 6. Regime-Adaptive Strategies

The system detects the current market regime in real-time and activates the appropriate strategy set. This adaptability is the core of its resilience.

| Detected Regime | Conditions | Active Strategies | Position Sizing |
|---|---|---|---|
| **TRENDING BULL** | VIX < 15, clear uptrend, DXY stable | MTF momentum long, VWAP pullback scalps, EMA crossovers | Standard ×1.0 |
| **TRENDING BEAR** | VIX 15–20, clear downtrend, DXY strong | MTF momentum short, bounce scalps, Bollinger upper mean-rev | Standard ×1.0 |
| **RANGING** | VIX 15–25, no clear trend, range defined | Bollinger mean reversion, RSI divergences, GEX pinning | Reduced ×0.8 |
| **HIGH VOLATILITY** | VIX 25–35, frequent breakouts | Spike scalping, dynamic hedging, stop-hunt plays | Reduced ×0.5 |
| **CRISIS / EVENT** | VIX > 35, FOMC/NFP/Earnings active | PAUSE new entries, surveillance only, post-event scalping | Minimal ×0.2 |
| **CRYPTO BULL** | Positive funding rate, BTC dominance rising | Long momentum altcoins, breakout structures | Standard ×1.0 |
| **LIQUIDATION CASCADE** | Negative funding rate, open interest dropping | Short momentum, cascade scalping | Concentrated ×1.5 |
| **CENTRAL BANK EVENT** | Scheduled announcement ±45min | Block entries, read post-announcement momentum | Post-event only |

---

## 7. Asset Universe & Dynamic Selection

### Phase 1 — Core Markets

**US Equities (NYSE / Nasdaq)**
- Average daily volume > 5M shares
- Bid-ask spread < 0.05% of price
- Daily volatility (ATR%) between 1.5% and 6%
- Primary universe: S&P 500 + Nasdaq 100
- Priority sectors: Technology, Energy (oil price sensitive), Finance

**Crypto (Binance)**
- BTC/USDT, ETH/USDT (Phase 1 core)
- Unique advantages: 24/7 market, measurable liquidation cascades, free L2 order book via WebSocket, structurally higher volatility
- Key indicators: Funding rate (sentiment), Open Interest, Liquidation heatmap

### Phase 2 — Expansion

| Asset | Ticker | Relevance | Broker |
|---|---|---|---|
| WTI Crude Oil | CL | Geopolitical (Iran/OPEC), energy sector driver | IBKR |
| Gold | GC | Safe haven, correlated with VIX and DXY | IBKR |
| S&P 500 Futures | ES | Equity market proxy, very liquid | IBKR |
| Nasdaq Futures | NQ | Tech proxy, high reactivity | IBKR |
| EUR/USD | FX | Correlated with DXY, European macro | IBKR/OANDA |

### Dynamic Opportunity Scoring

Every 5 minutes, the system computes an Opportunity Score for each eligible asset:

```
OpScore(asset) = w1×Volatility_rank 
               + w2×OFI_strength 
               + w3×Regime_alignment 
               + w4×Spread_quality 
               + w5×Volume_rank
               + w6×Session_prime_bonus
               + w7×MTF_alignment_score
```

Capital is allocated in priority to assets with the highest OpScores, within global risk limits.

---

## 8. Microservices Architecture

The system is decomposed into **10 independent services** communicating via ZeroMQ (real-time signals) and Redis (shared state). Each service has a single responsibility and can be started, stopped, tested, and replaced independently.

### Architectural Principles

- **Single Responsibility**: each service does one thing perfectly
- **Loose Coupling**: services communicate exclusively via the message bus
- **Fail-Safe by Design**: non-critical service failure does not stop trading
- **Full Observability**: every action is logged, timestamped, and traceable
- **Data Immutability**: every tick, signal, and order is immutable once created

### Communication Bus

| Tool | Role | Pattern | Use Case |
|---|---|---|---|
| **ZeroMQ** | Real-time transport | PUB/SUB + PUSH/PULL | Ticks, signals, orders |
| **Redis** | Shared state & cache | Key-Value + Pub/Sub + Streams | Positions, regime, scores |
| **TimescaleDB** | Historical persistence | Time-series SQL | Historical ticks, trades |
| **FastAPI + WS** | Monitoring interface | REST + WebSocket | Real-time dashboard |

### ZeroMQ Topic Convention

```
tick.{market}.{SYMBOL}          e.g. tick.crypto.BTCUSDT
signal.technical.{SYMBOL}       e.g. signal.technical.AAPL
signal.validated.{SYMBOL}
order.candidate
order.approved
order.blocked
order.filled
order.cancelled
risk.breach
regime.update
service.health.{service_id}
macro.catalyst.{event_type}     e.g. macro.catalyst.FOMC
session.pattern.{type}          e.g. session.pattern.US_OPEN
```

### Service Communication Flow

```
[Binance WS] ──tick──► 
[Alpaca WS]  ──tick──►  S01:DataIngestion ──ZMQ PUB "tick.*"──────────────────┐
[FRED API]   ──macro─►                                                         │
                                                                                │
                        ┌──────────────────────────────────────────────────────┘
                        │   ZMQ SUB "tick.*"
                        ▼
                  S02:SignalEngine ──── computes OFI, CVD, Kyle λ, RSI, BB, EMA, GEX
                        │ writes Redis: signal_strength, direction, mtf_alignment
                        │ ZMQ PUB "signal.technical.*"
                        ▼
                  S03:RegimeDetector ── reads macro data, session patterns, CB calendar
                        │ writes Redis: macro_regime, session_context, event_active
                        │ ZMQ PUB "regime.update" + "macro.catalyst.*"
                        ▼
                  S04:FusionEngine ──── combines micro + macro + MTF cascade logic
                        │ applies Kelly sizing, confluence bonus, hedge trigger detection
                        │ ZMQ PUB "order.candidate"
                        ▼
                  S05:RiskManager ◄──── reads Redis: positions, exposure, drawdown
                        │ APPROVES or BLOCKS ← VETO ABSOLUTE, cannot be bypassed
                        │ ZMQ PUB "order.approved" or "order.blocked"
                        ▼
                  S06:Execution ──────── paper or live (Alpaca / Binance / IBKR)
                        │ writes Redis: updated positions, P&L
                        │ ZMQ PUB "order.filled"
                        ▼
                  S10:Monitor ◄─────── subscribes to ALL topics, passive observer
                        real-time dashboard, alerts, PnL tracking

S07:QuantAnalytics ← reads tick history, computes Hurst, GARCH, Hawkes, HMM
S08:MacroIntelligence ← CB calendar, geopolitics, session patterns → feeds S03
S09:FeedbackLoop ← post-trade analysis, signal performance attribution
```

---

## 9. Service Specifications

### SERVICE 01 — Data Ingestion Layer

**Single Responsibility**: Ingest all raw data sources, normalize to a uniform format, publish on the bus.

**Data Sources:**

| Source | Type | Frequency | Data | Cost |
|---|---|---|---|---|
| Binance WebSocket | Stream | ~ms | Price, volume, side, L2 order book | Free |
| Alpaca WebSocket | Stream | ~ms | US equity price, volume, trades | Free |
| Binance REST | Polling | 1s | Order book snapshot, funding rate, OI | Free |
| FRED API | Polling | 15min | VIX, DXY, yield curve | Free |
| Yahoo Finance | Polling | 5min | Index prices, sector ETFs | Free |
| SEC EDGAR | Event | On publish | Filings, earnings dates | Free |
| Economic Calendar | Polling | 1h | FOMC, NFP, CPI, ECB dates | Free |

**Normalized Data Model:**
```python
NormalizedTick:
  symbol       : str           # "BTCUSDT", "AAPL"
  market       : str           # "crypto" | "us_equity" | "futures" | "forex"
  timestamp    : datetime      # UTC, millisecond precision
  price        : Decimal
  volume       : Decimal
  side         : str           # "buy" | "sell" | "unknown"
  bid          : Decimal
  ask          : Decimal
  spread_bps   : float         # spread in basis points
  session      : str           # "us_open" | "us_close" | "asian" | "london" | "after_hours"
```

**Design Patterns**: Adapter (Binance/Alpaca unified interface), Factory (feed instantiation), Circuit Breaker (WebSocket auto-reconnect with exponential backoff)

---

### SERVICE 02 — Quant Signal Engine

**Single Responsibility**: Compute all quantitative signals from ticks. The analytical core of the system.

**Module A — Microstructure Order Flow**
```
OFI_t       = ΔBid_vol_t - ΔAsk_vol_t
CVD_t       = Σ(buy_vol_i - sell_vol_i)  rolling 1h/4h/session
Kyle λ      = Cov(ΔP, signed_volume) / Var(signed_volume)  rolling 100 trades
Absorption  = large_order AND |ΔP| < threshold → absorption signal
Spread_evo  = ΔSpread/Spread_0  → rapid widening = danger
Trade_int   = nb_trades / second  → institutional activity detection
```

**Module B — Technical Indicators**
```
RSI(14)            : 1m, 5m, 15m — divergence detection (bullish/bearish)
Bollinger(20, 2σ)  : squeeze detection, close outside bands
EMA(8/21/55)       : crossovers in regime direction
VWAP (daily)       : institutional reference, reversion zones
ATR(14)            : local volatility, dynamic stop loss
Volume Profile      : intraday POC, VAH, VAL structural levels
```

**Module C — Crowd Behavior**
```
GEX_mapping         = Σ(Gamma_i × OI_i × 100) per strike  → price magnet levels
Stop_clusters       = statistical clustering of price levels → stop hunting zones
Liq_heatmap(crypto) = estimated mass liquidation price levels
Funding_rate        = directional sentiment perpetuals (positive = longs crowded)
MTF_alignment       = score [0→1] of signal alignment across timeframes
Session_bonus       = multiplier if signal occurs in prime session window
```

**Signal Output:**
```python
Signal:
  symbol       : str
  direction    : str          # "long" | "short" | "neutral"
  strength     : float        # [-1.0 → +1.0]
  timeframe    : str
  triggers     : List[str]    # which modules contributed
  entry_price  : Decimal
  stop_loss    : Decimal      # ATR-based
  take_profit  : List[Decimal] # [short_term_target, medium_term_target]
  confidence   : float        # [0 → 1]
  hedge_signal : bool         # whether a counter-position is recommended
  mtf_context  : dict         # higher timeframe alignment summary
```

---

### SERVICE 03 — Regime Detector

**Single Responsibility**: Determine the current market regime. Does NOT generate trading signals. Provides a contextual multiplier and session context to all other services.

**Inputs:**
- VIX: < 15 (low vol), 15–25 (normal), 25–35 (high), > 35 (crisis)
- DXY: rising strongly → risk-off
- Yield Curve (10Y–2Y): inversion = systemic stress signal
- Rolling 20-day inter-asset correlations: contagion detection
- Central bank calendar: FOMC, ECB, BOJ, BOE scheduled events
- Session clock: US open/close prime windows, overnight sessions

**Central Bank Protocol:**
```python
CentralBankEvent:
  institution   : str    # "FED" | "ECB" | "BOJ" | "BOE" | "SNB"
  event_type    : str    # "rate_decision" | "press_conf" | "minutes" | "speech"
  scheduled_at  : datetime
  impact_level  : str    # "critical" | "high" | "medium"
  block_window  : int    # minutes before event to block new trades (default: 45)
  monitor_window: int    # minutes after event to scalp momentum (default: 60)
```

**Regime Output:**
```python
Regime:
  trend_regime    : str    # "bull" | "bear" | "neutral"
  vol_regime      : str    # "low" | "normal" | "high" | "crisis"
  risk_mode       : str    # "risk_on" | "risk_off"
  event_active    : bool   # CB or macro event in block window
  session_context : str    # "us_prime" | "us_normal" | "crypto_asia" | "off_hours"
  macro_mult      : float  # [0.0 → 1.0] applied to all signal strengths
  session_mult    : float  # [0.5 → 1.5] boost for prime sessions
  cb_calendar     : List[CentralBankEvent]  # upcoming events
```

---

### SERVICE 04 — Fusion Engine & MTF Strategy

**Single Responsibility**: Combine micro signals + macro context + MTF cascade logic to produce structured candidate orders. Applies Kelly Criterion sizing and hedge trigger detection.

**Fusion Logic:**
```
final_score = signal.strength
            × macro_mult(regime)
            × confluence_bonus(nb_triggers)
            × session_mult(session_context)
            × mtf_alignment_score

confluence_bonus:
  3+ modules aligned → ×1.35
  2 modules aligned  → ×1.00
  1 module only      → ×0.50  (usually filtered)

mtf_alignment_score:
  1D + 4H + 1H aligned with signal → ×1.30
  4H + 1H aligned                  → ×1.10
  Only entry TF                    → ×0.80
```

**Kelly Criterion Sizing:**
```
f* = (p × b - q) / b
  p = estimated win rate (from rolling backtest)
  q = 1 - p
  b = average gain/loss ratio (Risk-Reward)

f_used = f* × 0.25   # Kelly/4: prudence against estimation uncertainty
position_size = capital × f_used × macro_mult × session_mult × (1/λ_kyle_normalized)
```

**Multi-Target Orders:**
```python
OrderCandidate:
  symbol           : str
  direction        : str         # "long" | "short"
  entry_price      : Decimal
  stop_loss        : Decimal     # ATR-based, mandatory
  target_scalp     : Decimal     # short-term target (15min/5min resistance)
  target_swing     : Decimal     # medium-term target (4H/1D level)
  size_total       : Decimal
  size_scalp_exit  : float       # fraction to close at target_scalp (0.30–0.40)
  size_swing_exit  : float       # fraction to hold for swing (0.60–0.70)
  hedge_recommended: bool
  hedge_direction  : str | None  # "long" | "short"
  hedge_size       : float       # fraction of main position
  score            : float
  rationale        : List[str]   # full traceability
```

---

### SERVICE 05 — Risk Manager (Critical Service)

**Single Responsibility**: Approve, modify, or block every candidate order. Continuously monitor global exposure. **This service cannot be bypassed under any circumstances.**

**Circuit Breaker — 3 States:**

```
CLOSED  → Normal trading, active monitoring
HALF_OPEN → Sizing reduced 50%, conditional triggers
OPEN    → No new orders, existing positions held until TP/SL

CLOSED → OPEN triggers:
  Daily drawdown > 3%
  Loss > 2% in 30 minutes
  VIX spike > 20% in 1 hour
  Data or Signal service down > 60 seconds
  Data anomaly detected (price gap > 5%)
  Active CB event in block window
```

**Risk Rules:**

| Parameter | Value | Justification |
|---|---|---|
| Max risk per trade | 0.5% of capital | Allows 200 consecutive losing trades before ruin |
| Stop loss | Mandatory (ATR-based) | No order without defined stop |
| Minimum Risk-Reward | 1 : 1.5 | Profitable above 40% win rate |
| Max size per position | 10% of capital | Prevents over-concentration |
| Max simultaneous positions | 5 | Limits global correlation |
| Max total exposure | 40% of capital | 60% remains in cash/reserve |
| Max inter-position correlation | 0.70 | Prevents duplicate positions |
| Max exposure per asset class | 25% of capital | Mandatory diversification |
| Crypto size multiplier | ×0.70 | Structurally higher volatility |
| Prime session size multiplier | ×1.10 | Increased edge during prime windows |

---

### SERVICE 06 — Execution Layer

**Single Responsibility**: Execute approved orders. Paper trading first (perfect simulation), then live trading via broker API after validation.

**Paper Trading Simulation:**
- Realistic slippage: `spread/2 + impact_cost(λ_kyle × size)`
- Latency simulation: 5–50ms random
- Liquidity rejection simulation: order cancelled if insufficient volume
- Transaction costs included in PnL calculation
- Multi-target exit simulation (scalp partial + swing partial)

**Live Brokers (Phase 2+):**

| Broker | Markets | Order Types | Notes |
|---|---|---|---|
| Alpaca | US Equities, ETFs | Market, Limit, Stop | Clean API, integrated paper trading |
| Binance | BTC, ETH, altcoins | Market, Limit, OCO | WebSocket execution, low fees |
| IBKR (Phase 3) | Equities, Options, Futures, Forex | All types | Full access, TWS API |

**Security:** Execution API key isolated (write-only, IP-whitelisted). Chrome extension NEVER used for order placement — direct API only.

---

### SERVICE 07 — Quant Analytics Engine

**Single Responsibility**: Advanced mathematical computations from academic research. Provides high-quality quantitative metrics to all other services.

**Market Statistics Module:**
```
Autocorrelation      : Ljung-Box test — residual predictability detection
Hurst Exponent       : H = log(R/S) / log(n)
                       H > 0.5 → trending, H < 0.5 → mean-reverting
GARCH(1,1)           : σ²_t = ω + α×ε²_(t-1) + β×σ²_(t-1)  [Bollerslev 1986]
RV vs IV             : Realized vol vs Implied vol ratio — compression signal
```

**Regime Detection Module (Phase 2):**
```
HMM (4 states)       : Hidden Markov Model on returns — regime change detection
PELT Algorithm       : Breakpoint detection — structural change identification
Engle-Granger        : Cointegration test — pair identification for stat arb
```

**Advanced Microstructure Module:**
```
Amihud Ratio         : ILLIQ_t = |r_t| / Volume_t  — alternative illiquidity measure
PIN Model            : Probability of Informed Trading [Easley-O'Hara 1987]
Hawkes Process       : λ(t) = μ + Σ α×exp(-β×(t-t_i))
                       Models order flow self-excitation (clustering)
```

**Performance Attribution:**
```
Sharpe (annualized), Sortino, Calmar ratios
Information Ratio per signal source
Maximum Drawdown + Duration
Factor Attribution: PnL decomposed by regime / asset / session / signal type
```

**Monte Carlo Risk Engine** *(CPU-bound — Rust core + Python orchestration)*:
```
VaR (Value at Risk)      : VaR_α = -quantile(returns, 1-α)
CVaR (Expected Shortfall): CVaR_α = -E[R | R < -VaR_α]   ← more robust than VaR
PnL Distribution         : Bootstrap 10,000–100,000 paths from historical trades
Drawdown Paths           : MC on equity curve → P5/P50/P95 of max drawdown
Kelly Optimisation       : Scan f ∈ [0.05, 0.50], select max growth with DD < 10%
Stress Testing           : Flash crash (-20%), vol spike (VIX ×2), liquidity gone,
                           CB surprise (±200bps) — applied to all open positions

Concurrency: ProcessPoolExecutor (true parallelism, bypasses Python GIL)
Inner loop:  Rust crate apex_mc (PyO3 bindings) → 50-100x faster than Python
Build:       maturin build --release → apex_mc.so importable from Python
```

---

### SERVICE 08 — Macro & Context Intelligence

**Single Responsibility**: Aggregate macro and context data. Compute the global macro score. Feed the macro_multiplier and cb_calendar to Service 03.

- VIX, DXY, 10Y yield, HY spread, inter-asset correlation monitoring
- Central bank calendar: automatic loading of FOMC, ECB, BOJ, BOE, BOE schedules
- Geopolitical event detection (energy price impacts: Iran, OPEC, Saudi Arabia)
- Sector rotation detection: energy, tech, financials relative performance
- Session transition alerts: Asian → London → US open triggers
- Economic surprise index: actual vs consensus for NFP, CPI, GDP

---

### SERVICE 09 — Feedback Loop & Learning

**Single Responsibility**: Learn from past trades. Detect system degradation.

- Performance by signal type, regime, session, hour of day, asset
- Win rate drift detection: alert if win rate drops >10% over 50 trades
- Signal quality evolution: which indicators contribute most to PnL
- Slippage analysis: paper vs live comparison
- Daily automated report generation

> **This service does NOT automatically adjust parameters. It informs. Humans validate all changes.**

---

### SERVICE 10 — Monitor, Dashboard & Alerts

**Single Responsibility**: Observe the entire system in real-time. Provide visual interface. Trigger alerts on anomalies.

- Subscribes to ALL ZeroMQ topics — passive observer, never interferes
- Real-time PnL: realized, unrealized, daily, cumulative
- FastAPI + WebSocket dashboard: accessible in local browser
- Rolling performance metrics: Sharpe, win rate, profit factor
- Service health status with latency (p50, p95, p99)
- Alerts: SMS/email on drawdown threshold, service down, data anomaly, CB event approaching

---

### SUPERVISOR — Watchdog & Orchestrator

**Startup Order (critical — strictly enforced):**
```
1.  Redis
2.  ZeroMQ bus
3.  S10 Monitor      ← observe the startup itself
4.  S01 Data
5.  S07 QuantAnalytics
6.  S08 MacroIntel
7.  S02 SignalEngine
8.  S03 RegimeDetector
9.  S04 FusionEngine
10. S05 RiskManager
11. S06 Execution     ← last, only when everything else is operational
12. S09 FeedbackLoop
```

**Health Checks:** Ping every 5s → no response ×3 → auto-restart → ×5 restarts in 10min → critical alert + suspend execution.

---

## 10. Mathematical & Quantitative Engine

The following equations are the mathematical backbone of the system. Every signal, sizing decision, and risk metric has a formal mathematical grounding.

### Core Equations

```
━━━ ORDER FLOW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OFI_t = ΔBid_vol_t - ΔAsk_vol_t
CVD_t = Σ(buy_vol_i - sell_vol_i)
Kyle λ = Cov(ΔP, Q) / Var(Q)      where Q = signed order flow

━━━ POSITION SIZING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

f* = (p×b - q) / b                 Kelly Criterion (Kelly, 1956)
f_used = f* × 0.25                 Quarter-Kelly (prudent)
size = capital × f_used × regime_mult × session_mult / λ_normalized

━━━ TECHNICAL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RSI = 100 - 100/(1 + RS)           where RS = avg_gain_n / avg_loss_n
BB_upper = SMA(n) + k×σ(n)
BB_lower = SMA(n) - k×σ(n)
EMA(n)_t = P_t × α + EMA(n)_(t-1) × (1-α)    where α = 2/(n+1)
VWAP_t = Σ(P_i × V_i) / Σ(V_i)
ATR = EMA(max(H-L, |H-C_p|, |L-C_p|), 14)

━━━ VOLATILITY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

σ²_t = ω + α×ε²_(t-1) + β×σ²_(t-1)        GARCH(1,1) — Bollerslev (1986)
H = log(R/S) / log(n)                       Hurst Exponent — Hurst (1951)
ILLIQ_t = |r_t| / Volume_t                  Amihud (2002)

━━━ OPTIONS / HEDGING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GEX = Σ(Γ_i × OI_i × contract_size)        per strike i
Hedge_size = main_size × hedge_ratio × (1 - MTF_alignment_score)

━━━ ORDER FLOW SELF-EXCITATION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

λ(t) = μ + Σ_i α×exp(-β×(t-t_i))          Hawkes Process — Hawkes (1971)

━━━ PERFORMANCE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sharpe = (R_p - R_f) / σ_p × √252
Sortino = (R_p - R_f) / σ_downside × √252
Calmar = Annual_return / Max_Drawdown
IR = (R_p - R_benchmark) / Tracking_Error
```

---

## 11. Design Patterns

| Pattern | Services | Benefit |
|---|---|---|
| **Chain of Responsibility** | Full pipeline Tick→Execution; Risk Manager sequential rules | Each service can enrich, modify, or stop the flow |
| **Observer / Pub-Sub** | All services via ZeroMQ | Total decoupling, service replaceable without impact |
| **Strategy Pattern** | Technical indicators; Broker connectors (Alpaca/Binance/IBKR) | Interchangeable algorithms without modifying calling code |
| **Factory Pattern** | Data Ingestion (feed creation); Execution (connector creation) | Configured instantiation, no coupling to concrete type |
| **Circuit Breaker** | Risk Manager; WebSocket reconnection | Fault isolation, graceful degradation |
| **Adapter Pattern** | Binance/Alpaca normalization → common format | Single interface regardless of source |
| **Decorator Pattern** | Progressive order enrichment | OrderCandidate → ApprovedOrder → ExecutedOrder |
| **Repository Pattern** | Historical data access (TimescaleDB) | Storage abstraction, testable with mocks |
| **Null Object Pattern** | Order blocked by Risk Manager | No exception, normal flow, traceable "null" order |
| **Supervisor Pattern** | Watchdog process | System resilience, automatic self-healing |

### Data Object Hierarchy — Full Traceability

```
RawTick
  └─► NormalizedTick          (S01 — with session context)
        └─► TechnicalFeatures  (S02 — OFI, CVD, λ, RSI, BB, EMA, GEX)
              └─► Signal        (S02 — with MTF alignment, hedge signal)
                    └─► OrderCandidate   (S04 — dual target, hedge size)
                          └─► ApprovedOrder    (S05 — risk-validated)
                                └─► ExecutedOrder    (S06 — with actual slippage)
                                      └─► TradeRecord  (S09 — full attribution)
```

Every executed trade can be traced back to its originating tick.

---

## 12. Technology Stack

### Language Architecture

| Language | Role | Services | Justification |
|---|---|---|---|
| **Python 3.11+** | Primary — orchestration, strategy, signal logic, async I/O | All 10 services | Ecosystem richness, development speed |
| **Rust** (via PyO3) | CPU-bound computation, inner loops, memory-safe numerics | `apex_mc`, `apex_risk` crates | 50-100× faster than Python on tight loops, zero GC pauses, no GIL |
| **Go** *(Phase 2, optional)* | Pure network layer if ingestion bottlenecks | S01 replacement | Native goroutines, no GIL, ~10× lower memory than Python |

> **Boundary rule**: Rust handles *only* stateless math functions. Python retains all business logic. Go (if used) speaks only ZeroMQ to the rest of the system.

### Python Libraries

| Layer | Component | Role |
|---|---|---|
| **Concurrency** | asyncio | Lightweight internal concurrency per service |
| **Messaging** | pyzmq | ZeroMQ — inter-service real-time transport |
| **State** | redis[asyncio] | Shared state, cache, pub/sub |
| **Validation** | pydantic v2 | Strict typing of all data models |
| **US Equities** | alpaca-trade-api | WebSocket + paper trading |
| **Crypto** | python-binance | WebSocket, order book, funding rate |
| **Indicators** | pandas-ta | RSI, Bollinger, EMA, ATR, VWAP |
| **Math/Stats** | numpy + scipy | Statistical computations, HMM, GARCH |
| **DataFrames** | polars | Ultra-fast DataFrame operations |
| **MC Parallelism** | concurrent.futures | ProcessPoolExecutor for Monte Carlo |
| **Time-series DB** | TimescaleDB | Historical persistence (Phase 2) |
| **API** | fastapi + uvicorn | Monitoring REST + WebSocket |
| **Logging** | structlog | Structured JSON logs, full traceability |
| **Testing** | pytest + pytest-asyncio | Unit + integration tests |
| **Property Tests** | hypothesis | Automatic edge case generation |
| **Secrets** | python-dotenv | API keys via .env |
| **Containers** | docker + compose | Isolation and reproducible deployment |

### Rust Crates

| Crate | Purpose | Phase |
|---|---|---|
| `apex_mc` | Monte Carlo: GBM simulation, VaR, CVaR, Kelly optimisation | Phase 8 |
| `apex_risk` | Greeks approximation, correlation matrix, exposure aggregation | Phase 6 ext. |

Built via `maturin build --release` → `.so` importable directly from Python.

---

## 13. Repository Structure

```
apex-trading/
│
├── core/                          # Shared foundations
│   ├── base_service.py            # Abstract base class for all services
│   ├── bus.py                     # ZeroMQ wrapper (PUB/SUB/PUSH/PULL)
│   ├── state.py                   # Redis wrapper (get/set/stream/pubsub)
│   ├── config.py                  # Centralized config from .env
│   ├── logger.py                  # Uniform structured logging
│   └── models/                    # Pydantic v2 shared models
│       ├── tick.py                # RawTick, NormalizedTick
│       ├── signal.py              # Signal, TechnicalFeatures, MTFContext
│       ├── order.py               # OrderCandidate, ApprovedOrder, ExecutedOrder, TradeRecord
│       └── regime.py              # Regime, MacroContext, CentralBankEvent, SessionContext
│
├── services/
│   ├── s01_data_ingestion/
│   │   ├── service.py             # Service entry point
│   │   ├── binance_feed.py        # Binance WebSocket (crypto)
│   │   ├── alpaca_feed.py         # Alpaca WebSocket (US equities)
│   │   ├── macro_feed.py          # FRED, Yahoo Finance, economic calendar
│   │   └── normalizer.py         # Unified output format + session tagging
│   │
│   ├── s02_signal_engine/
│   │   ├── service.py
│   │   ├── microstructure.py      # OFI, CVD, Kyle lambda, absorption, spread
│   │   ├── technical.py           # RSI, Bollinger, EMA, VWAP, ATR, Volume Profile
│   │   ├── crowd_behavior.py      # GEX mapping, stop clusters, liquidation heatmap
│   │   └── mtf_aligner.py        # Multi-timeframe alignment scoring
│   │
│   ├── s03_regime_detector/
│   │   ├── service.py
│   │   ├── regime_engine.py       # VIX, DXY, yield curve, correlations
│   │   ├── cb_calendar.py         # Central bank event tracking (FOMC, ECB, BOJ, BOE)
│   │   └── session_tracker.py    # US open/close, Asian, London session context
│   │
│   ├── s04_fusion_engine/
│   │   ├── service.py
│   │   ├── fusion.py              # Signal + macro + MTF confluence scoring
│   │   ├── strategy.py            # Regime-based strategy selection
│   │   ├── kelly_sizer.py         # Kelly Criterion fractional sizing
│   │   └── hedge_trigger.py      # Long/short hedge recommendation logic
│   │
│   ├── s05_risk_manager/
│   │   ├── service.py
│   │   ├── circuit_breaker.py     # CLOSED/HALF_OPEN/OPEN state machine
│   │   ├── position_rules.py      # Per-position risk validation
│   │   ├── exposure_monitor.py    # Global exposure, correlation limits
│   │   └── cb_event_guard.py     # Central bank event trade blocking
│   │
│   ├── s06_execution/
│   │   ├── service.py
│   │   ├── paper_trader.py        # Perfect simulation with slippage + latency
│   │   ├── order_manager.py       # Order lifecycle, timeout, retry
│   │   ├── broker_alpaca.py       # Alpaca connector (US equities)
│   │   └── broker_binance.py     # Binance connector (crypto)
│   │
│   ├── s07_quant_analytics/
│   │   ├── service.py
│   │   ├── market_stats.py        # Autocorr, Hurst, GARCH, RV/IV
│   │   ├── microstructure_adv.py  # Amihud, PIN, Hawkes process
│   │   ├── regime_ml.py           # HMM, PELT breakpoints (Phase 2)
│   │   └── performance.py         # Sharpe, Sortino, Calmar, factor attribution
│   │
│   ├── s08_macro_intelligence/
│   │   ├── service.py
│   │   ├── cb_watcher.py          # FOMC, ECB, BOJ, BOE live monitoring
│   │   ├── geopolitical.py        # Energy prices, Iran/OPEC, geopolitical news
│   │   ├── sector_rotation.py     # Sector relative performance
│   │   └── surprise_index.py     # Economic data vs consensus
│   │
│   ├── s09_feedback_loop/
│   │   ├── service.py
│   │   ├── trade_analyzer.py      # Post-trade performance attribution
│   │   ├── signal_quality.py      # Signal performance by type/regime/session
│   │   └── drift_detector.py     # Model degradation detection
│   │
│   └── s10_monitor/
│       ├── service.py
│       ├── pnl_tracker.py         # Real-time P&L calculation
│       ├── health_checker.py      # Per-service health + latency
│       ├── alert_engine.py        # SMS/email alerts
│       └── dashboard.py           # FastAPI + WebSocket real-time UI
│
├── supervisor/
│   ├── watchdog.py                # Per-service health monitoring + auto-restart
│   └── orchestrator.py           # Ordered startup, shutdown, dependency management
│
├── backtesting/
│   ├── engine.py                  # Event-driven backtest engine
│   ├── data_loader.py             # Historical tick/OHLCV data loading
│   ├── metrics.py                 # Sharpe, DD, WR, profit factor, by-regime breakdown
│   └── walk_forward.py           # Walk-forward validation (Lopez de Prado method)
│
├── tests/
│   ├── unit/                      # Per-service unit tests
│   │   ├── test_signal_engine.py
│   │   ├── test_risk_manager.py
│   │   ├── test_fusion_engine.py
│   │   └── test_kelly_sizer.py
│   └── integration/               # Full pipeline integration tests
│       ├── test_pipeline_paper.py
│       └── test_circuit_breaker.py
│
├── docker/
│   ├── docker-compose.yml         # Redis + TimescaleDB + all services
│   └── Dockerfile.service         # Common service image
│
├── scripts/
│   ├── download_history.py        # Download 2+ years of historical data
│   └── validate_setup.py          # Pre-flight check all connections and keys
│
├── rust/                          # Rust performance extensions (PyO3)
│   ├── Cargo.toml                 # Workspace root
│   ├── apex_mc/                   # Monte Carlo engine (Phase 8)
│   │   └── src/
│   │       ├── lib.rs             # PyO3 bindings
│   │       ├── simulation.rs      # GBM + jump diffusion inner loop
│   │       └── stats.rs           # VaR, CVaR, percentile computation
│   └── apex_risk/                 # Risk computation engine (Phase 6 ext.)
│       └── src/
│           ├── lib.rs             # PyO3 bindings
│           ├── greeks.rs          # Delta/Gamma approximation
│           ├── correlation.rs     # Correlation matrix (large portfolios)
│           └── exposure.rs        # Real-time exposure aggregation
│
├── .env.example                   # API key template (never commit real keys)
├── requirements.txt
├── MANIFEST.md                    # This file
└── README.md
```

---

## 14. Security & Capital Protection

| Risk Vector | Protection Measure |
|---|---|
| API key leakage | Environment variables only (.env), never in code or Git, .gitignore enforced |
| Unauthorized broker access | IP whitelisting mandatory, write-only API key for Execution service only |
| Compromised web session | Chrome extension NEVER used for real orders — direct API only |
| Risk Manager bug | Exhaustive unit tests, property-based testing, mandatory simulation before deployment |
| Service crash during open trade | Supervisor watchdog, positions logged in Redis with TTL, auto-close rule on recovery |
| Data anomaly (aberrant price) | Strict Pydantic validation, outlier detection (>5σ → tick rejected) |
| Accidental over-exposure | Double validation before order send: Risk Manager + Execution pre-flight check |
| Catastrophic loss | Absolute 3% daily circuit breaker — architecturally impossible to bypass |
| Central bank event surprise | Automatic trade blocking 45min before scheduled events |

---

## 15. Economics & Profitability

### Costs by Phase

| Source | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Binance API | Free | Free | Free |
| Alpaca API | Free | Free | Free |
| SEC EDGAR | Free | Free | Free |
| FRED API | Free | Free | Free |
| Yahoo Finance | Free | Free | Free |
| Polygon.io (enriched tick data) | — | $29–79/mo | $79/mo |
| IBKR (options + futures) | — | ~$10/mo | ~$10/mo |
| VPS 24/7 (optional) | — | $20/mo | $20/mo |
| **Total** | **~$0/mo** | **~$50–110/mo** | **~$110/mo** |

### Profitability Simulation

| Scenario | Win Rate | R/R | Trades/day | Monthly Return | On $3,000 |
|---|---|---|---|---|---|
| Conservative | 52% | 1:1.5 | 5 | 3–5% | $90–150 |
| Normal | 55% | 1:1.8 | 8 | 8–12% | $240–360 |
| Optimal | 58% | 1:2.0 | 12 | 15–20% | $450–600 |
| Break-even Phase 1 | 51% | 1:1.5 | 3 | ~1% | $30 (costs ≈ $0) |

> ⚠️ These projections are estimates based on backtesting assumptions. Past performance does not guarantee future results. Phase 1 must validate these assumptions before any real capital is engaged.

### Paper → Live Transition Criteria (ALL required simultaneously)

| Criterion | Required Threshold | Measurement Period |
|---|---|---|
| Paper trading profitability | Profitable | 3 consecutive months |
| Sharpe Ratio | > 1.5 | Over the 3 months |
| Maximum Drawdown | < 5% | Over the 3 months |
| Win Rate | > 52% stable | Over the 3 months |
| Backtest vs Paper coherence | < 20% deviation | Direct comparison |
| All services unit tested | 100% critical coverage | Before deployment |
| Circuit breaker validated | Tested and functional | In forced simulation |
| Engaged capital | Money you can afford to lose entirely | Risk acceptance |

---

## 16. Roadmap

| Phase | Duration | Objective | Key Deliverables |
|---|---|---|---|
| **P1 — Core Foundations** | Weeks 1–2 | core/ layer, Pydantic models, ZeroMQ bus, Redis, Supervisor | base_service.py, all models/, bus.py, state.py, watchdog.py |
| **P1 — Data Layer** | Weeks 3–4 | S01 Binance WebSocket + S10 Monitor minimal. Prove bus works. | Live Binance ticks visible in real-time |
| **P1 — Signal Engine** | Weeks 5–6 | S02 Signal Engine: OFI, CVD, Kyle λ, RSI, Bollinger, EMA, GEX | Signals published on bus |
| **P1 — Regime & Macro** | Weeks 7–8 | S03 Regime Detector with CB calendar + session tracker | Regime context flowing through system |
| **P1 — Execution** | Weeks 9–10 | S05 Risk Manager + S06 Paper Execution + Circuit Breaker | Simulated trades, PnL calculated |
| **P1 — Validation** | Weeks 11–14 | Backtesting 2yr historical, S07 Analytics, parameter optimization | Performance report: Sharpe, DD, WR, by-session |
| **P2 — US Equities** | Months 4–5 | S01 Alpaca feed + S04 Fusion MTF logic + S08 Macro Intel | Multi-asset, MTF cascade operational |
| **P2 — Advanced Micro** | Months 5–6 | L2 microstructure, absorption detection, hedge trigger | Long/short hedging operational |
| **P2 — ML Regime** | Months 6–8 | HMM regime detection, Hawkes process, signal ensemble | Signal quality +15–20% |
| **P3 — Live Trading** | Month 9+ | Paper → live (only if all criteria met), IBKR options + futures | Real capital engaged |

---

## 17. Out of Scope — Phase 1

| Excluded Component | Reason | Target Phase |
|---|---|---|
| ML ensemble (XGBoost) | Overfitting risk without 6+ months of real data | Phase 2 |
| Twitter/X NLP API | $100/month cost, macro = light filter only | Phase 3 if profitable |
| SEC PDF filing reader | Relevant for swing, not scalping | Phase 3 |
| Options trading (IBKR) | Additional capital + Greeks complexity | Phase 2–3 |
| Commodity futures | IBKR infrastructure not yet configured | Phase 2 |
| Embedded LLM (Ollama) | Not a priority for short-term alpha generation | Phase 3 |
| Co-location / HFT | Inadequate infrastructure, unnecessary for scalping | Out of scope |
| Rough Volatility (fBm) | High mathematical complexity, too early for Phase 1 | Phase 2–3 |

---

## 18. Academic References

| Author(s) | Year | Title | Used For |
|---|---|---|---|
| Kyle, A. | 1985 | Continuous auctions and insider trading. *Econometrica* | Kyle's Lambda, market impact |
| Almgren, R. & Chriss, N. | 2000 | Optimal execution of portfolio transactions. *Journal of Risk* | Execution cost minimization |
| Cont, R., Kukanov, A. & Stoikov, S. | 2014 | The price impact of order book events. *Journal of Financial Econometrics* | OFI signal |
| Jegadeesh, N. & Titman, S. | 1993 | Returns to buying winners and selling losers. *Journal of Finance* | Momentum strategy |
| Kelly, J. | 1956 | A new interpretation of information rate. *Bell System Technical Journal* | Position sizing |
| Bollerslev, T. | 1986 | Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics* | GARCH volatility model |
| Hawkes, A. | 1971 | Spectra of some self-exciting and mutually exciting point processes. *Biometrika* | Order flow clustering |
| Lopez de Prado, M. | 2018 | *Advances in Financial Machine Learning*. Wiley | Feature engineering, backtesting methodology |
| Gatheral, J., Jaisson, T. & Rosenbaum, M. | 2018 | Volatility is rough. *Quantitative Finance* | Volatility regime modeling |
| Shefrin, H. & Statman, M. | 1985 | The disposition to sell winners too early. *Journal of Finance* | Crowd behavior patterns |
| Easley, D. & O'Hara, M. | 1987 | Price, trade size, and information in securities markets. *Journal of Financial Economics* | PIN model |
| Amihud, Y. | 2002 | Illiquidity and stock returns. *Journal of Financial Markets* | Amihud illiquidity ratio |
| Hurst, H.E. | 1951 | Long-term storage capacity of reservoirs. *Transactions of the American Society of Civil Engineers* | Hurst Exponent |
| Engle, R. & Granger, C. | 1987 | Co-integration and error correction. *Econometrica* | Pair trading cointegration |

---

*APEX Trading System — Confidential — Internal use only — v1.1*