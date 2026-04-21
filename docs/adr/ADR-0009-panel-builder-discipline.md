# ADR-0009 — Panel Builder Discipline

> *This ADR is authored as part of Document 3 — [Phase 5 v3 Multi-Strat Aligned Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (§10.3). It formalizes Charter §5.3 (Q3) — the panel-builder microservice and the strategy-subscribes-to-panels discipline.*
>
> **POST-MERGE ACTION**: on Roadmap v3.0 ratification, this file is moved from `docs/adr_pending_roadmap_v3/` to `docs/adr/` by the CIO (see Roadmap §16.1 note on path protection).

| Field | Value |
|---|---|
| Status | Accepted (on Roadmap v3.0 merge) |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Related | Charter §5.3; ADR-0001 (ZMQ broker); ADR-0003 (universal data schema); ADR-0007 (strategy microservice); ADR-0006 (fail-closed risk) |

---

## 1. Context

The APEX platform hosts strategies with heterogeneous data needs:

- Strategy #1 (Crypto Momentum) — cross-sectional basket across top-20 Binance USDT-quoted pairs.
- Strategy #2 (Trend Following) — multi-asset daily: BTC, ETH, SPY, GLD spanning Binance + Alpaca venues.
- Strategy #3 (Mean Rev Equities) — S&P 500 top-100 by liquidity, 5min–1h intraday.
- Strategy #4 (VRP) — VIX + VIX term-structure + SPY RV from Yahoo + FRED + Alpaca.
- Strategy #5 (Macro Carry) — G10 FX daily + central bank rates.
- Strategy #6 (News-driven) — equities + crypto with GDELT/FinBERT overlay.

Without a shared panel-building layer, each strategy would re-invent multi-asset snapshot logic — tick buffering, point-in-time synchronization, cross-sectional feature computation — with the same bugs, the same warm-up code, the same per-venue edge cases.

The **Multi-Strat Readiness Audit** ([`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q3, Q6) confirms:

- The `features/` layer is multi-strategy-ready (FeatureCalculator ABC, pure functions, point-in-time FeatureStore) — ✅ ready.
- The S02 Signal Engine's analyzer state is **per-symbol only**: `self._micro: dict[str, MicrostructureAnalyzer]` at `service.py:56-67`. **Cross-sectional computation spanning multiple symbols does not exist** — no aggregator between raw ticks and the feature pipeline.
- Q3: "Strategy #1 crypto top-20 momentum requires a new cross-symbol aggregator that does not exist today."

The Charter §5.3 (Q3 decision) resolves this via a **new microservice** `services/data/panels/` that aggregates raw tick/bar streams into coherent multi-asset snapshots per universe, published to strategies on `panel.{universe_id}` topics.

The discipline is **uniform**: every strategy consumes panels, **including** strategies that in principle could operate on a single asset. This trades a small amount of ceremony for architectural uniformity and compounds across the 6-strategy portfolio.

This ADR formalizes the panel builder, the `PanelSnapshot` schema, the subscribe/publish contract, staleness tolerance, and the fail-closed behavior when panels go stale.

---

## 2. Decision

### D1 — `services/data/panels/` microservice aggregates raw streams into panels

The panel builder is implemented as a standalone microservice:

- **Path**: `services/data/panels/` (target topology per Charter §5.4 and ADR-0010).
- **Inheritance**: `PanelBuilderService(BaseService)`.
- **Startup order** (Charter §5.9): position 5 (after Redis, ZMQ broker, monitor dashboard, data ingestion; before signal services).
- **Resource budget** (typical): 1 CPU, 2 GB memory — aggregation is lightweight; the service is I/O bound on tick consumption.

**Module structure**:

```
services/data/panels/
├── __init__.py
├── service.py                  # PanelBuilderService(BaseService)
├── universe.py                 # Universe registry
├── snapshot.py                 # PanelSnapshot Pydantic model
├── aggregator.py               # Per-universe tick/bar → snapshot reducer
├── staleness.py                # Staleness tolerance + is_stale semantics
├── cross_sectional.py          # Cross-sectional features (rank, dispersion, corr)
├── config.yaml                 # Universe registry, tolerance, cadences
└── tests/
    ├── unit/
    │   ├── test_snapshot_schema.py
    │   ├── test_universe_registry.py
    │   ├── test_aggregator.py
    │   ├── test_staleness.py
    │   └── test_cross_sectional.py
    └── integration/
        └── test_panel_publishing_e2e.py
```

### D2 — `PanelSnapshot` Pydantic model (authoritative schema)

```python
# services/data/panels/snapshot.py
from __future__ import annotations
from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssetSnapshot(BaseModel):
    """Single asset's point-in-time snapshot within a panel."""
    model_config = ConfigDict(frozen=True)
    symbol: str
    timestamp_ms: int = Field(..., gt=0, description="Asset's last observation ms epoch UTC")
    last_price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume_24h: Decimal | None = None
    features: dict[str, Decimal] = Field(default_factory=dict,
        description="Per-asset features computed by features/ layer")


class PanelSnapshot(BaseModel):
    """Multi-asset point-in-time panel consumed by StrategyRunner.on_panel().

    Every strategy subscribes to a universe's panel.{universe_id} topic.
    Published atomically; assets[] is a coherent cross-sectional state at
    snapshot_ts_utc.
    """
    model_config = ConfigDict(frozen=True)
    universe_id: str  # e.g., "crypto_top20", "multi_asset_trend", "sp500_liquid"
    snapshot_ts_utc: datetime
    panel_seq: int = Field(..., ge=0,
        description="Monotonic per-universe sequence; strategies detect gaps")
    assets: list[AssetSnapshot]
    cross_sectional_metadata: dict = Field(default_factory=dict,
        description="Cross-sectional features (rank, dispersion, corr) per cross_sectional.py")
    is_stale: bool = False
    stale_reason: str | None = None
```

**Invariants**:

- `ConfigDict(frozen=True)` per CLAUDE.md §2.
- `timestamp_ms` per asset is the last observation time at or before `snapshot_ts_utc`.
- `panel_seq` is strictly monotonic per universe; strategies can detect dropped panels by gap in sequence.
- `is_stale = True` if any asset exceeds its universe-configured `max_tick_lag_seconds`; `stale_reason` names the offending asset(s).
- All Decimal fields per CLAUDE.md §10 (no float for prices).
- All datetimes are UTC-aware per CLAUDE.md §10.

### D3 — Subscribe/publish contract

**Subscribes** (per universe configuration):

- `tick.crypto.*` — Binance WS tick stream (Charter §5.7 topics).
- `tick.us_equity.*` — Alpaca WS tick stream.
- `tick.futures.*` — placeholder for future use.

**Publishes**:

- `panel.{universe_id}` — on every snapshot emit for that universe.

**Topic factory** addition to [`core/topics.py`](../../core/topics.py):

```python
@staticmethod
def panel(universe_id: str) -> str:
    """Per-universe panel topic.

    Example: Topics.panel('crypto_top20') == 'panel.crypto_top20'
    """
    return f"panel.{universe_id}"
```

**Consumers**: strategy microservices subscribe to exactly one (or more) `panel.{universe_id}` topic matching their declared universe.

### D4 — Universe registry

Universes are configured in `services/data/panels/config.yaml`:

```yaml
universes:
  crypto_top20:
    members:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT
      - XRPUSDT
      - ADAUSDT
      # ... top 20 by market cap, refreshed monthly
    source_topics:
      - "tick.crypto.*"
    snapshot_cadence_ms: 1000        # 1-second snapshots
    max_tick_lag_seconds:
      default: 10
      # per-symbol overrides allowed

  multi_asset_trend:
    members:
      - BTCUSDT
      - ETHUSDT
      - SPY
      - GLD
    source_topics:
      - "tick.crypto.*"
      - "tick.us_equity.*"
    snapshot_cadence_ms: 86400000    # Daily snapshots
    max_tick_lag_seconds:
      BTCUSDT: 10
      ETHUSDT: 10
      SPY: 3600           # Tolerance for closed-market hours
      GLD: 3600

  sp500_liquid:
    members: [AAPL, MSFT, ...]  # top 100 by ADV
    source_topics:
      - "tick.us_equity.*"
    snapshot_cadence_ms: 60000       # 1-minute snapshots for intraday strategy
    max_tick_lag_seconds:
      default: 30
    operating_session: "US_REGULAR"   # Panels only emitted during US session
```

**Universe membership updates** (e.g., top-20 crypto refreshed monthly) are config changes merged via PR with CIO ratification. No dynamic membership logic in D1.

### D5 — Point-in-time correctness

**Algorithm** (in `aggregator.py`):

1. For each universe, buffer incoming ticks per symbol with their `timestamp_ms`.
2. On snapshot emit at `snapshot_ts_utc = T`, for each universe member symbol:
   - Select the asset's last tick with `timestamp_ms <= T` (within `max_tick_lag_seconds` tolerance).
   - Construct `AssetSnapshot(symbol, timestamp_ms, last_price, ...)`.
3. Compute cross-sectional features (rank, dispersion, Herfindahl concentration, cross-asset correlation window) on the snapshot itself.
4. Emit `PanelSnapshot(universe_id, snapshot_ts_utc=T, panel_seq=++seq, assets=[...], cross_sectional_metadata=...)`.
5. Ticks arriving after T (with `timestamp_ms > T`) are buffered for the next snapshot; they do **not** retroactively modify the emitted panel.

**Invariant**: there is no look-ahead. A cross-sectional signal at time T never uses a tick with `timestamp_ms > T`. This is the subtle bias the panel pattern eliminates by construction (Charter §5.3 Two Sigma standard pattern reference).

### D6 — Staleness tolerance and fail-closed behavior

Each universe member has a `max_tick_lag_seconds` threshold. On snapshot emit:

- For every asset in the universe, compute `tick_lag_seconds = (T - asset.last_tick_ts_ms) / 1000`.
- If any asset exceeds its threshold:
  - `is_stale = True`.
  - `stale_reason = "assets <SYMBOL[, SYMBOL, ...]> exceed max_tick_lag"`.
  - The panel is **still published** — consumers (strategies) decide whether to act on it. This is an important distinction from fail-closed risk controls (ADR-0006): the panel builder is a data provider, not a safety gate; it provides the data and tags staleness; the safety decision belongs to the strategy and the VETO chain.

**Strategy contract** (enforced in ADR-0007 `StrategyRunner` via contract test):

- Strategies **MUST** check `panel.is_stale` in `on_panel(panel)` and return `None` (no signal) when stale.
- Strategies that generate signals on stale panels are violating the `StrategyRunner` contract; a contract-test fixture fires a stale panel and asserts the strategy returns None.

**No-data case**: if an asset has never emitted a tick (cold start, or permanent data-source failure), the panel is emitted with `is_stale = True` and that asset's `last_price = Decimal("0")` as sentinel. Strategies continue to no-op on stale panels.

**Full-universe outage**: if every asset in a universe exceeds staleness, the panel is still emitted (flagged stale) so downstream consumers observe the staleness. The panel builder does not self-halt on stale universe; it reports the state accurately. Higher-layer controls (Charter §5.8 fail-closed state, Charter §8 hard CBs) handle systemic outages.

### D7 — Feature computation discipline

The panel builder computes:

- **Per-asset features** in the `AssetSnapshot.features` dict — by invoking `features/calculators/*` modules on the buffered tick history for each asset (e.g., OFI over last 5min; HAR-RV on daily history for `multi_asset_trend`).
- **Cross-sectional features** in `PanelSnapshot.cross_sectional_metadata` — rank, dispersion, cross-asset correlation matrix — by operating on the cross-section at T.

**Reuse of `features/` layer** (no duplication): every feature computed by the panel builder is implemented in `features/calculators/` per ADR-0004 and consumed via `FeatureCalculator` ABC (MULTI_STRAT_READINESS_AUDIT_2026-04-18.md Q3 confirms the feature layer is multi-strategy-ready today). The panel builder does not reimplement features; it invokes the existing calculators on the buffered data.

**Warm-up**: each calculator's warm-up requirement is respected per `FeatureCalculator.required_columns()` and `FeatureCalculator.compute()` semantics. A panel is not marked ready until all universe members have sufficient history for their configured features.

### D8 — Alternative: strategies subscribe to raw ticks (REJECTED)

The Charter §5.3 explicitly considered and rejected the alternative where each strategy subscribes to raw tick streams and builds its own panels locally:

- **Pros**: simpler (no panel builder container); lower latency for single-asset strategies (tick → strategy directly).
- **Cons**:
  - Cross-sectional strategies (Strategy #1 top-20 momentum, Strategy #3 S&P 500 mean-rev basket) would each reimplement snapshot logic; bug surface multiplied by N strategies.
  - Point-in-time correctness enforcement distributed to strategy implementations; high risk of silent look-ahead bias in one strategy.
  - Per-strategy warm-up of shared feature computations duplicates work.
  - Charter §5.3 Two Sigma pattern reference points at centralized panel builders.

**Rejected** per Charter §5.3 (Q3). +1 container is accepted for architectural cleanliness.

### D9 — Transitional behavior during Phase B-D overlap

During the window between Phase B (StrategyRunner ABC lands) and Phase D (panel builder goes live), strategies consume raw ticks via the `on_tick(NormalizedTick)` transitional entry point on the `StrategyRunner` ABC (ADR-0007 D3). Post-Phase-D, the transition is:

1. Strategy microservice begins subscribing to `panel.{universe_id}` alongside `tick.*`.
2. Strategy's primary entry point shifts from `on_tick` to `on_panel`.
3. `on_tick` becomes a no-op (implemented to preserve the ABC contract, but produces no signals).
4. Subscribing to `tick.*` is eventually dropped to reduce bus noise.

The transition is **per-strategy** — each strategy migrates to panels as part of its Gate 2 PR (Roadmap §6.3 for Strategy #1, etc.). `LegacyConfluenceStrategy` continues to operate on `on_tick` indefinitely until it is decommissioned (ADR-0007 D4).

---

## 3. Consequences

### 3.1 Positive

- **DRY across strategies**: one panel builder, six+ consumers. Feature warm-up cost amortized.
- **Point-in-time correctness by construction**: no strategy can accidentally introduce cross-sectional look-ahead bias.
- **Observable**: panels are structured events on the bus; any strategy's input can be inspected independently.
- **Two Sigma pattern match**: Charter §5.3 institutional precedent.
- **Cross-sectional features free**: rank, dispersion, correlation matrix computed once per panel; strategies consume without reimplementation.
- **Universe membership is a config change**: adding a symbol to a universe is a PR to `config.yaml`, not a code change in N strategies.

### 3.2 Negative

- **Additional latency**: tick → panel builder aggregation → publish → strategy consumer. Target: < 50ms p99 added latency for 1-second cadence panels. Acceptable at mid-frequency cadence (Charter §1.4 "not HFT"); might be a blocker for strategies requiring sub-10ms tick-to-signal. None of the six boot strategies require sub-10ms.
- **Additional container**: one more service to orchestrate.
- **Staleness false positives**: too-tight `max_tick_lag_seconds` during normal venue hiccups (brief WebSocket disconnects) would cause no-signal periods. Mitigated by starting with generous tolerances and tuning down based on 30 days of live data.

### 3.3 Mitigations

- **Latency**: benchmark `panel publish → strategy on_panel < 50ms p99` before Phase D merge; profile and optimize if exceeded.
- **Container operational cost**: standard APEX Docker Compose pattern; no added ops burden.
- **Staleness tuning**: config.yaml tolerances are non-material changes per Roadmap §15.3; can be adjusted via PR without ADR.

---

## 4. Alternatives Considered

### 4.1 Per-strategy tick subscription (no panel builder)

Covered in D8; rejected per Charter §5.3.

### 4.2 Shared in-process panel library (no dedicated service)

**Description**: a Python package `panels/` imported by each strategy microservice; each strategy constructs its own panels from the imported library.

**Pros**: no extra container; amortized bug-fix path via library updates.

**Cons**:

- Each strategy still runs its own aggregation in-process, duplicating CPU cost N times.
- Point-in-time correctness semantics distributed across N containers; harder to reason about globally.
- Dashboard cannot inspect a "panel" independently of a strategy.

**Rejected**.

### 4.3 TimescaleDB continuous aggregates

**Description**: use TimescaleDB continuous aggregates to produce per-universe panels as materialized views.

**Pros**: leverages existing TimescaleDB infrastructure (MULTI_STRAT_READINESS_AUDIT_2026-04-18.md §1 — `services/data_ingestion/serving/`).

**Cons**:

- Continuous aggregates are batch, not streaming; refresh cadence is typically 1-second minimum but actual refresh lag is higher in practice.
- Cross-sectional features requiring joins across asset series are complex to express in SQL.
- Adds Postgres as a critical path between ticks and strategies, creating an additional failure point.

**Rejected** for Phase 1. Might be revisited as a backfill/reconciliation backstop for historical panels.

---

## 5. Implementation Sketch

### 5.1 Phase D tasks (Roadmap §5.2.1)

1. Scaffold `services/data/panels/` with `PanelBuilderService(BaseService)`.
2. Implement `snapshot.py` (Pydantic models per D2).
3. Implement `universe.py` (registry + config.yaml schema).
4. Implement `aggregator.py` (per-universe point-in-time reducer per D5).
5. Implement `staleness.py` (per-asset tolerance + is_stale marking per D6).
6. Implement `cross_sectional.py` (rank/dispersion/correlation on snapshot).
7. Add `Topics.panel(universe_id)` factory to `core/topics.py`.
8. Initial universes configured: `crypto_top20` (Strategy #1), `multi_asset_trend` (Strategy #2).
9. Write property tests + regression tests + staleness tests.
10. Deploy as Docker container per Charter §5.9 startup order position 5.
11. Strategies migrate to `on_panel` consumption per their Gate 2 schedule.
12. Author this ADR.

### 5.2 Phase D+ — additional universes per later strategies

Each subsequent boot strategy adds its universe to `config.yaml`:

- Strategy #3 (Mean Rev Equities) → `sp500_liquid` universe (1-minute cadence, US session only).
- Strategy #4 (VRP) → `vix_complex` universe (daily cadence; VIX + VIX3M + VIX6M + SPY).
- Strategy #5 (Macro Carry) → `g10_fx` universe (daily cadence; 10 FX pairs + VIX composite risk indicator).
- Strategy #6 (News-driven) → reuses `crypto_top20` and `sp500_liquid`; GDELT/FinBERT overlay arrives via separate topic (`macro.geopolitics.score`).

---

## 6. Compliance Verification

### 6.1 CI-enforced invariants

- **PanelSnapshot schema frozen**: Pydantic `ConfigDict(frozen=True)`; mutation raises at runtime.
- **panel_seq monotonic per universe**: property test verifies no duplicates, no regressions in a fuzz-tested 10k-panel sequence.
- **Point-in-time correctness**: regression test with a fixed tick fixture + known emit schedule; asserts no asset's `timestamp_ms > snapshot_ts_utc`.
- **Staleness flagging**: a test injects a tick with `timestamp_ms = snapshot_ts_utc - (max_tick_lag + 1)` seconds; asserts `is_stale = True` and `stale_reason` names the asset.
- **Strategy no-op on stale panels**: `tests/unit/strategies/test__base_contract.py` provides a fixture strategy subclass and asserts `on_panel(stale_panel)` returns None.

### 6.2 Manual verification checklist

- [ ] `services/data/panels/` container in supervisor startup order position 5 (Charter §5.9).
- [ ] At least one universe (`crypto_top20`) publishing real panel messages observable on the ZMQ bus.
- [ ] Staleness alerts visible in `services/ops/monitor_dashboard/`.
- [ ] Strategy Gate 2 PRs migrate from `on_tick` to `on_panel` consumption.

---

## 7. References

### 7.1 Academic / industry

- Two Sigma — multi-asset panel-based research framework (publicly discussed in industry press).
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. [Point-in-time correctness, feature anti-leakage]

### 7.2 Charter and Playbook

- Charter §5.3 (Q3 panel builder decision); §5.4 (target topology).
- Charter §5.5 (per-strategy identity; extensibility to panel subscriptions).
- Playbook §5.2.2 (paper-trading strategy consumes panels).

### 7.3 Roadmap

- Roadmap v3.0 §5.2.1 (Phase D PanelBuilder scope).
- Roadmap §6.4 (Strategy #1 Gate 3 paper transitions to panel-native consumption).
- Roadmap §7.2.3 (Strategy #2 Gate 3 requires `multi_asset_trend` panel).

### 7.4 Internal code references

- [`core/topics.py`](../../core/topics.py) — topic factories; extended with `Topics.panel(universe_id)`.
- [`core/models/tick.py`](../../core/models/tick.py) — `NormalizedTick` schema (ADR-0003 Universal Data Schema); source for panel buffering.
- [`features/base.py`](../../features/base.py), [`features/pipeline.py`](../../features/pipeline.py) — `FeatureCalculator` / `FeaturePipeline` consumed by aggregator.
- [`services/data_ingestion/`](../../services/data_ingestion/) — upstream tick producer; post Phase D.5 at `services/data/ingestion/`.

---

**END OF ADR-0009.**
