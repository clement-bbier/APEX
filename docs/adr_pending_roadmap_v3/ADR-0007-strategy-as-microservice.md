# ADR-0007 — Strategy as Microservice

> *This ADR is authored as part of Document 3 — [Phase 5 v3 Multi-Strat Aligned Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (§10.1). It formalizes Charter §5.1 (Q1) — "each strategy is a complete, isolated microservice under `services/strategies/<strategy_name>/`".*
>
> **POST-MERGE ACTION**: on Roadmap v3.0 ratification, this file is moved from `docs/adr_pending_roadmap_v3/` to `docs/adr/` by the CIO (see Roadmap §16.1 note on path protection).

| Field | Value |
|---|---|
| Status | Accepted (on Roadmap v3.0 merge) |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Related | Charter §5.1, §5.6, §5.9; ADR-0001 (ZMQ broker); ADR-0008 (allocator); ADR-0009 (panels); ADR-0010 (topology) |

---

## 1. Context

The APEX platform is transitioning from a single-strategy architecture (Phase 1-4, Phase 5.1 through Phase 5.10 per PHASE_5_SPEC_v2) to a multi-strategy platform per the Charter ratified on 2026-04-18.

The **Multi-Strat Readiness Audit** ([`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md)) identified the current signal pipeline as the dominant architectural blocker to multi-strategy deployment:

- [`services/s02_signal_engine/pipeline.py`](../../services/s02_signal_engine/pipeline.py) (487 LOC) implements a single-path 5-component confluence pipeline with a 290-LOC hardcoded `_run()` method. No ABC for signal generators exists; no registry.
- [`services/s04_fusion_engine/strategy.py`](../../services/s04_fusion_engine/strategy.py) (124 LOC) defines a `STRATEGY_REGISTRY` of 4 hardcoded regime-keyed strategies (momentum_scalp, mean_reversion, spike_scalp, short_momentum) — these are **regime profiles**, not independent strategies producing independent bets.
- Two Claude Code agents developing Strategy A and Strategy B in parallel would git-conflict on `services/s02_signal_engine/pipeline.py`, `services/s02_signal_engine/signal_scorer.py`, and `services/s04_fusion_engine/strategy.py` simultaneously.

The Charter (§5.1) resolves this via Q1 — strategies are **complete microservices**, not plug-ins. This is the Citadel/Millennium pod-model reference: each pod is isolated at the operating-system level (separate container, separate process, dedicated resources), not a module inside a shared monolith.

A candidate alternative — the plug-in-in-single-process pattern — was evaluated during the Charter interview (Charter §5.1 decision rationale) and rejected on the basis of Principle 7 (senior-quant tie-breaker) and Principle 2 (institutional standards). The +20% operational maintenance cost of the microservice-per-strategy approach is accepted in exchange for crash isolation, parallel development, and independent deploy.

This ADR formalizes the microservice pattern and the `StrategyRunner` ABC that every strategy inherits.

---

## 2. Decision

### D1 — Each strategy is a complete microservice

Every strategy deployed on APEX is a standalone microservice with:

- Its own Docker container (separate `Dockerfile` or `docker-compose` service definition).
- Its own Python process (no shared memory with other strategies).
- Its own resource budget (CPU, memory limits enforced by Docker; `ulimit`s where applicable).
- Its own location under `services/strategies/<strategy_id>/`.
- Its own configuration file at `config/strategies/<strategy_id>.yaml` loaded at startup.
- Its own test tree under `services/strategies/<strategy_id>/tests/`.
- Its own README and per-strategy Charter at `docs/strategy/per_strategy/<strategy_id>.md`.

The **`strategy_id`** is a snake_case identifier matching the folder name (Charter §5.5, Playbook §2.2). Examples: `crypto_momentum`, `trend_following`, `mean_rev_equities`, `volatility_risk_premium`, `macro_carry`, `news_driven`.

Legacy single-strategy behavior is preserved by a **`LegacyConfluenceStrategy`** (D4) that wraps the current `services/s02_signal_engine/pipeline.py` unchanged. The legacy path continues under `strategy_id = "default"` during the multi-strat transition; once Strategy #1 reaches Gate 4 Live Full, the legacy path is decommissioned per the standard decommissioning protocol (Playbook §10).

### D2 — `StrategyRunner` ABC location

The `StrategyRunner` Abstract Base Class lives at **`services/strategies/_base.py`** (Option B of Roadmap §3.2.1), not in the `features/` tree.

**Rationale**:

- Strategies are runtime services, not library functions. The `features/` tree owns pure computation contracts (`FeatureCalculator`, `FeatureStore`, `FeatureValidator`) that are consumed by both backtests and live services; strategies are the consumers of those features, and their contract belongs where they execute.
- Co-location of the ABC with its concrete implementations (`services/strategies/crypto_momentum/signal_generator.py`, etc.) follows SOLID-D (depend on abstractions where they are used).
- The `_base.py` prefix (leading underscore) signals "internal to the `services/strategies/` tree; do not import from outside" — consistent with Python package conventions for internal modules.

**Alternatives considered**:

- **`features/strategies/base.py`** — symmetric with existing `features/base.py:19` `FeatureCalculator` ABC; pros: aligned pattern; cons: couples `features/` (research/backtest) with `services/strategies/` (runtime) in a way that would complicate any future decoupling. Rejected.
- **`core/strategies/base.py`** — `core/` currently holds runtime-adjacent contracts (models, topics, state); adding an ABC there would expand `core/`'s scope beyond its current role. Rejected.

### D3 — `StrategyRunner` ABC contract

The minimal contract every strategy must honor:

```python
# services/strategies/_base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

from core.models.signal import Signal
from core.models.tick import NormalizedTick


class StrategyHealthState(str):
    """Strategy operational state (Playbook §8.0 canonical enumeration)."""
    HEALTHY = "healthy"
    DD_KELLY_ADJUSTED = "dd_kelly_adjusted"
    PAUSED_24H = "paused_24h"
    PAUSED_OPERATIONAL = "paused_operational"
    REVIEW_MODE = "review_mode"
    DECOMMISSIONED = "decommissioned"


class StrategyRunner(ABC):
    """Abstract base class for every strategy on the APEX platform.

    Contract:
    - strategy_id: str — unique identifier; matches the folder name
      services/strategies/<strategy_id>/ and config file
      config/strategies/<strategy_id>.yaml.
    - on_panel / on_tick: market-data entry points per Charter §5.3.
    - health: strategy reports its current operational state to STEP 3
      StrategyHealthCheck of the VETO chain (Charter §8.2, Playbook §8.0).
    """

    strategy_id: str

    @abstractmethod
    def on_panel(self, panel) -> Optional[Signal]:
        """Consume a PanelSnapshot and optionally emit a Signal.

        Panel-driven entry point per Charter §5.3. Panels are published by
        services/data/panels/ on topic panel.{universe_id}. The PanelSnapshot
        type is defined in services/data/panels/snapshot.py (ADR-0009).

        Returns None when no signal is generated. Never raises on normal
        operation; exceptional conditions (stale data, malformed panel) log
        via structlog and return None per CLAUDE.md §10 exception handling.
        """
        raise NotImplementedError

    @abstractmethod
    def on_tick(self, tick: NormalizedTick) -> None:
        """Consume a raw NormalizedTick (transitional legacy-compat path).

        Legacy strategies subscribed to Topics.tick(...) call this on every
        tick. Post-Phase-D (Roadmap §5), panel-native strategies may implement
        this as a no-op and rely exclusively on on_panel.

        Returns None; signal emission happens via on_panel or via direct
        self.publish(signal) in advanced subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def health(self) -> StrategyHealthState:
        """Return the strategy's current operational state.

        Consumed by STEP 3 StrategyHealthCheck of the VETO chain
        (Charter §8.2). Implementations SHOULD read from the authoritative
        state (Redis key strategy_health:<strategy_id>:state) rather than
        from in-process cache, so state-machine semantics remain coherent
        across container restarts.
        """
        raise NotImplementedError
```

**Design discipline** enforced by the ABC:

- **Minimal surface**: only the three abstract methods every strategy must implement. Extensions (per-strategy Kelly sizing, stops, takes) live in subclass code or in the strategy's `config.yaml`.
- **Pure logic**: the ABC does not mandate a specific storage mechanism, event-loop pattern, or sizing algorithm. Subclasses compose those concerns freely under CLAUDE.md discipline.
- **Principle 4 enforcement**: the ABC **cannot** be bypassed. A concrete class that does not implement all three abstract methods raises `TypeError` on instantiation. There is no "duck-typed strategy" path.

### D4 — `LegacyConfluenceStrategy` — preserve current behavior

The current `services/s02_signal_engine/pipeline.py` behavior is preserved **unchanged** by wrapping it as a concrete `StrategyRunner` subclass named `LegacyConfluenceStrategy`, located at `services/strategies/legacy_confluence/`.

**Folder structure**:

```
services/strategies/legacy_confluence/
├── __init__.py
├── service.py               # LegacyConfluenceService(BaseService)
├── strategy.py              # LegacyConfluenceStrategy(StrategyRunner)
├── config.yaml              # Current S02 confluence parameters
├── README.md                # Operator note; explicitly marks transitional status
└── tests/
    └── test_legacy_confluence.py  # Bit-identical regression vs pre-Phase-B baseline
```

**Principle 6 assertion**: the `LegacyConfluenceStrategy` produces bit-identical `Signal`s and `OrderCandidate`s to the pre-Phase-B `services/s02_signal_engine/pipeline.py` on a fixed fixture tick stream (the 30-day BTCUSDT 1-min fixture at [`tests/fixtures/30d_btcusdt_1m.parquet`](../../tests/fixtures/30d_btcusdt_1m.parquet)). The scope-guard test blocks any Phase B PR that would alter this behavior.

**Decommissioning plan**: `LegacyConfluenceStrategy` is a **transitional artifact**. Once Strategy #1 (Crypto Momentum) reaches Gate 4 Live Full (Roadmap §6.5), the legacy strategy is decommissioned per Playbook §10 (standard decommissioning protocol). The physical folder remains in git history; its Docker container is halted; its Redis state keys are archived.

**Not subject to the four-gate lifecycle**: `LegacyConfluenceStrategy` is not retrospectively evaluated against Playbook §3–§6 gates. It is a Principle-6 continuity artifact, not a validated strategy candidate.

### D5 — Docker + supervisor orchestration

Each strategy microservice has its own Docker entry:

```yaml
# docker-compose.yml (excerpt — post-Phase-B)
services:
  strategy-crypto-momentum:
    build:
      context: .
      dockerfile: services/strategies/crypto_momentum/Dockerfile
    depends_on:
      - redis
      - zmq-broker
      - data-panels
      - portfolio-strategy-allocator
      - portfolio-risk-manager
    environment:
      APEX_STRATEGY_ID: crypto_momentum
      APEX_CONFIG_PATH: /app/config/strategies/crypto_momentum.yaml
    resources:
      limits:
        cpus: "1.0"
        memory: "2G"
```

**Startup order** (Charter §5.9):

1. Redis
2. ZMQ broker (XSUB/XPUB)
3. `services/ops/monitor_dashboard/`
4. `services/data/ingestion/`
5. `services/data/panels/`
6. `services/data/macro_intelligence/`
7. `services/signal/quant_analytics/`
8. `services/signal/regime_detector/`
9. `services/signal/engine/` (legacy confluence wrapped strategy if still active)
10. `services/signal/fusion/`
11. `services/portfolio/strategy_allocator/`
12. `services/portfolio/risk_manager/`
13. `services/execution/engine/`
14. `services/research/feedback_loop/`
15+. `services/strategies/<strategy_id>/` — each strategy deploys as its Gate 4 completes

The supervisor (`supervisor/orchestrator.py`) manages the startup order. Strategies that fail to start do not block other strategies; the supervisor logs and continues.

### D6 — `strategy_id` first-class field

Per Charter §5.5 and Roadmap Phase A §2.2.1, every Pydantic model crossing a service boundary on the order path carries a `strategy_id: str = "default"` field:

- `Signal` (published on `Topics.signal_for(strategy_id, symbol)` per Charter §5.5)
- `OrderCandidate` (published on `order.candidate` — strategies publish with their own `strategy_id`)
- `ApprovedOrder` (from Risk Manager, carrying through)
- `ExecutedOrder` (from Execution)
- `TradeRecord` (persisted per-strategy)

**Default value `"default"`** preserves backward compatibility with the legacy single-strategy codebase during Phase A-B transition. The `LegacyConfluenceStrategy` subclass tags its output with `strategy_id="default"` explicitly.

### D7 — Per-strategy topic factories

The `Topics.signal_for(strategy_id, symbol)` factory (Roadmap Phase A §2.2.2) produces:

```
Topics.signal_for("crypto_momentum", "BTCUSDT")
    == "signal.technical.crypto_momentum.BTCUSDT"
Topics.signal_for("default", "BTCUSDT")
    == "signal.technical.default.BTCUSDT"
```

The legacy `Topics.signal(symbol)` factory continues to exist for backward compatibility during the Phase A-B transition; after the LegacyConfluenceStrategy migrates to `Topics.signal_for("default", symbol)`, the legacy factory is used only by tests.

Consumers subscribe on the prefix `signal.technical.` and route by the `strategy_id` component. The Fusion Engine (`services/signal/fusion/`) subscribes per-strategy post-Phase-B, operating one per-strategy fusion instance per active strategy.

### D8 — Per-strategy Redis partitioning

Per-strategy Redis keys (Charter §5.5):

- `kelly:<strategy_id>:<symbol>` — per-strategy Kelly win_rate, avg_rr.
- `trades:<strategy_id>:all` — per-strategy trade list.
- `pnl:<strategy_id>:daily` — per-strategy daily PnL.
- `pnl:<strategy_id>:24h` — per-strategy 24h PnL (for soft CB triggers, Charter §8.1.1).
- `meta_label:latest:<strategy_id>:<symbol>` — per-strategy meta-labeler cards.
- `strategy_health:<strategy_id>:state` — per-strategy health state (Playbook §8.0).
- `portfolio:allocation:<strategy_id>` — allocator-assigned weight (written by `services/portfolio/strategy_allocator/`, read by STEP 6 `PerStrategyExposureGuard`).

Global keys (unchanged):

- `portfolio:capital`
- `risk:heartbeat`
- `risk:circuit_breaker:state`
- `correlation:matrix`
- `regime:current`
- `session:current`

### D9 — Independent deployment and failure isolation

Each strategy container can be independently:

- **Deployed**: `docker-compose up -d services/strategies/<strategy_id>` without disrupting other strategies.
- **Restarted**: container restart does not affect other strategies' running positions.
- **Rolled back**: a buggy deploy can be reverted by re-deploying the previous image; other strategies continue unaffected.
- **Resource-limited**: noisy strategies cannot starve quiet strategies.

**Crash isolation**: an unhandled Python exception in Strategy #3 halts only Strategy #3's container. Other strategies continue. The supervisor detects the dead container via heartbeat missing > 60s and triggers the Playbook §8.5 pod-crash protocol (strategy enters `PAUSED_OPERATIONAL` state; STEP 3 rejects subsequent candidates).

---

## 3. Consequences

### 3.1 Positive

- **Crash isolation** at OS level per Citadel/Millennium pod model (Charter §5.1 rationale).
- **Parallel development**: two Claude Code agents can work on Strategy A and Strategy B without git conflicts on shared source files. The current `services/s02_signal_engine/pipeline.py` hot spot is resolved by the LegacyConfluenceStrategy wrap.
- **Independent deployment and rollback** per strategy.
- **SOLID-S and SOLID-O**: each strategy is a single-responsibility unit; new strategies extend the platform without modifying existing code.
- **Principle-6 compliant**: the LegacyConfluenceStrategy wraps current behavior; nothing functional is deleted.
- **Observable per strategy**: per-strategy dashboard panels, per-strategy drift monitoring, per-strategy PnL — all mechanically enabled by the `strategy_id` plumbing.

### 3.2 Negative

- **+20% operational maintenance**: N strategies ≈ N containers + startup coordination + per-container log aggregation. The Charter explicitly accepts this cost (Charter §5.1 accepted cost note).
- **Feature warm-up duplication**: each strategy pays its own feature-warmup cost (deferred to Phase C/D observation — if warm-up becomes a bottleneck, a shared `services/signal/feature_cache/` can be introduced without amending this ADR).
- **Config duplication**: config sharing across strategies (e.g., common Binance API credentials) is handled via environment variables rather than shared YAML — small amount of config management overhead.

### 3.3 Mitigations

- **Operational overhead**: supervisor + Docker Compose handles container orchestration; no manual per-strategy ops. Per-strategy dashboard panels surface issues uniformly.
- **Warm-up cost**: bounded by the per-strategy container resource limit; a strategy with slow warm-up pays its own cost without affecting others.
- **Config duplication**: environment-variable injection from `.env` + per-strategy `config.yaml` is the standard pattern; no duplication of credentials.

---

## 4. Alternatives Considered

### 4.1 Plug-in-in-single-process

**Description**: strategies are Python classes loaded into a single `services/signal/engine/` process, sharing memory and compute.

**Pros**: simpler deployment (1 container, not N); shared warm-up cost amortized.

**Cons**:

- No crash isolation. A bug in Strategy X halts all strategies.
- Parallel development git-conflicts on the strategies' registration point.
- SRP violated: the shared engine has N+1 responsibilities (infrastructure + N strategies).
- Citadel/Millennium pod-model precedent strongly favors separate processes (Charter Principle 7).

**Rejected** per Charter §5.1 decision (Q1). +20% operational cost accepted as the tradeoff for pod-model benefits.

### 4.2 Full serverless / FaaS per strategy

**Description**: each strategy runs on-demand in a serverless platform (AWS Lambda, Google Cloud Functions) per signal event.

**Pros**: zero idle cost; automatic scaling.

**Cons**:

- Cold-start latency incompatible with sub-second strategy cadence.
- Stateful strategies (rolling features, open positions) require external state; negates the "serverless" simplicity.
- Cost unpredictable at scale.
- Outside the operator's personal-infrastructure comfort zone (Principle 3 — acknowledged constraints favor a single-host pattern).

**Rejected**. The platform is a single-host Docker Compose estate (Charter §5.9, Principle 3).

### 4.3 Kubernetes per strategy

**Description**: each strategy is a Kubernetes Deployment, with Service + HPA for autoscaling.

**Pros**: industrial-grade orchestration; declarative deployments.

**Cons**:

- Operator has no Kubernetes expertise.
- 10+ microservices + 6 strategies on Kubernetes is enterprise-scale overkill for a solo operator.
- Docker Compose already provides 95% of the orchestration value at < 10% of the operational overhead.

**Rejected** at Charter time per Principle 3 and Principle 7 (senior-quant-at-AQR would use the simpler tool). Phase 7.5 may revisit if live-trading scale demands.

---

## 5. Implementation Sketch

### 5.1 Phase B tasks (Roadmap §3)

1. Create `services/strategies/_base.py` with the `StrategyRunner` ABC (D3).
2. Create `services/strategies/legacy_confluence/` folder with `LegacyConfluenceStrategy` (D4) wrapping the current `services/s02_signal_engine/pipeline.py`.
3. Migrate `LegacyConfluenceStrategy` publishing from `Topics.signal(symbol)` to `Topics.signal_for("default", symbol)` per D7.
4. Add per-strategy Redis partitioning for `kelly:default:*` and `trades:default:all` (the legacy strategy is the first to exercise the per-strategy key pattern).
5. Update `supervisor/orchestrator.py` startup order per D5.
6. Update `docker-compose.yml` with the new strategy container.

### 5.2 Phase B+ tasks (Roadmap §6–§8)

Per strategy Gate 2 (Roadmap §6.3, §7.2.2, etc.):

1. Create `services/strategies/<strategy_id>/` folder with `signal_generator.py` inheriting `StrategyRunner`.
2. Populate `config/strategies/<strategy_id>.yaml`.
3. Write unit + integration tests; smoke test passes.
4. Deploy as additional Docker container.
5. Register with `services/portfolio/strategy_allocator/` (allocator includes the new strategy in the next weekly rebalance).

---

## 6. Compliance Verification

### 6.1 CI-enforced invariants

- **Strategy isolation test**: `tests/integration/test_strategy_isolation.py` verifies that inducing a `RuntimeError` in one strategy microservice does not affect other strategies.
- **ABC contract test**: `tests/unit/strategies/test__base_contract.py` parametrizes across all concrete `StrategyRunner` subclasses; asserts each implements `on_panel`, `on_tick`, `health` and carries a non-empty `strategy_id`.
- **LegacyConfluenceStrategy bit-identical**: `tests/regression/test_legacy_confluence_bit_identical.py` runs the fixture tick stream through both pre-Phase-B `SignalPipeline` and post-Phase-B `LegacyConfluenceStrategy`; asserts bit-identical output on `Signal` and `OrderCandidate` produced.

### 6.2 Manual verification checklist

- [ ] Every Gate 2 PR for a new strategy creates its `services/strategies/<strategy_id>/` folder in the target topology.
- [ ] Every Gate 2 PR references ADR-0007 in the PR body.
- [ ] Every strategy's `signal_generator.py` inherits `StrategyRunner`.
- [ ] `config/strategies/<strategy_id>.yaml` exists and is Pydantic-validated at startup.

---

## 7. References

### 7.1 Charter and Playbook

- APEX Multi-Strat Charter v1.0 §5.1, §5.5, §5.6, §5.9 — [`docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md`](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md).
- Playbook v1.0 §8.0 (StrategyHealthCheck state machine); §4.2.3 (production microservice file structure).

### 7.2 Roadmap

- Roadmap v3.0 §3 (Phase B deliverables scheduling).
- Roadmap §6.3, §7.2.2 (Strategy #1 and #2 Gate 2 microservice build).

### 7.3 Industry / academic

- Citadel Multi-Strategy pod model (publicly discussed in industry press).
- Millennium Management per-pod risk budgets and isolation discipline.
- Fowler, M. (2015). "Microservices — a definition of this new architectural term."
- Nygard, M. (2007). *Release It! Design and Deploy Production-Ready Software*. Pragmatic Bookshelf. Isolation and bulkhead patterns.

### 7.4 Internal code references

- [`services/s02_signal_engine/pipeline.py`](../../services/s02_signal_engine/pipeline.py) — current legacy single-path pipeline (487 LOC), wrapped as `LegacyConfluenceStrategy` per D4.
- [`services/s04_fusion_engine/strategy.py`](../../services/s04_fusion_engine/strategy.py) — current `STRATEGY_REGISTRY` of regime-keyed profiles (124 LOC).
- [`core/base_service.py`](../../core/base_service.py) — `BaseService` that every strategy microservice inherits from.
- [`core/topics.py`](../../core/topics.py) — `Topics` factory; extended with `signal_for` per Roadmap Phase A §2.2.2.
- [`core/models/order.py`](../../core/models/order.py), [`core/models/signal.py`](../../core/models/signal.py) — Pydantic models gaining `strategy_id` in Phase A §2.2.1.
- [`features/base.py`](../../features/base.py) — `FeatureCalculator` ABC (reference pattern for the `StrategyRunner` ABC).

---

**END OF ADR-0007.**
