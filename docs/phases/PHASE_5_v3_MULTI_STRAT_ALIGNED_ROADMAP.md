# APEX Multi-Strategy Platform — Phase 5 v3 Multi-Strat Aligned Roadmap

**Document 3 of 3** (executional layer)
**Version**: v3.0 (DRAFT — awaiting CIO ratification)
**Status**: ACTIVE once merged (supersedes [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md) and [`docs/PROJECT_ROADMAP.md`](../PROJECT_ROADMAP.md))
**Authoring date**: 2026-04-20
**Inherits from**:
- [APEX Multi-Strat Charter v1.0](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) (ratified 2026-04-18 via PR #184)
- [APEX Strategy Development Lifecycle Playbook v1.0](../strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) (ratified 2026-04-20 via PR #186)
**Supersedes on merge**:
- `docs/phases/PHASE_5_SPEC_v2.md` (ACTIVE pre-Charter execution spec)
- `docs/PROJECT_ROADMAP.md` (pre-Charter top-level roadmap)
**Binding authority**: Every engineering work item executed on the APEX platform from Charter ratification onward is sequenced by this Roadmap until explicitly amended or superseded. Roadmap deviations require CIO ratification and a Changelog entry; material scope changes require a new ADR.

---

## §0 — Preamble and Scope

### 0.1 Purpose

This Roadmap is the **executional layer** of the APEX Multi-Strategy Platform. Where the Charter (Document 1) defines *what* the platform is and *what* the gates require, and where the Playbook (Document 2) defines *how* each gate is operated mechanically, this Roadmap defines **when** each piece of work happens and **in what order** over a 24-month horizon.

It is the document an Implementation Lead (Claude Code agent) consults to answer the single operational question: *"What do I work on next, and why now?"* Every section below answers that question against a specific calendar slice, a specific dependency chain, and a specific set of Charter-mandated success criteria.

The Roadmap is **time-ordered** but **trigger-gated** — calendar windows are indicative, but work does not advance until its dependencies are satisfied and its exit criteria are met. A slip in one phase compresses the overlap of the next; a hard Charter floor (e.g., Gate 3's 8-week paper minimum) is never shortened to preserve the schedule.

### 0.2 Audience

Three concurrent audiences:

1. **CIO — Clement Barbier**. The Roadmap is his scheduling source of truth. When the CIO asks "where do we stand versus the 24-month plan?", the answer is expressed in terms of this Roadmap's phases and strategy-lifecycle milestones.
2. **Claude Code Implementation Lead** (every session, every model). Before opening any work PR, the agent reads this Roadmap to confirm the work belongs to the **current active phase**. An agent opening Strategy #3 Gate 2 code while Phase C is still in flight has violated the Roadmap regardless of code quality.
3. **Future maintainers and external auditors** (theoretical). The Roadmap documents that the platform's build-out is **defensible as a plan** — not an accumulation of tactical decisions that compound into a surprise outcome.

### 0.3 Relationship to Charter and Playbook

The Roadmap **inherits** and **schedules**:

| Charter / Playbook section | Roadmap section |
|---|---|
| Charter §5 (architectural foundations) | §2–§5 (Phases A–D schedule the infrastructure that the Charter specifies) |
| Charter §5.10 (infrastructure lift Phase A-B-C-D naming) | §2–§5 (Phase A-B-C-D inherited verbatim; Phase D.5 Topology Migration scheduled as addendum) |
| Charter §6 (capital allocator framework) | §4 (Phase C builds `services/portfolio/strategy_allocator/`); ADR-0008 authored here |
| Charter §7 (gate timeline floors) | §6–§8 (strategy lifecycle sections respect every Charter floor) |
| Charter §12.4 (anticipated new ADRs) | §10 (ADR-0007, ADR-0008, ADR-0009, ADR-0010 authored as part of this Roadmap PR) |
| Playbook §1.2 (timeline expectations per strategy) | §6–§8 (per-strategy timelines built on Playbook floor numbers) |
| Playbook §3–§6 (four gates full protocol) | §6–§8 (strategy sections invoke Playbook templates by reference, never duplicate) |
| Playbook §10 (decommissioning) | §11 (contingency playbook invokes Playbook §10 operationally) |

Where the Roadmap and the Charter or Playbook appear to conflict: the conflict is almost always a **scope difference** (the Roadmap schedules, the Charter/Playbook specify). In genuine conflict, the Charter prevails over the Roadmap; the Playbook prevails over the Roadmap for any operational rule; the Roadmap prevails only for scheduling order where Charter/Playbook are silent. See Playbook §0.6 and §0.7 for the binding-precedence chain.

### 0.4 What this Roadmap supersedes

On merge, this Document 3 explicitly supersedes:

1. **[`docs/phases/PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md)** — the current active Phase 5 execution spec. A follow-up PR (post-merge action per §16.1) adds a `SUPERSEDED` banner to PHASE_5_SPEC_v2. The file remains in the repository for historical reference; no content is deleted. Ongoing 5.2/5.3/5.5/5.4/5.8/5.10 sub-phase work is re-sequenced by this Roadmap (see §2.4 for the explicit mapping).

2. **[`docs/PROJECT_ROADMAP.md`](../PROJECT_ROADMAP.md)** — the pre-Charter high-level roadmap. A follow-up PR (post-merge action per §16.1) adds a `SUPERSEDED` banner. The file remains for historical reference; Charter §10.5 and this Roadmap's §9 together replace its forward-looking content.

Pre-Charter documents that **are not** superseded:

- [CLAUDE.md](../../CLAUDE.md) — code conventions remain binding unchanged.
- [MANIFEST.md](../../MANIFEST.md) — technical architecture description, updated incrementally as the Roadmap executes.
- [ADRs 0001–0006](../adr/) — binding architectural decisions carry forward; ADR-0007, ADR-0008, ADR-0009, ADR-0010 are **added** (not superseding).
- [Audits](../audits/) — read-only evidence; not scheduling documents.
- [`docs/claude_memory/`](../claude_memory/) — cross-session operational record; continues.

### 0.5 What this Roadmap does NOT do

- **Does not redefine Charter decisions**. The Q1–Q8 Charter decisions are inherited verbatim.
- **Does not author per-strategy Charters**. Those are drafted during Gate 1 per strategy, per Playbook §2.3. This Roadmap schedules *when* each per-strategy Charter is drafted; it does not author their content.
- **Does not guarantee live PnL**. Charter Principle 3 (acknowledged constraints) binds every calendar estimate in this Roadmap. Markets, implementation surprises, validation failures at any gate may reshape the timeline. The Roadmap's job is to *plan*, not to *promise*.
- **Does not specify code conventions**. CLAUDE.md prevails unconditionally.
- **Does not schedule paper-trading decisions**. Paper-to-live and live-full promotions are trigger-based per Playbook §5–§6; the Roadmap's per-strategy windows are indicative, not binding, on those trigger decisions.

### 0.6 Status and revision model

The Roadmap is **versioned**. Material changes — adding or removing a phase, changing an exit criterion, shifting a boot-strategy deployment window by > 60 days, resequencing infrastructure phases — require:

1. A new ADR documenting the change and its rationale.
2. A version bump (`v3.0 → v3.1` for additive clarifications; `v3.x → v4.0` for breaking changes).
3. An entry in [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
4. A pull request reviewed and merged by the CIO.

Cosmetic edits (typos, link fixes, updated commit SHAs in phase-exit evidence, additional worked examples that do not alter procedure) do not require version bumps but must be logged in the Changelog (§17).

### 0.7 Binding precedence (restated)

Per Playbook §0.6, the precedence chain governing conflicts among the APEX documentation corpus is:

```
Charter  >  ADRs (for their technical surface)  >  Playbook  >  Roadmap
                                                       ↓
                                              CLAUDE.md (code conventions,
                                              overrides all for forbidden patterns)
```

The Roadmap operates **below** the Charter, **below** ADRs on their technical scope, and **below** the Playbook on operational rules. The Roadmap is **only authoritative** for scheduling order and phase exit criteria where the higher-precedence documents do not speak.

---

## §1 — Roadmap at a Glance

### 1.1 Visual timeline — 24-month horizon

The Roadmap covers months 0–24 from Charter ratification (2026-04-18, week 0). Infrastructure Phases A, B, C, D, D.5 execute early with overlapping windows; the six boot strategies deploy sequentially but with significant concurrent-gate overlap per Charter §7.5 and Playbook §1.3.

```
Month:  0       3       6       9      12      15      18      21      24
        │       │       │       │       │       │       │       │       │
        ├─ Phase A ─┤
        │  (W1-8)   │
        │           │
        │       ├─── Phase B ───┤
        │       │    (W6-14)    │
        │       │               │
        │       │           ├───── Phase C ─────┤
        │       │           │     (W12-22)     │
        │       │           │                  │
        │       │           │           ├───── Phase D ─────┤
        │       │           │           │     (W18-28)     │
        │       │           │           │                  │
        │       │           │           │             ├─ D.5 ─┤
        │       │           │           │             │(W26-28)│
        │       │           │           │             │        │
        │       │           │                                  │
        │       │   ┌─ Strategy #1 Crypto Momentum ─────────┐ │
        │       │   │  G1(W10-14) → G2(W14-18) → G3(W18-26) │ │
        │       │   │  → G4 ramp(W27-36) → Live Full       │ │
        │       │   └───────────────────────────────────────┘ │
        │       │                                             │
        │           ┌─ Strategy #2 Trend Following ───────────┐
        │           │  G1(W20-24) → G2(W24-30) → G3(W30-42)   │
        │           │  → G4(W43-52)                            │
        │           └─────────────────────────────────────────┘
        │                                                       │
        │               ┌─ Strategy #3 Mean Rev Equities ───────────┐
        │               │  G1(W40-46) → G2(W46-52) → G3(W52-60)    │
        │               │  → G4(W61-70)                              │
        │               └───────────────────────────────────────────┘
        │                                                              │
        │                       ┌─ Strategy #4 VRP ────────┐
        │                       │  G1(W52-58) → G2(W58-66) │
        │                       │  → G3(W66-76) → G4(W77-86)│
        │                       └─────────────────────────┘
        │                                                              │
        │                               ┌─ Strategy #5 Macro Carry ┐
        │                               │  G1(W64-72) → G2(W72-80) │
        │                               │  → G3(W80-92) → G4       │
        │                               └──────────────────────────┘
        │                                                              │
        │                                       ┌─ Strategy #6 News-driven ┐
        │                                       │  G1(W76-84) →           │
        │                                       │  G2(W84-94) → G3 → G4   │
        │                                       └─────────────────────────┘
        │                                                                    │
        ▼       ▼       ▼       ▼       ▼       ▼       ▼       ▼       ▼
        │   Charter     │   Survival   │ Legitimacy   │   Institutional
        │  ratified     │  benchmark   │ benchmark    │   benchmark
        │ (month 0)     │ (~month 9    │ (~month 15)  │   (~month 24)
        │               │  Strategy #1 │ Strategies   │   Strategies
        │               │  live full)  │ #1+#2 live)  │   #1+#2+#3 live
```

Legend:
- **W** = week from Charter ratification (W0 = week of 2026-04-18)
- **G1/G2/G3/G4** = Playbook §3/§4/§5/§6 gates
- Phase letters (**A**, **B**, **C**, **D**, **D.5**) = Charter §5.10 + this Roadmap §5.5 Topology Migration addendum

### 1.2 Big-picture milestones on a 24-month horizon

| Horizon | Milestone | Gate posture |
|---|---|---|
| Months 0–3 | Phase A infrastructure lift; Strategy #1 informal research in parallel | Phase A exit criteria (§2.6) cleared |
| Months 2–5 | Phase B begins; Strategy #1 Gate 1 PR window | Phase B exit criteria (§3.5) cleared |
| Months 4–7 | Phase C (allocator + 7-step chain); Strategy #1 Gate 2 | Phase C exit criteria (§4.5) cleared |
| Months 6–9 | Phase D (panels + per-strategy FB loop + portfolio backtest); Strategy #1 Gate 3 paper (8 weeks); Strategy #2 Gate 1 begins | Phase D exit criteria (§5.4) cleared |
| Months 6.5–7 | Phase D.5 Topology Migration (folder reorganization) | §5.5 exit criteria cleared |
| Months 7–9 | Strategy #1 Gate 4 live-micro 60-day ramp; Survival benchmark evaluation | Charter §10.1 Survival criteria |
| Months 9–12 | Strategy #1 Live Full; Strategy #2 Gate 2/3 | Charter §10.2 early Legitimacy |
| Months 12–15 | Strategy #2 Live Micro → Live Full; Strategy #3 Gate 1/2; Phase 2 allocator trigger evaluation | Charter §6.2.1 trigger check |
| Months 15–18 | Strategy #3 Gate 3/4; Strategies #4 Gate 1/2 begin; Legitimacy benchmark candidate | Charter §10.2 Legitimacy |
| Months 18–24 | Strategies #4/#5/#6 lifecycle tracks; Institutional benchmark candidate | Charter §10.3 Institutional |

### 1.3 Critical path dependencies

The following dependency chain is the **critical path**. A slip in any earlier link cascades to every later item.

```
Phase A strategy_id + Topics.signal_for
    │
    ▼
Phase B StrategyRunner ABC + LegacyConfluenceStrategy wrap
    │                                          │
    │                                          ▼
    │                                 Strategy #1 Gate 1 PR
    │                                          │
    ▼                                          ▼
Phase C StrategyAllocator + 7-step chain ←── Strategy #1 Gate 2 PR
    │                                          │
    ▼                                          ▼
Phase D PanelBuilder + per-strat feedback ←── Strategy #1 Gate 3 paper
    │                                          │
    ▼                                          ▼
Phase D.5 Topology Migration           Strategy #1 Gate 4 live-micro
    │                                          │
    ▼                                          ▼
[target topology in place]            [Strategy #1 Live Full]
                                               │
                                               ▼
                                  Strategy #2 Gate 1 → Gate 4
                                               │
                                               ▼
                              Strategies #3, #4, #5, #6 (parallel tracks)
```

Notes on the dependency graph:

- **Phase A must precede every other phase.** Without `strategy_id` on the five order-path Pydantic models and without `Topics.signal_for`, there is no way to distinguish Strategy #N's signals from legacy confluence signals downstream — the architecture literally cannot host two strategies simultaneously.
- **Phase B is required before Strategy #1 Gate 2**, not before Gate 1. Gate 1 is a research-only artifact (notebook + backtest); Gate 2 requires a production microservice that implements `StrategyRunner` (Playbook §4.2.3).
- **Phase C is required before Strategy #1 Gate 2 closes**, because the 7-step chain and allocator must be in place for the Gate 2 smoke test (Playbook §4.2.5) to exercise the full live path. Strategy #1 is the first strategy to exercise per-strategy STEP 3 (StrategyHealthCheck) and STEP 6 (PerStrategyExposureGuard).
- **Phase D is required before Strategy #1 Gate 3**, because Gate 3 runs against live panel data emitted by `services/data/panels/` (Charter §5.3); until Phase D, strategies use raw tick streams as a transitional pattern, which does not satisfy the Charter's panel discipline for a paper-eligible strategy.
- **Phase D.5 Topology Migration is scheduled after D** (weeks 26-28) specifically to avoid merge conflicts with in-flight Strategy #1 Gate 3/4 work. The reorganization is mechanical (`git mv` + import-path fixups) and reversible.
- **Strategy #2 begins Gate 1 only after Strategy #1 reaches Gate 3**. This is a deliberate gating: Strategy #1 must validate the end-to-end lifecycle pipeline before the platform invests in Strategy #2's Gate 1/2 microservice work. Early concurrent Strategy #2 Gate 1 is allowed only as **informal research in parallel** (notebook-only, no Gate 1 PR), not formal Gate 1 evidence.
- **Strategies #3, #4, #5, #6** can proceed with more overlap once Strategy #2 reaches Gate 3 (month ~12): the platform has by then accumulated operational experience with the full pipeline, and parallel Gate 1/2 work across strategies does not compete for critical-path allocator/panel-builder work.

### 1.4 What can slip, and what cannot

**Can slip without Charter amendment** (Roadmap is authoritative):

- Phase A, B, C, D, D.5 calendar windows — if dependencies require more time, the slip is documented in the Changelog (§17) and per-strategy timelines shift accordingly.
- Strategy lifecycle windows between gates — a strategy that needs 4 weeks to build its Gate 2 microservice instead of 2 weeks slips the Gate 2 PR date, which slips the Gate 3 paper-start date, etc.
- New-candidate onboarding (Charter §11) timing — driven entirely by CIO discretion.

**Cannot slip without Charter amendment**:

- Gate 3 minimum 8-week paper (Charter §7.3, Playbook §1.2).
- Gate 4 minimum 60-day live-micro ramp (Charter §6.1.3, §7.4).
- Seven-step VETO chain structure (Charter §8.2) — adding/removing steps requires Charter amendment + new ADR.
- Risk Parity Phase 1 activation on Strategy #2 Live Full (Charter §6.1, §6.2.1) — Phase 2 Sharpe overlay cannot activate before the § 6.2.1 trigger conditions are met.
- Category budgets (Charter §9.1) and decommissioning rules (Charter §9.2).

---

## §2 — Multi-Strat Infrastructure Lift — Phase A (Weeks 1–8)

### 2.1 Goal

Enable `strategy_id` across the contract surface without breaking current single-strategy operation, un-muzzle the CI backtest gate so strategy work can rely on mechanical backtest validation, and resolve the Redis orphan-read trap identified in prior audits.

Phase A is the **foundational contract shift**. Every subsequent phase and every boot strategy depends on `strategy_id` flowing through the five order-path Pydantic models, on the `Topics.signal_for` factory producing per-strategy ZMQ topics, and on per-strategy Redis key partitioning being available. Without Phase A, the platform cannot distinguish Strategy #1's signals from legacy confluence signals.

Phase A is scoped to **8 weeks** wall-clock (weeks 1–8 post Charter ratification; calendar: 2026-04-20 → 2026-06-15). The estimate embeds Principle 3 realism: the changes are mechanical but span many files, require careful backward-compatibility preservation (Principle 6), and depend on coverage and mypy-strict discipline remaining green.

### 2.2 Deliverables

#### 2.2.1 `strategy_id` field on five frozen Pydantic models

**Scope**: add a `strategy_id: str = "default"` field to each of the following models per Charter §5.5. Default value `"default"` preserves all current single-strategy behavior (the legacy confluence path tags every `OrderCandidate` it produces as `strategy_id="default"` until it is wrapped as `LegacyConfluenceStrategy` in Phase B).

| Model | File | Current LOC (approx) | Insertion point |
|---|---|---|---|
| `Signal` | [`core/models/signal.py`](../../core/models/signal.py) | ~100 | After existing core fields, before extensibility fields |
| `OrderCandidate` | [`core/models/order.py:40-60`](../../core/models/order.py) | ~80 (entry) | After `timestamp_ms`, before sizing fields |
| `ApprovedOrder` | [`core/models/order.py`](../../core/models/order.py) | — | Inherited-convention slot |
| `ExecutedOrder` | [`core/models/order.py`](../../core/models/order.py) | — | Inherited-convention slot |
| `TradeRecord` | [`core/models/order.py`](../../core/models/order.py) | — | Inherited-convention slot |

**Implementation discipline**:

- Field is `str` (not enum) to support open-ended strategy IDs across the Charter's six boot strategies and any extensibility per Charter §11.
- Default value `"default"` is a magic string; its semantics are documented in `core/models/order.py` docstring and in MANIFEST.md per CLAUDE.md §8 checklist.
- All five models remain `ConfigDict(frozen=True)` per CLAUDE.md §2.
- No field validator restricting `strategy_id` values — Charter §11 (extensibility) explicitly permits new strategies to be added without Pydantic-level gate modification.

**Issues to open** (list for Phase A kickoff):

- **Issue "[phase-A.1] Add strategy_id to Signal Pydantic model"** — scope: `core/models/signal.py` + tests; acceptance: `Signal(strategy_id="crypto_momentum", ...)` round-trips via `model_dump_json()` and reconstruction; coverage ≥ 90% on the modified model.
- **Issue "[phase-A.2] Add strategy_id to OrderCandidate Pydantic model"** — similar scope on `core/models/order.py:OrderCandidate`.
- **Issue "[phase-A.3] Add strategy_id to ApprovedOrder, ExecutedOrder, TradeRecord"** — bundled PR across the three adjacent models.

#### 2.2.2 `Topics.signal_for(strategy_id, symbol)` factory

**Scope**: add a new static method to [`core/topics.py:Topics`](../../core/topics.py) (currently 110 LOC per `wc -l`) producing `f"signal.technical.{strategy_id}.{symbol.upper()}"`.

```python
@staticmethod
def signal_for(strategy_id: str, symbol: str) -> str:
    """Per-strategy signal topic.

    Example: Topics.signal_for('crypto_momentum', 'BTCUSDT')
             == 'signal.technical.crypto_momentum.BTCUSDT'

    The existing Topics.signal(symbol) factory remains unchanged for
    backward compatibility during Phase A/B transition. Strategies
    migrating to per-strategy topics publish on signal_for; consumers
    subscribe on the prefix 'signal.technical.' and route by the
    strategy_id component.
    """
    return f"signal.technical.{strategy_id}.{symbol.upper()}"
```

**Backward compatibility**: the existing `Topics.signal(symbol)` factory at [`core/topics.py:77-86`](../../core/topics.py) remains unchanged. The legacy single-strategy path continues to publish on `signal.technical.{symbol}` until Phase B wraps it as `LegacyConfluenceStrategy` and migrates it to `Topics.signal_for("default", symbol)`.

**Issue**: **"[phase-A.4] Add Topics.signal_for factory for per-strategy signal topics"** — scope: `core/topics.py` + unit test; 0.5 day effort.

#### 2.2.3 Un-muzzle CI `backtest-gate`

**Scope**: remove `continue-on-error: true` from [`.github/workflows/ci.yml:130`](../../.github/workflows/ci.yml), restore thresholds to CLAUDE.md §6 targets (`BACKTEST_MIN_SHARPE=0.8`, `BACKTEST_MAX_DD=0.08`) at [`ci.yml:151-152`](../../.github/workflows/ci.yml), and close out GitHub issue **#102** (`[phase-5.x] backtest-gate continue-on-error removal`, currently open per CONTEXT.md).

**Prerequisite**: the `full_report` Sharpe bug that motivates the muzzle must be fixed first. Per [`backtesting/metrics.py:1392-1397`](../../backtesting/metrics.py), Sharpe must be computed on daily-resampled equity-curve returns (not per-trade returns); per [`backtesting/metrics.py:1401-1406`](../../backtesting/metrics.py), max drawdown must use the same daily curve; per [`backtesting/metrics.py:1409-1421`](../../backtesting/metrics.py), PSR must use the same excess-return series as headline Sharpe. If any of these invariants is currently violated on the CI fixture (30-day BTCUSDT 1-min per [`tests/fixtures/30d_btcusdt_1m.parquet`](../../tests/fixtures/30d_btcusdt_1m.parquet)), the muzzle stays until the fix lands.

**Issues**:

- **"[phase-A.5] Fix full_report Sharpe/DD/PSR consistency bug (close #102 prerequisite)"** — scope: `backtesting/metrics.py` + regression test.
- **"[phase-A.6] Un-muzzle CI backtest-gate and restore Sharpe ≥ 0.8 / DD ≤ 8% thresholds (closes #102)"** — scope: `.github/workflows/ci.yml`.

#### 2.2.4 Resolve Redis orphan-read audit findings from PR #178

**Scope**: address the orphan-read trap identified in [`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md) (referenced by [`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) P2-4). The keys with unverified writers per the audit:

| Key | Reader | Current writer status | Phase A resolution |
|---|---|---|---|
| `portfolio:capital` | S05 context_loader | Unverified | Implement `PortfolioTracker` component in S06 on-fill updates (inherits from PHASE_5_SPEC_v2.md §3.2) |
| `pnl:daily` | S05 | Unverified | Implement `PnLTracker` in S09 `trade_analyzer.py` per PHASE_5_SPEC_v2.md §3.2 |
| `pnl:intraday_30m` | S05 | Unverified | Same as above |
| `portfolio:positions` | S05 | Unverified | Implement `PositionAggregator` in S09 per PHASE_5_SPEC_v2.md §3.2 |
| `correlation:matrix` | S05 | Unverified | OUT OF PHASE A (deferred to Phase D per PHASE_5_SPEC_v2.md §3.2); identity-fallback retained with structured logging |
| `session:current` | S05 | Unverified | Persistence shim in S03 `session_tracker.py` |
| `macro:vix_current` | S05 | Unverified | Persistence shim in S01 `macro_feed.py` |
| `macro:vix_1h_ago` | S05 | Unverified | Rolling-snapshot task in S01 `macro_feed.py` |

**Principle 6 continuity**: these are the same writers scoped in the existing PHASE_5_SPEC_v2.md §3.2 Event Sourcing sub-phase. Phase A inherits that scope; no rework.

**Issues**:

- **"[phase-A.7] Implement portfolio:capital writer in S06 on-fill updates"** — scope: `services/s06_execution/portfolio_tracker.py` (new, ~100 LOC).
- **"[phase-A.8] Implement pnl:daily + pnl:intraday_30m writers in S09"** — scope: `services/s09_feedback_loop/pnl_tracker.py` (new, ~120 LOC).
- **"[phase-A.9] Implement portfolio:positions aggregator in S09"** — scope: `services/s09_feedback_loop/position_aggregator.py`.
- **"[phase-A.10] Session/macro Redis persistence shims in S03 + S01"** — bundled.

#### 2.2.5 Per-strategy Redis key adoption

**Scope**: introduce per-strategy variants of the Redis keys listed in Charter §5.5. Migration-by-rename is not required; legacy keys and per-strategy keys coexist during transition. Consumers read per-strategy keys first with a fallback to the legacy global key (logged when the fallback fires).

| Key pattern | Writer | Reader | Phase A work |
|---|---|---|---|
| `kelly:{strategy_id}:{symbol}` | S09 | S04 | Extend [`services/s09_feedback_loop/drift_detector.py`](../../services/s09_feedback_loop/drift_detector.py) (currently 160 LOC) and `kelly_updater.py` to accept optional `strategy_id`; write both `kelly:{symbol}` (legacy) and `kelly:{strategy_id}:{symbol}` (new) until Phase B decommissions the legacy write |
| `trades:{strategy_id}:all` | S06 + S09 | S09 fast_analysis | Extend S09 `service.py` persistence to write per-strategy Redis list; legacy `trades:all` continues until Phase B |
| `pnl:{strategy_id}:daily` | S09 PnLTracker | S05, S10 | Per-strategy scoping in the PnLTracker introduced in §2.2.4 |
| `portfolio:allocation:{strategy_id}` | (Phase C allocator) | S05 PerStrategyExposureGuard | **OUT OF PHASE A** — scheduled for Phase C §4.2.2 |

**Discipline**:

- Keys that are genuinely global (`portfolio:capital`, `risk:heartbeat`, `correlation:matrix`, `risk:circuit_breaker:state`) remain global per Charter §5.5. No change.
- Per-strategy keys use the separator `:` consistent with existing convention.
- During the dual-write transition (Phase A → Phase B), S09 writes both legacy and per-strategy keys. Phase B decommissions the legacy write with an explicit PR that removes the legacy write and cleans up the corresponding Redis keys.

**Issues**:

- **"[phase-A.11] Dual-write kelly and trades Redis keys with per-strategy partitioning"** — scope: S09.
- **"[phase-A.12] Per-strategy scoping in new PnLTracker"** — scope: S09 PnLTracker (from §2.2.4 A.8).

#### 2.2.6 Raise CI coverage gate from 75% to 85%

**Scope**: once all Phase A §2.2.1 through §2.2.5 deliverables are merged and main has stably shown total coverage ≥ 85% for at least 7 days, raise the CI coverage gate in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) from `--cov-fail-under=75` to `--cov-fail-under=85`. This aligns the mechanical gate with the CLAUDE.md §6 target.

**Prerequisite**: main shows `pytest --cov` ≥ 85% for 7 consecutive days.

**Issue**: **"[phase-A.13] Raise CI coverage gate from 75% to 85% (post-Phase-A stabilization)"**.

### 2.3 Testing discipline

Every Phase A deliverable ships with:

1. **Hypothesis property tests** for the Pydantic model changes — the `strategy_id` field must round-trip via `model_dump_json() / model_validate_json()` under arbitrary ASCII strings; the default value `"default"` must be preserved when the field is omitted on construction.
2. **Integration test for backward compatibility** — a test that constructs an `OrderCandidate` *without* `strategy_id`, passes it through the current legacy chain (S04 → S05 → S06), and verifies behavior is unchanged bit-for-bit against a pre-Phase-A baseline. This is the Principle-6-in-code assertion.
3. **Coverage discipline**: CI's current repository coverage gate (`--cov-fail-under=75`, per [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)) continues to pass. Phase A §2.2 deliverables are expected to raise effective total coverage to ≥ 85% (CLAUDE.md §6 target); ≥ 90% coverage on new modules remains the standard pattern. A Phase-A-scoped action item raises the CI gate itself from 75% to 85% once Phase A deliverables land on main — see Phase A §2.2.6 below.
4. **mypy strict clean; ruff clean; bandit clean** per CI contract.

**Regression harness**: a dedicated `tests/regression/test_phase_a_backward_compat.py` is introduced to hold the Phase A backward-compatibility assertions. This file persists beyond Phase A and is consulted whenever future phases touch the `strategy_id` plumbing.

### 2.4 Phase A resequencing relative to PHASE_5_SPEC_v2

The active Phase 5 sub-phases in PHASE_5_SPEC_v2.md (5.2 Event Sourcing, 5.3 Streaming Inference, 5.5 Drift Monitoring, 5.4 Short-Side, 5.8 Geopolitical NLP, 5.10 Closure) **continue** per their existing specifications in parallel with Phase A infrastructure work. The mapping:

| PHASE_5_SPEC_v2 sub-phase | Phase A impact |
|---|---|
| 5.2 Event Sourcing + Producers | **Absorbed into Phase A §2.2.4** (orphan-read resolution) and §2.2.5 (per-strategy Redis partitioning). The 5.2 Event Sourcing deliverables are Phase A deliverables with `strategy_id` dimension added. |
| 5.3 Streaming Inference | **Runs in parallel**; no direct conflict. Once Phase B wraps the legacy path as `LegacyConfluenceStrategy`, 5.3 streaming applies to that wrapper for the `strategy_id="default"` strategy. |
| 5.5 Drift Monitoring | **Runs in parallel**; extended to per-strategy partitioning in Phase D §5.2 (not Phase A). Phase A ships the `strategy_id` field on `TradeRecord` so Phase D's extension is mechanical. |
| 5.4 Short-Side + Regime Fusion | **Runs in parallel** on the legacy path. Short-side work carries forward into any strategy that inherits the direction-aware meta-labeler after Phase B. |
| 5.8 Geopolitical NLP (GDELT + FinBERT) | **Runs in parallel**; geopolitical guard lands as a STEP on the chain (likely STEP 1 or STEP 7 depending on Phase C chain restructure). Integrated into the 7-step chain in §4.2.3. |
| 5.10 Phase 5 Closure Report | **Absorbed into §12.3** of this Roadmap (Phase A-D closure). The standalone PHASE_5_SPEC_v2 closure report is NOT authored; the Roadmap's per-phase exit criteria serve that function. |

This resequencing is the primary reason PHASE_5_SPEC_v2.md is SUPERSEDED (§13) rather than amended: the 5.2/5.3/5.5/5.4/5.8/5.10 work is preserved but recast into a multi-strat-aligned execution plan.

### 2.5 Concurrent informal strategy work

During Phase A, Strategy #1 (Crypto Momentum) is in **informal research** per Playbook §3.1 entry criteria. The CIO and Head of Strategy Research conduct informal backtesting in notebooks, assemble the preliminary thesis defense, and draft the skeleton per-strategy Charter at `docs/strategy/per_strategy/crypto_momentum.md`. This work does NOT open a Gate 1 PR yet — Gate 1 requires `strategy_id` on `Signal` (Phase A §2.2.1 complete) for a formally reproducible backtest artifact.

The window for Strategy #1 informal research is weeks 1–10 (indicative). Gate 1 PR opens at week ~10 (see §6.2), after Phase A exit criteria are cleared.

### 2.6 Phase A exit criteria

Phase A is closed when **all** of the following hold (verifiable via CI, PR review, or direct inspection):

- [ ] All five Pydantic models in `core/models/{signal,order}.py` carry a `strategy_id: str = "default"` field, frozen, with hypothesis property tests passing.
- [ ] `Topics.signal_for(strategy_id, symbol)` is callable, unit-tested, and documented in [`core/topics.py`](../../core/topics.py).
- [ ] CI `backtest-gate` is un-muzzled (`continue-on-error: true` removed from [`ci.yml:130`](../../.github/workflows/ci.yml)); threshold `BACKTEST_MIN_SHARPE=0.8`, `BACKTEST_MAX_DD=0.08` restored; `backtest-gate` job is passing green on `main`.
- [ ] `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `session:current`, `macro:vix_current`, `macro:vix_1h_ago` all have production writers; CI grep audit passes. `correlation:matrix` continues to use the identity fallback per Charter §5.5 operational note.
- [ ] Per-strategy Redis key dual-write active for `kelly:{strategy_id}:{symbol}` and `trades:{strategy_id}:all` (legacy keys still written; per-strategy keys additionally written).
- [ ] CI pipeline (quality + rust + unit-tests + integration-tests + backtest-gate) green on `main`.
- [ ] Overall coverage maintained ≥ 85% (CLAUDE.md §6).
- [ ] CI coverage gate raised from `--cov-fail-under=75` to `--cov-fail-under=85` (issue `[phase-A.13]` closed), OR a documented exception noting the gate remains at 75% pending further deliverables in Phase B.
- [ ] mypy strict clean across the repository.
- [ ] Regression harness `tests/regression/test_phase_a_backward_compat.py` is present and green.

### 2.7 Phase A success signal

A synthetic "Strategy X" fixture (pure test strategy, no production presence) publishes signals on `signal.technical.x.BTCUSDT` through the full legacy chain (S02 signal adapter → S04 fusion → S05 risk → S06 execution simulation) with no breakage. The same fixture publishes a legacy-style signal on `signal.technical.BTCUSDT` in parallel; both paths coexist without interference. This is the end-to-end demonstration that the contract surface is ready for Phase B.

Test location: `tests/integration/test_phase_a_dual_path_signal_flow.py`.

### 2.8 Risks and mitigations (Phase A)

| Risk | Impact | Mitigation |
|---|---|---|
| Pydantic model changes break downstream deserializers (Signal, OrderCandidate persisted in TimescaleDB) | Historical data becomes unreadable | Default `"default"` preserves round-trip on rows written without `strategy_id`; TimescaleDB schema migration adds nullable column; existing rows are populated with `"default"` on read |
| `Topics.signal_for` introduces naming collision with existing `Topics.signal` on consumer subscribe prefix | Dropped or duplicated messages | Consumers subscribe on `signal.technical.` prefix and route by segment; unit tests verify the routing table |
| Un-muzzling backtest-gate reveals the Sharpe bug fix was incomplete; CI red | Phase A blocked | Stage the un-muzzle PR only after the `full_report` fix is merged and has passed the existing muzzled gate for ≥ 7 days with stable output |
| Orphan-read resolution exposes latent bugs in S05 context loading | S05 rejects legitimate orders | Reconciliation loop (per PHASE_5_SPEC_v2.md §3.2 item 3) + staleness timeout + integration tests |
| Phase A overruns 8 weeks | Strategy #1 Gate 1 PR slips | Roadmap is designed with 2-week overlap into Phase B (week 6 start); slip absorbed until week 10 without affecting Strategy #1 Gate 1 window |

---

## §3 — Multi-Strat Infrastructure Lift — Phase B (Weeks 6–14)

### 3.1 Goal

Introduce the `StrategyRunner` ABC that every strategy microservice (boot and future) inherits from; wrap the legacy S02 single-path pipeline as `LegacyConfluenceStrategy(StrategyRunner)` preserving all current behavior per Principle 6; implement the `StrategyHealthCheck` state machine (Playbook §8.0) as the foundation for STEP 3 of the Charter's 7-step VETO chain; add per-strategy dashboard panels to `services/s10_monitor/` so operators see state per strategy.

Phase B begins at week 6 (overlapping the last 2 weeks of Phase A) and runs 8 weeks total (weeks 6–14; calendar: 2026-05-25 → 2026-07-27). The overlap with Phase A is deliberate: Pydantic model changes and topic factory must be **merged** before `StrategyRunner` ABC design settles, but the ABC design itself, the `LegacyConfluenceStrategy` wrap, and the state machine can be drafted and unit-tested in parallel on a separate branch.

### 3.2 Deliverables

#### 3.2.1 `StrategyRunner` ABC

**Location**: authored at either `features/strategies/base.py` or `services/strategies/_base.py`. The location decision is documented in **ADR-0007 — Strategy as Microservice** (§10.1). Rationale for the two options:

- **Option A**: `features/strategies/base.py`. Pros: aligns with the existing `FeatureCalculator` ABC pattern ([`features/base.py:19`](../../features/base.py)); pure logic, no runtime concerns; strategies inherit a clean interface independent of the microservice scaffolding. Cons: slight coupling between the `features/` tree (research/backtest domain) and the `services/strategies/` tree (runtime domain).
- **Option B**: `services/strategies/_base.py`. Pros: co-located with the runtime microservices that implement the ABC; SOLID-D (depend on abstractions where they are used). Cons: `features/` tree already owns contract definitions for other ABCs, breaking symmetry.

**ADR-0007 ratifies Option B** (`services/strategies/_base.py`) on the basis that strategies are fundamentally **runtime services** whose backtest counterparts are notebook fixtures rather than shared-library logic; the ABC lives where the concrete services live.

**Contract** (authoritative — ADR-0007 §2):

```python
# services/strategies/_base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

from core.models.signal import Signal
from core.models.tick import NormalizedTick
# PanelSnapshot ABC lands in Phase D §5.1; until then, strategies consume raw NormalizedTick
# via a temporary on_tick adapter. Post-Phase-D, on_panel is the primary entry point.

class StrategyHealthState(str):
    """Enum-like sentinel matching Playbook §8.0 state machine."""
    HEALTHY = "healthy"
    DD_KELLY_ADJUSTED = "dd_kelly_adjusted"
    PAUSED_24H = "paused_24h"
    PAUSED_OPERATIONAL = "paused_operational"
    REVIEW_MODE = "review_mode"
    DECOMMISSIONED = "decommissioned"


class StrategyRunner(ABC):
    """Abstract base class for every strategy on the APEX platform.

    Inheritance contract:
    - strategy_id: str — unique identifier; matches the folder at
      services/strategies/<strategy_id>/ and the config file at
      config/strategies/<strategy_id>.yaml.
    - on_panel / on_tick: strategy consumes market data and optionally
      emits Signals (Charter §5.3 panel discipline).
    - health: strategy reports its current StrategyHealthState for
      the STEP 3 StrategyHealthCheck consumer.

    Legacy single-strategy behavior is preserved by LegacyConfluenceStrategy
    (§3.2.2) which wraps services/s02_signal_engine/pipeline.py unchanged.
    """

    strategy_id: str

    @abstractmethod
    def on_panel(self, panel) -> Optional[Signal]:
        """Consume a PanelSnapshot (Phase D) and optionally emit a Signal.

        Panel-driven entry point per Charter §5.3. Returns None when no signal
        is generated.
        """
        raise NotImplementedError

    @abstractmethod
    def on_tick(self, tick: NormalizedTick) -> None:
        """Consume a raw NormalizedTick (legacy compat path).

        Legacy strategies subscribed to Topics.tick(...) call this on every
        tick. Post-Phase-D, panel-native strategies may implement this as a
        no-op and rely exclusively on on_panel.
        """
        raise NotImplementedError

    @abstractmethod
    def health(self) -> StrategyHealthState:
        """Return the strategy's current operational state.

        Consumed by STEP 3 StrategyHealthCheck of the VETO chain (Charter §8.2,
        Playbook §8.0). Implementations should read from the authoritative
        state (typically Redis key strategy_health:<strategy_id>:state)
        rather than from in-process cache, so the state machine semantics
        are coherent across restarts.
        """
        raise NotImplementedError
```

The ABC is **minimal by design** — it expresses only the contract every strategy must honor. Concrete subclasses implement domain-specific logic (feature pipelines, sizing, stops, takes) in their own modules.

**Issues**:

- **"[phase-B.1] Author StrategyRunner ABC at services/strategies/_base.py"** — scope: `services/strategies/_base.py` (new, ~80 LOC) + `tests/unit/strategies/test__base_contract.py` (new, ~40 tests via hypothesis on a fixture subclass).

#### 3.2.2 `LegacyConfluenceStrategy` — wrap the current pipeline

**Location**: `services/strategies/legacy_confluence/service.py` and `services/strategies/legacy_confluence/strategy.py`.

**Scope**: wrap the current `SignalPipeline` at [`services/s02_signal_engine/pipeline.py`](../../services/s02_signal_engine/pipeline.py) (487 LOC per `wc -l`) as a concrete `StrategyRunner` subclass carrying `strategy_id = "default"`. The `service.py` is a thin `BaseService` that instantiates the subclass and routes ticks to it; the existing `services/s02_signal_engine/` module tree remains in place unchanged during Phase B (ripped out only after Phase D.5 Topology Migration).

**Principle 6 assertion**: every integration test that currently passes on `services/s02_signal_engine/` continues to pass against the legacy wrap. The scope-guard test in Phase B's PR verifies that the LegacyConfluenceStrategy's output on a fixture tick stream is bit-identical (within Decimal tolerance) to the pre-Phase-B output.

**Issues**:

- **"[phase-B.2] Wrap current S02 pipeline as LegacyConfluenceStrategy"** — scope: `services/strategies/legacy_confluence/` (new, ~150 LOC) + bit-identical regression test against pre-Phase-B baseline.
- **"[phase-B.3] Migrate LegacyConfluenceStrategy to Topics.signal_for('default', symbol)"** — scope: publisher changes; the legacy `Topics.signal(symbol)` factory continues to work but is no longer used by the wrapped path. A 7-day overlap period is maintained where both topics are published; after 7 days, the legacy publisher is turned off.

#### 3.2.3 `StrategyHealthCheck` state machine — Playbook §8.0 canonical implementation

**Location**: `services/s05_risk_manager/strategy_health_check.py` (during Phase B the risk manager stays at its current S05 path; Phase D.5 moves it to `services/portfolio/risk_manager/`).

**Scope**: implement the 6-state machine defined canonically in Playbook §8.0:

| State | STEP 3 admission |
|---|---|
| `HEALTHY` | ALLOW |
| `DD_KELLY_ADJUSTED` | ALLOW (downstream sizing applies the adjustment) |
| `PAUSED_24H` | REJECT with `BlockReason.STRATEGY_PAUSED` until `pause_until` elapses |
| `PAUSED_OPERATIONAL` | REJECT with `BlockReason.STRATEGY_OPERATIONAL_HALT` until manual clear |
| `REVIEW_MODE` | ALLOW (strategy continues at floored allocation) |
| `DECOMMISSIONED` | REJECT with `BlockReason.STRATEGY_DECOMMISSIONED` permanently |

**Transition table**: the 14 transitions enumerated in Playbook §8.0 are enforced. Property tests in `tests/unit/services/s05_risk_manager/test_strategy_health_check.py` exhaustively verify every allowed transition fires correctly and every disallowed transition raises `ValueError`.

**Redis persistence**: each strategy's state is persisted at Redis key `strategy_health:<strategy_id>:state` with no TTL (state is authoritative and survives container restarts). Transitions are published via structlog event `strategy_health.transition` carrying `{from, to, trigger, timestamp, strategy_id}`.

**New Pydantic model**: `BlockReason.STRATEGY_PAUSED`, `BlockReason.STRATEGY_OPERATIONAL_HALT`, `BlockReason.STRATEGY_DECOMMISSIONED` are added to [`services/s05_risk_manager/models.py`](../../services/s05_risk_manager/models.py) `BlockReason` enum per CLAUDE.md §8 checklist.

**Issues**:

- **"[phase-B.4] Implement StrategyHealthCheck state machine per Playbook §8.0"** — scope: new module + property tests.
- **"[phase-B.5] Extend BlockReason enum with STRATEGY_* reasons"** — scope: `models.py`.
- **"[phase-B.6] Integrate StrategyHealthCheck as STEP 3 of the VETO chain"** — **PARTIALLY OUT OF PHASE B** — Phase B introduces the state machine and its Redis persistence; Phase C wires it into the chain orchestrator as an actual STEP 3 handler (§4.2.3). The decoupling is deliberate: the state machine is an independent unit that can be unit-tested without chain coupling.

#### 3.2.4 Per-strategy dashboard panels in S10

**Location**: [`services/s10_monitor/`](../../services/s10_monitor/) (current). The audit at [`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q8 notes **zero grep hits for "strategy"** in this service.

**Scope**: add per-strategy panels to the dashboard:

- Per-strategy state (current `StrategyHealthState`)
- Per-strategy rolling 7-day / 30-day PnL (consumed from `pnl:<strategy_id>:daily`)
- Per-strategy Kelly adjustment status (`kelly:<strategy_id>:adjust`)
- Per-strategy soft-CB trip count (7-day)
- Per-strategy drift alert log (subscribed to `feedback.drift_alert` with `strategy_id` filtering)

**UI layout**: the existing global panels remain (global equity curve, regime, circuit breaker state, service health grid). A new "Strategies" tab is added, showing one row per active strategy with the per-strategy columns above.

**Heartbeat and alerting**: the alert engine subscribes to `strategy_health.transition` events and pages on any transition into `PAUSED_OPERATIONAL`, `REVIEW_MODE`, or `DECOMMISSIONED`.

**Issues**:

- **"[phase-B.7] Add per-strategy panels to S10 monitor dashboard"** — scope: `services/s10_monitor/dashboard.py` + templates.

### 3.3 Testing discipline (Phase B)

- **ABC contract tests**: `tests/unit/strategies/test__base_contract.py` parametrizes a fixture subclass + the `LegacyConfluenceStrategy` subclass; asserts ABC invariants (every abstract method is overridden, `strategy_id` is set, etc.).
- **State machine property tests**: exhaustive transition coverage via hypothesis, per §3.2.3.
- **Bit-identical regression**: `LegacyConfluenceStrategy` must produce the same `Signal`s and `OrderCandidate`s as the pre-Phase-B `services/s02_signal_engine/pipeline.py` on the 30-day BTCUSDT 1-min fixture.
- **Coverage ≥ 90%** on all new modules; ≥ 85% overall.
- **mypy strict clean; ruff clean; bandit clean**.

### 3.4 Concurrent strategy work

During Phase B, **Strategy #1 Gate 1 PR opens** (weeks 10–14). The Gate 1 PR does not depend on Phase B being complete — it requires only Phase A §2.2.1 (strategy_id on Signal) and Phase A §2.2.2 (Topics.signal_for) — but by week 10 Phase B is far enough along that the Gate 1 PR can reference the `StrategyRunner` ABC in the per-strategy Charter's §10 Operational Interfaces section. See §6.2 for the full Strategy #1 Gate 1 detail.

### 3.5 Phase B exit criteria

Phase B is closed when **all** of the following hold:

- [ ] `StrategyRunner` ABC exists at `services/strategies/_base.py` with contract tests green.
- [ ] ≥ 2 concrete implementations of `StrategyRunner` exist in tests/fixtures — the `LegacyConfluenceStrategy` and a synthetic test fixture — both passing contract tests.
- [ ] `LegacyConfluenceStrategy` wraps the current pipeline; bit-identical regression passes on the 30-day BTCUSDT fixture; LegacyConfluenceStrategy publishes on `Topics.signal_for("default", symbol)` and the legacy `Topics.signal(symbol)` publisher is off (post-7-day-overlap).
- [ ] `StrategyHealthCheck` state machine implemented; 14-transition property tests green; Redis persistence operational.
- [ ] Per-strategy dashboard panels live in S10 and showing state for the single active `LegacyConfluenceStrategy`.
- [ ] ADR-0007 merged (§10.1).
- [ ] CI green; coverage ≥ 85%; mypy strict clean.

### 3.6 Risks and mitigations (Phase B)

| Risk | Impact | Mitigation |
|---|---|---|
| LegacyConfluenceStrategy wrap diverges from pre-Phase-B behavior | Silent alpha-path regression | Bit-identical regression test is blocking; any divergence halts the Phase B PR |
| State machine transitions introduce a deadlock (e.g., PAUSED_OPERATIONAL can only exit via manual clear, but the "manual" path is never implemented in Phase B) | Strategies stuck in paused state | Every manual-clear path has an operator-facing CLI (`scripts/strategy_state_clear.py`) + dashboard button; unit tests assert clear path is implemented for each Manual transition |
| S10 dashboard per-strategy panels slow on N>1 strategies | Dashboard latency | Eventual-consistency SLA (Playbook §7.5 — 30s) explicitly permits dashboard lag; panels use server-side caching; query latency benchmarked before merge |
| Phase B overruns 8 weeks | Strategy #1 Gate 2 slips | Phase B-C overlap (weeks 12-14) absorbs up to 2 weeks slip without propagation |

---

## §4 — Multi-Strat Infrastructure Lift — Phase C (Weeks 12–22)

### 4.1 Goal

Introduce the `StrategyAllocator` microservice (Charter §5.2, §6) implementing Phase 1 Risk Parity allocation; extend the Risk Manager's Chain of Responsibility from its current 6 steps to the Charter-mandated 7-step (STEP 0–7) structure; author ADR-0008 formalizing allocator topology and Risk Parity semantics.

Phase C begins at week 12 (overlapping the last 2 weeks of Phase B) and runs 10 weeks (weeks 12–22; calendar: 2026-07-06 → 2026-09-14). The overlap with Phase B is tight: allocator scaffolding can start while LegacyConfluenceStrategy work concludes, but chain orchestrator changes wait until the `StrategyHealthCheck` state machine from Phase B is merged.

### 4.2 Deliverables

#### 4.2.1 `services/portfolio/strategy_allocator/` microservice

**Location**: created directly in the target topology per CLAUDE.md top-banner guidance ("If the target-state location is already specified in the Charter, create the file directly in the target location"). This service is born in the target topology; it is not an ex-S0N service migrated in Phase D.5.

**Module structure**:

```
services/portfolio/strategy_allocator/
├── __init__.py
├── service.py                  # AllocatorService(BaseService); weekly-rebalance task
├── risk_parity.py              # Phase 1 Risk Parity allocator (inverse-volatility)
├── sharpe_overlay.py           # Phase 2 Sharpe overlay (activates per Charter §6.2.1)
├── ramp.py                     # Cold-start ramp factor per Charter §6.1.3
├── floors_ceilings.py          # 5% floor / 40% ceiling / turnover dampening
├── models.py                   # Pydantic: AllocatorResult, StrategyAllocation
├── config.yaml                 # rebalance cadence, floors, ceilings, beta
└── tests/
    ├── unit/
    │   ├── test_risk_parity.py
    │   ├── test_sharpe_overlay.py
    │   ├── test_ramp.py
    │   ├── test_floors_ceilings.py
    │   └── test_service.py
    └── integration/
        └── test_allocator_weekly_rebalance.py
```

**Phase 1 Risk Parity implementation** (Charter §6.1):

- **Formula**: diagonal-covariance approximation `w_i ∝ 1 / σ_i`, normalized so `Σ_i w_i = 1.0`, per Charter §6.1.1 and §6.1.5.
- **Sigma estimation**: rolling 60-day realized volatility from per-strategy daily PnL, consumed from Redis key `pnl:<strategy_id>:daily` (introduced in Phase A §2.2.5).
- **Rebalance cadence**: weekly, Sunday 23:00 UTC (Charter §6.1.2). Implemented as an `asyncio` task in `AllocatorService` using `datetime.now(timezone.utc)` scheduling (CLAUDE.md §10 compliance).
- **Floor**: 5% per active strategy (Charter §6.1.2).
- **Ceiling**: 40% per strategy (Charter §6.1.2); elevated to 45% for strategies meeting Charter §6.2.3 criteria (Sharpe > 2.0 stable ≥ 6 months).
- **Turnover dampening**: ±25% max weekly weight change per strategy.
- **Edge cases** (Charter §6.1.4): strategies in `review_mode` → floor 5% + excluded from upward tilts; paused strategies → excluded from allocation; N=1 active strategy → 100% allocation; N=0 active strategies → publish `portfolio.allocation.suspended`.

**Cold-start ramp** (Charter §6.1.3):

- Strategies entering Gate 4 live-micro receive a `ramp_factor = min(1.0, 0.20 + (0.80 × d / 60))` where `d` is days post-entry.
- Undersized fraction `(1 - ramp_factor(d))` is redistributed proportionally to other active strategies.
- Ramp terminates at day 60; the Day-60 decision (Playbook §6.3) flips `ramp_factor` to 1.0 on promote or freezes at 0.20 on observation-mode.

**Pydantic model** (authoritative):

```python
# services/portfolio/strategy_allocator/models.py
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from datetime import datetime

class StrategyAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_id: str
    weight_target: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    weight_effective: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    ramp_factor: Decimal = Field(..., ge=Decimal("0.20"), le=Decimal("1"))
    sigma_60d: Decimal
    is_excluded: bool  # paused or review_mode
    excluded_reason: str | None = None

class AllocatorResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    rebalance_ts_utc: datetime
    phase: str  # "phase1_risk_parity" | "phase2_sharpe_overlay"
    total_weight: Decimal  # sanity check; must == 1.0 within tolerance
    allocations: list[StrategyAllocation]
    algorithm_metadata: dict  # {beta, overlay_active, elevated_ceilings, ...}
```

**Topic publishing**:

- `portfolio.allocation.updated` — on every successful rebalance; message is the full `AllocatorResult`.
- `portfolio.allocation.suspended` — when N=0 active strategies or when in portfolio hard-CB halt state.

**Redis writes**:

- `portfolio:allocation:{strategy_id}` — per-strategy effective weight (consumed by STEP 6 `PerStrategyExposureGuard`).
- `portfolio:allocation:meta` — hash with `{last_rebalance_ts, phase, total_weight, n_active_strategies}`.

**Issues**:

- **"[phase-C.1] Scaffold services/portfolio/strategy_allocator/ with BaseService inheritance"**.
- **"[phase-C.2] Implement Risk Parity Phase 1 allocator (inverse-volatility + floors + ceilings + turnover damp)"**.
- **"[phase-C.3] Implement cold-start ramp factor per Charter §6.1.3"**.
- **"[phase-C.4] Weekly rebalance task with Sunday-23:00-UTC schedule"**.
- **"[phase-C.5] Author ADR-0008 Capital Allocator Topology"**.

#### 4.2.2 Extend VETO chain to 7 steps (Charter §8.2)

**Current state**: [`services/s05_risk_manager/chain_orchestrator.py`](../../services/s05_risk_manager/chain_orchestrator.py) (285 LOC) implements a 6-step chain (STEP 0 FailClosed → STEP 1 CBEvent → STEP 2 CircuitBreaker → STEP 3 MetaLabel → STEP 4 PositionRules → STEP 5 ExposureMonitor) per the Batch D refactor. The chain is wired by constructor injection per `__init__(fail_closed=, cb_guard=, circuit_breaker=, meta_gate=, context_load_fn=, decision_builder=)` at [`chain_orchestrator.py:81-96`](../../services/s05_risk_manager/chain_orchestrator.py).

**Target state** (Charter §8.2):

```
STEP 0  FailClosedGuard              [GLOBAL]  (inherited; ADR-0006)
STEP 1  CBEventGuard                 [GLOBAL]  (inherited; cb_event_guard.py)
STEP 2  PortfolioCircuitBreaker      [GLOBAL]  (extended from current circuit_breaker.py)
STEP 3  StrategyHealthCheck          [PER-STRAT]  (NEW — from Phase B §3.2.3)
STEP 4  MetaLabelGate                [PER-STRAT]  (extended: per-strategy model cards)
STEP 5  PerStrategyPositionRules     [PER-STRAT]  (refactor of current position_rules.py)
STEP 6  PerStrategyExposureGuard     [PER-STRAT]  (NEW — reads portfolio:allocation:<id>)
STEP 7  PortfolioExposureMonitor     [GLOBAL]  (refactor of current exposure_monitor.py)
```

The chain grows from **6 numbered steps (STEP 0–5)** to **8 numbered steps (STEP 0–7)** as literally enumerated. The Charter §8.2 titles this "the seven-step VETO Chain of Responsibility" — the `seven-step` naming refers to the seven gate transitions post-STEP 0 (i.e., 7 distinct gates after the global fail-closed gatekeeper). This Roadmap preserves the Charter's terminology.

**Refactor requirement — data-driven chain**: the audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q5) flagged the current chain orchestrator as Open/Closed-violating (hardcoded injection; adding a step requires modifying `__init__` signature AND `process()` method). Phase C refactors the orchestrator to accept `guards: list[RiskGuard]` where `RiskGuard` is a new ABC:

```python
# services/s05_risk_manager/risk_guard.py
from __future__ import annotations
from abc import ABC, abstractmethod

from services.s05_risk_manager.models import RuleResult
from core.models.order import OrderCandidate

class RiskGuard(ABC):
    name: str
    step: int  # STEP 0 through STEP 7 per Charter §8.2
    scope: str  # "GLOBAL" or "PER_STRATEGY"

    @abstractmethod
    async def check(
        self,
        candidate: OrderCandidate,
        context: dict,
    ) -> RuleResult:
        raise NotImplementedError
```

Each existing guard (`FailClosedGuard`, `CBEventGuard`, `CircuitBreaker`, `MetaLabelGate`, position/exposure helper functions) is refactored to inherit from `RiskGuard`. The orchestrator becomes:

```python
# services/s05_risk_manager/chain_orchestrator.py (post-refactor)
class RiskChainOrchestrator:
    def __init__(self, guards: list[RiskGuard], context_load_fn, decision_builder):
        # Sort by step; verify exactly one guard per step 0-7
        self._guards = sorted(guards, key=lambda g: g.step)
        self._validate_chain_integrity()

    async def process(self, candidate: OrderCandidate) -> RiskDecision:
        ctx = await self._context_load_fn(candidate.symbol, candidate.strategy_id)
        rule_results = []
        for guard in self._guards:
            result = await guard.check(candidate, ctx)
            rule_results.append(result)
            if not result.passed:
                return await self._builder.build_blocked(candidate, rule_results, ..., result.block_reason, ...)
        return await self._builder.build_approved(candidate, rule_results, ...)
```

**New guards in Phase C**:

1. **`StrategyHealthCheck`** (STEP 3) — inherits Playbook §8.0 semantics from Phase B §3.2.3; reads Redis `strategy_health:<strategy_id>:state`; admits or rejects per state.
2. **`PerStrategyPositionRules`** (STEP 5) — refactor of current `position_rules.py` functions with per-strategy parameterization: max size, max risk per trade, max open positions, max inter-position correlation within strategy. Parameters loaded from `config/strategies/<strategy_id>.yaml` at service start.
3. **`PerStrategyExposureGuard`** (STEP 6) — NEW; reads `portfolio:allocation:<strategy_id>` from Redis (written by the allocator in §4.2.1). Rejects candidates that would push the strategy's notional exposure past its current allocated envelope.
4. **`PortfolioExposureMonitor`** (STEP 7) — refactor of current `exposure_monitor.py` (check_max_positions, check_total_exposure, check_per_class_exposure, check_correlation). Now reads portfolio-level exposure across all strategies (not single-book).

**Issues**:

- **"[phase-C.6] Introduce RiskGuard ABC; refactor chain_orchestrator.py to data-driven"**.
- **"[phase-C.7] Migrate existing 6 guards to RiskGuard ABC subclass pattern"**.
- **"[phase-C.8] Implement StrategyHealthCheck as STEP 3 RiskGuard"** (inherits Phase B state machine).
- **"[phase-C.9] Implement PerStrategyExposureGuard as STEP 6 RiskGuard"**.
- **"[phase-C.10] Refactor PortfolioExposureMonitor to portfolio-level (STEP 7)"**.
- **"[phase-C.11] Extend chain to 7 steps with STEP 3–7 wiring"**.

#### 4.2.3 Geopolitical guard from PHASE_5_SPEC_v2.md §3.6 integration

The 5.8 Geopolitical NLP Overlay (GDELT + FinBERT) from PHASE_5_SPEC_v2.md §3.6 introduces a `GeopoliticalGuard`. Its placement in the new 7-step chain:

- The Charter's 7-step chain does not explicitly enumerate geopolitical as a step. The operationally correct placement is **alongside STEP 1 CBEventGuard** (both are temporal/event-window guards) OR **as a branch of STEP 7 PortfolioExposureMonitor** (both are portfolio-level protective guards).
- **Phase C decision** (ratified via ADR-0008 §6): GeopoliticalGuard runs as an **extension of STEP 1 CBEventGuard** — the semantics are coherent (both block new trades when an exogenous event warrants precautionary halt) and no additional step number is introduced (Charter §8.2 structure preserved).

This preserves Charter §8.2's step count while integrating the PHASE_5_SPEC_v2 carryover.

### 4.3 Testing discipline (Phase C)

- **Allocator property tests** on `risk_parity.py`: given any volatility vector `σ ∈ (0, ∞)^N`, output weights sum to 1.0 within Decimal tolerance; floor/ceiling respected; turnover dampening respected; N=1 degenerate case returns `[1.0]`.
- **Allocator regression tests** for the Charter §6.4 worked example: σ = (35%, 18%, 10%, 28%, 8%, 22%) must produce weights (7.3%, 14.2%, 25.6%, 9.1%, 32.0%, 11.6%) within Decimal tolerance.
- **RiskGuard ABC contract tests**: parametrize across all 7 concrete guards; assert each guard's `check()` returns a valid `RuleResult`, each guard's `step` is unique in [0, 7], each guard's `scope` is one of {GLOBAL, PER_STRATEGY}.
- **Chain orchestrator property tests**: with 7 guards (one per step), 7-step chain rejects correctly for each of the 7 possible per-step failure reasons.
- **Chain latency benchmark**: <5ms p99 latency preserved (Charter §8.3 implicit). Benchmark harness at `tests/bench/test_chain_latency.py`.
- **Coverage ≥ 90%** on new allocator modules and new risk guards; ≥ 85% overall.
- **mypy strict clean; ruff clean; bandit clean**.

### 4.4 Concurrent strategy work

- **Weeks 12–14**: Phase B closes; Strategy #1 Gate 1 PR under review.
- **Weeks 14–18**: Strategy #1 Gate 2 work begins (per §6.3) — microservice at `services/strategies/crypto_momentum/`, CPCV runs, 10 stress tests. Strategy #1 Gate 2 PR cannot merge until Phase C §4.2.1 allocator scaffolding is complete (strategy must participate in allocator-aware tests).
- **Weeks 18–22**: Strategy #1 Gate 2 PR review/merge; Strategy #1 Gate 3 paper trading begins immediately after.

### 4.5 Phase C exit criteria

- [ ] `services/portfolio/strategy_allocator/` microservice running; weekly rebalance task scheduled.
- [ ] Risk Parity Phase 1 allocator produces weights for a 3-strategy test fixture matching Charter §6.4 worked example within Decimal tolerance.
- [ ] Cold-start ramp factor computed correctly at day 0, 7, 14, 30, 45, 60 per Charter §6.1.3 table.
- [ ] `RiskGuard` ABC exists; all existing guards refactored as `RiskGuard` subclasses.
- [ ] Chain orchestrator is data-driven (`__init__(guards: list[RiskGuard])`).
- [ ] 7-step chain (STEP 0–7) operational; property tests rejecting correctly at each step.
- [ ] Chain latency p99 < 5ms on benchmark fixture.
- [ ] `PerStrategyExposureGuard` reads `portfolio:allocation:<strategy_id>` and rejects candidates past envelope.
- [ ] `portfolio.allocation.updated` events published on weekly cadence; observable in S10 dashboard.
- [ ] ADR-0008 merged.
- [ ] CI green; coverage ≥ 85%; mypy strict clean.

### 4.6 Risks and mitigations (Phase C)

| Risk | Impact | Mitigation |
|---|---|---|
| RiskGuard ABC refactor regresses existing 6-step chain behavior | Live orders silently blocked or admitted incorrectly | Bit-identical regression test against pre-refactor chain behavior on the existing fixture set |
| Risk Parity allocator produces weights outside floor/ceiling (numerical edge case) | Strategy receives 0% or > 40% allocation | Property tests exhaustively hit boundary conditions; CI assertion `assert floor ≤ weight ≤ ceiling` on every allocator output |
| Weekly rebalance Sunday-23:00-UTC fires during a portfolio hard-CB halt | Allocator publishes new weights during halt | `AllocatorService.run_rebalance()` reads `risk:circuit_breaker:state` first; if `HARD_TRIPPED`, publishes `portfolio.allocation.suspended` and skips rebalance |
| Chain latency regresses past 5ms p99 | Live trading slower than current baseline | Benchmark harness fails CI if p99 > 5ms; optimization done before merge |
| Phase C overruns 10 weeks | Strategy #1 Gate 2 slips; Gate 3 paper delayed | Phase C-D overlap (weeks 18-22) absorbs up to 2 weeks slip |

---

## §5 — Multi-Strat Infrastructure Lift — Phase D (Weeks 18–28)

### 5.1 Goal

Introduce the `PanelBuilder` microservice (Charter §5.3) that aggregates multi-asset snapshots consumed by every strategy; partition the feedback loop by `strategy_id` so drift detection operates independently per strategy (Charter §5.5); add the `run_portfolio` entry point to the backtest engine so Gate 2 CPCV runs can produce cross-strategy correlation matrices; author ADR-0009 (panel discipline) and ADR-0010 (topology reorganization).

Phase D begins at week 18 (overlapping the last 4 weeks of Phase C) and runs 10 weeks (weeks 18–28; calendar: 2026-08-24 → 2026-11-02). Phase D.5 (topology migration) is scheduled as a **contained mini-phase** during weeks 26–28, separated from the rest of Phase D to minimize merge-conflict surface.

### 5.2 Deliverables

#### 5.2.1 `services/data/panels/` microservice

**Location**: created directly in the target topology per CLAUDE.md top-banner guidance.

**Module structure**:

```
services/data/panels/
├── __init__.py
├── service.py                  # PanelBuilderService(BaseService)
├── universe.py                 # Universe registry (crypto_top20, multi_asset_trend, etc.)
├── snapshot.py                 # PanelSnapshot Pydantic model (frozen)
├── aggregator.py               # Per-universe tick/bar → panel reducer
├── staleness.py                # Staleness tolerance + fail-closed on universe timeout
├── config.yaml                 # Universe registry, tolerance settings, rebalance cadence
└── tests/
    ├── unit/
    │   ├── test_snapshot_schema.py
    │   ├── test_universe_registry.py
    │   ├── test_aggregator.py
    │   └── test_staleness.py
    └── integration/
        └── test_panel_publishing_e2e.py
```

**PanelSnapshot Pydantic model** (authoritative — ADR-0009 §2):

```python
# services/data/panels/snapshot.py
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from datetime import datetime

class AssetSnapshot(BaseModel):
    """Single asset's point-in-time snapshot within a panel."""
    model_config = ConfigDict(frozen=True)
    symbol: str
    timestamp_ms: int = Field(..., gt=0)
    last_price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume_24h: Decimal | None = None
    features: dict[str, Decimal] = Field(default_factory=dict)

class PanelSnapshot(BaseModel):
    """Multi-asset point-in-time panel consumed by StrategyRunner.on_panel()."""
    model_config = ConfigDict(frozen=True)
    universe_id: str  # e.g., "crypto_top20", "multi_asset_trend", "sp500_liquid"
    snapshot_ts_utc: datetime
    panel_seq: int  # monotonic; strategy can detect missed snapshots
    assets: list[AssetSnapshot]
    cross_sectional_metadata: dict = Field(default_factory=dict)
    is_stale: bool = False
    stale_reason: str | None = None
```

**Subscribe/publish contract**:

- Subscribes to `tick.crypto.*`, `tick.us_equity.*`, `tick.futures.*` per universe configuration.
- Publishes on `panel.{universe_id}` (e.g., `panel.crypto_top20`, `panel.multi_asset_trend`, `panel.sp500_liquid`).
- Snapshot cadence per universe: configurable in `config.yaml`, e.g., 1-second snapshots for crypto intraday strategies, daily snapshots for trend-following and macro strategies.

**Staleness tolerance** (fail-closed per ADR-0006 pattern):

- Each asset in a universe has a `max_tick_lag_seconds` threshold in `config.yaml`.
- If any asset in a universe exceeds its threshold on snapshot emission, the snapshot is marked `is_stale=True` with `stale_reason` naming the asset(s).
- Strategies consuming a stale snapshot are expected to return `None` from `on_panel(panel)` (i.e., no signal produced on stale data). This is enforced via contract tests per `StrategyRunner` ABC.

**Point-in-time correctness** (Charter §5.3):

- The aggregator buffers incoming ticks with their `timestamp_ms`. On snapshot emit at time `T`, each asset's last tick at or before `T` (within tolerance) is selected. Ticks arriving after snapshot emit are buffered for the next snapshot.
- Cross-sectional features (rank, dispersion, cross-asset correlation) are computed on the snapshot itself, not on ticks arriving later.

**Issues**:

- **"[phase-D.1] Scaffold services/data/panels/ with PanelSnapshot Pydantic model"**.
- **"[phase-D.2] Implement per-universe aggregator with point-in-time discipline"**.
- **"[phase-D.3] Staleness tolerance + fail-closed on universe timeout"**.
- **"[phase-D.4] Author ADR-0009 Panel Builder Discipline"**.

#### 5.2.2 Per-strategy feedback loop partitioning

**Scope**: extend [`services/s09_feedback_loop/drift_detector.py`](../../services/s09_feedback_loop/drift_detector.py) (160 LOC) to operate per strategy. Currently, `DriftDetector.check_drift(recent_trades, baseline_win_rate)` is strategy-agnostic; it pools all trades globally.

**Changes** ([`services/s09_feedback_loop/drift_detector.py:35-80`](../../services/s09_feedback_loop/drift_detector.py)):

1. **New method** `check_drift_per_strategy(strategy_id, recent_trades, baseline_win_rate)` — same semantics as `check_drift` but tagged with `strategy_id`. The legacy `check_drift` continues to work on the `"default"` strategy until Phase D.5.
2. **DriftAlert gains `strategy_id`** field (requires Pydantic model update — already compatible after Phase A §2.2.1 `strategy_id` adoption discipline).
3. **Baseline source** per Charter §5.5: reads `trades:<strategy_id>:all` (introduced in Phase A §2.2.5) instead of global `trades:all`. Baseline rolls forward across 3-month trailing windows captured during Gate 3 paper trading (Playbook §5.2.3).

**Minimum-sample floor**: the existing `MIN_TRADES = 50` ([drift_detector.py:43](../../services/s09_feedback_loop/drift_detector.py)) stays per strategy. A strategy with < 50 completed trades since baseline capture does not receive drift alerts (this is intentional statistical discipline — noise dominates below 50 trades).

**Drift threshold**: the existing `DRIFT_THRESHOLD = 0.10` ([drift_detector.py:42](../../services/s09_feedback_loop/drift_detector.py)) stays per strategy at Phase D default; per-strategy overrides may be introduced in later phases via `config/strategies/<strategy_id>.yaml`.

**Issues**:

- **"[phase-D.5] Extend DriftDetector to per-strategy partitioning"**.
- **"[phase-D.6] Per-strategy baseline capture in S09 trade_analyzer"**.
- **"[phase-D.7] DriftAlert carries strategy_id field"**.

#### 5.2.3 Backtest portfolio runner

**Scope**: add a `run_portfolio` entry point to the backtest engine consumable by Gate 2 CPCV runs per Playbook §4.2.1.

**New module**: `backtesting/portfolio_runner.py`:

```python
# backtesting/portfolio_runner.py (new)
from __future__ import annotations
from decimal import Decimal
from dataclasses import dataclass

from core.models.tick import NormalizedTick
from core.models.order import TradeRecord
from services.strategies._base import StrategyRunner  # from Phase B
# Optional allocator injection: None → equal-weight; else → allocator-driven sizing
AllocatorLike = "RiskParityAllocator | None"  # typed in real impl

@dataclass(frozen=True)
class PortfolioResult:
    per_strategy_trades: dict[str, list[TradeRecord]]  # strategy_id → trades
    by_strategy_breakdown: dict[str, dict]  # strategy_id → full_report dict
    cross_strategy_correlation: dict  # off-diagonal matrix + HHI
    aggregate_full_report: dict  # portfolio-level full_report
    portfolio_equity_curve: list[float]
    n_strategies: int

def run_portfolio(
    strategies: list[StrategyRunner],
    ticks: list[NormalizedTick],
    initial_capital_per_strategy: Decimal,
    allocator: "RiskParityAllocator | None" = None,
) -> PortfolioResult:
    """Replay a tick stream across N strategies concurrently.

    Each strategy receives the same tick stream; each generates its own
    OrderCandidates; allocator (optional) combines them into a portfolio
    position. Returns per-strategy and aggregate metrics.
    """
    ...
```

**Integration with existing backtest engine**:

- The existing [`backtesting/engine.py`](../../backtesting/engine.py) and single-strategy `run()` remain unchanged (Principle 6).
- `run_portfolio` is additive; it composes N `BacktestEngine` instances (one per strategy), feeds the same tick stream, merges trade records per `strategy_id`, and computes aggregate metrics.

**Extension to `full_report`**: [`backtesting/metrics.py`](../../backtesting/metrics.py) (1774 LOC) gets a new `by_strategy_breakdown` field in the `full_report` output — a `dict[strategy_id, SingleStrategyReport]` where `SingleStrategyReport` is the existing `full_report` output computed on the strategy's trade list. Plus a `cross_strategy_correlation` field containing the off-diagonal correlation matrix and its Herfindahl-Hirschman Index (HHI) concentration measure.

**CPCV integration**: the [`backtesting/walk_forward.py:CombinatorialPurgedCV`](../../backtesting/walk_forward.py) (533 LOC) currently operates on a single strategy. Phase D adds a `CombinatorialPurgedCV.run_portfolio(strategies=[...], ...)` method that runs CPCV across the portfolio — each fold runs `run_portfolio` on the fold's test data and returns per-strategy + aggregate PBO, OOS Sharpe median.

**Issues**:

- **"[phase-D.8] Implement run_portfolio in backtesting/portfolio_runner.py"**.
- **"[phase-D.9] Add by_strategy_breakdown + cross_strategy_correlation to full_report"**.
- **"[phase-D.10] Extend CPCV to portfolio mode"**.

#### 5.2.4 ADR-0010 — Target Topology Reorganization (documented only; physical migration in Phase D.5)

**Scope**: author ADR-0010 which ratifies the topology migration per Charter §5.4. The ADR documents:

- The full mapping from `services/s01-s10/` to `services/{data,signal,portfolio,execution,research,ops,strategies}/` (enumerated at §10.4).
- The migration procedure: staged PRs per domain (one PR per `services/<domain>/` target), with `git mv` preserving file history.
- The rollback procedure: each staged PR is individually revertible; until the final migration PR merges, both old and new paths coexist.
- Import-path shim semantics: during migration, old-path imports (`from services.s05_risk_manager import ...`) continue to work via a `__init__.py` redirect; new imports (`from services.portfolio.risk_manager import ...`) are the target. The shim is removed in the final migration PR.

**Physical migration is scheduled for Phase D.5** (§5.5) to contain its merge-conflict surface.

### 5.3 Testing discipline (Phase D)

- **PanelSnapshot property tests**: frozen, round-trips via JSON, invariants on `is_stale` semantics.
- **Aggregator regression tests** on fixed tick streams producing fixed panel outputs (determinism).
- **Staleness tests** simulating asset tick lag > threshold → `is_stale=True`; verifying strategies ignore stale panels.
- **DriftDetector per-strategy tests** verifying two concurrent strategies with different win rates produce independent alerts.
- **`run_portfolio` regression tests** verifying equal-weight-no-allocator behavior matches concatenated single-strategy runs.
- **Cross-strategy correlation test** on a synthetic pair (Strategy A = +alpha, Strategy B = -alpha) showing correlation < 0 computed correctly.
- **ADR-0010 dry-run test**: a test that constructs the target topology import graph and verifies every import resolves (without performing the `git mv`).
- **Coverage ≥ 90%** on new modules; ≥ 85% overall.

### 5.4 Phase D exit criteria (excluding D.5)

- [ ] `services/data/panels/` microservice live; emits `panel.{universe_id}` snapshots on configurable cadence.
- [ ] At least one universe (`crypto_top20`, Strategy #1's universe) operational with real Binance tick data.
- [ ] Per-strategy DriftDetector partitioning active; 2+ concurrent fixtures tested.
- [ ] `backtesting.portfolio_runner.run_portfolio` works on a 3-strategy test fixture producing `by_strategy_breakdown` + `cross_strategy_correlation`.
- [ ] CPCV portfolio mode operational.
- [ ] ADR-0009 merged.
- [ ] ADR-0010 merged (documentation-only; physical migration in D.5).
- [ ] CI green; coverage ≥ 85%; mypy strict clean.

### 5.5 Phase D.5 — Topology Migration (Weeks 26–28)

**Goal**: physically reorganize `services/s01-s10/` into the Charter §5.4 target topology per ADR-0010. This is a mechanical migration: `git mv` + import-path fixups, no behavior changes.

**Why a separate mini-phase**: the migration touches every service in the repository; doing it in parallel with in-flight Strategy #1 Gate 3 or any Strategy #2 work would create massive merge-conflict surface. Phase D.5 is scheduled immediately after Phase D's substantive work completes and before Strategy #1 Gate 4 begins in earnest.

**Mapping** (full table — authoritative; ADR-0010 §3):

| Current path | Target path |
|---|---|
| `services/s01_data_ingestion/` | `services/data/ingestion/` |
| `services/s02_signal_engine/` | `services/signal/engine/` (legacy confluence retained as strategy runner post-Phase B) |
| `services/s03_regime_detector/` | `services/signal/regime_detector/` |
| `services/s04_fusion_engine/` | `services/signal/fusion/` |
| `services/s05_risk_manager/` | `services/portfolio/risk_manager/` |
| `services/s06_execution/` | `services/execution/engine/` |
| `services/s07_quant_analytics/` | `services/signal/quant_analytics/` |
| `services/s08_macro_intelligence/` | `services/data/macro_intelligence/` |
| `services/s09_feedback_loop/` | `services/research/feedback_loop/` |
| `services/s10_monitor/` | `services/ops/monitor_dashboard/` |

**New services born in Phase C/D** are already in target topology:

- `services/portfolio/strategy_allocator/` (Phase C).
- `services/data/panels/` (Phase D).
- `services/strategies/<boot_strategies>/` (introduced per-strategy at Gate 2; Phase B wrapper is at `services/strategies/legacy_confluence/`).

**Migration procedure** (staged; ADR-0010 §4):

1. **PR 1 — `services/data/` domain**: `git mv` of `s01_data_ingestion/` → `data/ingestion/` and `s08_macro_intelligence/` → `data/macro_intelligence/`. Import-path shims added at the old paths. CI green.
2. **PR 2 — `services/signal/` domain**: `git mv` of `s02_signal_engine/`, `s03_regime_detector/`, `s04_fusion_engine/`, `s07_quant_analytics/` into `services/signal/`. Shims.
3. **PR 3 — `services/portfolio/` domain**: `git mv` of `s05_risk_manager/` → `portfolio/risk_manager/`. Shims.
4. **PR 4 — `services/execution/` domain**: `git mv` of `s06_execution/` → `execution/engine/`. Shims.
5. **PR 5 — `services/research/` domain**: `git mv` of `s09_feedback_loop/` → `research/feedback_loop/`. Shims.
6. **PR 6 — `services/ops/` domain**: `git mv` of `s10_monitor/` → `ops/monitor_dashboard/`. Shims.
7. **PR 7 — remove shims**: delete the `services/s0N/__init__.py` redirect shims. All imports now reference the new paths directly.

Each PR is individually revertible. The supervisor/orchestrator startup order (CLAUDE.md §8 checklist, Charter §5.9) is updated in PR 7 to match the new topology.

**Rollback procedure** (ADR-0010 §5):

- **Pre-PR-7**: any staged PR can be reverted; shims make the revert binary.
- **Post-PR-7**: revert is more invasive but still mechanical — `git revert` the shim-removal PR restores shims; subsequent `git revert`s reverse the individual domain moves.

**Git history preservation**: every move uses `git mv` (not manual delete+create). `git log --follow <new-path>` traces back through the move.

**Phase D.5 exit criteria**:

- [ ] All 10 former S01-S10 services live at their target domain paths.
- [ ] All imports reference target paths (no shims remain).
- [ ] Supervisor startup order updated to match target topology (Charter §5.9).
- [ ] CI green across all PRs.
- [ ] Integration test fixtures passing unchanged on new paths.

### 5.6 Concurrent strategy work (during Phase D + D.5)

- **Weeks 18–22**: Strategy #1 Gate 2 PR under review/merge (per §6.3). Gate 2 microservice is born at `services/strategies/crypto_momentum/` (target topology).
- **Weeks 22–26**: Strategy #1 Gate 3 paper trading runs (§6.4) against the Phase D-native panel builder once live.
- **Weeks 26–28**: Phase D.5 migration runs. Strategy #1 paper continues unaffected (its target-topology path doesn't change). Strategy #2 Gate 1 informal research begins in parallel.

### 5.7 Risks and mitigations (Phase D + D.5)

| Risk | Impact | Mitigation |
|---|---|---|
| PanelBuilder introduces latency between tick and strategy on_panel call | Strategy signal latency increases vs current tick-native path | Benchmark: panel publish → strategy on_panel < 50ms p99. The current tick-to-signal baseline is 10-30ms; a 50ms budget is acceptable for mid-frequency strategies and matches Charter §5.3 stance |
| Staleness tolerance triggers too often during normal venue hiccups | Strategies produce no signals; operational complaints | Start with generous `max_tick_lag_seconds` (e.g., 30s for crypto); tune down based on 30 days of live panel data |
| DriftDetector per-strategy partitioning misses cross-strategy drift patterns (e.g., all strategies degrade together) | Correlated-risk failures not caught | Cross-strategy correlation check happens at monthly review (Playbook §7.3) and triggers 3-strategies-DEGRADED hard CB (Charter §8.1.2) |
| Phase D.5 migration PR breaks imports mid-stream | Some services fail to start | Each PR is individually CI-green before merge; shims provide immediate fallback; supervisor starts services in startup-order to catch early failures |
| Phase D.5 runs simultaneously with Strategy #1 Gate 3 paper trading | Paper trading disrupted | Strategy #1 is already at target-topology path (`services/strategies/crypto_momentum/`); migration does not touch it |

---

## §6 — Strategy #1 — Crypto Momentum Lifecycle (Weeks 10–36)

### 6.1 Overview

Strategy #1 is **Crypto Momentum** per Charter §4.1 and Playbook §2.4.1. Its lifecycle is the prototype that validates the entire multi-strat pipeline end-to-end before the platform commits to Strategies #2–#6. Every gate transition for Strategy #1 is a platform milestone, not merely a strategy milestone.

**Timeline anchor** (Playbook §1.2 floors applied):

| Stage | Window (weeks from Charter) | Gate criteria (Playbook) |
|---|---|---|
| Informal research | 1–10 | N/A (preparatory) |
| Gate 1 PR open | 10 | §3.1 entry criteria |
| Gate 1 PR review + merge | 10–14 | §3.2 deliverables |
| Gate 2 PR open | 14 | §4.1 entry criteria |
| Gate 2 PR review + merge | 14–18 | §4.2 deliverables |
| Gate 3 paper trading start | 18 | §5.1 entry criteria |
| Gate 3 paper trading closeout | 26 (8 weeks minimum) | §5.3 all criteria simultaneous |
| Gate 4 live-micro Day 0 | 27 | §6.1 entry criteria + capital seed |
| Gate 4 ramp | 27–36 (60 calendar days) | §6.2 ramp logic |
| Day-60 decision | 36 | §6.3 70% threshold |
| Live Full | 37+ | §7 steady state |

Total wall-clock from Charter ratification to Live Full: **~37 weeks = 8.5 months**. This matches the Playbook §1.2 "5-8 months for the first strategy" envelope.

### 6.2 Gate 1 — Research → Approved Backtest (Weeks 10–14)

**Dependencies satisfied**:

- Phase A complete (§2.6) — `strategy_id` available on `Signal` and `OrderCandidate`; `Topics.signal_for` available.
- Phase B NOT strictly required for Gate 1 (notebook-only evidence per Playbook §3.2.2).

**Deliverables** (Playbook §3.2 verbatim):

1. **Per-strategy Charter draft** at `docs/strategy/per_strategy/crypto_momentum.md` — §1–§4 fully populated (identity, thesis, universe and timeframes, required features and data).
2. **Research notebook** at `notebooks/research/crypto_momentum/gate1_backtest.ipynb` — 5 sections per Playbook §3.2.2.
3. **Backtest artifact** at `reports/crypto_momentum/gate1/full_report.json`.
4. **Required metrics** (Charter §7.1 thresholds — all simultaneous):
   - Backtest span ≥ 2 years (target: 2023-01-01 → 2025-12-31, ~3 years)
   - Historical Sharpe (daily) > 1.0 (academic baseline 0.8–1.4 per Liu & Tsyvinski 2021)
   - Historical max DD < 15%
   - PSR > 95%
   - PBO < 0.5 (CPCV preview, N=6, k=2)
5. **ADR-0002 10-point evaluation checklist** — all 10 items checked (Playbook §3.2.5).
6. **Thesis defense** (≤ 500 words) in PR body (Playbook §3.2.6).

**Gate 1 PR**: titled `[crypto_momentum] Gate 1 — Research → Approved Backtest`.

**Reviewers** (Playbook §3.3): CIO (strategic fit + Charter draft §1–§4) + Head of Strategy Research (statistical soundness + ADR-0002 checklist) + Claude Code Implementation Lead (assembles evidence) + CI (mechanical gates).

**Success signal**: PR merged → `crypto_momentum` formally enters Gate 2 pipeline.

### 6.3 Gate 2 — Approved Backtest → Paper Trading (Weeks 14–18)

**Dependencies satisfied**:

- Phase A complete (strategy_id + topics + Redis keys).
- Phase B substantially complete (StrategyRunner ABC available; StrategyHealthCheck state machine available; LegacyConfluenceStrategy wrap confirms pattern).
- Phase C in progress (allocator operational in test-fixture mode; 7-step chain scaffolding in place). **Phase C full completion is required for Gate 2 PR merge** — the smoke test (Playbook §4.2.5) exercises STEP 6 `PerStrategyExposureGuard` which requires the allocator writing `portfolio:allocation:crypto_momentum`.

**Deliverables** (Playbook §4.2 verbatim):

1. **CPCV walk-forward OOS evidence** — `reports/crypto_momentum/gate2/cpcv_result.json` with `oos_sharpe_median > 0.8` and `pbo < 0.5` and `recommendation == DEPLOY` (Playbook §4.2.1).
2. **10 canonical stress scenarios** — `reports/crypto_momentum/gate2/stress_tests.json`; all 10 PASS per category budgets (Medium Vol: max DD 12%) per Playbook §4.2.2. Structural exemption: scenario #4 (SNB-class FX shock) — documented in per-strategy Charter §9 per Playbook §4.2.2.
3. **Production microservice** at `services/strategies/crypto_momentum/` per Playbook §4.2.3:
   - `service.py` — `CryptoMomentumService(BaseService)` subscribing to `panel.crypto_top20` (or raw `tick.crypto.*` until Phase D lands, per Charter §5.3 transitional note).
   - `signal_generator.py` — `CryptoMomentumStrategy(StrategyRunner)` implementing `on_panel` (and `on_tick` for legacy path).
   - `config.yaml` — universe, 3/7/14/30-day lookbacks, Kelly fraction 0.4 (Medium Vol default), ATR-based stop multipliers, top-quintile/bottom-quintile ranking thresholds.
   - `README.md` — 1-page operator note.
   - `tests/unit/` + `tests/integration/`.
4. **Test coverage ≥ 90%** on the new strategy microservice + any new feature calculators.
5. **Operational smoke test** per Playbook §4.2.5 — service starts, heartbeats, subscribes, publishes `order.candidate` with `strategy_id="crypto_momentum"`, observable by the Risk Manager through the 7-step chain.
6. **Per-strategy Charter ratification** at Gate 2 PR merge (Playbook §4.2.6) — CIO signs §11.
7. **Human code review + Copilot auto-review** cleared (Playbook §4.2.7).

**Concurrent Phase C dependency**: allocator must be writing `portfolio:allocation:crypto_momentum` by the smoke-test step. Since Strategy #1 is the only active strategy at this point, the allocator degenerate case (N=1 → 100% allocation) applies (Charter §6.1.4).

**Gate 2 PR**: titled `[crypto_momentum] Gate 2 — Approved Backtest → Paper Trading`.

**Reviewers** (Playbook §4.3): CIO (Charter §11 sign-off, signal_generator.py thesis fidelity, stress tests) + Head of Strategy Research (CPCV methodology, stress methodology) + CI.

**Success signal**: PR merged → `crypto_momentum` deployed to paper-trading environment within 24h; Gate 3 8-week clock starts.

### 6.4 Gate 3 — Paper Trading → Live Micro (Weeks 18–26)

**Dependencies satisfied**:

- Phase C complete.
- Phase D must land during the paper period (weeks 18–22 is the Phase D substantive window). Strategy #1 begins paper on tick-native path; transitions to panel-native consumption when the `services/data/panels/` service goes live during weeks 18–22.

**Paper trading period** (Playbook §5.2):

- **Minimum 8 weeks** AND **≥ 50 trades**. For Crypto Momentum with 4h–24h signal horizon on top-20 USDT pairs, trade count floor typically reaches 50 within 2–3 weeks; the 8-week floor binds. Target: ~260 trades over 8 weeks per Playbook §5.6.1 worked example.
- **Daily dashboard review** (Playbook §5.2.2 active responsibilities).
- **No parameter tuning during paper** (Playbook §5.2.2 prohibitions — frozen at Gate 2).
- **No pod crash during the final valid 8-week window** (Playbook §5.2.4 — clock resets on crash, limit 3 resets).

**Deliverables** (Playbook §5.3 — all simultaneous):

- Duration ≥ 8 weeks AND trades ≥ 50.
- Paper Sharpe > 0.8 over full period.
- Paper max DD < 10% (tighter than Medium Vol category max 12% — Playbook §5.3.2).
- Win rate consistent with backtest (±10%).
- Zero pod crashes during final valid 8-week window.
- Observability green: dashboard panels functional, drift baseline captured (Playbook §5.2.3).

**Paper evidence package** at `reports/crypto_momentum/gate3/paper_evidence_v1.0.md` per Playbook §5.4.1.

**Gate 3 PR** (evidence-only; microservice already deployed): titled `[crypto_momentum] Gate 3 — Paper Evidence Package`. PR body uses Playbook §5.4.1 template.

**Reviewers**: CIO (final signoff, paper-to-live decision per Playbook §5.4.2) + Head of Strategy Research.

**Success signal**: CIO signs "PROMOTED TO GATE 4" decision in the paper evidence package §7; `crypto_momentum` scheduled for live-micro deployment within 5 working days.

### 6.5 Gate 4 — Live Micro → Live Full (Weeks 27–36)

**Dependencies satisfied**:

- Phase D complete.
- Phase D.5 migration substantially complete (weeks 26–28). Strategy #1 is at target-topology path `services/strategies/crypto_momentum/` throughout (was born there in Gate 2 per §6.3); migration does not touch it.

**Live micro phase** (Playbook §6.2, Charter §6.1.3):

- **Day 0** (week 27): live-micro PR merged; allocator includes Strategy #1 with `ramp_factor(0) = 0.20`; Binance live credentials configured; capital seed confirmed.
- **Days 0–60** (weeks 27–36 — exactly 60 calendar days): linear ramp from 20% to 100% of target allocation.
- **Daily operator monitoring** (Playbook §6.2.2): live Sharpe vs paper Sharpe; live max DD vs paper max DD; cost realization; heartbeat health.
- **Weekly allocator rebalance** (Sunday 23:00 UTC per Charter §6.1.2).
- **Intervention rules** (Playbook §6.2.3): no parameter tuning; no ramp override; no allocator override; pause only for confirmed bug or soft CB trigger.

**Day-60 decision** (Playbook §6.3, Charter §7.4):

- If **live Sharpe > 70% of paper Sharpe** → **Live Full**. Allocator releases ramp factor; standard Risk Parity sizing applies.
- Otherwise → **observation mode** at 20% allocation indefinitely until CIO decision.

**Day-60 evidence package** at `reports/crypto_momentum/gate4/day60_evidence.md` per Playbook §6.3.2.

**Gate 4 PR**: titled `[crypto_momentum] Gate 4 — Day-60 Evidence Package`.

**Reviewers**: CIO (binding decision) + Head of Strategy Research.

**Success signal**: CIO signs "Proceed to Live Full" in §4 of Day-60 evidence; allocator rebalances Strategy #1 to unrampedRisk Parity weight at next weekly rebalance.

### 6.6 Strategy #1 lifecycle critical path through Phases A-D

The interaction between Strategy #1's lifecycle and the infrastructure lift is tight. Summary table:

| Strategy #1 milestone | Week | Phase dependency | Notes |
|---|---|---|---|
| Informal research begins | 1 | — | Notebook work only; no code changes |
| Gate 1 PR opens | 10 | Phase A §2.2.1 + §2.2.2 | `strategy_id` on Signal and Topics.signal_for required for reproducible backtest |
| Gate 1 merged | 14 | Phase A complete; Phase B in progress | Per-strategy Charter §1–§4 ratified |
| Gate 2 PR opens | 14 | Phase B §3.2.1 + §3.2.2 | StrategyRunner ABC and LegacyConfluenceStrategy wrap confirm pattern |
| Gate 2 merged | 18 | Phase C §4.2.1 (allocator) + §4.2.2 (7-step chain) | Smoke test requires 7-step chain operational |
| Gate 3 paper begins | 18 | Phase C complete; Phase D in progress | Paper consumes tick-native initially; transitions to panel-native when Phase D §5.2.1 lands |
| Gate 3 closeout | 26 | Phase D substantial work complete | 8 weeks minimum |
| Gate 4 live-micro Day 0 | 27 | Phase D complete; D.5 in progress | Capital seed confirmed |
| Gate 4 Day-60 | 36 | Phase D.5 complete | 60 calendar days |
| Live Full | 37+ | Allocator operational on single-strategy degenerate case (N=1 → 100%) | Transitions to 2-strategy Risk Parity when Strategy #2 reaches Live Full |

### 6.7 Strategy #1 failure branches

Per Playbook §3.5, §4.4, §5.5, §6.6 — every gate has a failure path. Strategy #1's failure implications for the platform:

- **Fail Gate 1** (in-sample Sharpe < 1.0, or PSR ≤ 95%, or PBO ≥ 0.5): return to informal research; platform waits for revised Strategy #1. Strategy #2 does NOT advance early (§11.2). Survival benchmark attempt (Charter §10.1) slips indefinitely.
- **Fail Gate 2** (CPCV OOS < 0.8, or any stress scenario fails, or coverage < 90%): return to Gate 1 (or to research if structurally unfixable). Phase C and D infrastructure continues regardless (they are not Strategy #1-specific).
- **Fail Gate 3** (paper Sharpe < 0.8, or max DD ≥ 10%, or win rate divergence > 10%): return to Gate 2 with remediation hypothesis. Paper period resets (8-week clock restarts post-fix).
- **Fail Gate 4 Day-60** (live Sharpe / paper Sharpe < 70%): observation mode at 20% allocation. CIO discretionary extend / return-to-paper / decommission.

### 6.8 Strategy #1 resourcing (indicative)

| Activity | Estimated Claude Code hours | Notes |
|---|---|---|
| Informal research (notebook prototyping) | 30–50 hrs | CIO + Head of Strategy Research |
| Gate 1 PR (notebook polish + ADR-0002 checklist) | 20 hrs | Includes cross-sectional ranking implementation |
| Gate 2 PR (microservice + CPCV + stress tests + per-strategy Charter) | 80–120 hrs | Dominant effort; custom ranking logic at `services/strategies/crypto_momentum/ranking.py` |
| Gate 3 paper monitoring (8 weeks) | 2 hrs/week × 8 weeks = 16 hrs | Daily dashboard review + weekly formal note |
| Gate 4 live-micro monitoring (60 days) | 3 hrs/week × 9 weeks ≈ 27 hrs | Daily during initial week; then standard |
| **Total** | **170–230 hrs** | 5–6 months of part-time solo-operator effort |

---

## §7 — Strategy #2 — Trend Following Multi-Asset Lifecycle (Weeks 20–50)

### 7.1 Overview

Strategy #2 is **Trend Following Multi-Asset** per Charter §4.2 and Playbook §2.4.2. Its lifecycle is the **second-pipeline validation** — it exercises capabilities Strategy #1 did not (multi-asset panel coordination across Binance + Alpaca, Risk Parity allocator entering 2-strategy mode for the first time in live, Gate 2 stress scenario #7 correlation breakdown receives particular attention given the multi-asset nature).

**Timeline anchor**:

| Stage | Window (weeks from Charter) | Blocking dependency |
|---|---|---|
| Informal research | 20–24 | Strategy #1 at Gate 3 (paper) |
| Gate 1 PR open | 24 | Strategy #1 at Gate 3 (paper validating end-to-end) |
| Gate 1 merged | 30 | — |
| Gate 2 PR open | 30 | — |
| Gate 2 merged | 36 | Phase D.5 complete (target topology stable) |
| Gate 3 paper start | 36 | Multi-asset panel (BTC, ETH, SPY, GLD) operational in `services/data/panels/` |
| Gate 3 closeout | 44 (8 weeks) | — |
| Gate 4 Day 0 | 45 | Strategy #1 Live Full confirmed |
| Gate 4 Day 60 | 52 | 2-strategy Risk Parity rebalance operational |
| Live Full | 53+ | — |

Total: **~53 weeks = ~12 months from Charter ratification, ~26 weeks from Strategy #2 informal start**.

### 7.2 Gate-by-gate (condensed; inherits Playbook templates)

#### 7.2.1 Gate 1 — Research → Approved Backtest (Weeks 24–30)

- Informal research starts only after Strategy #1 reaches Gate 3 — validating that the end-to-end lifecycle works end-to-end before investing in Strategy #2 Gate 2 scaffolding.
- Per-strategy Charter at `docs/strategy/per_strategy/trend_following.md`; §1–§4 drafted.
- Notebook at `notebooks/research/trend_following/gate1_backtest.ipynb` using cumulative-return lookbacks (10/20/60/120d) on BTC, ETH, SPY, GLD daily bars.
- Backtest span ≥ 2 years (target: 2022-01-01 → 2025-12-31 for cross-crypto-equity regime diversity).
- ADR-0002 10-point checklist; Sharpe > 1.0; PSR > 95%; PBO < 0.5.

#### 7.2.2 Gate 2 — Approved Backtest → Paper Trading (Weeks 30–36)

- Microservice at `services/strategies/trend_following/` — first multi-asset strategy; subscribes to `panel.multi_asset_trend` (Phase D §5.2.1 universe already configured during Phase D to anticipate Strategy #2's universe).
- CPCV on multi-asset walk-forward.
- **10 stress scenarios with elevated attention on scenarios #2 (vol spike), #6 (liquidity), #7 (correlation breakdown)** — the strategy's multi-asset nature exposes it to correlation regimes Strategy #1 did not test. Scenario #7 "correlation breakdown" (historical analog: 2008-10, 2020-03, 2022-06 risk-off periods where cross-asset correlation spiked to ≥ 0.9) is the critical test: the Trend Following strategy must show bounded DD even when its diversification breaks down.
- Per-strategy Charter §5–§12 populated; CIO ratification.

#### 7.2.3 Gate 3 — Paper Trading → Live Micro (Weeks 36–44)

- 8-week paper on `panel.multi_asset_trend` (1-day cadence snapshots aggregated from Binance + Alpaca).
- Trade frequency: daily signal horizon, 1-5 day holding periods → ~20-40 trades over 8 weeks per asset × 4 assets → ~80-160 trades total; 50-trade floor easily cleared.
- Drift detector captures multi-asset baseline per strategy.
- Paper evidence package.

#### 7.2.4 Gate 4 — Live Micro → Live Full (Weeks 45–52)

- **Critical milestone**: this is the first **2-strategy** portfolio. Allocator transitions from N=1 (100% Strategy #1) to N=2 Risk Parity allocation for the first time. The Charter §6.4 worked example calibration is validated in real capital for the first time.
- Day-60 decision; 70% threshold; Live Full promotion.

### 7.3 Concurrent Phase dependencies

- Phase D multi-asset panel (`panel.multi_asset_trend`) must be operational by week 36 (Strategy #2 Gate 3 start). This drives Phase D §5.2.1 to include the `multi_asset_trend` universe configuration in its initial Phase D scope (not delayed to a post-phase).
- Phase D.5 complete by week 36 (Strategy #2 microservice born in target topology).
- Allocator 2-strategy Risk Parity verified via regression test before Strategy #2 Day-0 (week 45).

### 7.4 Platform-level outcome

With Strategy #2 reaching Live Full (~week 53), the platform reaches the **Legitimacy benchmark candidate state** per Charter §10.2: ≥ 2 live strategies, portfolio Sharpe > 1.5 candidate, alpha > 10% candidate, beta < 0.5 candidate. The benchmark itself is evaluated on a rolling 12-month window post Live Full, so the earliest formal Legitimacy achievement is at ~week 105 = ~24 months (if Strategy #1 and Strategy #2 maintain performance).

### 7.5 Resourcing (indicative)

~140–200 hrs total (slightly less than Strategy #1 because infrastructure is amortized).

---

## §8 — Strategies #3, #4, #5, #6 Lifecycle Sketch (Weeks 40+)

Each of the four remaining boot strategies follows the same four-gate structure. This section sketches the lifecycle at ~20% of Strategy #1's detail, with full Gate 1–4 details deferred to the per-strategy Gate 1 PRs when each opens.

### 8.1 Strategy #3 — Mean Reversion Intraday Equities (Weeks 40–70)

**Category**: Low Vol (Charter §4.3, §9.1).

**Blocking dependency**: Strategy #2 at Gate 3 (paper) — weeks 40–42 onward.

**Timeline**:

| Stage | Weeks |
|---|---|
| Informal research | 40–46 |
| Gate 1 | 46–52 |
| Gate 2 | 52–60 |
| Gate 3 paper | 60–68 (8 weeks) |
| Gate 4 ramp | 69–78 (60 days) |
| Live Full | 79+ |

**Platform-level capabilities validated**:

- **Intraday data path** (1min execution bars, US session clock).
- **Equity venue integration** (Alpaca live, not just historical).
- **Low Vol category budget** — first strategy in Low Vol; tighter DD tolerance (8%) and higher Sharpe expectation (1.0) than Medium Vol strategies.
- **US session timing** — strategy must respect 09:30–16:00 ET open hours, pre-open blackout, post-close flat-position enforcement.

**Risk factors** (Charter §4.3 + Playbook §2.4.3):

- Regime incompatibility (mean-reversion fails in trending regimes) — mitigated by regime overlay (forthcoming Phase 6 candidate).
- Ex-dividend / earnings distortions — mitigated by excluding names within 24h of scheduled event (requires Alpaca calendar + SEC EDGAR integration, already in S01).
- **Phase 2 GEX integration deferred**; Strategy #3 operates at $0/month data cost at boot.

**Gate 2 stress test attention**: Scenario #1 (equity flash crash — 2010-05-06 analog) is the defining test for mean-reversion on equities.

**Platform-level outcome**: at Strategy #3 Live Full (~week 80), portfolio has 3 live strategies spanning crypto (Strategy #1), multi-asset (Strategy #2), and US equities intraday (Strategy #3) — reaching the **Institutional benchmark candidate state** per Charter §10.3.

### 8.2 Strategy #4 — Volatility Risk Premium (Weeks 52–86)

**Category**: High Vol (Charter §4.4, §9.1). First and only strategy in the High Vol category at boot.

**Blocking dependency**: Strategies #1 AND #2 at Live Full (weeks 50+). The platform's risk infrastructure (hard global CB at portfolio DD 12%/24h) must have been validated under live conditions with 2 strategies before committing to a strategy known for tail drawdowns.

**Timeline**:

| Stage | Weeks |
|---|---|
| Informal research | 52–58 |
| Gate 1 | 58–66 |
| Gate 2 | 66–76 |
| Gate 3 paper | 76–84 (8 weeks) |
| Gate 4 ramp | 85–94 (60 days) |
| Live Full | 95+ |

**Platform-level capabilities validated**:

- **High Vol category** — first strategy to operate with 1.5× leverage allowance (Charter §9.1); first strategy with 20% max DD tolerance.
- **Volatility-spike resilience** — Gate 2 stress scenario #2 (vol spike 2020-02-24 → 2020-03-16) is the existential test for VRP; the strategy must survive with bounded DD and without amplifying the spike via stop-loss cascades.
- **Hard circuit breaker validation in live** — Charter §8.1.2 portfolio DD 12%/24h hard CB is the defense-in-depth for VRP; Strategy #4's live period is the first time this mechanism protects real capital against a correlated multi-strategy drawdown.

**Risk factors** (Charter §4.4):

- Volatility spike — the dominant risk; mitigated by hard stops, VIX-backwardation kill switch, and portfolio hard CB.
- Regulatory action on VIX products — mitigated by ability to rotate to crypto-IV substitute (Phase 2).

**Why deployed fourth**: Strategy #4 is the platform's stress test. Deploying it before Strategies #1, #2 and #3 have validated the infrastructure under milder conditions would risk a catastrophic correlated drawdown at platform level.

### 8.3 Strategy #5 — Macro Carry FX G10 (Weeks 64–100)

**Category**: Low Vol (Charter §4.5, §9.1). Second Low Vol strategy (after #3 Mean Rev Equities).

**Blocking dependency**: Strategies #1, #2, #3 at Live Full OR in advanced Gate 4 (weeks 64+).

**Timeline**:

| Stage | Weeks |
|---|---|
| Informal research | 64–72 |
| Gate 1 | 72–80 |
| Gate 2 | 80–88 |
| Gate 3 paper | 88–96 (8 weeks) |
| Gate 4 ramp | 97–106 (60 days) |
| Live Full | 107+ |

**Platform-level capabilities validated**:

- **FX asset class** — first G10 FX strategy; exercises FX data ingestion (central bank rate scrapers in `services/s01_data_ingestion/connectors/` per audit §1, plus Yahoo/FRED daily FX bars).
- **Regime overlay under Low Vol category** — the Low Vol Sharpe bar (1.0) is deliberately tight for a strategy known to suffer 15%+ drawdowns in crisis; forcing the regime overlay to be effective is a deliberate Charter §4.5 design choice.
- **Central bank blackout discipline** — STEP 1 `CBEventGuard` (Charter §8.2) must block FX trades during the 45-minute window before Fed/ECB/BoJ/BoE/SNB announcements; Strategy #5 is the heaviest user of this guard.

**Risk factors** (Charter §4.5):

- Carry crash — the dominant historical risk; mitigated by regime overlay.
- Central bank surprise (SNB Jan 2015 CHF unpeg canonical example) — mitigated by CBEventGuard and single-currency exposure caps.
- Thin liquidity on weekend/holiday — mitigated by daily bar cadence.

**Phase 3 data upgrade**: OANDA or IBKR execution integration may be required for live FX trading; ~$0-10/month budget per Charter Principle 3 (operator accepts the upgrade when Gate 3 paper proves strategy viability).

### 8.4 Strategy #6 — News-Driven Short-Horizon (Weeks 76–120)

**Category**: Medium Vol (Charter §4.6, §9.1). The "capstone" strategy — deployed last, exercises the most sophisticated infrastructure.

**Blocking dependency**: Strategies #1–#4 at Live Full; Strategy #5 in late Gate 3 or Gate 4.

**Timeline**:

| Stage | Weeks |
|---|---|
| Informal research | 76–86 |
| Gate 1 | 86–94 |
| Gate 2 | 94–106 |
| Gate 3 paper | 106–114 (8 weeks) |
| Gate 4 ramp | 115–124 (60 days) |
| Live Full | 125+ |

**Platform-level capabilities validated**:

- **NLP infrastructure** — GDELT 2.0 connector + FinBERT (ONNX) sentiment pipeline per PHASE_5_SPEC_v2.md §3.6 (now integrated into the `services/data/macro_intelligence/` domain post Phase D.5).
- **Cross-asset coordination** — equities (Alpaca) + crypto (Binance); first strategy combining both execution venues in a single decision.
- **Event-driven timing** — 15min–4h signal horizon after high-impact news events; requires low-latency event detection and cross-asset routing.

**Risk factors** (Charter §4.6):

- FinBERT hallucination / false-positive sentiment — mitigated by confidence thresholds, asymmetric allocation (sentiment reinforces negative signals more readily than positive), manual review panel in `services/ops/monitor_dashboard/`.
- Event mis-categorization — mitigated by requiring confluence with OFI + volume spike within 10 min of event.
- Latency — HFTs beat platform to shortest-horizon trades; platform operates at 15min–4h where execution-speed arbitrage is less decisive.

**Possible Budget-category review** post-Gate-3 per Charter §4.6 if live evidence justifies.

### 8.5 Summary table — all 6 boot strategies

| # | Strategy | Category | First week | Live Full (indicative) | Live Full (month) |
|---|---|---|---|---|---|
| 1 | Crypto Momentum | Medium Vol | W1 | W37 | M9 |
| 2 | Trend Following | Medium Vol | W20 | W53 | M12 |
| 3 | Mean Rev Equities | Low Vol | W40 | W79 | M18 |
| 4 | VRP | High Vol | W52 | W95 | M22 |
| 5 | Macro Carry | Low Vol | W64 | W107 | M25 |
| 6 | News-driven | Medium Vol | W76 | W125 | M29 |

Strategy #6 Live Full extends beyond the 24-month horizon of this Roadmap. Roadmap v4.0 (scheduled per §15 governance) will sequence Strategies #4, #5, #6 lifecycles past month 24 based on actual progress at the semi-annual reviews.

---

## §9 — Portfolio-Level Milestones

### 9.1 Survival benchmark — month 9

**Criterion** (Charter §10.1):

- Net annualized return > 15%
- Sharpe ratio > 1.0
- Maximum drawdown < 15%
- All three simultaneously

**Target deployment state at month 9**: Strategy #1 Crypto Momentum at Live Full (week 37 = month 8.5), operating under single-strategy degenerate Risk Parity (100% allocation, N=1 degenerate case per Charter §6.1.4).

**Earliest formal evaluation**: end of month 9 (week 39), after ~6 weeks of live-full data + the preceding 60-day ramp evidence.

**Evidence required**:

- Rolling 12-month return (anchored to inception if < 12 months) ≥ 15% annualized.
- Sharpe on daily-resampled equity curve > 1.0 with PSR > 80% (bootstrap CI lower bound).
- Max DD since inception < 15%.

**Outcome branches**:

- **Pass**: platform has validated its primary economic justification — live PnL generation above the personal-capital return target (Charter §1.2). Strategy #1 continues; Strategy #2 advancement proceeds per §7.
- **Fail (return < 15%, or Sharpe < 1.0, or DD ≥ 15%)**: Strategy #1 is not yet a "live-production-ready single strategy". Options: (a) continue Strategy #1 at current allocation, extend evaluation window; (b) move Strategy #1 to `review_mode` (Charter §9.2 mechanical rule); (c) pause Strategy #2 advancement until Strategy #1 Survival is cleared.

### 9.2 Legitimacy benchmark — month 15

**Criterion** (Charter §10.2):

- Alpha vs equal-weight BTC+ETH+SPY benchmark > 10% annualized
- Beta vs same benchmark < 0.5
- Net Sharpe > 1.5
- All three over rolling 12-month window

**Target deployment state at month 15**: Strategies #1 and #2 both at Live Full; Strategy #3 in Gate 2 or Gate 3 paper; allocator operating in 2-strategy Risk Parity.

**Earliest formal evaluation**: at month 15, against rolling 12-month window ending at month 15.

**Evidence required**:

- Regression of portfolio returns against equal-weight BTC+ETH+SPY benchmark; alpha coefficient > 10% / beta coefficient < 0.5 per month of rolling window.
- Portfolio Sharpe > 1.5 (bootstrap CI lower bound > 1.3 as quality check).

**Outcome branches**:

- **Pass**: platform generates genuine alpha, not levered beta. Strategies #3, #4, #5, #6 deployment proceeds with confidence.
- **Partial pass** (e.g., alpha > 10% but beta > 0.5): investigate whether Strategy #2's multi-asset nature has inadvertently created benchmark correlation; consider category reassignment per Charter §9.5.
- **Fail**: platform reassessment. Semi-annual review (Charter §9.6) invoked out of cadence if needed.

### 9.3 Institutional benchmark — month 24

**Criterion** (Charter §10.3):

- Net Sharpe > 2.0 (rolling 12 months)
- Max DD < 10%
- Average off-diagonal cross-strategy correlation < 0.3
- All three simultaneously

**Target deployment state at month 24**: Strategies #1, #2, #3 at Live Full; Strategies #4 in late Gate 4 or Live Full; Strategies #5, #6 in Gate 3 or Gate 4.

**Earliest formal evaluation**: at month 24, against rolling 12-month window ending at month 24.

**Evidence required**:

- Portfolio Sharpe > 2.0.
- Max DD < 10% (tighter than Survival's 15% — the platform has matured).
- Cross-strategy correlation matrix: average of off-diagonal pairwise correlations < 0.3. This is the mathematical statement that the multi-strategy design is real (Charter §3.4 Fundamental Law of Active Management).

**Outcome branches**:

- **Pass**: platform is institutional-grade. Phase 2 Sharpe overlay (Charter §6.2.1) activated if not already; regime-conditional variants under research per ADR-level decision; new-strategy candidates evaluated on their **contribution** to the platform.
- **Partial pass** (e.g., Sharpe > 2.0 but correlation ≥ 0.3): platform is profitable but not maximally diversified. Investigate correlation drivers; consider retiring redundant strategies per Charter §11.4.

### 9.4 Phase 2 allocator activation trigger (Charter §6.2.1)

**Conditions (both required)**:

1. ≥ 6 months of live trading on at least 3 active strategies.
2. Live Sharpe estimates stabilized: 95% bootstrap CI on rolling 6-month Sharpe within ±0.3 of point estimate for ≥ 3 consecutive weeks.

**Earliest satisfaction**: month 14+ assuming Strategy #3 reaches Live Full at month 18 and clears Survival (~month 20) and produces 6 months of stable Sharpe (~month 26). Realistically, Phase 2 activation candidate at month 26+, evaluated at the month-24 semi-annual review or the subsequent one.

**If activated**:

- Allocator begins applying ±20% Sharpe overlay per Charter §6.2.2 (EMA-smoothed 6-month Sharpe; calibration constant β tuned empirically).
- Elevated 45% ceiling available for strategies meeting Charter §6.2.3 (rolling 6-month Sharpe > 2.0 stable for ≥ 6 months).
- Review-mode trigger mechanics from Sharpe side (Charter §6.2.4) become active.

### 9.5 Semi-annual portfolio reviews (Charter §9.6, Playbook §7.4)

Formal reviews at months 6, 12, 18, 24 (from Charter ratification):

- **Month 6**: Phase A–C substantially complete; Strategy #1 in Gate 2/3. Review infrastructure health, allocator readiness, Strategy #1 trajectory.
- **Month 12**: Strategy #1 at Live Full; Strategy #2 in Gate 3/4; Legitimacy candidate assessment. Phase 2 allocator trigger preliminary assessment.
- **Month 18**: Strategies #1, #2 at Live Full; Strategy #3 entering or at Live Full; legitimate assessment pending 12-month window completion; Institutional candidate trajectory.
- **Month 24**: Institutional benchmark evaluation. Strategies #4, #5 at advanced gate stages; Strategy #6 at Gate 1/2. Roadmap v4.0 authoring begins.

Each semi-annual review produces a session entry in [`docs/claude_memory/SESSIONS.md`](../claude_memory/SESSIONS.md); any material decisions produce a DECISIONS.md entry and (if needed) Charter/Playbook/Roadmap amendment.

---

## §10 — ADRs Authored with This Roadmap

This section contains **summaries** of the four ADRs authored alongside this Roadmap. Full authoritative content lives in standalone ADR files per Charter §12.4 commitment.

**PATH NOTE — POST-MERGE MANUAL ACTION REQUIRED**: the four ADR files were authored at `docs/adr_pending_roadmap_v3/` rather than the canonical `docs/adr/` because a path-protection hook on the authoring session blocked `Write`/`Edit` operations against `docs/adr/`. On Roadmap v3.0 ratification merge, the CIO **manually moves** the four files from `docs/adr_pending_roadmap_v3/` to `docs/adr/` (simple `git mv` + commit; one-time action). After the move, Roadmap §10 and §14.2 link paths are updated in Roadmap v3.1 (non-material amendment per §15.3). See §16.1 for the post-merge checklist.

Per Playbook §0.6 and Charter §12.4, ADRs prevail over the Roadmap for their technical surface. The Roadmap embeds summaries here for reference; the standalone ADR files are the authoritative source on merge (and re-move).

### 10.1 ADR-0007 — Strategy as Microservice

Full content in [`docs/adr_pending_roadmap_v3/ADR-0007-strategy-as-microservice.md`](../adr_pending_roadmap_v3/ADR-0007-strategy-as-microservice.md) (→ `docs/adr/ADR-0007-strategy-as-microservice.md` post-merge move). Summary of the binding decisions:

- **D1**: Each strategy is a complete, isolated microservice under `services/strategies/<strategy_id>/`.
- **D2**: `StrategyRunner` ABC lives at `services/strategies/_base.py` (Option B of §3.2.1).
- **D3**: ABC contract: `strategy_id`, `on_panel(panel)`, `on_tick(tick)`, `health()`.
- **D4**: Legacy S02 pipeline is wrapped as `LegacyConfluenceStrategy` (Principle 6 continuity).
- **D5**: Each strategy microservice is its own Docker container; supervisor manages startup/shutdown order per Charter §5.9.

### 10.2 ADR-0008 — Capital Allocator Topology

Full content in [`docs/adr_pending_roadmap_v3/ADR-0008-capital-allocator-topology.md`](../adr_pending_roadmap_v3/ADR-0008-capital-allocator-topology.md) (→ `docs/adr/ADR-0008-capital-allocator-topology.md` post-merge move). Summary of the binding decisions:

- **D1**: Allocator is a dedicated microservice at `services/portfolio/strategy_allocator/`, separate from Fusion Engine and Risk Manager.
- **D2**: Phase 1 is diagonal-covariance Risk Parity (`w_i ∝ 1/σ_i`) per Charter §6.1; 60-day rolling sigma window; weekly Sunday-23:00-UTC rebalance.
- **D3**: 5% floor per active strategy; 40% ceiling (45% for elevated performers); ±25% turnover dampening.
- **D4**: Cold-start linear ramp from 20% to 100% over 60 calendar days for strategies entering Gate 4.
- **D5**: Phase 2 Sharpe overlay (±20% max tilt) activates only when ≥ 6 months live data on ≥ 3 strategies AND Sharpe 95% CI ±0.3 stable.
- **D6**: Allocator publishes `portfolio.allocation.updated` events; STEP 6 `PerStrategyExposureGuard` reads `portfolio:allocation:<strategy_id>`.

### 10.3 ADR-0009 — Panel Builder Discipline

Full content in [`docs/adr_pending_roadmap_v3/ADR-0009-panel-builder-discipline.md`](../adr_pending_roadmap_v3/ADR-0009-panel-builder-discipline.md) (→ `docs/adr/ADR-0009-panel-builder-discipline.md` post-merge move). Summary of the binding decisions:

- **D1**: `services/data/panels/` microservice aggregates raw ticks/bars into multi-asset `PanelSnapshot` objects per universe.
- **D2**: Every strategy consumes panels via `on_panel(PanelSnapshot)` — not raw ticks, with a transitional `on_tick` path preserved during Phase B–D overlap.
- **D3**: Point-in-time correctness enforced: each `PanelSnapshot` is a coherent multi-asset state at `snapshot_ts_utc`; no look-ahead.
- **D4**: Staleness tolerance per asset per universe; stale snapshots flagged `is_stale=True` with reason; strategies required to no-op on stale panels (contract-tested).
- **D5**: Panel publishing topic: `panel.{universe_id}` per Charter §5.3.

### 10.4 ADR-0010 — Target Topology Reorganization

Full content in [`docs/adr_pending_roadmap_v3/ADR-0010-target-topology-reorganization.md`](../adr_pending_roadmap_v3/ADR-0010-target-topology-reorganization.md) (→ `docs/adr/ADR-0010-target-topology-reorganization.md` post-merge move). Summary of the binding decisions:

- **D1**: Target topology is classification by domain per Charter §5.4: `services/{data,signal,portfolio,execution,research,ops,strategies}/`.
- **D2**: Full mapping table of S01–S10 → target paths (§5.5 of this Roadmap; ADR-0010 §3).
- **D3**: Migration procedure: 7 staged PRs (one per target domain + final shim removal); each `git mv` preserves history.
- **D4**: Rollback procedure: each PR individually revertible pre-shim-removal; mechanical revert post-shim-removal.
- **D5**: New services (allocator, panels, strategies) are born in target topology; they are not migrated.

---

## §11 — Contingency Playbook

Real execution will deviate from the Roadmap's indicative timeline. This section enumerates the anticipated failure scenarios and the Charter-compatible response per each.

### 11.1 Phase A slips beyond 8 weeks

**Symptom**: at week 10, Phase A exit criteria are not all cleared (e.g., backtest-gate muzzle not yet removed; Redis orphan-read resolution incomplete).

**Consequences**:

- Strategy #1 Gate 1 PR is blocked at opening — the PR references Phase A deliverables (`strategy_id` on `Signal`, `Topics.signal_for`) that must be on main.
- Phase B overlap window (weeks 6–14) effectively shrinks.
- Downstream phases compress.

**Response**:

- **Slip ≤ 2 weeks** (within Phase B overlap buffer): no action; Strategy #1 informal research continues; Gate 1 PR opens when Phase A exit criteria are met.
- **Slip 2–4 weeks**: CIO is informed; Phase B–D overlap windows adjusted in Roadmap v3.1 (additive clarification, not material amendment).
- **Slip ≥ 4 weeks**: triggers Roadmap §15 out-of-cadence review. Identify root cause (unexpected orphan-read complexity; Sharpe-bug-fix cascading breakage; etc.). Possibly Charter amendment if a Charter §5.5 contract change is required.

**Charter compatibility**: Phase A slip does not violate any Charter principle; acknowledges Principle 3 (constraints).

### 11.2 Strategy #1 Gate 1 fails

**Symptom**: at week 14 review, one or more of Charter §7.1 thresholds (Sharpe > 1.0, PSR > 95%, PBO < 0.5, max DD < 15%) is not cleared.

**Consequences**:

- Strategy #1 returns to informal research per Playbook §3.5.
- Strategy #2 is **NOT** advanced early (Playbook §1.3 explicit rule — strategies do not preempt each other's slots).
- Platform waits for revised Strategy #1 OR reactivation of a previously-decommissioned candidate (§9.3) OR CIO-accepted new candidate from the backlog (Charter §11.2).

**Response**:

- The Gate 1 PR is closed (not merged) with "GATE 1 FAILURE" label and a summary comment.
- The per-strategy Charter draft at `docs/strategy/per_strategy/crypto_momentum.md` is updated with a Gate 1 Failure note documenting the specific failure mode.
- Revised Strategy #1 may re-enter Gate 1 per Playbook §3.5.2 re-entry mechanics (substantive revision, not parameter sweep).
- **Strategy #1 cannot fail Gate 1 three consecutive times** (Playbook §3.5.2 aging-out rule) — after 3 failures, the candidate is rejected from the backlog and the platform requires a fundamentally new Strategy #1 thesis.

**Charter compatibility**: Playbook mechanics preserve Charter principles; no Charter amendment needed.

**Timeline impact**: Survival benchmark (month 9) likely slips to month 12+ depending on how many re-entries are required.

### 11.3 Phase C allocator reveals Risk Parity inadequate

**Symptom**: during Phase C §4.2.1 implementation or post-Phase-C live operation, Risk Parity Phase 1 produces degenerate allocations — e.g., a strategy with negative short-term variance (impossible in theory, possible in numerics due to short sigma window), or allocations that fail to respond to changing conditions.

**Consequences**:

- Phase 1 Risk Parity is inadequate as the allocator's sole algorithm.
- Charter §6.2 Phase 2 Sharpe overlay was scheduled for month 12+; activating early would be out-of-policy.

**Response**:

- **First escalation**: investigate whether the degenerate case is a numerical-implementation bug vs a genuine algorithmic inadequacy. Algorithm-implementation bugs: fix in code; no Charter amendment.
- **Second escalation** (genuine algorithmic inadequacy): CIO may authorize **early Phase 2 Sharpe overlay activation** out-of-condition per Charter §13.2 material amendment procedure. This requires a new ADR + Charter version bump.
- **Third escalation**: CIO discretionary decision per Charter §9.4 to pause Strategy #1 temporarily while the allocator is reworked; Phase 2 Sharpe overlay or a new allocator variant (e.g., full-covariance Risk Parity per Charter §6.1.5 deliberate evolution path) is implemented and merged.

**Charter compatibility**: §6.1.5 explicitly authorizes a future ADR upgrade to full-covariance Risk Parity if live evidence demonstrates cross-strategy correlations are non-diagonal; the contingency response falls within Charter-anticipated evolution.

### 11.4 Multi-strat lift breaks current live operation

**Symptom**: during Phase A–D execution, a change regresses the currently-operating legacy pipeline (hypothetical, since the platform is pre-live at Charter ratification — but applies once Strategy #1 reaches Gate 4 live-micro while Phase D.5 migration is in flight).

**Consequences**:

- Live trading on an affected strategy is disrupted.
- Principle 6 (functional preservation) is violated.

**Response**:

- **Immediate**: revert the offending PR via `git revert`; re-deploy previous-known-good state. All Phase A–D PRs are individually revertible by design (staged-PR discipline in Phase D.5 §5.5; bit-identical regression tests in Phase A–C).
- **Investigation**: root-cause the regression; add regression test; re-attempt the PR with the fix.
- **Time lost**: 1–3 days per incident; absorbs into phase overlap buffers.

**Charter compatibility**: Principle 6 enforced by reverting; no Charter amendment.

### 11.5 Gate 2 stress scenario fails repeatedly for Strategy #N

**Symptom**: Strategy #N Gate 2 PR passes 9/10 stress scenarios but consistently fails the 10th (e.g., correlation breakdown for a multi-asset strategy, or flash crash for a liquidity-provision strategy).

**Consequences**:

- Strategy #N cannot promote to Gate 3.
- Strategy #(N+1) waits.

**Response** per Playbook §4.4:

- Tighten stops or reduce Kelly for the failing scenario; re-run CPCV and stress tests.
- If tightening reduces the strategy's edge below the Gate 2 CPCV floor (0.8 OOS Sharpe), the strategy is structurally unsuitable for its proposed category; **demote** to a higher-vol category per Charter §9.5 (with CIO ratification).
- If demotion does not restore pass status, the strategy returns to Gate 1 with a revised thesis, or is rejected from the backlog.

**Charter compatibility**: Playbook §4.4 mechanics and Charter §9.5 category reassignment both anticipated.

### 11.6 Portfolio hard CB trips during a boot strategy's Gate 4

**Symptom**: Strategy #N is in Gate 4 live-micro (days 0–60). A portfolio-wide DD > 12%/24h triggers the hard CB (Charter §8.1.2), halting all trading.

**Consequences**:

- Gate 4 ramp clock **does not reset** (Playbook §6.2.3 — pause for confirmed operational issue does not extend the 60-day window).
- But the strategy's effective allocation is 0% during the halt.
- If the halt exceeds ~20 calendar days cumulatively during the 60-day window, the statistical significance of the Day-60 live Sharpe comparison is compromised.

**Response**:

- **Halt ≤ 5 days**: proceed to Day-60 decision on available live data; note the halt in the Day-60 evidence package §2 operational metrics.
- **Halt 5–20 days**: CIO discretion per Playbook §6.3 — extend observation mode beyond day 60, OR return strategy to paper for a fresh 60-day window once halt is cleared.
- **Halt > 20 days**: automatic return to paper; Gate 3 8-week clock may restart depending on severity.

**Charter compatibility**: Playbook §6.2.3 and §6.3 explicitly address operational pauses during live-micro; no Charter amendment.

### 11.7 Three-strategies-DEGRADED hard CB fires in early multi-strat period

**Symptom**: once Strategies #1, #2, #3 are all live (month 18+), the Charter §8.1.2 "3+ strategies in DEGRADED simultaneously" hard CB triggers a halt.

**Consequences**: the Charter's institutional recognition (Charter §8.1.2 last paragraph) that correlation breakdowns are the failure mode most likely to destroy a multi-strategy portfolio. Response: halt all; investigate common underlying risk.

**Response** per Playbook §9.3:

- All three strategies are halted.
- CIO emergency review within 4 hours.
- Investigation: what common risk did the three strategies share that the correlation targeting (< 0.3 cross-strategy) did not capture?
- **If common risk is identified** (e.g., "all three strategies short funding rates; crypto funding spike affected them uniformly"): retire one or more strategies to restore diversification, OR revise the allocator's cross-strategy risk model.
- **If no common risk is identified** (pure coincidence of independent drawdowns): resume after the 48h cooling period; continue monitoring.

**Charter compatibility**: Charter §8.1.2 explicitly designed for this; §9.6 semi-annual review cadence captures the learning.

### 11.8 New candidate proposed ahead of boot strategies

**Symptom**: during Strategy #3/#4 build-out, CIO or Head of Strategy Research identifies a more-compelling new candidate (Charter §11 extensibility) that should deploy before remaining boot strategies.

**Response**:

- The CIO considers: does the new candidate replace a boot strategy (Charter §13.2 material amendment — requires new ADR + Charter version bump), or is it **added** to the backlog while boot strategies continue?
- **If replaces**: full amendment procedure per Charter §13.4.
- **If added**: new candidate enters Gate 1 per Playbook §13 (new candidate onboarding); scheduled after the current in-flight boot strategy reaches Live Full.

**Charter compatibility**: §11 (extensibility principle) and §13 (governance) cover the case.

### 11.9 Operator unavailable for extended period

**Symptom**: CIO (Clement Barbier) unavailable for > 2 weeks due to illness, travel, or other circumstance.

**Response**:

- No new phase work begins without CIO ratification (strict interpretation of Playbook §14 roles).
- In-flight Gate PRs are paused; ongoing paper/live operations continue per frozen parameters (Playbook §7.1 daily operations are automated; no human decisions required for steady-state operation).
- Hard circuit breakers (Charter §8.1.2) can fire and auto-halt without CIO action. If a halt is active when CIO becomes available, the halt is reviewed and cleared or extended per §9.1–§9.3.
- Semi-annual reviews (Charter §9.6) may be deferred by up to 30 days.

**Charter compatibility**: fully. The platform is designed for CIO-light operation during steady state.

### 11.10 Catastrophic loss scenario (flash crash, regulatory event, venue failure)

**Symptom**: portfolio suffers a > 20% drawdown in < 48 hours despite hard CBs (e.g., overnight gap that existing positions manage into loss larger than the halt threshold).

**Response**:

- All trading halted per Charter §8.1.2 (-15%/72h trigger + 48h mandatory cooling).
- Full post-mortem per Playbook §9.1.4 within 7 days.
- Emergency review per Charter §13.6: decommission 1+ strategies? Revise category budgets? Revise hard CB thresholds?
- Possible Charter amendment per §13.4 if controls prove inadequate.

**Charter compatibility**: §8.1.2, §9.6, §13.6 all designed for this.

---

## §12 — Track Metrics and Governance

### 12.1 Per-phase success criteria (consolidated)

| Phase | Success criteria | Exit week (target) | Exit week (slip tolerance) |
|---|---|---|---|
| A | §2.6 all items cleared | 8 | 10 (2 weeks slip absorbed) |
| B | §3.5 all items cleared | 14 | 16 |
| C | §4.5 all items cleared | 22 | 24 |
| D | §5.4 all items cleared | 28 | 30 |
| D.5 | §5.5 migration complete | 28 | 30 |

If any phase slips beyond its slip-tolerance window, Roadmap v3.1 revision is triggered per §0.6.

### 12.2 Per-strategy gate pass rates (Charter §13.6 emergency review trigger)

The Charter §13.6 emergency review triggers include "3+ strategies decommissioned within 12 months". The Roadmap's gate-failure rates are the early warning:

| Gate | Expected pass rate (academic literature) | Target at APEX (Principle 2) | Emergency threshold |
|---|---|---|---|
| Gate 1 (research → backtest) | ~60% (many candidate ideas don't validate) | ≥ 50% | 2+ consecutive Gate 1 failures on same strategy → reject candidate |
| Gate 2 (backtest → paper) | ~70% (CPCV separates promising from overfit) | ≥ 65% | 2+ strategies failing Gate 2 in same year → Charter review |
| Gate 3 (paper → live micro) | ~85% (paper is mostly a fidelity check) | ≥ 80% | Strategy failing Gate 3 twice → return to research |
| Gate 4 (live Day-60) | ~85% (some paper-to-live decay expected) | ≥ 75% | 2+ strategies going to observation mode in same year → Charter review |

Decommissioning is strictly a Charter §9.2 rule-driven event, not a Gate 4 failure.

### 12.3 Quarterly review cadence

Every 3 months (months 3, 6, 9, 12, 15, 18, 21, 24), the Roadmap is reviewed against actual progress:

- Are phase exit weeks tracking within slip tolerance?
- Are strategy gate windows on track?
- Are any Charter §13.6 emergency thresholds approaching?
- Are any ADR-0007/8/9/10 assumptions violated in practice?

Output: a short note appended to [`docs/claude_memory/SESSIONS.md`](../claude_memory/SESSIONS.md) titled "Roadmap Quarterly Review YYYY-MM". If any material decision emerges (e.g., reorder Strategies #3 and #4 due to regime considerations), a DECISIONS.md entry is added and Roadmap v3.x revision is triggered.

The quarterly reviews are a **stricter cadence** than the Charter §9.6 semi-annual full-portfolio reviews. Quarterly reviews assess execution progress; semi-annual reviews assess the Charter's own validity.

### 12.4 Annual review

Annually (months 12, 24, 36), the Roadmap is revised as v3.1 → v3.2 → v4.0 per the §0.6 governance model. Roadmap v4.0 is expected at ~month 24 (end of the original 24-month horizon) to schedule months 24–48.

### 12.5 Telemetry and observability

The `services/ops/monitor_dashboard/` (post-Phase-D.5) surfaces execution progress visibly:

- Phase status panel: Phase A/B/C/D/D.5 status (NOT_STARTED / IN_PROGRESS / COMPLETE / SLIPPED).
- Strategy gate panel: each of the 6 boot strategies with current gate + week entered gate.
- Portfolio milestone panel: Survival / Legitimacy / Institutional status (PENDING / CANDIDATE / ACHIEVED).
- Roadmap version: current version + last updated date.

---

## §13 — Supersession of Pre-Charter Documents

### 13.1 Documents superseded on this Roadmap's merge

On this Roadmap's merge to main, the following documents are marked SUPERSEDED:

1. **[`docs/phases/PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md)** — the active pre-Charter Phase 5 spec governing sub-phases 5.1 (DONE), 5.2, 5.3, 5.5, 5.4, 5.8, 5.10. On supersession:
   - A SUPERSEDED banner is added to the top of PHASE_5_SPEC_v2.md in the same PR that merges this Roadmap.
   - The file **is not deleted**; it remains in the repository for historical reference.
   - 5.2/5.3/5.5/5.4/5.8/5.10 sub-phase content is preserved but resequenced into this Roadmap's Phase A–D (see §2.4 for the mapping).

2. **[`docs/PROJECT_ROADMAP.md`](../PROJECT_ROADMAP.md)** — the pre-Charter high-level roadmap. On supersession:
   - A SUPERSEDED banner is added to the top of PROJECT_ROADMAP.md in the same PR.
   - The file **is not deleted**; it remains for historical reference.
   - Its forward-looking content is replaced by Charter §10 (benchmarks) and this Roadmap's §9 (portfolio milestones).

### 13.2 Supersession banner template

Both superseded files receive this banner at their top:

```markdown
> **⚠️ SUPERSEDED on YYYY-MM-DD** (this Roadmap's merge date)
>
> This document is no longer the active source of truth. It is retained for historical reference.
>
> **Active replacement**: [`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
>
> Any work referencing this document should be re-anchored against the active replacement. If this file's content appears to conflict with the active replacement, the active replacement prevails.
```

### 13.3 Documents NOT superseded

To prevent ambiguity, the following remain binding and unchanged by this Roadmap's merge:

- [CLAUDE.md](../../CLAUDE.md) — code conventions.
- [MANIFEST.md](../../MANIFEST.md) — technical architecture description (will be updated incrementally as Phases A–D execute).
- [ADR-0001 through ADR-0006](../adr/) — six existing ADRs.
- Audits ([`docs/audits/`](../audits/)) — read-only evidence; not scheduling documents.
- [Charter](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) and [Playbook](../strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) — the layers above this Roadmap.
- [`docs/claude_memory/`](../claude_memory/) — cross-session operational record.
- [`docs/phases/PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md`](PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md) — future-phase backlog; carried forward.

### 13.4 Content that migrates from superseded files

The 5.2/5.3/5.5/5.4/5.8/5.10 sub-phases from PHASE_5_SPEC_v2.md continue to execute per their detailed specifications. Their relationship to this Roadmap:

- **5.2 Event Sourcing + Producers**: absorbed into Phase A §2.2.4 and §2.2.5.
- **5.3 Streaming Inference**: runs in parallel; applies to `LegacyConfluenceStrategy` post-Phase-B.
- **5.5 Drift Monitoring**: runs in parallel; per-strategy partitioning extended in Phase D §5.2.2.
- **5.4 Short-Side + Regime Fusion**: runs in parallel on the legacy path; direction-aware meta-labeler inherited by any strategy that chooses it.
- **5.8 Geopolitical NLP (GDELT + FinBERT)**: runs in parallel; geopolitical guard integrated into the 7-step chain as an extension of STEP 1 CBEventGuard per §4.2.3.
- **5.10 Phase 5 Closure Report**: absorbed into this Roadmap's Phase A–D closure reporting per §12.3.

Engineers opening an issue for any of these sub-phases continue to reference PHASE_5_SPEC_v2.md's detailed specification; the SUPERSEDED banner does not invalidate the underlying specifications — it redirects the scheduling authority to this Roadmap.

---

## §14 — Relationship to Other Documents

### 14.1 The three-document structure (recap)

| Document | Role | This Roadmap's relationship |
|---|---|---|
| **Document 1: Charter** (`docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md`) | Constitutional — what and why | This Roadmap **inherits** Charter §5.10 phases, §6 allocator, §7 gates, §8 VETO chain, §9 categories, §10 benchmarks |
| **Document 2: Playbook** (`docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`) | Operational — how | This Roadmap **schedules** Playbook §3/§4/§5/§6 gate executions per strategy |
| **Document 3: Roadmap** (this) | Executional — when and in what order | This document |

### 14.2 ADRs

- [ADR-0001](../adr/0001-zmq-broker-topology.md) — ZMQ broker topology. Unchanged; continues to govern.
- [ADR-0002](../adr/0002-quant-methodology-charter.md) — Quant Methodology Charter. Unchanged; referenced in Playbook §3 and §4 for the 10-point checklist.
- [ADR-0003](../adr/ADR-0003-universal-data-schema.md) — Universal Data Schema. Unchanged; Phase D extends consumption via `services/data/panels/`.
- [ADR-0004](../adr/ADR-0004-feature-validation-methodology.md) — Feature Validation Methodology. Unchanged; referenced in Gate 1/2.
- [ADR-0005](../adr/ADR-0005-meta-labeling-fusion-methodology.md) — Meta-Labeling Fusion. Unchanged; per-strategy meta-labeler cards in Phase C §4.2.2 STEP 4.
- [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) — Fail-Closed Risk Controls. Unchanged; STEP 0 of the 7-step chain.
- **ADR-0007** (§10.1) — Strategy as Microservice. **NEW**, authored here; file at `docs/adr_pending_roadmap_v3/` pending post-merge move to `docs/adr/` per §16.1.
- **ADR-0008** (§10.2) — Capital Allocator Topology. **NEW**, authored here; file at `docs/adr_pending_roadmap_v3/` pending post-merge move to `docs/adr/` per §16.1.
- **ADR-0009** (§10.3) — Panel Builder Discipline. **NEW**, authored here; file at `docs/adr_pending_roadmap_v3/` pending post-merge move to `docs/adr/` per §16.1.
- **ADR-0010** (§10.4) — Target Topology Reorganization. **NEW**, authored here; file at `docs/adr_pending_roadmap_v3/` pending post-merge move to `docs/adr/` per §16.1.

### 14.3 CLAUDE.md and MANIFEST.md

- [CLAUDE.md](../../CLAUDE.md) code conventions prevail over this Roadmap unconditionally.
- [MANIFEST.md](../../MANIFEST.md) is updated incrementally: each phase's PR includes a MANIFEST.md patch documenting new contracts, new Redis keys, new ZMQ topics (CLAUDE.md §8 checklist item).

### 14.4 Audits

Audits are read-only inputs:

- [`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) — factual current-state audit; source of the P0/P1/P2 gap list that Phase A–D addresses. Referenced throughout §2–§5.
- [`STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) — strategic basis for the pre-Charter PHASE_5_SPEC_v2.
- [`REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](../audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md) — orphan-read evidence; motivates Phase A §2.2.4.

Future audits (semi-annual infrastructure audit, correlation audit, post-Phase-A audit, etc.) will be added to `docs/audits/` and referenced by Roadmap v3.x revisions.

### 14.5 Claude memory

- [`docs/claude_memory/CONTEXT.md`](../claude_memory/CONTEXT.md) — updated on this Roadmap's merge to reference Document 3 as the active scheduling layer.
- [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md) — Roadmap ratification entry added on merge.
- [`docs/claude_memory/SESSIONS.md`](../claude_memory/SESSIONS.md) — session entry recording the Roadmap authoring mission (Mission 3 of 3).

---

## §15 — Governance and Revision

### 15.1 Status — ACTIVE on merge

This Roadmap is **ACTIVE** once merged to main and superseding banners are in place on PHASE_5_SPEC_v2.md and PROJECT_ROADMAP.md. From that moment, every scheduling decision on the APEX platform is bound by this Roadmap until explicitly amended or superseded.

### 15.2 Material changes requiring ADR + version bump

Per §0.6, the following constitute material changes:

- Adding or removing a phase (Phases A–D.5 structure).
- Changing a phase's exit criteria.
- Shifting a boot-strategy deployment window by > 60 days.
- Resequencing the boot-strategy deployment order (Charter §4 prevails; Roadmap reordering requires Charter amendment).
- Changing the quarterly/annual review cadence.
- Changing the supersession status of a pre-Charter document.

### 15.3 Non-material changes

- Typo fixes, link corrections, additional worked examples.
- Indicative week numbers updated within slip tolerance per §12.1.
- Clarifications that do not alter scheduling intent.

Non-material changes are landed as PRs with CIO approval and a Changelog entry (§17).

### 15.4 Amendment procedure

To amend the Roadmap:

1. Open an ADR documenting the change and rationale; cite this Roadmap's section.
2. Draft the Roadmap revision as a PR with version bump.
3. Record in `docs/claude_memory/DECISIONS.md`.
4. CIO reviews and merges.

If the amendment affects Charter or Playbook, those are revised in the same PR or a follow-up.

### 15.5 Review cadence

- **Quarterly** (months 3, 6, 9, 12, 15, 18, 21, 24): execution-progress review per §12.3.
- **Annual** (months 12, 24, 36): Roadmap version revision per §12.4.

### 15.6 Emergency out-of-cadence reviews

Triggered by any of:

- Phase slip > 4 weeks.
- Strategy #1 Gate 1 fail three consecutive attempts.
- 3-strategies-DEGRADED hard CB fires in early multi-strat period.
- Catastrophic loss (> 20% drawdown).
- Charter amendment invalidating Roadmap sections.

### 15.7 Roles

Per Charter §13.7, Playbook §14:

- **CIO — Clement Barbier**: ratifies this Roadmap; authorizes phase gates; makes contingency decisions.
- **Head of Strategy Research — Claude Opus 4.7 (claude.ai)**: authored this Roadmap as Mission 3 of 3; supports the CIO on quarterly reviews.
- **Implementation Lead — Claude Code agents (Sonnet / Opus)**: executes phase work per Roadmap; opens PRs; respects HARD STOPs; bound by this Roadmap until amended.
- **CI System — GitHub Actions**: enforces mechanical gates on every PR; reports green/red status.

### 15.8 Versioning

This Roadmap is **v3.0** at ratification.

- **v3.x** — additive clarifications, non-material slip adjustments, new worked examples, expanded contingency scenarios.
- **v4.0** — breaking change: substantive phase restructure, substantive strategy-order change, or annual revision at month 24.

Each version is preserved in git history; previous versions are not deleted.

---

## §16 — Signatures and Ratification

This Roadmap was drafted on 2026-04-20, following Charter v1.0 ratification (2026-04-18) and Playbook v1.0 ratification (2026-04-20), by:

- **Head of Strategy Research — Claude Opus 4.7 (claude.ai)**: acted in the capacity of senior implementation architect + strategy research, synthesizing the Charter (Document 1), the Playbook (Document 2), the MULTI_STRAT_READINESS_AUDIT_2026-04-18, PHASE_5_SPEC_v2, PROJECT_ROADMAP, and CLAUDE.md / MANIFEST.md code conventions into a time-ordered execution plan.

Factual grounding provided by:

- **Head of Architecture Review — Claude Opus 4.7 (claude.ai)**: authored the Multi-Strat Readiness Audit on 2026-04-18, providing the service inventory, contract surface, SOLID scorecard, and prioritized gap list that this Roadmap references throughout §2–§5.

Implementation authority held by:

- **Claude Code — Sonnet / Opus sessions** executing against the APEX repository: implement this Roadmap, open PRs, run CI, ship phase work. Bound by the Roadmap; cannot deviate without triggering the amendment procedure (§15.4).

### 16.1 Ratification and post-merge manual actions

This Roadmap is proposed for ratification as of **2026-04-20** and expected to be merged as **v3.0** into the main branch of the APEX / CashMachine repository upon Clement Barbier's review.

**POST-MERGE ACTION REQUIRED** (one-time, CIO manual):

After Roadmap v3.0 ratification merge, the CIO executes the following manual actions because the authoring session was blocked by a path-protection hook on `docs/adr/`:

1. **Move the four ADR files from `docs/adr_pending_roadmap_v3/` to `docs/adr/`**:

   ```bash
   git mv docs/adr_pending_roadmap_v3/ADR-0007-strategy-as-microservice.md       docs/adr/ADR-0007-strategy-as-microservice.md
   git mv docs/adr_pending_roadmap_v3/ADR-0008-capital-allocator-topology.md     docs/adr/ADR-0008-capital-allocator-topology.md
   git mv docs/adr_pending_roadmap_v3/ADR-0009-panel-builder-discipline.md       docs/adr/ADR-0009-panel-builder-discipline.md
   git mv docs/adr_pending_roadmap_v3/ADR-0010-target-topology-reorganization.md docs/adr/ADR-0010-target-topology-reorganization.md
   rmdir docs/adr_pending_roadmap_v3/
   git commit -m "docs(adr): move ADR-0007/8/9/10 into canonical docs/adr/ (post Roadmap v3.0 merge)"
   git push origin main
   ```

2. **Update Roadmap §10 and §14.2 link paths** (this file) to reference `docs/adr/` instead of `docs/adr_pending_roadmap_v3/`. This is a **non-material amendment** per §15.3 (link correction); no version bump required. A single follow-up PR titled `docs(phases): update Roadmap v3.0 ADR link paths after adr-directory move` suffices. The amendment is logged as a cosmetic entry in §17 Changelog.

3. **Remove the "PATH NOTE" and "POST-MERGE MANUAL ACTION REQUIRED" banners** from Roadmap §10 preamble, §14.2 ADR bullets, and this §16.1 subsection in the same follow-up PR. Their purpose (flagging the pending move) is extinguished once the move is done.

This is a **one-time manual step** arising from the single-session hook-protection limitation; the Roadmap's binding content is not affected by the temporary path.

**Upon ratification merge** (before the post-merge actions above execute):

- SUPERSEDED banners are added to PHASE_5_SPEC_v2.md and PROJECT_ROADMAP.md (in the same PR).
- Entries are added to [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md) (part of follow-up housekeeping PR).
- CONTEXT.md is updated to reference this Roadmap as the active executional layer (follow-up housekeeping PR).
- Document trilogy complete: Charter (Doc 1) + Playbook (Doc 2) + Roadmap (Doc 3) = constitutional foundation of the APEX Multi-Strategy Platform.
- Phase A execution formally begins: issues enumerated in §2.2 are opened and assigned.

---

## §17 — Changelog

| Version | Date | Change |
|---|---|---|
| v3.0-draft | 2026-04-20 | Initial draft authored in the `docs/phase-5-v3-roadmap-document-3` branch. Encodes Charter §5.10 Phases A-B-C-D + this Roadmap's Phase D.5 topology migration addendum. Sequences the six boot strategies (Crypto Momentum → Trend Following → Mean Rev Equities → VRP → Macro Carry → News-driven) per Charter §4 across the 24-month horizon. Authors ADR-0007 (Strategy as Microservice), ADR-0008 (Capital Allocator Topology), ADR-0009 (Panel Builder Discipline), ADR-0010 (Target Topology Reorganization) as embedded summaries and standalone files. Supersedes PHASE_5_SPEC_v2.md and PROJECT_ROADMAP.md on merge. Awaiting CIO review and ratification. |

---

**END OF ROADMAP v3.0-draft.**
