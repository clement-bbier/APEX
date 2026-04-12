# APEX Architecture Overview

## High-level diagram

```
                    ┌─────────────────────────────────────────────────┐
                    │              Market Data Sources                │
                    │  Binance  Alpaca  Yahoo  FRED  ECB  BoJ  SEC   │
                    └─────────────────────┬───────────────────────────┘
                                          │
                    ┌─────────────────────▼───────────────────────────┐
                    │         S01 Data Ingestion                      │
                    │  connectors → normalizers → quality → serving   │
                    └─────────────────────┬───────────────────────────┘
                                          │ ZMQ XSUB/XPUB (tick.*)
                    ┌─────────────────────▼───────────────────────────┐
                    │         S02 Signal Engine                       │
                    │  SignalPipeline → indicators → scorer → signal  │
                    ├─────────────────────────────────────────────────┤
                    │  S03 Regime Detector   S08 Macro Intelligence   │
                    │  (vol/trend regime)    (FOMC/ECB/BoJ events)    │
                    └─────────────────────┬───────────────────────────┘
                                          │ ZMQ (signal.*, regime.*)
                    ┌─────────────────────▼───────────────────────────┐
                    │         S04 Fusion Engine                       │
                    │  strategy selection → sizing → order candidate  │
                    └─────────────────────┬───────────────────────────┘
                                          │ ZMQ (order.candidate)
                    ┌─────────────────────▼───────────────────────────┐
                    │         S05 Risk Manager (VETO)                 │
                    │  circuit breaker ← position rules ← Kelly      │
                    └─────────────────────┬───────────────────────────┘
                                          │ ZMQ (order.approved)
                    ┌─────────────────────▼───────────────────────────┐
                    │         S06 Execution                           │
                    │  BrokerFactory → Alpaca / Binance / PaperTrader │
                    └─────────────────────┬───────────────────────────┘
                                          │ ZMQ (order.filled)
                    ┌─────────────────────▼───────────────────────────┐
                    │  S07 Quant Analytics    S09 Feedback Loop       │
                    │  (PSR/DSR/PBO/CPCV)    (drift, signal quality)  │
                    ├─────────────────────────────────────────────────┤
                    │         S10 Monitor                             │
                    │  command API (FastAPI) + alerts + dashboard     │
                    └─────────────────────────────────────────────────┘

    Cross-cutting: core/ (models, config, base_service, math)
                   Redis (state)  |  TimescaleDB (time-series)
                   Rust extensions: apex_mc, apex_risk
```

## Services

| Service | Responsibility |
|---|---|
| **S01** Data Ingestion | Multi-source market data ingestion, normalization, quality checks |
| **S02** Signal Engine | Tick-to-signal pipeline (OFI, VPIN, Bollinger, EMA, RSI, VWAP) |
| **S03** Regime Detector | Market regime classification (trending/ranging x high/low vol) |
| **S04** Fusion Engine | Strategy selection based on regime affinity, order candidate sizing |
| **S05** Risk Manager | Circuit breakers, position rules, Kelly sizing, exposure monitoring. **VETO -- cannot be bypassed** |
| **S06** Execution | Broker-agnostic order execution via Broker ABC (Alpaca, Binance, PaperTrader) |
| **S07** Quant Analytics | Institutional metrics: PSR, DSR, PBO, CPCV, Sharpe, bootstrap CIs |
| **S08** Macro Intelligence | Central bank events (FOMC, ECB, BoJ), macro surprise indices |
| **S09** Feedback Loop | Drift detection, signal quality tracking, Kelly parameter updates |
| **S10** Monitor | Command API (FastAPI), alerting (email/Twilio), read-only dashboard |

## Core layer (cross-cutting)

| Module | Purpose |
|---|---|
| `core/models/` | Immutable Pydantic v2 data models: Tick, Bar, Signal, Order, Regime |
| `core/config.py` | Settings with SecretStr for credentials, TradingMode enum |
| `core/base_service.py` | BaseService ABC: ZMQ pub/sub, Redis state, heartbeat, lifecycle |
| `core/bus.py` | ZMQ broker abstraction (XSUB/XPUB proxy) |
| `core/state.py` | Redis wrapper (StateStore) with `.client` property |
| `core/math/` | Fractional differentiation, labeling utilities |
| `core/topics.py` | Canonical ZMQ topic strings (never hardcode topics) |

## Infrastructure

| Component | Technology | Purpose |
|---|---|---|
| Messaging | ZeroMQ XSUB/XPUB | Inter-service communication (see ADR-0001) |
| State | Redis | Ephemeral state, position tracking, VPIN cache |
| Time-series DB | TimescaleDB | Historical bars, ticks, features (see ADR-0003) |
| Rust extensions | PyO3/Maturin | `apex_mc` (Monte Carlo), `apex_risk` (risk math) |

## Key constraints

- **No cross-service imports**: services communicate only via ZMQ and Redis
- **core/ never imports services/**: Dependency Inversion Principle
- **S01 internal layering**: connectors -> orchestrator -> normalizers (DI via factory)
- **Decimal for all financial values**: prices, sizes, PnL, fees, commissions
- **UTC datetimes only**: `datetime.now(timezone.utc)`, never naive
- **Immutable data pipeline**: Tick -> Signal -> OrderCandidate -> ApprovedOrder -> ExecutedOrder
- **S05 is a VETO**: Risk Manager cannot be bypassed under any circumstance

## Data flow example: tick to executed order

1. **S01** receives a BTC trade from Binance WebSocket
2. **S01** normalizes it into a `NormalizedTick` and publishes on `tick.crypto.BTCUSDT`
3. **S02** receives the tick, runs it through `SignalPipeline`:
   - Updates microstructure (OFI, CVD, Kyle lambda)
   - Updates technical indicators (RSI, Bollinger, EMA, VWAP)
   - Computes VPIN toxicity (gates on extreme levels)
   - Scores 5 components via `SignalScorer` (confluence required)
   - If confluence: builds `Signal` with ATR-based price levels
4. **S02** publishes `Signal` on `signal.technical.BTCUSDT`
5. **S03** publishes current `Regime` (e.g. LOW_VOL + TRENDING)
6. **S04** receives Signal + Regime, selects strategy, sizes position, creates `OrderCandidate`
7. **S04** publishes on `order.candidate`
8. **S05** validates: circuit breaker OK, position rules OK, Kelly sizing OK -> `ApprovedOrder`
9. **S05** publishes on `order.approved`
10. **S06** receives, routes via `BrokerFactory` -> `BinanceBroker.place_order()`
11. Fill confirmed -> `ExecutedOrder` published on `order.filled`, position stored in Redis

## Deeper dives

- **ADR-0001**: ZMQ broker topology
- **ADR-0002**: Quant methodology charter
- **ADR-0003**: Universal data schema
- **ADR-0004**: Feature validation methodology
- **MANIFEST.md**: Full service contracts and data model specifications
- **docs/phases/PHASE_3_SPEC.md**: Phase 3 detailed specification
