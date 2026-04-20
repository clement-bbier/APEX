# ADR-0008 — Capital Allocator Topology

> *This ADR is authored as part of Document 3 — [Phase 5 v3 Multi-Strat Aligned Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (§10.2). It formalizes Charter §5.2 (Q2) and §6 — the dedicated capital-allocator microservice and the two-phase allocation framework (Risk Parity → Sharpe overlay).*
>
> **POST-MERGE ACTION**: on Roadmap v3.0 ratification, this file is moved from `docs/adr_pending_roadmap_v3/` to `docs/adr/` by the CIO (see Roadmap §16.1 note on path protection).

| Field | Value |
|---|---|
| Status | Accepted (on Roadmap v3.0 merge) |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Related | Charter §5.2, §6; ADR-0007 (strategy microservice); ADR-0009 (panels); ADR-0006 (fail-closed risk) |

---

## 1. Context

The APEX platform will host up to 6 boot strategies (Charter §4) with the potential to add more per Charter §11 extensibility. Each strategy produces `OrderCandidate` messages independently; the platform must size those candidates into a coherent portfolio position respecting per-strategy risk budgets (Charter §9.1) and portfolio-level constraints (Charter §10.3 correlation target, Charter §8 hard circuit breakers).

The **Multi-Strat Readiness Audit** ([`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q2) records **zero grep hits** for `StrategyAllocator`, `PortfolioAllocator`, `RiskParity`, or `BlackLitterman` across the entire codebase. This is a net-new service on the critical path; the Charter requires it to exist before Strategy #2 deploys live.

The Charter §5.2 (Q2 decision) ratifies a **dedicated microservice** approach over absorbing the allocator into the Fusion Engine (S04). The decision is driven by:

- **Single Responsibility** (Principle 4, SOLID-S): capital allocation is distinct from signal fusion and from risk VETO.
- **Swappable algorithm**: the Charter Phase 1 uses Risk Parity; Phase 2 adds Sharpe overlay; Phase 6+ may introduce Black-Litterman or regime-conditional variants. Keeping the allocator isolated means the algorithm can evolve without touching surrounding services.
- **Institutional precedent**: every multi-strategy firm referenced in Charter §1.3 runs a centralized capital allocator distinct from signal generation and risk veto.
- **Observability**: a dedicated service emits its own logs, metrics, and decisions to the dashboard.

This ADR formalizes the allocator topology, the Risk Parity Phase 1 formulas, the Sharpe overlay Phase 2 trigger conditions, the cold-start ramp, and the integration with the 7-step VETO chain via STEP 6 `PerStrategyExposureGuard`.

---

## 2. Decision

### D1 — Allocator is a dedicated microservice at `services/portfolio/strategy_allocator/`

The allocator is implemented as a standalone microservice:

- **Path**: `services/portfolio/strategy_allocator/` (target topology per Charter §5.4 and ADR-0010).
- **Inheritance**: `AllocatorService(BaseService)` — standard APEX service contract (CLAUDE.md §8 checklist).
- **Not absorbed into S04 Fusion Engine**: S04 handles per-strategy signal fusion (meta-labeler + IC-weighted combination within a single strategy's signal set); the allocator handles capital allocation across strategies. Two distinct concerns, two distinct services.
- **Not absorbed into S05 Risk Manager**: the Risk Manager is the VETO layer (approves or rejects); the allocator is an **assignment** layer (tells each strategy how much capital it has). Risk Manager vetoes happen downstream of allocator decisions via STEP 6 `PerStrategyExposureGuard`.

**Architectural position**:

```
[Strategy Microservices]       per-strategy order.candidate (strategy_id tagged)
         │
         ▼
[services/signal/fusion/]       per-strategy fused OrderCandidate
         │
         ▼
[services/portfolio/strategy_allocator/]    ← reads per-strategy 60d σ,
         │                                     writes portfolio:allocation:<id>
         ▼
    portfolio.allocation.updated event
         │
         ▼
[services/portfolio/risk_manager/]          ← STEP 6 PerStrategyExposureGuard
         │                                     reads portfolio:allocation:<id>
         ▼
      order.approved / order.blocked
         │
         ▼
[services/execution/engine/]
```

The allocator does **not** sit in the hot path of every order candidate — it runs weekly, writing new envelope allocations; the Risk Manager reads the current envelope per order.

### D2 — Phase 1 algorithm — Risk Parity (diagonal covariance)

Target allocation per Charter §6.1.1:

```
w_i ∝ 1 / σ_i,   normalized so Σ_i w_i = 1.0
```

where `σ_i` is the 60-day rolling annualized realized volatility of strategy `i`, computed from daily per-strategy PnL (consumed from Redis key `pnl:<strategy_id>:daily`).

**Parameters** (Charter §6.1.2, reproduced here for authoritative reference):

| Parameter | Value | Justification |
|---|---|---|
| Sigma estimation window | 60 days rolling | Stable estimate (noise ~ 1/√60 ≈ 13%); adapts within a quarter |
| Rebalancing frequency | Weekly, Sunday 23:00 UTC (before Asia open Monday) | AQR Risk Parity published cadence; daily is noisy, monthly too slow |
| Floor per active strategy | 5% | Prevents starvation; ensures drift-monitor learnability |
| Ceiling per strategy | 40% (45% elevated per D5) | Prevents single-strategy dominance; preserves diversification |
| Turnover dampening | ±25% max weekly weight change | Reduces transaction cost churn |

**Rationale for diagonal covariance** (Charter §6.1.5):

- Sample-size constraint: with 6 strategies × 60 days = 360 observations, full-covariance estimation produces a noisy off-diagonal matrix.
- Live tracking-error gain of full-covariance is minimal when cross-strategy correlation is targeted at < 0.3 (Charter §10.3).
- Interpretability: `w_i ∝ 1/σ_i` is auditable in one glance.

Future upgrade path: Charter §6.1.5 explicitly authorizes a future ADR upgrade to full-covariance Risk Parity when live evidence demonstrates cross-strategy correlations are persistently non-zero.

### D3 — Phase 2 algorithm — Sharpe overlay on Phase 1 base

Phase 2 activation trigger (Charter §6.2.1, **both** required):

1. ≥ 6 months of live trading on at least 3 active strategies.
2. Live Sharpe estimates stabilized: 95% bootstrap CI on rolling 6-month Sharpe within ±0.3 of point estimate for ≥ 3 consecutive weeks.

Until both hold, allocator operates strictly in Phase 1.

**Specification** (Charter §6.2.2):

```
w_i_phase2 = w_i_phase1 × tilt_i
tilt_i     = 1.0 + clip(β × (S_i - S_mean), -0.20, +0.20)
```

where:

- `S_i` = EMA-smoothed 6-month rolling Sharpe of strategy `i` (half-life ~ 2 months).
- `S_mean` = weighted average Sharpe across active strategies (weighted by current `w_i_phase1`).
- `β` = calibration constant, initial value `0.5 / (max_sharpe_spread / 2)` so that a 1-unit-Sharpe lead over mean produces ~+10% tilt; fine-tuned empirically live.
- `clip(x, -0.20, +0.20)` enforces ±20% maximum tilt per strategy.

After tilting, weights re-normalize to sum to 1.0; floor (5%) and ceiling (40% or 45%) re-apply with overflow redistribution.

**Why ±20% tilt cap** (Charter §6.2.5): recent Sharpe is a noisy estimator of future Sharpe (Lo 2002); bootstrap CI on 6-month Sharpe is typically ±0.5 to ±1.0 wide. A ±20% cap prevents the allocator from over-reacting to pure noise.

### D4 — Cold-start ramp

Strategies entering Gate 4 live-micro receive a linear ramp from 20% → 100% over 60 calendar days (Charter §6.1.3):

```
ramp_factor(d) = min(1.0, 0.20 + (0.80 × d / 60))
w_i_effective = ramp_factor(d) × w_i_target
```

Undersized fraction `(1 - ramp_factor(d))` is redistributed proportionally to other active strategies.

Day 60 decision (Playbook §6.3):

- Live Sharpe > 70% of paper Sharpe → `ramp_factor` set to 1.0; strategy transitions to standard Risk Parity sizing.
- Otherwise → `ramp_factor` frozen at 0.20; strategy enters observation mode until CIO discretion.

### D5 — Elevated ceiling for exceptional performers

If a strategy's rolling 6-month Sharpe is > 2.0 stable for ≥ 6 months (95% bootstrap CI lower bound stays above 2.0), its ceiling is elevated from 40% to 45% per Charter §6.2.3.

Elevation requires **CIO ratification** via a single commit to the strategy's `config/strategies/<strategy_id>.yaml` setting `ceiling_elevated: true`. The Charter does not auto-elevate.

### D6 — Edge cases and operational behavior

Per Charter §6.1.4:

- **Strategy in `review_mode`**: floor drops to 5%; excluded from Phase 2 Sharpe-overlay upward tilts.
- **Strategy paused** (operational, not decommissioned): excluded from allocation; share redistributed proportionally.
- **N=1 active strategy**: 100% allocation (bypasses 40% ceiling).
- **N=0 active strategies**: publish `portfolio.allocation.suspended` on every rebalance tick.
- **During portfolio hard-CB halt**: reads `risk:circuit_breaker:state` first; if `HARD_TRIPPED`, publishes `portfolio.allocation.suspended` and skips rebalance.

### D7 — Observability and integration

**Events published**:

- `portfolio.allocation.updated` — on every successful rebalance; message is the full `AllocatorResult` Pydantic frozen model.
- `portfolio.allocation.suspended` — when N=0 active strategies or during hard-CB halt.

**Redis writes**:

- `portfolio:allocation:<strategy_id>` — per-strategy effective weight as Decimal string (read by STEP 6 `PerStrategyExposureGuard`).
- `portfolio:allocation:meta` — hash: `{last_rebalance_ts, phase, total_weight, n_active_strategies, algorithm_metadata}`.

**Dashboard** (`services/ops/monitor_dashboard/`): per-strategy allocation timeline; rebalance log; deviation alerts if actual exposure diverges > 5% from target weight.

**Persistence**: historical allocations persisted to TimescaleDB for attribution analysis (schema: `(rebalance_ts, strategy_id, weight_target, weight_effective, sigma_60d, phase, algorithm_metadata_json)`).

### D8 — Pydantic contract

The authoritative Pydantic models for the allocator:

```python
# services/portfolio/strategy_allocator/models.py
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from datetime import datetime

class StrategyAllocation(BaseModel):
    """Per-strategy allocator output for a single rebalance event."""
    model_config = ConfigDict(frozen=True)
    strategy_id: str
    weight_target: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    weight_effective: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    ramp_factor: Decimal = Field(..., ge=Decimal("0.20"), le=Decimal("1"))
    sigma_60d: Decimal
    is_excluded: bool
    excluded_reason: str | None = None

class AllocatorResult(BaseModel):
    """Full allocator output for a single weekly rebalance."""
    model_config = ConfigDict(frozen=True)
    rebalance_ts_utc: datetime
    phase: str  # "phase1_risk_parity" | "phase2_sharpe_overlay"
    total_weight: Decimal  # sanity check: == 1.0 within Decimal tolerance
    allocations: list[StrategyAllocation]
    algorithm_metadata: dict
```

### D9 — Decoupling from the Kelly risk-taker profile

Per Charter §6.3, capital allocation (this ADR) is **separate** from per-strategy aggressiveness (Kelly fraction, stop-loss multipliers, etc.). The allocator does not see Kelly; it sees only per-strategy capital allocations. Each strategy configures its own Kelly in `config/strategies/<strategy_id>.yaml` with documented justification.

Kelly adjustments from soft circuit breakers (Playbook §8.1, Kelly × 0.5 on DD 8%/24h) apply **within** the strategy's allocated envelope; they do not change the envelope itself. The envelope is the allocator's output; the Kelly adjustment modifies how the strategy uses the envelope.

---

## 3. Consequences

### 3.1 Positive

- **SOLID-S, SOLID-D**: allocator is one responsibility; Fusion and Risk Manager remain unchanged.
- **Algorithm evolution**: Phase 1 → Phase 2 → future Black-Litterman upgrades do not touch adjacent services.
- **Observable**: dashboard shows allocator decisions, history, deviations.
- **Institutional-grade**: matches AQR, Citadel, Millennium references (Charter §1.3).
- **Principle 4**: Charter §6 allocation rules are mechanically enforced (floor, ceiling, ramp in code; cannot be bypassed).

### 3.2 Negative

- **Additional ZMQ hop**: order.candidate → allocator → risk manager introduces serialization round-trip. Mitigated: allocator writes envelope **once per week**; risk manager reads from Redis on order (O(1) hash lookup), so per-order latency is negligible.
- **Operational complexity**: one more container to orchestrate. Mitigated by standard supervisor startup ordering (Charter §5.9).
- **Weekly cadence reaction time**: a strategy whose volatility spikes mid-week does not get its allocation reduced until Sunday. Mitigated by soft CB triggers (Charter §8.1.1) that reduce Kelly intra-week independently of allocator.

### 3.3 Mitigations

- **Hot-path latency**: the allocator is not on the hot path. Risk manager reads `portfolio:allocation:<id>` as a Redis hash lookup per order; O(1).
- **Weekly staleness**: acceptable because Charter mid-week responses to drawdown are soft CBs (Kelly × 0.5 on DD > 8%), not allocation changes.
- **Allocator crash**: if allocator is down during a rebalance window, the last-written `portfolio:allocation:<id>` remains; strategies operate at the last-valid envelope. This is **fail-static** (not fail-closed), by design — the allocator is an envelope-setter, not a safety-critical gate. Charter §8 circuit breakers remain the safety layer.

---

## 4. Alternatives Considered

### 4.1 Absorb into S04 Fusion Engine

**Description**: the allocator is a sub-module inside the existing Fusion Engine.

**Pros**: fewer containers; reuse of Fusion's Redis + ZMQ connections.

**Cons**:

- SRP violation: Fusion Engine would have two concerns (per-signal fusion + cross-strategy allocation).
- Charter §5.2 (Q2) explicitly rejected.
- Evolution of the allocator algorithm would force churn in Fusion code.

**Rejected** per Charter §5.2.

### 4.2 Absorb into S05 Risk Manager

**Description**: the allocator is a sub-module inside the Risk Manager.

**Pros**: colocated with the envelope consumer (STEP 6 `PerStrategyExposureGuard`).

**Cons**:

- Risk Manager is the VETO layer; adding assignment logic violates its singular role.
- Allocator is weekly; Risk Manager is per-order. Mixing cadences complicates the design.

**Rejected**.

### 4.3 Static per-strategy budgets (no dynamic allocator)

**Description**: each strategy has a hardcoded capital budget in its `config.yaml`; no dynamic allocation.

**Pros**: trivial implementation.

**Cons**:

- Does not respond to changing per-strategy volatility. A strategy whose σ spikes 2× gets unchanged budget → contributes 2× as much risk to the portfolio.
- Violates Charter §6 Risk Parity principle.
- Does not respond to new-strategy cold-start ramp (Charter §6.1.3).

**Rejected** — Risk Parity is a Charter-binding decision.

### 4.4 Mean-variance (Markowitz) allocator

**Description**: solve a quadratic program with expected returns + full covariance to maximize Sharpe.

**Pros**: theoretically optimal under known-true-parameters assumption.

**Cons**:

- Expected-return estimation is notoriously unstable (Michaud 1989 "estimation error" critique).
- Solutions are "optimistic" — concentrated on a few high-Sharpe strategies, defeating diversification.
- AQR and Bridgewater publications favor Risk Parity over mean-variance in practice.

**Rejected** for Phase 1. Might be revisited as Phase 3+ alternative if Sharpe overlay proves inadequate.

---

## 5. Implementation Sketch

### 5.1 Phase C tasks (Roadmap §4)

1. Scaffold `services/portfolio/strategy_allocator/` with `BaseService` inheritance.
2. Implement `risk_parity.py` per D2 (inverse-volatility weights + floors + ceilings + turnover dampening).
3. Implement `ramp.py` per D4 (cold-start factor calculation).
4. Implement `floors_ceilings.py` per D2 (floor/ceiling enforcement with overflow redistribution).
5. Implement `service.py` with weekly Sunday-23:00-UTC rebalance task (asyncio scheduled).
6. Implement `sharpe_overlay.py` per D3 (dormant until Phase 2 trigger).
7. Write property tests per Roadmap §4.3.
8. Deploy as Docker container per Charter §5.9 startup order position 11.
9. Author this ADR.

### 5.2 Phase 2 activation (post-month-12)

When Charter §6.2.1 trigger conditions hold, flip `phase = "phase2_sharpe_overlay"` in `config.yaml`; the service begins applying the Sharpe overlay on the next rebalance. No code change required; the overlay logic is already in `sharpe_overlay.py` and waits for the config flag.

---

## 6. Compliance Verification

### 6.1 CI-enforced invariants

- **Sum-to-one**: for every `AllocatorResult`, `total_weight == 1.0` within Decimal tolerance (1e-9). Property-tested.
- **Floor/ceiling**: for every `StrategyAllocation`, `floor ≤ weight_effective ≤ ceiling`, respecting ramp reductions. Property-tested.
- **Charter §6.4 worked example regression**: given σ = (35%, 18%, 10%, 28%, 8%, 22%), the allocator must produce weights (7.3%, 14.2%, 25.6%, 9.1%, 32.0%, 11.6%) within Decimal tolerance.
- **Rebalance schedule**: integration test verifies rebalance task fires at Sunday 23:00 UTC (deterministic via injected clock).
- **Hard-CB halt precedence**: when `risk:circuit_breaker:state == HARD_TRIPPED`, allocator publishes `portfolio.allocation.suspended` and skips rebalance.

### 6.2 Manual verification checklist

- [ ] Allocator container in supervisor startup order position 11 (Charter §5.9).
- [ ] `portfolio:allocation:<strategy_id>` Redis keys written for every active strategy after each rebalance.
- [ ] Dashboard panel showing weekly allocator decisions.
- [ ] Phase 2 activation documented in Roadmap §9.4.

---

## 7. References

### 7.1 Academic

- Maillard, S., Roncalli, T., Teiletche, J. (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *Journal of Portfolio Management* 36, 60-70. [Risk Parity]
- Lo, A. W. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal* 58, 36-52. [Sharpe estimation uncertainty]
- Michaud, R. O. (1989). "The Markowitz Optimization Enigma." *Financial Analysts Journal* 45, 31-42. [Estimation error critique of mean-variance]

### 7.2 Charter and Playbook

- Charter §5.2 (Q2 decision); §6 (full allocation framework); §6.1 (Phase 1 spec); §6.2 (Phase 2 spec); §6.4 (worked example).
- Playbook §6 (Gate 4 live-micro ramp mechanics); §7.1.1 (allocator weekly rebalance).

### 7.3 Roadmap

- Roadmap v3.0 §4 (Phase C deliverables).
- Roadmap §7.2.4 (2-strategy Risk Parity first live activation at Strategy #2 Day 0).
- Roadmap §9.4 (Phase 2 activation trigger evaluation).

### 7.4 Internal code references (target paths, post Phase D.5)

- `services/portfolio/strategy_allocator/` (new in Phase C).
- `services/portfolio/risk_manager/chain_orchestrator.py` — 7-step chain; STEP 6 consumes allocator output.
- `core/base_service.py` — `BaseService` inheritance.
- `core/models/order.py` — `OrderCandidate` carries `strategy_id` (Phase A).

---

**END OF ADR-0008.**
