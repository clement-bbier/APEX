# APEX Multi-Strategy Platform — Strategy Development Lifecycle Playbook

**Document 2 of 3** (operational layer)
**Version**: v1.0 (RATIFIED)
**Status**: ACTIVE (binding)
**Authoring date**: 2026-04-19
**Inherits from**: [`docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md`](ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) (Charter v1.0, ratified 2026-04-18)
**Binds**: Document 3 (`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`, pending authoring)

---

## §0 — Preamble and Scope

### 0.1 Purpose

This Playbook is the **operational manual** of the APEX Multi-Strategy Platform. Where the Charter (Document 1) defines *what* the platform is, *what* the gates require, and *what* the rules are, this Playbook defines *how* a strategy is built, validated, deployed, monitored, and retired in mechanical detail.

It is the document a new researcher joining a quant pod at Millennium, Citadel, or AQR would read on day 1 to understand the firm's operational discipline. For APEX, the new researcher is either the CIO returning to the platform after a gap, or — far more often — a Claude Code agent invoked on a new session against the repository. In either case, the Playbook compresses thousands of small decisions into a single reference: at this stage, this person performs this evaluation against this evidence using this template, hands off in this form, and waits for this signal before proceeding.

The Playbook is **operationally specific**. Every section answers four questions: *who acts*, *what they consume as input*, *what they produce as output*, and *what triggers the next step*. Vague prescriptions ("the CIO reviews periodically") are explicitly forbidden; concrete prescriptions ("the CIO signs the Gate 3 evidence package within 5 working days of paper closeout, ratifying in the form of a merged PR with the artifact attached") are mandatory.

### 0.2 Audience

The Playbook serves three concurrent audiences:

1. **CIO — Clement Barbier**. The Playbook is his standing-order book for managing the strategy portfolio. When a strategy enters a gate, when it trips a circuit breaker, when it approaches decommissioning, when a new candidate emerges from the literature, the CIO consults the Playbook to confirm the operational steps and to gate his own decisions.

2. **Claude Code agents — every session, every model**. The Playbook is the single document an agent reads to orient itself when invoked on strategy work. It tells the agent *what stage the work belongs to*, *what artifacts must be produced*, *what templates to copy*, *what tests to run*, *what HARD STOPs to respect*. An agent that produces a Gate 2 PR without the CPCV evidence the Playbook prescribes has violated the Playbook regardless of code quality.

3. **Future maintainers and external auditors** (theoretical — APEX has no external investors, but the Playbook is written as if it would be reviewed by a senior allocator's operational due-diligence team). The Playbook documents that the platform's strategy decisions are **defensible against institutional standards** — not the product of one person's mood on a given day.

### 0.3 Relationship to the Charter

The Playbook **inherits**, **operationalizes**, and **does not contradict** the Charter:

| Charter section | Playbook section |
|---|---|
| §2 — Seven binding principles | Inherited verbatim; cited in tie-breaking decisions |
| §4 — Six boot strategies | §2.4 provides per-strategy Charter templates filled in for each |
| §7 — Four-gate lifecycle (overview) | §3 (Gate 1), §4 (Gate 2), §5 (Gate 3), §6 (Gate 4) — full operational protocol |
| §8 — Circuit breakers and VETO | §8 (soft CB responses), §9 (hard CB responses) — operational playbooks per trigger |
| §9 — Categories, decommissioning, reactivation | §10 (decommissioning checklist), §11 (reactivation checklist), §12 (category reassignment) |
| §11 — Extensibility | §13 (new candidate onboarding) |
| §13.7 — Roles | §14 (per-role operational responsibilities) |

Where the Charter defines a *what*, the Playbook defines the *how*. The Playbook never softens, extends, or contradicts a Charter rule. If an operational reality emerges that requires the Charter to change, the Playbook does not absorb the change unilaterally; the change goes back through the Charter amendment procedure (Charter §13.4) and the Playbook is updated downstream.

### 0.4 What this Playbook does NOT do

- **Does not redefine Charter decisions.** The Q1–Q8 Charter decisions are inherited verbatim. The Playbook never authors a new architectural decision; it executes the Charter's.
- **Does not replace ADRs.** ADR-0002 (Quant Methodology Charter, 10-point checklist), ADR-0004 (Feature Validation), ADR-0005 (Meta-Labeling), ADR-0006 (Fail-Closed Risk) are inherited. The Playbook references them; it does not re-author them.
- **Does not author per-strategy Charters.** Section 2 provides a **template** for the per-strategy Charter that the CIO fills in for each strategy at Gate 2. The Playbook authors the template, not the contents.
- **Does not schedule work.** Document 3 (Roadmap) sequences when each strategy goes through each gate. The Playbook describes the gates themselves.
- **Does not specify code conventions.** Inherited from [CLAUDE.md](../../CLAUDE.md) verbatim. Forbidden patterns (float for prices, naive datetimes, `print()`, `except: pass`, etc.) are not restated here; they apply unconditionally.

### 0.5 Status and revision model

The Playbook is **versioned**. Material changes — adding or removing a gate criterion, changing a gate threshold, modifying the per-strategy Charter template, changing a circuit-breaker response protocol, restructuring decommissioning execution — require:

1. A new ADR documenting the change and its rationale.
2. A version bump (`v1.0 → v1.1` for additive clarifications; `v1.x → v2.0` for breaking changes).
3. An entry in [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
4. A pull request reviewed and merged by the CIO.

Cosmetic edits (typos, link corrections, additional worked examples that do not alter procedure) do not require version bumps but must be logged in the Changelog (§18).

### 0.6 Binding precedence

If the Playbook and the Charter conflict, the Charter prevails. If the Playbook and an ADR conflict, the ADR prevails for the technical surface it governs. If the Playbook and CLAUDE.md conflict on a coding convention, CLAUDE.md prevails. If the Playbook and Document 3 (Roadmap) conflict on schedule vs operational order, the conflict resolution depends on whether the disagreement is about **what the gate requires** (Playbook prevails) or **when the gate runs** (Roadmap prevails).

In practice, no conflict is anticipated — the documents operate on different levels.

---

## §1 — The Strategy Lifecycle at a Glance

### 1.1 Visual — the four-gate flow

```
                                    ┌─────────────────────────────────────────────────┐
                                    │                                                 │
                                    │     APEX STRATEGY DEVELOPMENT LIFECYCLE         │
                                    │                                                 │
                                    │     (per-strategy; strategies in different      │
                                    │      gates simultaneously, no lockstep)         │
                                    │                                                 │
                                    └─────────────────────────────────────────────────┘

                             [INFORMAL RESEARCH]
                                     │
                                     ▼
                  ┌────────────── GATE 1 ──────────────┐
                  │   Research → Approved Backtest     │
                  │   (Charter §7.1)                   │
                  │   • Thesis with academic ref       │
                  │   • 2y+ backtest data              │
                  │   • Sharpe > 1.0, max DD < 15%     │
                  │   • PSR > 95%, PBO < 0.5           │
                  │   • ADR-0002 10-point checklist    │
                  └────────────────┬───────────────────┘
                                   │ (PASS)            │ (FAIL)
                                   ▼                   ▼
                                                ┌─────────────────────────────┐
                                                │ RETURN TO RESEARCH          │
                                                │ documented reason; revise;  │
                                                │ re-enter Gate 1             │
                                                └─────────────────────────────┘
                                   │
                  ┌────────────── GATE 2 ──────────────┐
                  │   Backtest → Paper Trading         │
                  │   (Charter §7.2)                   │
                  │   • Per-strategy Charter ratified  │
                  │   • CPCV OOS Sharpe > 0.8          │
                  │   • 10 stress scenarios passed     │
                  │   • Coverage ≥ 90% on microservice │
                  │   • Smoke-test green               │
                  │   • PR review (human + Copilot)    │
                  └────────────────┬───────────────────┘
                                   │ (PASS)
                                   ▼
                  ┌────────────── GATE 3 ──────────────┐
                  │   Paper Trading → Live Micro       │
                  │   (Charter §7.3)                   │
                  │   • ≥ 8 weeks paper                │
                  │   • ≥ 50 trades                    │
                  │   • Paper Sharpe > 0.8             │
                  │   • Paper max DD < 10%             │
                  │   • Win rate ±10% vs backtest      │
                  │   • Zero pod crash                 │
                  │   • Observability green            │
                  └────────────────┬───────────────────┘
                                   │ (PASS)
                                   ▼
                  ┌────────────── GATE 4 ──────────────┐
                  │   Live Micro → Live Full           │
                  │   (Charter §7.4)                   │
                  │   • 60-day linear ramp 20% → 100%  │
                  │   • Day-60 decision:               │
                  │       Live Sharpe > 70% paper      │
                  │   • Otherwise: observation mode    │
                  └────────────────┬───────────────────┘
                                   │ (PASS)
                                   ▼
                  ┌─────────── STEADY STATE ───────────┐
                  │   Full allocation, weekly          │
                  │   rebalance, soft + hard CBs       │
                  │   active, semi-annual review       │
                  └────────────────┬───────────────────┘
                                   │
                                   │  (over time, may trigger)
                                   ▼
                  ┌──── DECOMMISSION (§9.2 rules) ─────┐
                  │   Sharpe < 0 (9M), Sharpe < -0.5   │
                  │   (6M), 90d in review_mode, DD     │
                  │   > 20% peak-to-trough, 3 hard CB  │
                  │   trips in 6M, CIO discretion      │
                  └────────────────┬───────────────────┘
                                   │
                                   │  (after ≥ 6 months + corrected root cause)
                                   ▼
                  ┌─────────── REACTIVATION ───────────┐
                  │   Re-run Gate 1, 2, 3 from         │
                  │   scratch; live-micro re-ramp      │
                  └────────────────────────────────────┘
```

### 1.2 Timeline expectations

The lifecycle is **trigger-based**, not calendar-based (Charter §7). Strategies advance only when their gate criteria are met; there are no "we're three months in, time to deploy" deadlines.

That said, the Charter binds two **floors** that cannot be shortened:

- **Gate 3 paper trading**: minimum **8 weeks** AND minimum **50 trades** (Charter §7.3). A strategy that is too low-frequency to accumulate 50 trades in 8 weeks waits longer; the 50-trade floor is statistical (anything less produces too-wide bootstrap CIs on Sharpe and win rate).
- **Gate 4 live-micro ramp**: minimum **60 calendar days** at the linear 20% → 100% ramp (Charter §6.1.3, §7.4). The Day-60 decision is binding; no early promotion, no shortcuts.

There are no maximum durations. A strategy may sit in Gate 1 for months (waiting for sufficient academic grounding), in Gate 2 for weeks (waiting for stress-test work to complete), in Gate 3 indefinitely (if the operator wants extra paper evidence), or in observation mode at 20% allocation indefinitely (until the CIO decides to clear or decommission).

Indicative timelines for a typical first-deployment strategy (Strategy #1 Crypto Momentum is the worked-example anchor throughout this Playbook):

| Stage | Wall-clock estimate (Strategy #1) |
|---|---|
| Informal research → Gate 1 PR opened | 2–6 weeks |
| Gate 1 PR review + merge | 3–7 days |
| Gate 1 merge → Gate 2 PR opened | 4–8 weeks (microservice build + CPCV + stress tests) |
| Gate 2 PR review + merge | 5–10 days |
| Gate 2 merge → Gate 3 paper start | 1–3 days (deployment + smoke test) |
| Gate 3 paper trading | 8–12 weeks |
| Gate 3 closeout → Gate 4 live-micro start | 5–10 days (CIO ratification + capital movement) |
| Gate 4 live-micro 60-day ramp | exactly 60 calendar days |
| Day-60 decision → Live Full | 1–5 days (CIO ratification) |

**Total wall-clock from informal research to Live Full**: ~5–8 months for the first strategy. Subsequent strategies benefit from infrastructure compounding (per Charter §3.3) and may compress to ~3–5 months.

### 1.3 Concurrent strategies — no lockstep

Strategies progress through the lifecycle **independently**. Per Charter §7.5:

- Strategy #1 may be in Gate 4 (live full) while Strategy #2 is in Gate 3 (paper) and Strategy #3 is in Gate 1 (backtest).
- A strategy in Gate 2 has no operational claim on a strategy in Gate 4; they are separate objects in separate microservices.
- The CIO's review cadence is per-strategy at the daily/weekly level and portfolio-level at the monthly/semi-annual level (§7).

This independence is a deliberate operational property of the multi-strat architecture. The platform never enters a "we are between strategies" state; at every moment, several strategies are at different stages of the pipeline.

### 1.4 Entry points

A new strategy enters the lifecycle at **Gate 1**. There are no shortcuts:

- The six boot strategies (Charter §4) entered Gate 1 at the time of platform launch in deployment-order sequence (§7.5: Crypto Momentum first, News-driven last).
- New candidates from the open backlog (Charter §11.2) enter Gate 1 when the CIO accepts the candidate for formal pipeline entry (§13).
- A previously decommissioned strategy entering reactivation (Charter §9.3) re-enters Gate 1 from scratch — no grandfathering of prior gate passes.

### 1.5 Exit points

A strategy may exit the lifecycle at any gate:

- **Gate 1 fail**: return to research with documented reason; the strategy is not "decommissioned" because it was never deployed. The research code is preserved; the candidate is parked in the backlog with a note explaining what would need to change for re-entry.
- **Gate 2 fail**: same — return to research; per-strategy Charter (if drafted) is archived with an appendix documenting the failure mode.
- **Gate 3 fail**: return to research, with the per-strategy microservice preserved in the codebase. Common Gate 3 failures (paper Sharpe gap vs backtest, win-rate divergence, pod stability issues) reveal implementation bugs or regime mismatches that re-research can address.
- **Gate 4 fail (Day 60 decision)**: enter observation mode at 20% allocation. The CIO may extend observation, return to paper, or decommission per Charter §9.4.
- **Steady state → decommissioning**: triggered by the six rules of Charter §9.2 (operationalized in §10 of this Playbook).

The exit paths are designed to **preserve work**. Failing a gate is not catastrophic; it is data. The strategy's research, code, configuration, and historical evidence remain in the repository, available for revision and re-entry.

### 1.6 Roles at a glance

Per Charter §13.7, four roles operate the lifecycle. Their responsibilities at each stage are detailed in §14; here they are at a glance:

| Role | Primary responsibilities (lifecycle context) |
|---|---|
| **CIO** (Clement Barbier) | Ratifies each gate transition; signs per-strategy Charters at Gate 2; makes Day-60 Gate 4 decisions; rules on decommissioning and reactivation; conducts semi-annual reviews. |
| **Head of Strategy Research** (Claude Opus 4.7, claude.ai) | Reviews academic grounding of new candidates; reviews Gate 1 backtest results for statistical soundness; reviews Gate 3 paper evidence packages; drafts mission prompts for Claude Code. |
| **Claude Code Implementation Lead** (Sonnet/Opus, repository sessions) | Develops strategy microservices; runs backtests, CPCV, stress tests; opens PRs at gate handoffs; respects HARD STOPs and waits for CIO ratification. |
| **CI System** (GitHub Actions per [.github/workflows/ci.yml](../../.github/workflows/ci.yml)) | Enforces coverage gates, linting, typing, security; runs the (currently muzzled — issue #102) backtest-gate; refuses merges on red pipelines. |

No role makes ratification decisions outside its scope. Claude Code does not promote a strategy past a gate; only the CIO does. The Head of Strategy Research does not merge code; only the CIO does. The CI system does not interpret evidence; it enforces mechanical checks.

### 1.7 The "default strategy" — backward-compatibility footprint

During the multi-strat infrastructure lift (Charter §5.10, scheduled in Document 3), the legacy single-strategy signal path in [`services/signal_engine/pipeline.py`](../../services/signal_engine/pipeline.py) is wrapped as a concrete `StrategyRunner` subclass called `LegacyConfluenceStrategy`. This strategy carries `strategy_id = "default"` (the Pydantic backward-compatibility default per Charter §5.5).

For Playbook purposes:

- `LegacyConfluenceStrategy` is **not** subject to the four-gate lifecycle in retrospective evaluation. It is a transitional artifact preserving Phase 4 single-strategy behavior under the multi-strat architecture (Principle 6).
- Once Strategy #1 (Crypto Momentum) reaches Gate 4 Live Full, the default strategy is decommissioned per the standard decommissioning protocol (§10). Until then, it remains operational at whatever paper/live posture is current per the Roadmap (Document 3).
- New strategies are not built on top of `LegacyConfluenceStrategy`; they are independent microservices under `services/strategies/<name>/`.

---

## §2 — The Per-Strategy Charter Template

Every strategy deployed on APEX has its own one-page Charter — distinct from and subordinate to the platform Charter (Document 1). The per-strategy Charter is **drafted by the Head of Strategy Research** (or by Claude Code under explicit prompt), **ratified by the CIO** at Gate 2, and **stored alongside the strategy's microservice** at `docs/strategy/per_strategy/<strategy_id>.md`.

The per-strategy Charter is the strategy's standing-order document: what the strategy is, why it exists, what universe and timeframes it operates on, what features it consumes, what risk budgets it inherits, what it must do and what it must not do.

### 2.1 Why the per-strategy Charter exists

The platform Charter (Document 1) governs the *platform*. The per-strategy Charter governs *one strategy* with the same constitutional weight at the strategy scale. It serves three concrete operational functions:

1. **Onboarding** — a Claude Code agent invoked on Strategy X work reads the per-strategy Charter for X first; this single page contains everything the agent needs to make defensible local decisions.
2. **Configuration ground truth** — the per-strategy Charter declares the strategy's parameters; `config/strategies/<strategy_id>.yaml` implements them. Any divergence is a bug.
3. **Audit trail** — when a strategy is decommissioned or reviewed, the per-strategy Charter provides the original specification against which actual behavior is judged.

### 2.2 Storage and naming

| Property | Convention |
|---|---|
| File location | `docs/strategy/per_strategy/<strategy_id>.md` |
| `strategy_id` format | `snake_case`, descriptive, no numbers — e.g., `crypto_momentum`, `mean_rev_equities`, `volatility_risk_premium` |
| Mirror in code | `services/strategies/<strategy_id>/` (matching folder name) |
| Mirror in config | `config/strategies/<strategy_id>.yaml` (matching base name) |
| Mirror in tests | `tests/unit/strategies/<strategy_id>/` |

The `strategy_id` is the **single source of truth identifier** that links the per-strategy Charter, the microservice, the config, the tests, the per-strategy Redis keys (`kelly:{strategy_id}:{symbol}`, `trades:{strategy_id}:all`, `pnl:{strategy_id}:daily`), and the per-strategy ZMQ topics (`Topics.signal_for(strategy_id, symbol)` — planned, see Charter §5.5 / CONTEXT.md).

### 2.3 The Template

Copy-paste this block as the starting point for any new per-strategy Charter. Every section is mandatory; sections that do not apply ("no overrides from category defaults") are **explicitly stated** as such, never omitted.

```markdown
# Per-Strategy Charter — <Strategy Display Name>

**Strategy ID**: `<strategy_id>`
**Status**: <DRAFT (Gate 1) | RATIFIED (Gate 2) | LIVE MICRO | LIVE FULL | OBSERVATION | REVIEW MODE | DECOMMISSIONED>
**Authoring date**: YYYY-MM-DD
**Author**: <Head of Strategy Research / Claude Code session ID>
**Ratified by CIO**: YYYY-MM-DD (or "PENDING")
**Inherits from**: APEX Multi-Strat Charter v1.0
**Category**: <Low Vol | Medium Vol | High Vol> (Charter §9.1)

---

## 1. Identity

| Field | Value |
|---|---|
| Display name | <Human-readable name> |
| `strategy_id` | `<snake_case>` |
| Deployment order | <1–6 for boot strategies; "post-boot candidate N" otherwise> |
| Microservice path | `services/strategies/<strategy_id>/` |
| Config path | `config/strategies/<strategy_id>.yaml` |

## 2. Thesis

**Edge mechanism (1–3 sentences)**: <What is the alpha source? Why does it exist? Why has it not been arbitraged away?>

**Academic basis** (≥ 1 reference, peer-reviewed or established research lineage):
- <Author (Year). "Title". Journal Volume, Pages.> [Cite the specific paper that establishes the edge]
- Optional: <Additional supporting references>

**Expected Sharpe range (academic baseline)**: <e.g., 0.8 – 1.4>

**Expected behavior regimes**: <Where the edge is strongest (e.g., "low-vol grinding markets", "post-CB-announcement windows") and where it is weakest>

## 3. Universe and timeframes

| Field | Value |
|---|---|
| Asset universe | <e.g., "Binance USDT-quoted top 20 by market cap, refreshed monthly"> |
| Signal horizon | <e.g., 4h to 24h> |
| Execution bar frequency | <e.g., 5min> |
| Operating sessions | <e.g., "24/7 (crypto)" or "US regular hours 09:30-16:00 ET"> |
| Universe rebalancing cadence | <e.g., monthly first-Sunday> |

## 4. Required features and data

**Features consumed** (cite [features/](../../features/) tree where applicable):
- `<feature_name>` — <purpose in this strategy>
- ...

**Data sources** (with cost disclosure per Charter Principle 3):
- <source>: <purpose>; cost: $<amount>/month
- Total monthly data cost: $<sum>

**Data freshness requirements**: <e.g., "tick latency < 250ms acceptable; bar lag > 30s triggers strategy pause">

## 5. Budget and risk

**Category inheritance**: <Low Vol | Medium Vol | High Vol> — inherits the following defaults (Charter §9.1):
- Max DD: <8% | 12% | 20%>
- Min Sharpe: <1.0 | 0.8 | 0.6>
- Max leverage: <1× | 1× | 1.5×>

**Overrides from category defaults**: <"None at boot" OR list each override with explicit justification>

**Per-strategy soft circuit-breaker thresholds** (Charter §8.1.1):
- DD 24h soft trigger: <8% | other with justification> → Kelly × 0.5
- DD 24h pause trigger: <12% | other> → 24h pause
- DD 72h review-mode trigger: <15% | other> → review_mode
- Win rate alert: <25% over 50 trades | other>

## 6. Position sizing and aggressiveness

| Parameter | Value |
|---|---|
| Kelly fraction (default) | 0.4 (Charter §6.3) |
| Kelly fraction override | <"None" OR value with justification> |
| Max risk per trade | <e.g., 1% of strategy allocation> |
| Max position size | <e.g., 10% of strategy allocation per symbol> |
| Max open positions | <e.g., 5 simultaneous> |
| Max inter-position correlation within strategy | <e.g., 0.7> |

## 7. Stop-loss and take-profit logic

**Stop-loss rule**: <Specify exactly: ATR-based, fixed-bps, time-based, etc.>

**Take-profit rule**: <Specify exactly>

**Holding period bounds**: <min | max | typical>

**Forced exit conditions**: <e.g., "all positions flat 60min before scheduled CB announcement">

## 8. Expected trade frequency

| Metric | Estimate |
|---|---|
| Trades per day (typical) | <range> |
| Trades per week (typical) | <range> |
| Annualized turnover | <range, % of allocation> |

## 9. Known risk factors and mitigations

For each material risk, state: (a) the risk, (b) the historical example or analog, (c) the mitigation in this strategy.

| # | Risk | Historical analog | Mitigation |
|---|---|---|---|
| 1 | <e.g., regulatory enforcement on crypto venue> | <e.g., FTX 2022, Binance CFTC 2023> | <Specific mitigation in this strategy> |
| 2 | ... | ... | ... |
| 3 | ... | ... | ... |

## 10. Operational interfaces

**Subscribes to** (ZMQ topics, with strategy_id qualification where applicable):
- <topic pattern>

**Publishes to**:
- `order.candidate.<strategy_id>.<symbol>` (per Charter §5.5)
- `signal.technical.<strategy_id>.<symbol>` (planned topic factory; until available, uses current `Topics.signal(symbol)` and tags `strategy_id` at producer level)

**Redis keys it reads**:
- `kelly:<strategy_id>:<symbol>` (its own Kelly state)
- `meta_label:latest:<strategy_id>:<symbol>` (its own meta-labeler card)
- ...

**Redis keys it writes**:
- `pnl:<strategy_id>:daily`
- `trades:<strategy_id>:all`
- ...

## 11. Reviewer sign-off

| Reviewer | Action | Date |
|---|---|---|
| Head of Strategy Research | Drafted | YYYY-MM-DD |
| Claude Code | Implemented per draft | YYYY-MM-DD |
| **CIO (Clement Barbier)** | **RATIFIED at Gate 2** | YYYY-MM-DD |

## 12. Revision history

| Version | Date | Change |
|---|---|---|
| v1.0 | YYYY-MM-DD | Initial Charter; Gate 2 ratification |
| v1.1 | YYYY-MM-DD | <e.g., "Kelly override added per CIO post-Gate-3 observation"> |
```

### 2.4 Worked references — the six boot strategies

Each of the six boot strategies (Charter §4) gets a per-strategy Charter at Gate 2. The full content of each is owned by the strategy's per-strategy Charter file (e.g., `docs/strategy/per_strategy/crypto_momentum.md`); below is a short-form reference for each, derived from Charter §4.

#### 2.4.1 `crypto_momentum` — Charter §4.1

| Field | Value |
|---|---|
| Display name | Crypto Momentum |
| Category | Medium Vol |
| Universe | Binance top-20 USDT-quoted (BTCUSDT, ETHUSDT, SOLUSDT, …) |
| Signal horizon | 4h – 24h |
| Execution bars | 5min |
| Academic basis | Liu & Tsyvinski (2021), *Review of Financial Studies* 34, 2689-2727 |
| Expected Sharpe | 0.8 – 1.4 |
| Required features | Momentum (3/7/14/30d); OFI (`features/calculators/ofi.py`); CVD/Kyle λ (`features/calculators/cvd_kyle.py`); Rough Vol (`features/calculators/rough_vol.py`); funding-rate proxy |
| Data sources | Binance WebSocket + REST (free) |
| Budget overrides | None at boot |
| Deployment order | 1 of 6 |

#### 2.4.2 `trend_following` — Charter §4.2

| Field | Value |
|---|---|
| Display name | Trend Following Multi-Asset |
| Category | Medium Vol |
| Universe | BTC, ETH, SPY, GLD (daily) |
| Signal horizon | 1d – 5d |
| Execution bars | Daily |
| Academic basis | Moskowitz, Ooi & Pedersen (2012), *J. Financial Economics* 104, 228-250 |
| Expected Sharpe | 0.8 – 1.2 per asset; portfolio 1.0 – 1.5 |
| Required features | Cumulative return (10/20/60/120d); HAR-RV (`features/calculators/har_rv.py`); cross-asset correlation matrix |
| Data sources | Binance + Alpaca (free) |
| Budget overrides | None at boot |
| Deployment order | 2 of 6 |

#### 2.4.3 `mean_rev_equities` — Charter §4.3

| Field | Value |
|---|---|
| Display name | Mean Reversion Intraday Equities |
| Category | Low Vol |
| Universe | S&P 500 liquid names (ADV > 5M shares, spread < 5bps), top 100 |
| Signal horizon | 5min – 1h |
| Execution bars | 1min |
| Academic basis | Avellaneda & Lee (2010), *Quantitative Finance* 10, 761-782 |
| Expected Sharpe | 1.0 – 1.8 |
| Required features | Bollinger Bands (5min, 15min); RSI(14); VWAP deviation; OFI; HAR-RV; **GEX (Phase 2 only — requires options-chain data ~$200-300/month)** |
| Data sources | Alpaca (free) + optional Polygon/CBOE/ORATS for GEX (Phase 2) |
| Budget overrides | None at boot |
| Deployment order | 3 of 6 |

#### 2.4.4 `volatility_risk_premium` — Charter §4.4

| Field | Value |
|---|---|
| Display name | Volatility Risk Premium |
| Category | High Vol |
| Universe | VIX (VXX/UVXY); Phase 2 extension to crypto IV via Deribit |
| Signal horizon | 1d – 7d |
| Execution bars | Daily |
| Academic basis | Carr & Wu (2009), *Review of Financial Studies* 22, 1311-1341 |
| Expected Sharpe | 0.6 – 1.0 (no tail hedge); 0.8 – 1.4 (with tail hedge) |
| Required features | VIX spot + term structure (VIX/VIX3M, VIX/VIX6M); HAR-RV on SPY; RV/IV spread |
| Data sources | Yahoo + FRED + Alpaca (free) |
| Budget overrides | High Vol category permits 1.5× leverage and 20% DD specifically for VRP |
| Deployment order | 4 of 6 |

#### 2.4.5 `macro_carry` — Charter §4.5

| Field | Value |
|---|---|
| Display name | Macro Carry FX G10 |
| Category | Low Vol |
| Universe | G10 FX pairs (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) |
| Signal horizon | 1d – 30d |
| Execution bars | Daily |
| Academic basis | Lustig, Roussanov & Verdelhan (2011), *Review of Financial Studies* 24, 3731-3777 |
| Expected Sharpe | 0.6 – 1.2 (no carry-crash hedge); 0.8 – 1.5 (with hedge) |
| Required features | Central-bank policy rates (FRED + ECB/BoE/BoJ scrapers per [`services/data_ingestion/connectors/`](../../services/data_ingestion/)); FX spot vol per pair; global risk indicator (VIX or composite) |
| Data sources | Yahoo + FRED + CB scrapers (free); Phase 3 OANDA/IBKR for execution |
| Budget overrides | None at boot — Low Vol Sharpe bar (1.0) deliberately tight to force regime overlay efficacy |
| Deployment order | 5 of 6 |

#### 2.4.6 `news_driven` — Charter §4.6

| Field | Value |
|---|---|
| Display name | News-Driven Short-Horizon |
| Category | Medium Vol |
| Universe | Liquid US equities (S&P 500 subset) + BTC + ETH |
| Signal horizon | 15min – 4h |
| Execution bars | 5min |
| Academic basis | Tetlock (2007), *J. Finance* 62, 1139-1168; Tetlock, Saar-Tsechansky & Macskassy (2008) |
| Expected Sharpe | 0.8 – 1.5 |
| Required features | GDELT 2.0 event stream (15min); FinBERT sentiment (rolling 4h); OFI + CVD; HAR-RV |
| Data sources | GDELT 2.0 (free) + FinBERT ONNX (free) + Binance + Alpaca |
| Budget overrides | None at boot; flagged for Budget-category review post-Gate-3 if live evidence justifies |
| Deployment order | 6 of 6 |

### 2.5 Per-strategy Charter authoring discipline

Three rules govern per-strategy Charter authoring:

1. **Specificity over generality**. "Reasonable position sizing" is forbidden; "max 10% of strategy allocation per symbol, max 5 simultaneous open positions, max 0.7 inter-position correlation within strategy" is mandatory.

2. **Citation over assertion**. Every academic claim cites a specific paper. Every code claim cites a specific path (`features/calculators/ofi.py`, `services/risk_manager/chain_orchestrator.py:61`). Vague references ("our existing OFI module") are forbidden.

3. **Override-with-reason discipline**. Any deviation from category defaults (Charter §9.1) requires explicit justification. "Crypto Momentum overrides max-leverage to 2×" is forbidden as a bare statement; it requires either "(a) inherited from Medium Vol category defaults, no override" or "(b) override to 2× justified by [specific empirical / academic argument]".

---

## §3 — Gate 1 — Research → Approved Backtest

Gate 1 is the **research-to-formal-evidence** gate. A candidate strategy that has shown promise in informal backtesting is promoted to a formal, reproducible, multi-metric backtest artifact that satisfies the Charter §7.1 criteria and the ADR-0002 10-point evaluation checklist.

### 3.1 Entry criteria

A candidate enters Gate 1 when **all** of the following are true:

1. **Source identified.** The candidate is sourced from a legitimate channel per Charter §11.2: peer-reviewed academic literature, internal research spike with documented motivation, market observation with documented rationale, or reactivation of a previously decommissioned strategy. Speculative "what if" ideas without one of these sources are not Gate 1 candidates — they remain in informal research.
2. **Strategy ID assigned.** A `snake_case` `strategy_id` per §2.2 conventions is assigned. The CIO confirms the ID does not collide with existing or recently-decommissioned strategies.
3. **Informal evidence assembled.** A quick-and-dirty backtest (Jupyter notebook, no infrastructure ceremony) shows preliminary edge: positive in-sample Sharpe over a meaningful holdout, trade count above the noise floor, no obvious data-leakage. The CIO confirms this informal evidence is "interesting enough to formalize" before Gate 1 work begins.
4. **Per-strategy folder seed created.** A skeleton folder `docs/strategy/per_strategy/<strategy_id>/` exists (or will be created in the Gate 1 PR), holding the placeholder per-strategy Charter (§2.3 template). The Charter is *not* ratified at Gate 1 — it is drafted and ratified at Gate 2 — but its existence as a draft anchors the work.

### 3.2 Deliverables required for Gate 1 PASS

The Gate 1 PR (the pull request that merges Gate 1 evidence into `main`) MUST contain the following artifacts. Every item is mandatory; no item may be skipped.

#### 3.2.1 Documented thesis document

**Location**: `docs/strategy/per_strategy/<strategy_id>.md` (the per-strategy Charter file, in DRAFT status — sections 1, 2, 3, 4 fully populated; sections 5–12 may be partially populated and finalized at Gate 2).

**Mandatory content** (per §2.3 template):
- §1 Identity (strategy_id, display name, deployment-order tag, microservice/config/test paths planned)
- §2 Thesis: 1–3 sentences on edge mechanism + ≥ 1 academic reference + expected Sharpe range
- §3 Universe and timeframes
- §4 Required features and data (with cost disclosure per Charter Principle 3)

#### 3.2.2 Research notebook

**Location**: `notebooks/research/<strategy_id>/gate1_backtest.ipynb`

**Mandatory structure** — five sections in this order:

1. **Setup and data loading**. Imports, deterministic random seeds (per CLAUDE.md §10 forbidden patterns: use `secrets.SystemRandom()` for any seed-controlled randomness in the production microservice; in research notebooks `numpy.random.default_rng(seed=42)` is acceptable for reproducibility), data fetch from the project's data layer (TimescaleDB via existing connectors per [`services/data_ingestion/connectors/`](../../services/data_ingestion/)).
2. **Feature computation**. Concrete feature calculation using existing [`features/calculators/`](../../features/) modules where applicable. Custom features for the strategy go in `features/calculators/<strategy_id>/<feature>.py`, are tested in unit tests, and are reused by the production microservice — no notebook-only feature code that the microservice later re-implements.
3. **Backtest logic**. Either: (a) use the canonical [`backtesting/`](../../backtesting/) harness (preferred when applicable), or (b) for research-stage strategies whose semantics do not yet fit the canonical harness, a notebook-local backtest with explicit documentation of the deviations from the canonical harness. The canonical harness is the long-term target; notebook-local is acceptable transitional.
4. **Metrics output**. Call `backtesting.metrics.full_report(trades, …)` ([`backtesting/metrics.py:1327`](../../backtesting/metrics.py)) on the trade list. The full report produces all ADR-0002-mandated metrics in one call: Sharpe, PSR, DSR, bootstrap CI, Sortino, Calmar, CAGR, max DD, max DD absolute, max DD duration, Ulcer Index, Martin ratio, return skew/kurtosis/tail-ratio, win rate, profit factor, trade count, by_session, by_regime, regime concentration HHI, by_signal, equity curve. The PBO field is populated when `strategy_returns_matrix` is supplied (Gate 2 work; not strictly required at Gate 1 but encouraged as preview).
5. **Stress-test preview**. A first-pass stress test on at least 3 of the 10 stress scenarios (full set lands at Gate 2 per §4). Preview gives the CIO early signal on whether the strategy is robust enough to survive Gate 2.

The notebook is **versioned in git** (committed as part of the Gate 1 PR). Output cells are saved (not stripped) so that reviewers see the actual numbers without re-running. Notebooks larger than 5MB are split into a results-only notebook + a separately-runnable computation notebook.

#### 3.2.3 Backtest artifact (machine-readable summary)

**Location**: `reports/<strategy_id>/gate1/full_report.json`

**Content**: serialized output of `backtesting.metrics.full_report(...)` for the in-sample backtest. JSON-serializable; numeric fields as floats; equity curve as a list of floats. The dashboard, future audits, and CI-style mechanical comparisons consume this artifact.

#### 3.2.4 Required metrics — Charter §7.1 thresholds

All five thresholds from Charter §7.1 must hold simultaneously on the in-sample backtest:

| Metric | Threshold | Source |
|---|---|---|
| Backtest data span | **≥ 2 years** | Charter §7.1; required for stable Sharpe estimate |
| Historical Sharpe (in-sample) | **> 1.0** | Charter §7.1; computed on daily-resampled equity curve per ADR-0002 item 1 (NOT per-trade returns) |
| Historical max DD | **< 15%** | Charter §7.1; from `full_report["max_drawdown"]` |
| PSR (Probabilistic Sharpe Ratio) | **> 95%** | Charter §7.1; from `full_report["psr"]`; Bailey & López de Prado (2014) |
| PBO (Probability of Backtest Overfitting) | **< 0.5** | Charter §7.1; from `full_report["pbo"]` (requires `strategy_returns_matrix` argument); Bailey, Borwein, López de Prado & Zhu (2014); CPCV-derived |

**Computation discipline** (binding):

- Sharpe is computed on **daily-resampled equity-curve returns**, never on per-trade returns (ADR-0002 mandatory item 1; reason: per-trade returns of HFT magnitude become dominated by the annualized risk-free rate and produce arbitrarily-negative Sharpe even for highly profitable strategies — see issue #8 / [`backtesting/metrics.py:1392-1397`](../../backtesting/metrics.py)).
- Drawdown is computed on the **same daily curve** as Sharpe (see [`backtesting/metrics.py:1401-1406`](../../backtesting/metrics.py) — mixing per-trade and daily curves silently desynchronizes max_drawdown from ulcer_index).
- PSR uses the **same excess-return series** as the headline Sharpe (see [`backtesting/metrics.py:1409-1421`](../../backtesting/metrics.py) — otherwise PSR is silently inconsistent with Sharpe whenever risk-free rate ≠ 0).

#### 3.2.5 ADR-0002 10-point evaluation checklist

The Gate 1 PR body MUST include a checklist confirming all 10 items from [ADR-0002](../adr/0002-quant-methodology-charter.md). Reviewers reject the PR if any box is unchecked without explicit justification.

| # | ADR-0002 item | Where in `full_report` | Notebook section |
|---|---|---|---|
| 1 | Returns basis: daily-resampled equity-curve returns (not per-trade) | `sharpe`, `psr`, `dsr` (built on `daily_returns`) | §4 |
| 2 | OOS validation: train/test with embargoed gap OR walk-forward purge+embargo | `is_report` / `oos_report` when `oos_fraction > 0`; CPCV at Gate 2 | §3 + §4 |
| 3 | Statistical significance: 95% bootstrap CI + PSR with skew/kurtosis correction | `sharpe_ci_95_low`, `sharpe_ci_95_high`, `psr` | §4 |
| 4 | Multiple-testing correction: DSR with `n_trials` | `dsr` (pass `n_trials=N` if any variants tested) | §4 |
| 5 | Cross-validation discipline: CPCV + PBO | `pbo` when `strategy_returns_matrix` provided; full CPCV at Gate 2 | §4 + §5 (preview) |
| 6 | Drawdown and tail metrics: max DD, Calmar, Ulcer, return distribution stats | `max_drawdown`, `calmar`, `ulcer_index`, `martin_ratio`, `return_skewness`, `return_excess_kurtosis`, `tail_ratio` | §4 |
| 7 | Transaction-cost sensitivity: ≥ 3 cost scenarios (zero / realistic / 2× realistic), Sharpe degradation curve | Notebook computes 3 scenario backtests + reports degradation curve | §4 (sensitivity table) |
| 8 | Execution realism: Almgren-Chriss-style impact OR documented equivalent | Notebook documents the impact model used; canonical harness uses Almgren-Chriss | §3 |
| 9 | Turnover and capacity: annualized turnover, alpha decay half-life, capacity estimate (impact > 25% of edge) | `annualized_turnover`, `alpha_decay_half_life_days`, `capacity_estimate_usd` | §4 |
| 10 | Regime conditionality: Sharpe / DD / hit-rate decomposed by regime | `by_regime`, `regime_concentration` (HHI) | §4 |

For any item that cannot be fully computed at Gate 1 (typically item 5 CPCV when full multi-fold work is deferred to Gate 2), the PR body MUST state explicitly: *"Item N: deferred to Gate 2 — preview at notebook §X shows Y; full evaluation per §4.2.1 of the Lifecycle Playbook."* No silent skipping.

#### 3.2.6 Per-strategy thesis defense (1-page)

**Location**: PR body, dedicated section titled "## Thesis defense"

**Content** (≤ 500 words):

- Edge mechanism, restated for the reviewer.
- Why this edge is not already arbitraged away (capacity argument, market segmentation, behavioral persistence, etc.).
- Edge decay risk: known historical decay pattern, current evidence, mitigation in this strategy's design.
- Comparison to closest existing strategy in the platform (or "first of kind"): is this orthogonal, or correlated with what we already trade?

### 3.3 Evaluator roles

Gate 1 has **four evaluators**. Each has a defined responsibility and a defined output:

| Evaluator | Responsibility | Output | Timing |
|---|---|---|---|
| **CIO** (Clement) | Reviews the thesis defense (3.2.6) and the per-strategy Charter draft (3.2.1) for strategic fit with the platform. Confirms that the strategy belongs in the portfolio. | "STRATEGIC-FIT APPROVED" comment on PR + per-strategy Charter draft confirmation | Within 5 working days of PR open |
| **Head of Strategy Research** (Claude Opus 4.7) | Reviews the academic grounding, the statistical methodology, the ADR-0002 checklist, the consistency of metrics with backtest claims. | Detailed code-review comments + "STATISTICAL-SOUNDNESS APPROVED" comment | Within 7 working days of PR open |
| **Claude Code Implementation Lead** | Has produced the backtest, the notebook, the artifacts. Responds to review comments. Iterates until approval. | Revised PR commits | Continuous during review window |
| **CI System** | Validates that the PR passes mechanical gates: lint, type, security, unit-test coverage on any new feature/calculator code introduced. The backtest-gate is currently MUZZLED (issue #102 — see [`.github/workflows/ci.yml:121-130`](../../.github/workflows/ci.yml)) so its result does not block Gate 1; mechanical metric validation lives in PR review until the gate is un-muzzled. | Green CI checks | On every push |

### 3.4 Handoff mechanics — the Gate 1 PR template

Use this template verbatim as the PR body for any Gate 1 PR. Customize the `<...>` placeholders.

```markdown
# Gate 1 — <Strategy Display Name> (`<strategy_id>`)

**Lifecycle gate**: 1 (Research → Approved Backtest)
**Per-strategy Charter (DRAFT)**: [`docs/strategy/per_strategy/<strategy_id>.md`](docs/strategy/per_strategy/<strategy_id>.md)
**Notebook**: [`notebooks/research/<strategy_id>/gate1_backtest.ipynb`](notebooks/research/<strategy_id>/gate1_backtest.ipynb)
**Backtest artifact**: [`reports/<strategy_id>/gate1/full_report.json`](reports/<strategy_id>/gate1/full_report.json)

## Strategy identity

| Field | Value |
|---|---|
| Display name | <name> |
| `strategy_id` | `<id>` |
| Category (proposed) | <Low Vol | Medium Vol | High Vol> |
| Universe | <e.g., "Binance USDT-quoted top 20"> |
| Signal horizon | <e.g., "4h–24h"> |

## Thesis defense

<≤ 500 words per §3.2.6>

## Backtest summary

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| Backtest span | <N years> | ≥ 2 years | <✓ / ✗> |
| Sharpe (daily, IS) | <value> | > 1.0 | <✓ / ✗> |
| Max DD | <%> | < 15% | <✓ / ✗> |
| PSR | <%> | > 95% | <✓ / ✗> |
| PBO | <value> | < 0.5 | <✓ / ✗> |
| Trade count | <N> | (informational) | — |
| Years of data | <e.g., 2023-01-01 → 2025-12-31> | — | — |

## ADR-0002 10-point evaluation checklist

- [ ] **1. Returns basis** — Sharpe computed on daily-resampled equity curve. *(evidence: `full_report["sharpe"]` from notebook §4)*
- [ ] **2. OOS validation** — IS/OOS split with embargo OR walk-forward. *(evidence: notebook §3 + §4)*
- [ ] **3. Statistical significance** — Bootstrap 95% CI + PSR with skew/kurtosis. *(evidence: `sharpe_ci_95_low`, `sharpe_ci_95_high`, `psr`)*
- [ ] **4. Multiple-testing correction** — DSR with `n_trials=<N>`. *(evidence: `full_report["dsr"]`)*
- [ ] **5. Cross-validation discipline** — CPCV + PBO preview. *(evidence: `pbo` field, full CPCV at Gate 2)*
- [ ] **6. Drawdown and tail metrics** — max DD, Calmar, Ulcer, distribution stats. *(evidence: notebook §4 table)*
- [ ] **7. Transaction-cost sensitivity** — 3 cost scenarios. *(evidence: notebook §4 sensitivity table)*
- [ ] **8. Execution realism** — Almgren-Chriss impact (or equivalent documented). *(evidence: notebook §3 model)*
- [ ] **9. Turnover and capacity** — turnover, decay half-life, capacity. *(evidence: `annualized_turnover`, `alpha_decay_half_life_days`, `capacity_estimate_usd`)*
- [ ] **10. Regime conditionality** — `by_regime` decomposition. *(evidence: `full_report["by_regime"]`)*

## Risk factors and mitigations (preview — finalized at Gate 2)

| # | Risk | Mitigation |
|---|---|---|
| 1 | <e.g., regulatory> | <e.g., venue diversification> |
| 2 | <e.g., edge decay> | <e.g., drift monitoring> |

## Links

- Per-strategy Charter (DRAFT): `docs/strategy/per_strategy/<strategy_id>.md`
- Notebook: `notebooks/research/<strategy_id>/gate1_backtest.ipynb`
- Backtest artifact: `reports/<strategy_id>/gate1/full_report.json`
- Charter §7.1 (Gate 1 criteria): `docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md`
- ADR-0002 (Quant Methodology Charter): `docs/adr/0002-quant-methodology-charter.md`

## Reviewer checklist

- [ ] **CIO**: thesis defense reviewed; strategic fit confirmed; per-strategy Charter §1–§4 endorsed
- [ ] **Head of Strategy Research**: ADR-0002 10-point checklist reviewed; statistical soundness confirmed
- [ ] **CI**: green pipeline (quality, rust, unit-tests; backtest-gate muzzled per #102 — non-blocking)
```

### 3.5 Failure modes and re-entry

A Gate 1 candidate may fail any of the five Charter §7.1 thresholds, the ADR-0002 checklist, or the strategic-fit / statistical-soundness reviews. **Failure is not catastrophic — it is data.**

#### 3.5.1 Failure mode taxonomy

| Failure | Likely root cause | Re-entry path |
|---|---|---|
| Sharpe < 1.0 IS | Edge weaker than informal evidence suggested; or transaction-cost realism reduced raw Sharpe | Re-research with simplified signal (fewer features, longer holdings); or reject candidate |
| Max DD ≥ 15% | Position-sizing too aggressive in backtest; or edge is regime-conditional and includes drawdowns from off-regime periods | Tighten stops; restrict to strategy's natural regime; or reject |
| PSR ≤ 95% | Sharpe is a noisy estimator over the available history (insufficient data, or non-normal returns) | Extend backtest to more history if available; or reject if data limit is hard |
| PBO ≥ 0.5 | Strategy is over-fit to in-sample structure; CPCV reveals it does not generalize | Reduce parameter count; reduce feature count; simpler thresholds; re-CPCV |
| ADR-0002 item N unchecked | Methodology incomplete | Complete the missing methodology; re-open PR |
| Strategic fit rejected by CIO | Strategy belongs to a family already saturated, or duplicates an existing edge | Park in backlog with note; revisit when portfolio composition changes |
| Statistical soundness rejected by Head of Strategy Research | Methodological flaw | Address the specific flaw and re-open PR |

#### 3.5.2 Re-entry mechanics

- **No penalty for failing.** The candidate stays on the open backlog (Charter §11.2). The Gate 1 PR is closed (not merged) with a "GATE 1 FAILURE" label and a comment summarizing the specific failure mode. The notebook and per-strategy Charter draft remain in the branch (or in a stash branch if the work is parked).
- **Re-entry threshold.** A candidate that has failed Gate 1 may re-enter after **substantive revision** — not just a parameter sweep. The CIO must agree that the revision is substantive enough to justify a re-review. Cosmetic revisions ("changed the lookback from 14 to 21") are not substantive; they re-trigger the same overfit risk that the first failure exposed.
- **Aging out.** A candidate that has failed Gate 1 three times without a structural change is **rejected** from the backlog. The CIO marks it "REJECTED — see prior Gate 1 failures" with a brief rationale. Future re-introduction requires a fundamentally new thesis (new academic basis, new universe, etc.).

### 3.6 Worked example — `crypto_momentum` (Strategy #1) passing Gate 1

This subsection walks through the Gate 1 evidence package for Crypto Momentum. The same template applies to every other strategy.

#### 3.6.1 Strategy identity (filled-in)

| Field | Value |
|---|---|
| Display name | Crypto Momentum |
| `strategy_id` | `crypto_momentum` |
| Category (proposed) | Medium Vol (Charter §4.1) |
| Universe | Binance USDT-quoted top-20 by market cap (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, ADAUSDT, …) |
| Signal horizon | 4h – 24h |
| Execution bars | 5min |

#### 3.6.2 Thesis defense (filled-in, abbreviated)

> Liu & Tsyvinski (2021, *Review of Financial Studies* 34, 2689-2727) document a robust momentum effect in cryptocurrency at 1–4-week horizons that is not explained by standard asset pricing factors. The mechanism is under-reaction to novel information amplified by retail-dominated order flow and a self-reinforcing price-to-sentiment feedback loop. The edge has not been arbitraged away because of (a) market immaturity, (b) absence of long-short institutional presence at the speed required to exploit it, (c) capacity limits at the asset-cluster level (top-20 USDT-quoted has finite cross-sectional capacity).
>
> A cross-sectional long-short basket — long the top-quintile 14-day performers, short the bottom quintile — captures the edge while partially neutralizing broad market beta. This is critical because BTC dominance shifts rapidly (a pure long-only momentum strategy in crypto is largely a levered BTC bet).
>
> Edge decay risk: well-documented and active. The strategy includes drift monitoring (planned via `services/research/feedback_loop/` — see [`drift_detector.py`](../../services/feedback_loop/drift_detector.py:35), 10% relative win-rate drop alert + 50-trade minimum) so that decay triggers Kelly reduction (Charter §8.1.1) before capital damage compounds.
>
> Comparison to existing platform strategies: first of kind. Once Strategy #2 (Trend Following Multi-Asset) deploys, the two will be partially correlated (~0.3–0.5 expected per Charter §4.7) because BTC and ETH appear in both universes; the diversification value remains positive.

#### 3.6.3 Backtest summary (filled-in, indicative numbers)

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| Backtest span | 2023-01-01 → 2025-12-31 (3 years) | ≥ 2 years | ✓ |
| Sharpe (daily, IS) | 1.12 | > 1.0 | ✓ |
| Max DD | 11.8% | < 15% | ✓ |
| PSR | 96.4% | > 95% | ✓ |
| PBO (CPCV preview, N=6, k=2) | 0.31 | < 0.5 | ✓ |
| Trade count | 1,847 | informational | — |

These numbers are **indicative ranges** for what a passing Gate 1 looks like for this strategy. Actual values from the live Gate 1 PR will replace these.

#### 3.6.4 ADR-0002 checklist (filled-in)

All 10 items checked against the Crypto Momentum backtest. Notable points:

- **Item 7 (cost sensitivity)**: zero-cost Sharpe 1.34, realistic-cost Sharpe 1.12, 2×-realistic-cost Sharpe 0.91. Strategy remains profitable under realistic costs (passing Charter §7.1 implicit requirement) and remains above the 0.8 floor under stress, providing margin for Gate 2 stress-test work.
- **Item 9 (capacity)**: estimated capacity ~$5M USD before market impact consumes 25% of gross edge. Comfortable margin for personal-capital scale.
- **Item 10 (regime conditionality)**: Sharpe 1.41 in trending regimes (the strategy's natural home), 0.62 in choppy regimes. Strategy is regime-favored; the regime decomposition is documented and the operator accepts that paper/live performance will track current-regime mix.

#### 3.6.5 Notebook structure (filled-in skeleton)

```
notebooks/research/crypto_momentum/gate1_backtest.ipynb

§1. Setup and data loading
   - Imports (polars, numpy, decimal)
   - Random seed (np.random.default_rng(42))
   - Data fetch from TimescaleDB: top-20 USDT-quoted, 5min bars,
     2023-01-01 → 2025-12-31

§2. Feature computation
   - Cumulative return: 3d, 7d, 14d, 30d (computed from daily-resampled
     bars; reuses the bars table)
   - OFI: features.calculators.ofi.OFICalculator on 5min bars
   - CVD/Kyle λ: features.calculators.cvd_kyle on 5min bars
   - Rough vol: features.calculators.rough_vol on daily bars
   - Funding rate: read from binance_funding TimescaleDB table
   - Cross-sectional ranking (top quintile / bottom quintile per day)

§3. Backtest logic
   - Long top-quintile, short bottom-quintile, equal-weight within
     quintile, daily rebalance at 00:00 UTC
   - Position sizing: 1% of capital per name, Kelly fraction = 0.4
     (Medium Vol category default)
   - Stops: ATR-based, 2× ATR(14) trailing
   - Costs: Binance VIP-0 fee schedule (0.1% taker), spread model
     (1bp on top-5, 3bp on tail), Almgren-Chriss impact (k=10bps,
     adv=$1M typical)

§4. Metrics output
   - full_report(trades, initial_capital=100_000, n_trials=1,
                 oos_fraction=0.3, embargo_days=5,
                 strategy_returns_matrix=<built from CPCV preview>,
                 n_cv_splits=6, n_cv_test_splits=2)
   - Sensitivity table: zero / realistic / 2x cost scenarios
   - by_regime decomposition

§5. Stress-test preview
   - Scenario A: 2020-03 COVID crash replay (BTC -50% in 2 weeks)
   - Scenario B: 2022-05 LUNA collapse replay (correlated crypto sell-off)
   - Scenario C: 2021-05 China ban replay (one-day -20% on BTC)
   - For each: reconstructed P&L, drawdown curve, time-to-recovery
```

#### 3.6.6 Reviewer outcomes (illustrative)

- **CIO**: "STRATEGIC-FIT APPROVED. Crypto Momentum is the right Strategy #1 — single venue, single asset class, exercises the end-to-end pipeline, well-documented academic basis. Per-strategy Charter §1–§4 endorsed. Ratification of the full per-strategy Charter awaits Gate 2."
- **Head of Strategy Research**: "STATISTICAL-SOUNDNESS APPROVED. Backtest is methodologically clean; ADR-0002 10-point checklist complete; PSR 96.4% and PBO 0.31 are credible. Regime decomposition (Sharpe 1.41 in trending, 0.62 in choppy) is honest and consistent with Liu & Tsyvinski's edge model. Approved for Gate 2."
- **CI**: green pipeline; backtest-gate muzzled (issue #102), non-blocking.
- **Outcome**: PR merged; `crypto_momentum` formally enters Gate 2.

### 3.7 What Gate 1 does NOT do

To prevent scope creep into Gate 2:

- Gate 1 does **not** require a complete CPCV walk-forward — only a preview (full CPCV is Gate 2 deliverable per §4.2.1).
- Gate 1 does **not** require the production microservice — only the research notebook and per-strategy Charter draft.
- Gate 1 does **not** require the full 10 stress-test scenarios — only a preview of 3 (full set is Gate 2 deliverable per §4.2.2).
- Gate 1 does **not** require ≥ 90% coverage — that requirement applies to the production microservice built at Gate 2.
- Gate 1 does **not** ratify the per-strategy Charter — it ratifies §1–§4 of the draft; full ratification (including reviewer sign-off in §11) is Gate 2.

This separation is deliberate. Gate 1 validates that **the edge is real and the methodology is sound**; Gate 2 validates that **the production implementation faithfully captures the edge with operational discipline**. Conflating the two stages either over-engineers Gate 1 or under-validates Gate 2.

---

## §4 — Gate 2 — Approved Backtest → Paper Trading

Gate 2 is the **research-to-production-code** gate. The strategy moves from a research notebook + per-strategy Charter draft to a **production microservice** under `services/strategies/<strategy_id>/` that subscribes to live data, emits `OrderCandidate` messages with `strategy_id` (Charter §5.5), respects the VETO chain (Charter §8.2), and is robust enough to begin paper trading.

The critical Gate 2 deliverables are: (a) **CPCV walk-forward evidence** that the strategy generalizes out-of-sample under the canonical Lopez-de-Prado purged-and-embargoed methodology, (b) **10 stress-test scenarios** demonstrating robustness to adverse historical conditions, (c) the **production microservice** with ≥ 90% test coverage, and (d) the **per-strategy Charter ratified** by the CIO.

### 4.1 Entry criteria

A strategy enters Gate 2 when **all** of the following are true:

1. **Gate 1 PR merged** to `main`. The Gate 1 evidence package is in the repository, including the per-strategy Charter draft (DRAFT status), the research notebook, and the JSON backtest artifact.
2. **CIO has formally accepted Gate 1 outcomes**. This is implicit in the Gate 1 PR merge — by merging, the CIO ratified §1–§4 of the per-strategy Charter and confirmed strategic fit.
3. **Per-strategy microservice scaffold issue created**. A GitHub issue tracks the Gate 2 work; the issue body links to the Gate 1 PR, the per-strategy Charter draft, and the planned microservice path.

### 4.2 Deliverables required for Gate 2 PASS

#### 4.2.1 CPCV walk-forward OOS evidence

**Specification**:

- Use [`backtesting.walk_forward.CombinatorialPurgedCV`](../../backtesting/walk_forward.py) (the canonical CPCV implementation, see [`backtesting/walk_forward.py:374`](../../backtesting/walk_forward.py)).
- Default split parameters: `n_splits=6`, `n_test_splits=2`, `embargo_pct=0.01`. Strategy may override with documented justification (e.g., higher `n_splits` for longer history; larger `embargo_pct` for strategies with longer holding periods to prevent label leakage).
- Run on the **full Gate 1 backtest dataset** (minimum 2 years per Charter §7.1; preferably more).
- Output: `CPCVResult` (see [`backtesting/walk_forward.py:351-371`](../../backtesting/walk_forward.py)) containing `oos_sharpes` distribution, `is_sharpes` distribution, `oos_sharpe_median`, `pbo`, `n_combinations`, `recommendation`.

**Charter §7.2 threshold**: **CPCV OOS Sharpe (median) > 0.8**. Below this floor, the strategy does not deploy to paper, regardless of in-sample performance.

**Built-in deployment recommendation** (per [`backtesting/walk_forward.py:387-390`](../../backtesting/walk_forward.py)):

| `recommendation` | Conditions | Gate 2 implication |
|---|---|---|
| `DEPLOY` | `pbo < 0.25` AND `oos_sharpe_median > 0.5` | Aligned with Gate 2 pass; needs additional ≥ 0.8 floor check |
| `INVESTIGATE` | `pbo < 0.50` | Insufficient for Gate 2; needs more data or simpler model |
| `DISCARD` | `pbo ≥ 0.50` | Hard fail; return to research |

The Gate 2 acceptance is `CombinatorialPurgedCV.run(...).recommendation == "DEPLOY"` AND `oos_sharpe_median > 0.8`. The 0.8 floor is stricter than the 0.5 floor in the `DEPLOY` recommendation — this is intentional, encoding Charter's requirement that paper-eligible strategies have margin above the bare validation floor.

**Artifact**: `reports/<strategy_id>/gate2/cpcv_result.json` containing the serialized `CPCVResult`.

#### 4.2.2 Ten stress-test scenarios

The Charter §7.2 requires "10 stress-test scenarios passed". The Playbook fixes the canonical 10 scenarios so that every strategy faces a comparable test battery. Scenarios are simulated by **replaying historical analog dates** through the strategy's backtest harness; "pass" means portfolio drawdown remains within the strategy's category budget (Charter §9.1) over the scenario window.

**The 10 canonical stress scenarios**:

| # | Scenario | Historical analog (replay window) | Pass criterion (per category) |
|---|---|---|---|
| 1 | **Equity flash crash (-20% in 1 day)** | 2010-05-06 (S&P 500 flash crash) — replay on synthetic equity exposure if strategy is non-equity | DD within category max (8/12/20%); recovery within 30 trading days |
| 2 | **Volatility spike (VIX × 2 in one session)** | 2020-02-24 → 2020-03-16 (COVID volatility ramp; VIX 14 → 82) | DD within category max; strategy does not amplify the spike via stop-loss cascades |
| 3 | **Major Fed surprise (±100bps)** | 2022-09-21 (Fed +75bps "hawkish hold"); 2008-10-08 (Fed -50bps emergency cut) | DD within category max; strategy respects CB blackout (STEP 1 of VETO chain) |
| 4 | **SNB-class CB unpeg / FX shock** | 2015-01-15 (SNB removes EUR/CHF floor; CHF +30% in minutes) | DD within category max; FX-naive strategies show no exposure; FX strategies (Macro Carry) show category-bounded loss |
| 5 | **Geopolitical oil shock (±15%)** | 2022-02-24 (Russia invasion of Ukraine — oil +30% in 5 days); 2020-04-20 (WTI -300% to negative price) | DD within category max; commodity-naive strategies unaffected |
| 6 | **Liquidity evaporation (bid-ask spread × 10)** | 2008-10 (peak credit crisis, spreads 5× normal); 2020-03 (Treasury market liquidity drying up) | DD within category max; strategy throttles or pauses on widened spreads |
| 7 | **Correlation breakdown (cross-asset correlation spike to ≥ 0.9)** | 2008-10; 2020-03; 2022-06 (everything-correlated risk-off) | DD within category max; multi-asset strategies (Trend Following, News-driven) show diversification breakdown but bounded loss |
| 8 | **Crypto-specific tail event** | 2022-05-09 → 2022-05-12 (LUNA / UST collapse); 2022-11-08 → 2022-11-11 (FTX collapse) | DD within category max; crypto strategies (Crypto Momentum, News-driven crypto-side) show bounded loss |
| 9 | **Single-symbol gap (-30% overnight)** | Isolated equity examples (e.g., earnings miss with -25% gap); applied as synthetic single-name shock to equity strategies | DD within category max; per-position max-loss controls fire (Charter §8.1.1 implicitly via per-strategy position rules — STEP 5 of the chain — see [`services/risk_manager/chain_orchestrator.py:191-221`](../../services/risk_manager/chain_orchestrator.py)) |
| 10 | **Data feed outage (90 minutes mid-session)** | Synthetic; emulates a venue WebSocket disconnect during active trading | Strategy enters fail-closed (Charter §5.8 / [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md)); no orders submitted on stale data; resumes cleanly when feed restores |

**Methodology** for each scenario:

1. Reconstruct the strategy's positions and signals at the start of the analog window using the production microservice in **simulation mode** (the microservice is configured to read historical bars and dry-run its decision logic).
2. Step the simulation forward through the scenario window, day by day (or bar by bar for sub-daily scenarios).
3. Compute scenario-window equity curve, drawdown peak, recovery time.
4. Compare DD peak against category budget; record PASS / FAIL per scenario.

**Artifact**: `reports/<strategy_id>/gate2/stress_tests.json` containing per-scenario results.

**Charter §7.2 threshold**: **all 10 scenarios PASS**. A single FAIL fails Gate 2. Note: a strategy may be **structurally exempt** from a scenario if its universe demonstrably excludes the affected asset class (e.g., the FX shock scenario for a crypto-only strategy). Exemptions are explicitly stated in the per-strategy Charter §9 (risk factors) and require Head of Strategy Research review at Gate 2.

#### 4.2.3 Production microservice

**Location**: `services/strategies/<strategy_id>/`

**Mandatory file structure**:

```
services/strategies/<strategy_id>/
├── __init__.py
├── service.py            # inherits BaseService; subscribes to panels;
│                         # publishes order.candidate with strategy_id
├── signal_generator.py   # concrete StrategyRunner subclass (per Charter §5.6)
├── config.yaml           # per-strategy parameters (universe, timeframes,
│                         # thresholds, Kelly, stops, etc.)
├── README.md             # 1-page operator note (links to per-strategy
│                         # Charter, key parameters, ops gotchas)
└── tests/
    ├── unit/
    │   ├── test_signal_generator.py
    │   ├── test_config_loading.py
    │   └── ...
    └── integration/
        └── test_service_e2e.py
```

**Mandatory contracts**:

- `service.py` inherits from `core.base_service.BaseService` per [CLAUDE.md](../../CLAUDE.md) §8.
- `signal_generator.py` subclasses `StrategyRunner` (the new ABC per Charter §5.6 — `features/strategies/base.py` or `services/strategies/_base.py` per Roadmap-defined location).
- All `OrderCandidate` messages emitted carry `strategy_id = "<strategy_id>"` (the strategy's own ID, never `"default"`).
- All Redis keys read or written use the per-strategy partition: `kelly:<strategy_id>:<symbol>`, `meta_label:latest:<strategy_id>:<symbol>`, `pnl:<strategy_id>:daily`, `trades:<strategy_id>:all` (Charter §5.5).
- ZMQ topic publishing uses `Topics.signal_for(strategy_id, symbol)` once available; until the planned topic factory lands (see [CONTEXT.md](../claude_memory/CONTEXT.md) and Charter §5.5), strategies use the current `Topics.signal(symbol)` factory and tag `strategy_id` at the message producer level.
- `config.yaml` is loaded and validated at service startup via Pydantic v2 (frozen). No hardcoded constants in Python source.
- All Decimal arithmetic for prices/sizes/PnL/fees per [CLAUDE.md](../../CLAUDE.md) §10.
- All datetimes UTC-aware per [CLAUDE.md](../../CLAUDE.md) §10.
- All logging via `structlog` per [CLAUDE.md](../../CLAUDE.md) §10.

**No code duplication with research notebook**. The microservice consumes the same `features/calculators/` modules used in the Gate 1 notebook. If a feature was prototyped notebook-only, it is **promoted** to a production calculator (in `features/calculators/`) before Gate 2 PR merge. Notebook-only feature code that the microservice re-implements is a Gate 2 fail.

#### 4.2.4 Test coverage ≥ 90%

The strategy microservice (and any new feature calculators introduced for it) must have **≥ 90% line coverage** under `pytest --cov`. This exceeds the platform 85% floor (per [CLAUDE.md](../../CLAUDE.md) §6) — strategy code is critical-path and gets a higher bar.

**Coverage scope**:
- `services/strategies/<strategy_id>/**/*.py` — full coverage measured
- `features/calculators/<new feature paths introduced>/**/*.py` — full coverage measured
- Test files themselves are excluded from the coverage denominator

**Tests must include**:
- **Happy path** unit tests for every public method on `signal_generator.py`
- **Edge cases**: empty input, None values, boundary thresholds, stale data
- **Error cases**: malformed upstream data, missing config keys, Redis unavailable
- **Property tests** (hypothesis) for any mathematical function (signal computation, position sizing, threshold logic)
- **Integration test** spinning the service in a fakeredis + in-process ZMQ harness, asserting end-to-end: subscribe to panel snapshot → compute signal → publish `order.candidate` with `strategy_id`

**Gate 2 fail conditions**:
- Coverage < 90%
- Any happy-path or boundary test missing
- No integration test
- No property test on at least one mathematical function

#### 4.2.5 Operational smoke test

**Procedure**:
1. Start the multi-strat infrastructure stack via `docker compose -f docker/docker-compose.yml up -d` (or whatever the current local-stack invocation is — the CIO's developer environment per the project README).
2. Start the new strategy microservice: `docker compose up -d services/strategies/<strategy_id>` (or equivalent).
3. Verify the service heartbeats every 5 seconds to its Redis key (per `BaseService` convention, [CLAUDE.md](../../CLAUDE.md) §8).
4. Verify the service subscribes to its panel topics (or current-state tick topics until `services/data/panels/` lands per Charter §5.3).
5. Inject a synthetic panel/tick that should produce a signal; verify an `order.candidate` with `strategy_id == "<strategy_id>"` is published.
6. Verify the message is observed by the (current) Risk Manager (`services/risk_manager/`, soon `services/portfolio/risk_manager/`) via subscription on the bus.
7. Run for ≥ 10 minutes with no crashes, no unhandled exceptions, no heartbeat misses.

**Artifact**: `reports/<strategy_id>/gate2/smoke_test.log` containing the structured-log lines from the smoke test, with explicit timestamps and a final "SMOKE TEST PASSED" line.

#### 4.2.6 Per-strategy Charter — full ratification

The per-strategy Charter at `docs/strategy/per_strategy/<strategy_id>.md` is **completed** at Gate 2 (sections 5–12 of the §2.3 template, in addition to the Gate-1-completed §1–§4):

- §5 Budget and risk (category inheritance + per-strategy soft CB thresholds — defaults from Charter §9.1 unless overridden with documented reason)
- §6 Position sizing (Kelly fraction + max risk per trade + max position size + max open positions + max correlation)
- §7 Stop-loss and take-profit logic (specific, mechanical)
- §8 Expected trade frequency (estimates with rationale)
- §9 Known risk factors and mitigations (table; ≥ 3 risks identified)
- §10 Operational interfaces (subscribed topics, published topics, Redis keys read, Redis keys written)
- §11 Reviewer sign-off (CIO signs at Gate 2 PR merge)
- §12 Revision history (initial v1.0 entry)

The CIO sign-off in §11 is the **constitutional act** of Gate 2: by signing, the CIO ratifies the per-strategy Charter as binding for the strategy's operation.

#### 4.2.7 Human code review + Copilot auto-review

Both must clear before merge:

- **Human code review by CIO** — in particular reviewing the `signal_generator.py` for thesis fidelity (does the code actually implement the strategy described in the per-strategy Charter §2 thesis?), reviewing the `config.yaml` for parameter sanity, and confirming the test coverage report.
- **Copilot auto-review** — the GitHub Copilot review agent provides an independent code-quality signal. Copilot comments are addressed (either fixed or explicitly dismissed with reason) before merge.

### 4.3 Evaluator roles + handoff mechanics

| Evaluator | Responsibility | Output | Timing |
|---|---|---|---|
| **CIO** (Clement) | Reviews per-strategy Charter §5–§10 (sign-off in §11); reviews `signal_generator.py` for thesis fidelity; reviews stress-test scenario results; ratifies the strategy as paper-eligible | "GATE 2 RATIFIED" comment + per-strategy Charter §11 signature + PR merge | Within 7 working days of PR open |
| **Head of Strategy Research** (Claude Opus 4.7) | Reviews CPCV evidence for soundness; reviews stress-test methodology and conclusions; reviews per-strategy Charter §5–§10 for institutional appropriateness | Detailed code-review comments + "STATISTICAL & METHODOLOGY APPROVED" comment | Within 7 working days of PR open |
| **Claude Code Implementation Lead** | Has produced the microservice, the tests, the CPCV runs, the stress tests, the smoke test. Iterates on review comments. | Revised PR commits | Continuous during review window |
| **CI System** | Validates lint, type, security, ≥ 90% coverage on the new strategy code, integration tests passing | Green CI checks | On every push |

#### 4.3.1 Gate 2 PR template

```markdown
# Gate 2 — <Strategy Display Name> (`<strategy_id>`)

**Lifecycle gate**: 2 (Approved Backtest → Paper Trading)
**Per-strategy Charter (RATIFICATION)**: [`docs/strategy/per_strategy/<strategy_id>.md`](docs/strategy/per_strategy/<strategy_id>.md)
**Microservice**: [`services/strategies/<strategy_id>/`](services/strategies/<strategy_id>/)
**CPCV result**: [`reports/<strategy_id>/gate2/cpcv_result.json`](reports/<strategy_id>/gate2/cpcv_result.json)
**Stress tests**: [`reports/<strategy_id>/gate2/stress_tests.json`](reports/<strategy_id>/gate2/stress_tests.json)
**Smoke test log**: [`reports/<strategy_id>/gate2/smoke_test.log`](reports/<strategy_id>/gate2/smoke_test.log)

## CPCV walk-forward summary

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| n_splits | 6 (default) | — | — |
| n_test_splits | 2 (default) | — | — |
| embargo_pct | 0.01 (default) | — | — |
| n_combinations | 15 = C(6,2) | — | — |
| OOS Sharpe median | <value> | > 0.8 | <✓/✗> |
| PBO | <value> | < 0.5 (built-in DEPLOY: < 0.25 ideal) | <✓/✗> |
| Recommendation | <DEPLOY / INVESTIGATE / DISCARD> | DEPLOY | <✓/✗> |

## Stress test summary

| # | Scenario | Historical analog | DD peak | Recovery | Pass? |
|---|---|---|---|---|---|
| 1 | Equity flash crash | 2010-05-06 | <%> | <days> | <✓/✗> |
| 2 | Volatility spike | 2020-02-24 → 2020-03-16 | <%> | <days> | <✓/✗> |
| 3 | Fed surprise | 2022-09-21 / 2008-10-08 | <%> | <days> | <✓/✗> |
| 4 | SNB-class FX shock | 2015-01-15 | <%> | <days> | <✓/✗> |
| 5 | Geopolitical oil shock | 2022-02-24 / 2020-04-20 | <%> | <days> | <✓/✗> |
| 6 | Liquidity evaporation | 2008-10 / 2020-03 | <%> | <days> | <✓/✗> |
| 7 | Correlation breakdown | 2008-10 / 2020-03 / 2022-06 | <%> | <days> | <✓/✗> |
| 8 | Crypto tail event | 2022-05-09 / 2022-11-08 | <%> | <days> | <✓/✗> |
| 9 | Single-symbol gap | synthetic | <%> | <days> | <✓/✗> |
| 10 | Data feed outage | synthetic | n/a (fail-closed) | n/a | <✓/✗> |

## Test coverage

- `services/strategies/<strategy_id>/`: <coverage %> (threshold ≥ 90%)
- New `features/calculators/<paths>/`: <coverage %> (threshold ≥ 90%)
- Integration test: <PASS / FAIL>
- Property tests: <count> on <function names>

## Per-strategy Charter ratification

- [ ] §5 Budget and risk completed; category-default overrides documented
- [ ] §6 Position sizing parameters specified
- [ ] §7 Stop/take-profit logic specified
- [ ] §8 Trade frequency estimated
- [ ] §9 ≥ 3 risk factors identified with mitigations
- [ ] §10 Operational interfaces enumerated
- [ ] §11 CIO sign-off

## Smoke test attestation

- [ ] Service starts and heartbeats
- [ ] Subscribes to panel/tick topics
- [ ] Publishes `order.candidate` with `strategy_id == "<id>"`
- [ ] Risk Manager observes the message
- [ ] Runs ≥ 10 min with no crashes
- [ ] `smoke_test.log` ends with "SMOKE TEST PASSED"

## Reviewer checklist

- [ ] **CIO**: per-strategy Charter §11 signed; `signal_generator.py` thesis-faithful; stress-test results acceptable; GATE 2 RATIFIED
- [ ] **Head of Strategy Research**: CPCV methodology sound; PBO < 0.5; stress methodology defensible; STATISTICAL & METHODOLOGY APPROVED
- [ ] **CI**: green pipeline (quality, rust, unit-tests at ≥ 90% on strategy code, integration-tests)
- [ ] **Copilot review**: cleared
```

### 4.4 Failure modes and re-entry

| Failure | Likely root cause | Re-entry path |
|---|---|---|
| CPCV OOS Sharpe < 0.8 | Strategy was over-fit at Gate 1 (in-sample shine that does not generalize) | Reduce feature count; simplify thresholds; longer history if available; possibly retire candidate |
| CPCV `recommendation == DISCARD` (PBO ≥ 0.5) | Hard overfit; in-sample edge does not survive purged combinatorial splits | Substantive re-research; not just parameter tweaks |
| Stress scenario fail (DD exceeds category budget) | Strategy is not robust to the specific tail event | Tighten stops; reduce Kelly; restrict universe; add regime overlay; possibly demote category |
| Coverage < 90% | Tests incomplete | Add tests; common gaps are error paths and edge cases |
| Smoke test fail (crash, stale heartbeat) | Operational/integration bug | Debug; usually a wiring issue (Redis key naming, ZMQ topic mismatch, frozen-Pydantic violation) |
| Per-strategy Charter section incomplete | Specification gaps | Complete the section; CIO will not sign §11 with gaps elsewhere |
| Code review failure (CIO or Head of Strategy Research) | Thesis-code mismatch, methodological flaw, design issue | Address comments; re-request review |
| Copilot review unaddressed | Standard PR hygiene failure | Address or dismiss-with-reason; re-request |

Re-entry semantics for Gate 2 are stricter than Gate 1: by Gate 2, the strategy has consumed multi-week implementation effort, and re-entry without substantive change would re-trigger the same failure. The CIO must explicitly approve re-entry of a Gate 2 candidate after a fail.

### 4.5 Worked example — `crypto_momentum` passing Gate 2

#### 4.5.1 CPCV run (filled-in, indicative)

Configuration:
- `n_splits = 6` (default)
- `n_test_splits = 2` (default → C(6,2) = 15 combinations)
- `embargo_pct = 0.01` (default; appropriate for the strategy's 4h-24h signal horizon)
- Backtest data: same 2023-01-01 → 2025-12-31 dataset as Gate 1

Result (indicative):

| Field | Value |
|---|---|
| `n_combinations` | 15 |
| `is_sharpe_median` | 1.20 |
| `oos_sharpe_median` | 0.92 |
| `oos_sharpe_mean` | 0.88 |
| `oos_sharpe_std` | 0.31 |
| `pbo` | 0.27 |
| `recommendation` | `DEPLOY` |

Pass criteria: `oos_sharpe_median = 0.92 > 0.8` ✓; `pbo = 0.27 < 0.5` ✓; `recommendation == DEPLOY` ✓ → **CPCV PASS**.

#### 4.5.2 Stress test results (indicative)

| # | Scenario | DD peak | Recovery | Pass? |
|---|---|---|---|---|
| 1 | Equity flash crash 2010-05-06 (synthetic crypto-side via correlated risk-off) | -4.2% | 7 trading days | ✓ |
| 2 | Vol spike 2020-02-24 → 2020-03-16 | -9.8% | 14 trading days | ✓ (Medium Vol max 12%) |
| 3 | Fed +75bps 2022-09-21 (BTC -8% on the day) | -7.5% | 5 trading days | ✓ |
| 4 | SNB unpeg 2015-01-15 — STRUCTURAL EXEMPT (no FX exposure) | n/a | n/a | ✓ exempt |
| 5 | Russia oil shock 2022-02-24 (correlated risk-off, BTC -10%) | -8.1% | 8 trading days | ✓ |
| 6 | Liquidity 2020-03 (BTC bid-ask widened, OFI noise) | -10.4% | 12 trading days | ✓ (Medium Vol max 12%) |
| 7 | Correlation 2022-06 (everything-correlated risk-off) | -11.2% | 18 trading days | ✓ (just under Medium Vol max 12%) |
| 8 | LUNA collapse 2022-05-09 to 2022-05-12 | -9.1% | 11 trading days | ✓ |
| 9 | Single-symbol gap (synthetic SOL -30%) | -2.8% | 3 trading days | ✓ (per-position controls fired) |
| 10 | Data feed outage (90min) | n/a (fail-closed; 0 orders) | n/a | ✓ |

Result: **10 of 10 PASS** (1 structural exempt, 9 PASS).

Note that scenarios 6 and 7 push close to the Medium Vol category 12% DD ceiling. The Head of Strategy Research at review may flag these as "tight margin" — the strategy passes but with little headroom. Mitigation tracked in per-strategy Charter §9: increased correlation monitoring during risk-off regimes.

#### 4.5.3 Microservice file structure (filled-in)

```
services/strategies/crypto_momentum/
├── __init__.py
├── service.py                  # CryptoMomentumService(BaseService)
├── signal_generator.py         # CryptoMomentumStrategy(StrategyRunner)
├── ranking.py                  # cross-sectional momentum ranking helpers
├── config.yaml                 # universe, lookbacks, thresholds, Kelly, stops
├── README.md
└── tests/
    ├── unit/
    │   ├── test_signal_generator.py     # (28 tests)
    │   ├── test_ranking.py              # (15 tests, 3 hypothesis property tests)
    │   ├── test_config_loading.py       # (8 tests)
    │   └── test_position_sizing.py      # (12 tests)
    └── integration/
        └── test_service_e2e.py          # (4 tests; fakeredis + in-proc ZMQ)
```

Coverage: 93.7% over `services/strategies/crypto_momentum/` (threshold 90% ✓).

#### 4.5.4 Per-strategy Charter § 11 sign-off (illustrative)

> | Reviewer | Action | Date |
> |---|---|---|
> | Head of Strategy Research | Drafted sections 5-10 | 2026-XX-XX |
> | Claude Code | Implemented signal_generator.py + tests + CPCV + stress tests | 2026-XX-XX |
> | **CIO (Clement Barbier)** | **RATIFIED at Gate 2** | **2026-XX-XX** |

The CIO's signature in this section is the act of Gate 2 ratification. Until the section is signed, the strategy does not deploy to paper.

#### 4.5.5 Outcome

PR merged to `main`. Microservice deployed to paper-trading environment within 24 hours. Gate 3 begins.

---

## §5 — Gate 3 — Paper Trading → Live Micro

Gate 3 is the **simulation-to-real-capital** gate. The strategy, having passed methodological and stress-test validation in Gate 2, now runs against **live data** in a **paper-trading environment**: real-time market data, real Risk Manager VETO chain, real allocator, real observability — but no real capital. Paper trading is the most expensive part of the lifecycle in wall-clock time (≥ 8 weeks per Charter §7.3) and the most informative — it is where backtest assumptions meet the real frictions of live data.

### 5.1 Entry criteria

A strategy enters Gate 3 when **all** of the following are true:

1. **Gate 2 PR merged** to `main`. The microservice is in the codebase; the per-strategy Charter is ratified; CPCV and stress-test artifacts are in `reports/<strategy_id>/gate2/`.
2. **Paper-trading environment configured**. The deployment target environment has paper-broker credentials (Alpaca paper, Binance Testnet, etc. — venue-dependent), a paper instance of Redis + ZMQ broker (or shared with production paper if topology supports it), and an isolated "paper" partition for the strategy's Redis keys (e.g., `paper:kelly:<strategy_id>:<symbol>`) so paper data does not contaminate eventual live data.
3. **Smoke test from Gate 2 §4.2.5 still green** as the actual launch criterion (not just the historical artifact). The microservice is started in the paper environment, heartbeats, subscribes, publishes a first `order.candidate`, sees it through the VETO chain — all confirmed in real time.
4. **Gate 3 timer started**. The CIO records the paper-trading start date in the per-strategy Charter §12 revision history; the 8-week minimum begins counting from this date.

### 5.2 Paper trading period

#### 5.2.1 Duration floor

Per Charter §7.3, the **floor is 8 weeks AND ≥ 50 trades**. Both must be reached; whichever takes longer governs.

For high-frequency strategies (Mean Rev Equities, News-driven), 50 trades typically arrive within 2–4 weeks; the 8-week floor binds.
For low-frequency strategies (Trend Following at daily horizons, Macro Carry at multi-day horizons), the 50-trade floor may bind beyond 8 weeks; paper extends until reached.

There is **no upper bound** on Gate 3 duration. The CIO may extend paper to accumulate more evidence before committing real capital.

#### 5.2.2 What the operator does during paper

**Active responsibilities** (do):

- **Monitor the dashboard daily**. Per-strategy panel (see §7.1) shows: live Sharpe (rolling), live max DD, live win rate, position log, alert log, heartbeat status.
- **Document anomalies in real time**. Anything unexpected — a regime the strategy was not designed for, an unusually large position, a slow signal computation, a heartbeat blip — gets logged in `docs/strategy/per_strategy/<strategy_id>_paper_log.md` (a paper-period running log distinct from the Charter).
- **Confirm baseline win-rate capture by Day 30**. The drift detector (see [`services/feedback_loop/drift_detector.py:35`](../../services/feedback_loop/drift_detector.py)) needs ≥ 50 trades and a 3-month baseline to fire alerts; the operator confirms by Day 30 (week 4) that the baseline is being captured per the running paper trade log.

**Active prohibitions** (do not):

- **Do not tune parameters during paper**. Tuning during paper is overfitting under a different name. The strategy's parameters are frozen at Gate 2 ratification; paper validates the Gate 2 specification, not iteration toward better paper Sharpe. If parameters need adjustment, the strategy returns to Gate 1/2 with substantive change — there is no "while we're at it" tuning during paper.
- **Do not stop and restart the strategy except for operational issues**. Stopping for "I think I see a better entry condition" is forbidden. Stopping for a confirmed bug, an upstream data issue, or infrastructure maintenance is permitted (and documented in the paper log).
- **Do not size up beyond the planned paper notional**. Paper trading is at the strategy's planned starting allocation (e.g., the 20% target that will become the Day-0 live-micro allocation). Stretching paper to "see how it would do at 100%" is forbidden — paper is a fidelity test, not a capacity test.

#### 5.2.3 Drift detection during paper

The platform's drift detector ([`services/feedback_loop/drift_detector.py`](../../services/feedback_loop/drift_detector.py)) operates in paper exactly as it will in live:

- **Minimum sample**: 50 trades before any drift alert fires (line 43, `MIN_TRADES = 50`).
- **Threshold**: 10% relative drop in win rate vs baseline triggers `DriftAlert` (line 42, `DRIFT_THRESHOLD = 0.10`).
- **Baseline source**: the strategy's Gate 1 backtest provides the initial baseline win rate (transferred at deployment); after 3 months of paper data, the baseline rolls forward to the trailing 3-month paper win rate.

A drift alert during paper is a **non-blocking signal** — it does not pause the strategy automatically (Charter §8.1.1 soft CB triggers do, but those operate on drawdown, not on win-rate drift alone). The CIO reviews drift alerts within 48 hours; if the divergence is structural (regime change, implementation issue), the strategy may be returned to research.

#### 5.2.4 Pod-health monitoring during paper

The strategy microservice's pod-health is observed continuously:

- Heartbeat every 5 seconds (per `BaseService` convention)
- No unhandled exceptions (logged to structlog; counted)
- No restarts (counted)
- Memory growth stable (no leaks)
- CPU usage within budget (per-pod CPU target: < 50% of allocated cores at 1-minute average)

A single pod crash during paper does **not** automatically fail Gate 3 — but the cause is investigated, fixed, and the paper period restarts (the 8-week clock resets) per Charter §7.3 ("zero pod crash" criterion). The reset is explicit: the 8-week clock restarts from the day of the crash post-fix; the "zero pod crash" criterion in §5.3 measures zero crashes during the **final valid 8-week window**, not zero crashes across all paper attempts. Upstream resets are permitted. However, **three resets within the same paper trading attempt** (i.e., three crashes triggering three clock resets) is itself a stability failure — the strategy returns to Gate 2 for stability hardening, with a documented root-cause analysis required in the Gate 2 re-entry PR.

### 5.3 Deliverables required for Gate 3 PASS

All criteria from Charter §7.3 must be satisfied simultaneously across the paper period:

| Criterion | Threshold | Source / Evidence |
|---|---|---|
| Duration | **≥ 8 weeks** AND **≥ 50 trades** | Paper log + Gate 1/2 trade-record schema |
| Paper Sharpe | **> 0.8** over the full paper period | `full_report` over paper trade list |
| Paper max DD | **< 10%** | `full_report["max_drawdown"]` |
| Win rate consistent with backtest | **±10%** vs backtest baseline | Drift detector baseline vs paper actual |
| Pod crashes | **Zero** during the period | Pod health log; no container restarts during the final valid 8-week window (upstream resets permitted per §5.2.4, limit 3); no heartbeat misses > 60s |
| Observability | **Green** | All dashboard panels functional, no alerting anomalies, drift baseline captured |

#### 5.3.1 Paper Sharpe note

The 0.8 paper-Sharpe floor is the **same** as the Gate 2 CPCV OOS Sharpe floor and is intentionally so: paper is essentially live OOS evaluation. A meaningful paper-vs-CPCV gap (paper Sharpe much lower than CPCV OOS Sharpe) is itself a fail signal indicating either implementation drift or that the CPCV setup did not capture live frictions.

#### 5.3.2 Paper max DD note

The 10% paper-DD floor is **tighter** than Gate 2 backtest's 15% (Gate 1 criterion) and **tighter** than the Medium Vol category 12% live tolerance (Charter §9.1). Paper trading should not produce drawdowns approaching live tolerances; if it does, the strategy is too aggressive for its category and either Kelly is too high or stops are too loose.

#### 5.3.3 Win-rate consistency note

Backtest win-rate baseline is transferred from Gate 1 backtest. Paper actual is computed across the paper period. Acceptable range: ±10% relative (e.g., backtest 55% → paper 49.5%–60.5% is acceptable; paper 44% is a fail).

A meaningful divergence is **diagnostic**:
- Paper win-rate higher than backtest by > 10%: usually a slippage assumption being too pessimistic; investigate but generally acceptable
- Paper win-rate lower than backtest by > 10%: usually slippage worse than modeled, or the strategy hits an unfavorable regime; investigate and either remediate or return to research

### 5.4 Evaluator roles + handoff mechanics

| Evaluator | Responsibility | Output | Timing |
|---|---|---|---|
| **CIO** (Clement) | Daily monitoring during paper; final paper-to-live decision | Daily review (informal); paper-evidence-package signature at Gate 3 closeout | Daily during paper; signature within 5 working days of paper-period closeout |
| **Head of Strategy Research** (Claude Opus 4.7) | Reviews paper evidence package at closeout for statistical soundness; reviews drift attribution | Detailed comments + "PAPER EVIDENCE APPROVED" comment | Within 5 working days of paper closeout |
| **Claude Code Implementation Lead** | Assembles paper evidence package; addresses any operational issues during paper | Paper evidence package delivered | At paper closeout |
| **Paper trading infrastructure** (paper Alpaca, Binance Testnet, etc.) | Provides realistic price/fill simulation; provides realistic data feed cadence | Live paper data + paper trade-record stream | Continuous |

#### 5.4.1 Paper evidence package — structure

**Location**: `reports/<strategy_id>/gate3/paper_evidence_v1.0.md`

**Mandatory sections**:

```markdown
# Paper Evidence Package — <Strategy Display Name>

**Strategy ID**: `<strategy_id>`
**Paper period start**: YYYY-MM-DD
**Paper period end**: YYYY-MM-DD (inclusive)
**Duration**: <weeks> weeks (floor: 8 weeks)
**Trade count**: <N> (floor: 50)

---

## 1. Headline metrics

| Metric | Paper value | Threshold | Pass? | Backtest reference |
|---|---|---|---|---|
| Sharpe (annualized, daily) | <value> | > 0.8 | <✓/✗> | Gate 1: <value>; Gate 2 CPCV OOS: <value> |
| Max drawdown | <%> | < 10% | <✓/✗> | Gate 1 IS: <%>; Gate 2 stress max: <%> |
| Win rate | <%> | within ±10% of backtest | <✓/✗> | Gate 1: <%> |
| Trade count | <N> | ≥ 50 | <✓/✗> | — |
| Annualized return | <%> | informational | — | Gate 1: <%> |
| Sortino | <value> | informational | — | Gate 1: <value> |
| Calmar | <value> | informational | — | Gate 1: <value> |
| PSR (paper) | <%> | informational | — | Gate 1: <%> |

## 2. Operational metrics

| Metric | Paper value | Threshold | Pass? |
|---|---|---|---|
| Pod restarts | <N> | 0 | <✓/✗> |
| Unhandled exceptions | <N> | 0 | <✓/✗> |
| Heartbeat misses > 60s | <N> | 0 | <✓/✗> |
| Memory growth (peak / start) | <ratio> | ≤ 1.5× over period | <✓/✗> |
| CPU peak (1-min avg) | <%> | ≤ 50% of allocated | <✓/✗> |
| Average decision latency (signal → order.candidate) | <ms> | informational | — |

## 3. Drift attribution

| Window | Paper win rate | Baseline (backtest) | Drop | Drift alert fired? |
|---|---|---|---|---|
| Days 1-30 | <%> | <%> | <%> | <yes/no> |
| Days 31-60 | <%> | <%> | <%> | <yes/no> |
| Full period | <%> | <%> | <%> | <yes/no> |

If drift alerts fired: investigation summary (≤ 200 words) + remediation taken (or "no remediation; alert was false-positive — see analysis").

## 4. Anomaly log summary

Reference to `docs/strategy/per_strategy/<strategy_id>_paper_log.md` for full detail. Top 5 anomalies during paper:

1. <date> — <description> — <resolution>
2. ...

## 5. Backtest-vs-paper comparison

| Quantity | Backtest | Paper | Δ | Acceptable? |
|---|---|---|---|---|
| Sharpe | <Gate 1> | <paper> | <%> | <✓/✗> |
| Win rate | <Gate 1> | <paper> | <%> | <✓/✗> |
| Average trade duration | <bars> | <bars> | <%> | <✓/✗> |
| Average position size (% of allocation) | <%> | <%> | <%> | <✓/✗> |
| Average slippage (bps) | <bps> (modeled) | <bps> (paper realized) | <%> | <✓/✗> |

A material gap (Δ > 30% on Sharpe or > 10% on win rate) is interrogated: implementation drift, regime mismatch, slippage model error, etc.

## 6. Cost analysis

| Cost component | Modeled (Gate 1) | Realized (paper) | Δ |
|---|---|---|---|
| Commission (bps per side) | <bps> | <bps> | <%> |
| Spread (bps per round-trip) | <bps> | <bps> | <%> |
| Impact (bps, modeled vs realized) | <bps> | <bps> | <%> |
| Total cost per round-trip | <bps> | <bps> | <%> |

## 7. Recommendation

- [ ] **Promote to Gate 4 (Live Micro)** — all criteria PASS; CIO ratifies.
- [ ] **Extend paper trading by N weeks** — borderline; need more trades or another regime sample.
- [ ] **Return to Gate 2** — material gap requires re-engineering (e.g., implementation bug found mid-paper).
- [ ] **Return to Gate 1** — fundamental thesis gap exposed (rare).

## 8. Reviewer sign-off

| Reviewer | Action | Date |
|---|---|---|
| Head of Strategy Research | Reviewed | YYYY-MM-DD |
| **CIO** | **PROMOTED TO GATE 4 / EXTENDED / RETURNED** | YYYY-MM-DD |
```

#### 5.4.2 Paper-to-live decision meeting

Once the paper evidence package is delivered, the CIO and Head of Strategy Research convene a brief paper-to-live decision meeting (in solo-operator practice: a Claude Code session where the agent presents the evidence and the CIO reads/decides). The meeting outputs a **single decision** in the paper evidence package §7:

- **Promote to Gate 4** (default, when all PASS): the strategy is scheduled for live-micro deployment within 5 working days. CIO drafts the live-micro PR (see §6) which adds the strategy to the live supervisor startup list and configures live-broker credentials.
- **Extend paper**: typically when 1–2 criteria are borderline; the CIO sets a specific extension window (e.g., 4 more weeks) and a specific observable to watch (e.g., "want to see win rate stabilize above 50% for 2 consecutive 30-day windows"). The paper period clock continues; no Gate restart.
- **Return to Gate 2**: when an implementation issue is exposed (e.g., a slippage-model bug that paper revealed but Gate 2 stress tests did not). The strategy returns to Gate 2 with a documented remediation requirement; the new Gate 2 PR is reviewed and merged before paper restarts.
- **Return to Gate 1**: rare; only when paper evidence reveals a fundamental thesis gap (e.g., the academic paper the strategy was based on does not actually generalize to live data of the strategy's universe).

### 5.5 Failure modes

| Failure | Likely root cause | Re-entry path |
|---|---|---|
| Paper Sharpe < 0.8 | Backtest overfit (more thorough OOS lacking); or live frictions worse than modeled | Return to Gate 2: re-do CPCV with stricter purging; refine slippage/cost model; possibly Gate 1 retest |
| Paper max DD ≥ 10% | Strategy too aggressive for its category, or stops/sizing parameters too loose | Tighten parameters in Gate 2 (re-PR); re-enter Gate 3 (paper restart) |
| Pod crash (any) | Operational/infrastructure issue | Fix; restart paper period; no Gate-1/2 retest required if cause is purely operational |
| Win-rate divergence > 10% | Implementation issue (the live signal is not what the backtest signal was), or regime mismatch | Diagnose: implementation-fix path back to Gate 2; regime-mismatch may extend paper to capture more regime variety |
| Drift alert fires repeatedly | Edge has decayed during paper period (rare on 8-week timescale; more common at multi-month horizons) | If structural: return to research with documented decay analysis; if false positive: tune drift detector params (with CIO approval, in a paper-monitoring config) |

### 5.6 Worked example — `crypto_momentum` paper-trading 8-week session

#### 5.6.1 Timeline (illustrative)

| Week | Date range | Trades cumulative | Operator activity |
|---|---|---|---|
| 0 | Day -1 to 0 | 0 | Smoke test passed; paper environment confirmed; paper period starts |
| 1 | Days 1-7 | ~30 | Daily dashboard review; baseline win-rate capture begun (need ≥ 50 trades) |
| 2 | Days 8-14 | ~60 | Drift detector now eligible to fire; baseline transferred from Gate 1 |
| 3 | Days 15-21 | ~95 | Mid-period informal review with Head of Strategy Research |
| 4 | Days 22-28 | ~125 | First mid-point review documented in paper log; metrics on track |
| 5 | Days 29-35 | ~155 | Continue monitoring; document any anomalies |
| 6 | Days 36-42 | ~190 | Continue |
| 7 | Days 43-49 | ~225 | Begin assembling paper evidence package |
| 8 | Days 50-56 | ~260 | Final week; paper evidence package delivered Day 56 |
| 9 | Days 57-63 | n/a | CIO + Head of Strategy Research review; paper-to-live decision |

#### 5.6.2 Indicative metrics at closeout

| Metric | Paper value | Threshold | Pass? |
|---|---|---|---|
| Duration | 8.0 weeks (56 days) | ≥ 8 weeks | ✓ |
| Trade count | 261 | ≥ 50 | ✓ |
| Sharpe (annualized) | 0.97 | > 0.8 | ✓ |
| Max DD | 6.8% | < 10% | ✓ |
| Win rate | 53.2% | (backtest 55.7%; ±10% range 50.1%-61.3%) | ✓ |
| Pod crashes | 0 | 0 | ✓ |
| Heartbeat misses > 60s | 0 | 0 | ✓ |

Outcome: **PROMOTE TO GATE 4**.

#### 5.6.3 Backtest-vs-paper Sharpe gap

Gate 1 Sharpe was 1.12; Gate 2 CPCV OOS median 0.92; paper 0.97. This is a healthy distribution: paper is consistent with the conservative end of the CPCV OOS distribution, suggesting the CPCV-modeled OOS conditions are realistic and that the strategy did not benefit from in-sample optimism. No additional investigation required.

#### 5.6.4 Paper evidence package — outcome (illustrative)

> **§7. Recommendation**
>
> [✓] Promote to Gate 4 (Live Micro) — all criteria PASS; CIO ratifies.
>
> Live-micro deployment scheduled for 2026-XX-XX, starting at 20% of target allocation per Charter §6.1.3 cold-start ramp. Paper environment continues to run in parallel for an additional 30 days as a sanity check (live + paper deltas reviewed by the operator daily during initial live week).

---

## §6 — Gate 4 — Live Micro → Live Full

Gate 4 is the **real-capital ramp** gate. The strategy, having proven itself in paper trading, now deploys with **real capital** under the cold-start linear ramp specified in Charter §6.1.3: starting at 20% of target allocation, increasing linearly to 100% over 60 calendar days. At Day 60, a binding decision is made based on live-vs-paper Sharpe.

### 6.1 Entry criteria

A strategy enters Gate 4 when **all** of the following are true:

1. **Gate 3 paper evidence package signed off** by the CIO with explicit "PROMOTED TO GATE 4" decision.
2. **Live-broker credentials configured** for the strategy's universe (Alpaca live equity, Binance live spot, etc.). The credentials are scoped to the strategy's allocation envelope and IP-whitelisted per [CLAUDE.md](../../CLAUDE.md) §11.
3. **Allocator has been configured** to include the strategy in its weekly Risk Parity rebalance, with the cold-start ramp factor applied (Charter §6.1.3).
4. **Live-micro PR merged** to `main`. The PR adds the strategy to the live supervisor startup list (Charter §5.9 ordering), updates `config/strategies/<strategy_id>.yaml` with `live: true`, and links to the Gate 3 paper evidence package.
5. **Day-0 capital movement** completed: the operator has confirmed sufficient unencumbered capital in the broker accounts to support the strategy's 20%-of-target initial allocation.

### 6.2 Live micro phase — 60 days

#### 6.2.1 Ramp logic (Charter §6.1.3)

For day `d` post-entry (d=0 is first day of live allocation):

> `ramp_factor(d) = min(1.0, 0.20 + (0.80 × d / 60))`
>
> `w_i_effective(d) = ramp_factor(d) × w_i_target`

The undersized fraction (`1 - ramp_factor(d)`) is redistributed proportionally to other active strategies (per Charter §6.1.3 last paragraph).

| Day | `ramp_factor` | Effective allocation as % of target |
|---|---|---|
| 0 | 0.20 | 20% |
| 7 | 0.293 | 29.3% |
| 14 | 0.387 | 38.7% |
| 30 | 0.60 | 60% |
| 45 | 0.80 | 80% |
| 60 | 1.00 | 100% |
| 60+ | 1.00 (capped) | 100% |

The ramp is computed by the allocator at every weekly Sunday-23:00-UTC rebalance (Charter §6.1.2). Between rebalances, the strategy operates at its current effective allocation; the allocator does not adjust intra-week.

#### 6.2.2 What the operator monitors

**Daily** (during live-micro):

- **Live Sharpe tracking** vs paper Sharpe. The operator notes the rolling 7-day live Sharpe on the dashboard alongside the paper-period 8-week Sharpe baseline. A widening gap is the primary signal of paper-to-live decay.
- **Live max DD tracking**. Compared to paper max DD; the soft circuit breakers (Charter §8.1.1) operate in live exactly as they would in paper (DD > 8% / 24h → Kelly × 0.5, etc.). The operator notes any soft CB triggers.
- **Cost realization**. Actual commission, spread, and impact realized in live broker fills. Compared to the modeled costs in Gate 1 backtest. Significant divergence (modeled costs underestimating reality by > 30%) is investigated.
- **Heartbeat and pod health**. Same standards as paper.

**Weekly** (during live-micro):

- The Sunday-23:00-UTC allocator rebalance fires; the operator reviews the new ramped allocation.
- Trade log review for the past 7 days; anomalies recorded in the strategy's running paper-log-equivalent (now `<strategy_id>_live_log.md`).
- Drift detector status review.

#### 6.2.3 Intervention rules

**The operator does NOT** during the 60-day ramp:

- **Tune parameters**. Same prohibition as paper (§5.2.2). The strategy operates with the parameters ratified at Gate 2.
- **Override the ramp factor**. The 20% → 100% linear ramp is binding. Skipping ramp days ("we're confident, ramp faster") is forbidden.
- **Override allocator weights**. The allocator's Risk Parity allocation is binding. Manual overrides ("I think we should give Crypto Momentum more weight") are forbidden.
- **Pause unless soft CB fires** or operational issue confirmed.

**The operator MAY** during the 60-day ramp:

- **Pause for confirmed bug or broker issue**. Document in live log; resume when fixed (the ramp clock continues — the bug fix does not extend the 60-day window).
- **Mark for observation** if soft CB triggers persist (multiple soft DD triggers within a week → CIO may extend to formal observation mode at Day 60 regardless of Sharpe).
- **Decommission immediately** under Charter §9.4 (CIO discretionary, with documented reason). Rare; reserved for genuinely unrecoverable findings (e.g., the strategy's edge was an artifact of a backtest data bug that paper happened to mask).

### 6.3 Gate 4 decision — at Day 60

#### 6.3.1 The 70% threshold

Per Charter §7.4, at Day 60 the binding decision rule is:

- If **live Sharpe > 70% of paper Sharpe** → **proceed to full allocation** under standard Risk Parity sizing (the ramp factor is dropped; allocation is whatever the unrampedRisk Parity formula produces given current per-strategy volatility).
- Otherwise → **strategy enters observation mode** at 20% allocation indefinitely until CIO decision.

The 70% threshold encodes Charter's expectation that paper-to-live decay is typical (slippage worse, queue priority adversarial, sub-millisecond frictions not modeled) but not catastrophic. A live Sharpe within 70-100% of paper is acceptable; below 70% indicates either an implementation issue (the strategy is broken in live in a way paper did not catch) or paper-overfit (the paper environment was more permissive than reality).

**Computation specifics**:
- "Live Sharpe" = rolling Sharpe over the **full 60-day live-micro window** (not the trailing 30 days; not the trailing 7 days).
- "Paper Sharpe" = the headline Sharpe from the Gate 3 paper evidence package §1.
- Both Sharpes computed by `backtesting.metrics.sharpe_ratio` ([`backtesting/metrics.py:39`](../../backtesting/metrics.py)) with the same risk-free-rate assumption (default 5% annualized) and same annualization factor (`_ANNUAL_FACTOR_DAILY = √252`).

#### 6.3.2 Day-60 evidence package

**Location**: `reports/<strategy_id>/gate4/day60_evidence.md`

```markdown
# Day-60 Evidence Package — <Strategy Display Name>

**Strategy ID**: `<strategy_id>`
**Live-micro start (Day 0)**: YYYY-MM-DD
**Day 60**: YYYY-MM-DD
**Cumulative live trades**: <N>

---

## 1. Headline metrics

| Metric | Live (Day 0–60) | Paper (Gate 3) | Live / Paper ratio | Pass? |
|---|---|---|---|---|
| Sharpe (annualized, daily) | <value> | <value> | <%> | <≥ 70% / < 70%> |
| Max drawdown | <%> | <%> | — | (informational; soft CBs are real-time) |
| Win rate | <%> | <%> | — | (drift-detector signal) |
| Trade count | <N> | <N> | — | — |

## 2. Soft circuit breaker history

| Trigger | Count over 60-day window | Days in adjusted Kelly | Days paused |
|---|---|---|---|
| DD 24h > 8% (Kelly × 0.5) | <N> | <N> | n/a |
| DD 24h > 12% (24h pause) | <N> | n/a | <N> |
| DD 72h > 15% (review_mode) | <N> | n/a | n/a (review_mode is per-strategy long-term) |
| Win rate < 25% over 50 trades (alert + Kelly × 0.75) | <N> | <N> | n/a |
| Pod crash / heartbeat miss > 60s (pause until manual) | <N> | n/a | <N> |

## 3. Cost realization

| Cost component | Modeled (Gate 1) | Live realized | Δ |
|---|---|---|---|
| Commission per side | <bps> | <bps> | <%> |
| Spread per round-trip | <bps> | <bps> | <%> |
| Impact (modeled vs realized) | <bps> | <bps> | <%> |
| Total cost per round-trip | <bps> | <bps> | <%> |

## 4. Decision

- [ ] **Proceed to Live Full** — live Sharpe ≥ 70% of paper Sharpe; allocator releases ramp factor.
- [ ] **Observation mode** — live Sharpe < 70% of paper Sharpe; strategy stays at 20% indefinitely until CIO decision.
- [ ] **Decommission immediately** — Charter §9.4 discretionary; documented reason: <reason>.

## 5. CIO decision and rationale

<≤ 300 words>

## 6. Sign-off

| Reviewer | Action | Date |
|---|---|---|
| Head of Strategy Research | Reviewed | YYYY-MM-DD |
| **CIO** | **DECISION** | YYYY-MM-DD |
```

### 6.4 Observation mode semantics

A strategy in observation mode after a Day-60 fail:

- **Stays at 20% effective allocation**. The ramp factor is frozen at 0.20; the allocator does not increase it on subsequent weekly rebalances.
- **Continues to trade at this fixed allocation**, accumulating evidence.
- **Has no automatic escalation timeline**. Unlike `review_mode` (Charter §9.2 rule #1 / §6.2.4) which has a 90-day decision deadline, observation mode persists until the CIO acts.

The CIO's available actions in observation mode (per Charter §9.4):

| Action | Trigger |
|---|---|
| **Extend observation** at 20% | More data needed; specific observable named (e.g., "want to see live Sharpe stabilize above 0.5 for 4 consecutive weeks") |
| **Return to paper** | Implementation issue suspected; strategy returns to Gate 3 with documented hypothesis |
| **Decommission** | Confidence lost; Charter §9.4 discretionary |

The CIO documents the observation-mode decision in the per-strategy Charter §12 revision history with date and rationale.

### 6.5 Worked example — `crypto_momentum` Day 60 decision

#### 6.5.1 Indicative numbers

| Metric | Live (Day 0–60) | Paper (Gate 3) | Live / Paper | Pass? |
|---|---|---|---|---|
| Sharpe | 0.74 | 0.97 | 76% | ✓ (≥ 70%) |
| Max DD | 8.4% | 6.8% | — | informational; below Medium Vol 12% category max |
| Win rate | 51.0% | 53.2% | — | within drift tolerance |
| Trade count | 195 | 261 | — | (live cadence slightly lower due to ramped allocation) |

Soft CB history during 60-day window:
- DD 24h > 8% (Kelly × 0.5): **2 occurrences** (BTC sell-off Day 23; SOL gap Day 41); each cleared within 36 hours
- All other soft CBs: 0 occurrences
- Pod crashes: 0
- Heartbeat misses > 60s: 0

#### 6.5.2 Cost realization

| Cost component | Modeled | Live realized | Δ |
|---|---|---|---|
| Commission per side | 10 bps (Binance VIP-0) | 10 bps | 0% |
| Spread per round-trip | 4 bps (top-5) | 6 bps | +50% |
| Impact | 2 bps (Almgren-Chriss k=10bps, adv=$1M) | 4 bps | +100% |
| Total cost per round-trip | 26 bps | 30 bps | +15% |

The cost realization is **slightly worse than modeled** (+15% on total round-trip), explaining most of the live-vs-paper Sharpe gap (paper 0.97 → live 0.74, a ~24% Sharpe degradation that is consistent with a 15% cost increase plus normal noise).

#### 6.5.3 Decision

> [✓] **Proceed to Live Full** — live Sharpe 0.74 = 76% of paper Sharpe 0.97; threshold cleared.
>
> Allocator releases ramp factor at next Sunday-23:00-UTC rebalance. Strategy transitions to standard Risk Parity sizing per Charter §6.1.

**CIO rationale (illustrative)**:

> Crypto Momentum cleared the 70% threshold at 76%. Cost realization is the dominant explanatory factor for the paper-to-live gap; this is acceptable and predicted (Gate 1 cost-sensitivity analysis showed strategy remains profitable under 2× realistic cost). Two soft DD triggers during the 60-day window were both well-bounded and cleared within 36 hours each — consistent with the strategy's expected behavior in volatile crypto regimes. No structural concerns. Promoting to Live Full.

#### 6.5.4 Outcome

Strategy moves to full allocation at next weekly rebalance (Sunday following Day 60). Per-strategy Charter §12 updated with the Day-60 ratification entry. The strategy enters steady state operations (§7).

### 6.6 Failure modes at Gate 4

| Outcome | Operational consequence |
|---|---|
| Live Sharpe / paper Sharpe in [70%, 100%] | **Promote to Live Full**. Standard happy path. |
| Live Sharpe / paper Sharpe in [50%, 70%) | **Observation mode**. Strategy stays at 20%; CIO sets observable + extension period or decommissions. |
| Live Sharpe / paper Sharpe < 50% | **Observation mode AND active investigation**. Likely implementation issue or backtest/paper overfit; CIO highly likely to return to paper or decommission. |
| Live Sharpe negative across 60-day window | **Auto-trigger Charter §9.2 rule #2 candidacy** (Sharpe < 0 over short window — though rule #2 strictly requires 6 months; CIO discretion to invoke §9.4 immediate review). |
| 3+ hard global circuit breaker trips during the 60-day window attributable to this strategy | **Auto-trigger Charter §9.2 rule #5** (3 hard CB trips within 6 months → decommission). Rare during live-micro at 20% allocation but possible. |

---

## §7 — Steady-State Operation

Once a strategy is at full allocation (Live Full post Day-60 promotion), it enters **steady state**. The strategy continues to trade per its specifications, monitored continuously, reviewed at three cadences (daily, monthly, semi-annual). Steady state is the longest segment of a strategy's lifecycle — typically months or years before any decommissioning condition triggers.

### 7.1 Daily operations

#### 7.1.1 Allocator weekly rebalance

Per Charter §6.5, every Sunday at 23:00 UTC:

1. The allocator (`services/portfolio/strategy_allocator/`) fetches per-strategy 60-day rolling realized volatility from the research feedback loop (`services/research/feedback_loop/`, currently `services/feedback_loop/`).
2. Computes target weights via Phase 1 Risk Parity formula (Phase 2 Sharpe overlay if active per Charter §6.2.1 trigger conditions).
3. Applies floors (5% per active strategy) and ceilings (40% standard; 45% for elevated performers per Charter §6.2.3); redistributes overflow.
4. Applies turnover dampening (±25% per strategy max weekly weight change).
5. Publishes new weights to `portfolio:allocation:<strategy_id>` Redis key (per-strategy).
6. Publishes `portfolio.allocation.updated` event on the ZMQ bus for observability.
7. The `PerStrategyExposureGuard` (STEP 6 of the VETO chain) reads new weights on subsequent orders.

The rebalance does **not** generate trades directly — it updates the **capacity envelope** each strategy trades within. Strategies drift toward the new envelope as positions naturally open and close.

#### 7.1.2 Drift detector (continuous)

The drift detector (`services/research/feedback_loop/drift_detector.py`, currently [`services/feedback_loop/drift_detector.py`](../../services/feedback_loop/drift_detector.py)) runs on every closed trade for every active strategy:

- Reads the strategy's per-strategy trade history from `trades:<strategy_id>:all` (per-strategy partition per Charter §5.5).
- Computes rolling win rate over last 50 trades.
- Compares to baseline (3-month rolling per-strategy historical win rate, captured during Gate 3 paper trading and rolled forward continuously since).
- Emits `DriftAlert` if relative drop exceeds 10% (`DRIFT_THRESHOLD = 0.10` at line 42).
- Alerts surface in the dashboard; the operator reviews within 24 hours.

#### 7.1.3 Soft circuit breakers (continuous)

Per Charter §8.1.1, the soft CBs operate continuously per active strategy. Their detailed operational responses are in §8 of this Playbook.

#### 7.1.4 Hard circuit breakers (continuous)

Per Charter §8.1.2, the hard CBs operate continuously at the portfolio level. Their detailed operational responses are in §9 of this Playbook.

#### 7.1.5 Pod-health monitoring (continuous)

Each strategy microservice publishes a heartbeat to its Redis key every 5 seconds. The `services/ops/monitor_dashboard/` (currently `services/command_center/`) subscribes; misses > 60 seconds trigger an alert AND a soft pause per Charter §8.1.1.

### 7.2 Weekly review (CIO)

Every week (typical: Monday or Sunday evening), the CIO reviews each active strategy's per-strategy dashboard panel for ≤ 10 minutes per strategy:

- **Per-strategy PnL** (rolling 7-day, rolling 30-day).
- **Per-strategy DD curve** (peak-to-trough since inception).
- **Allocator weight history** for the strategy (any sustained reduction triggered by volatility increase?).
- **Soft CB trip log** for the past 7 days.
- **Drift alert log**.
- **Anomaly notes** in `<strategy_id>_live_log.md`.

**Output**: weekly review note appended to the strategy's live log (1-3 sentences per strategy). No formal artifact; this is operational vigilance, not a documented decision.

### 7.3 Monthly review (CIO)

Once per month, a more formal review:

- **Per-strategy Sharpe and DD on rolling 1M and 3M windows**, compared to category targets (Charter §9.1).
- **Cross-strategy correlation matrix** (target < 0.3 average off-diagonal per Charter §10.3).
- **Soft CB trip history** for the past 30 days; pattern analysis (any strategy showing escalating stress?).
- **Strategies approaching decommissioning thresholds**: any strategy with rolling 3M Sharpe < 0 trends? Any strategy approaching the 9-month Sharpe < 0 rule (Charter §9.2 #1)?
- **Allocator weight stability**: any strategy whose weight has moved >50% within the month? Investigation as needed.
- **Cost realization tracking**: any cost component drifting from Gate 1 baseline by > 30%?

**Output**: monthly review note in `docs/claude_memory/SESSIONS.md` (a session entry titled "Monthly Portfolio Review YYYY-MM"). If any binding decision is made (e.g., ratify category reassignment, initiate observation mode, ratify decommissioning), an entry in `docs/claude_memory/DECISIONS.md` is also added.

### 7.4 Semi-annual review (Charter §9.6)

Every six months, the CIO conducts a **formal portfolio review**:

- **Full strategy portfolio review**: every active strategy, every observation-mode strategy, every decommissioned-but-not-yet-archived strategy.
- **Category reassignment consideration** per Charter §9.5: any strategy operating systematically outside its category bounds?
- **Active `review_mode` strategies decision**: continue or decommission?
- **New-candidate backlog review**: any candidates ready to enter Gate 1?
- **Allocator behavior review**: does Risk Parity (Phase 1) or Risk Parity + Sharpe (Phase 2) appear to be tracking reality, or has it accumulated bias?
- **Charter and Playbook revision review**: have any operational realities emerged that justify amendment?

The semi-annual review is documented as a formal session entry in `docs/claude_memory/SESSIONS.md` and, if it produces material decisions, in `docs/claude_memory/DECISIONS.md` and (when appropriate) Charter or Playbook version bumps per the amendment procedures (Charter §13.4, Playbook §16).

### 7.5 Steady-state operational SLAs

| Operation | Cadence | SLA |
|---|---|---|
| Heartbeat refresh per strategy | Every 5 seconds | TTL 5 seconds |
| Risk heartbeat refresh | Every 2 seconds | TTL 5 seconds (per [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) D2) |
| Allocator rebalance | Weekly Sunday 23:00 UTC | Within 5 minutes of scheduled time |
| Drift detector evaluation | Every closed trade | Within 1 second of trade close |
| Soft CB evaluation | Every order candidate | < 10ms p95 |
| Hard CB evaluation | Continuous + every order | < 10ms p95 |
| Dashboard update | Every 5 seconds | Eventually consistent within 30 seconds |
| Weekly review | Weekly | Within 24 hours of weekend close |
| Monthly review | Monthly | Within 7 days of month-end |
| Semi-annual review | Every 6 months | Within 14 days of period-end |

---

## §8 — Soft Circuit Breaker Response Protocols

This section operationalizes Charter §8.1.1. For each soft CB trigger, it specifies what happens mechanically, what the operator checks, and the recovery protocol.

### 8.0 StrategyHealthCheck state machine (canonical specification)

The `StrategyHealthCheck` is STEP 3 of the VETO chain (Charter §8.2). Per-strategy, it tracks the strategy's operational state. Every `OrderCandidate` from a strategy passes through STEP 3, which consults the strategy's current state and either ALLOWS the candidate forward to STEP 4 or REJECTS with a `BlockReason`.

This subsection defines the canonical state machine that all strategy microservices inherit. Implementation lives at `services/portfolio/risk_manager/strategy_health_check.py` (post-multi-strat-lift Phase B; until then, the state is tracked in Redis keys `strategy_health:<strategy_id>:state`).

**States** (enum):

| State | Semantics | STEP 3 behavior |
|---|---|---|
| `HEALTHY` | Normal operation; Kelly at nominal value | ALLOW |
| `DD_KELLY_ADJUSTED` | Kelly reduced (× 0.5 per §8.1, or × 0.75 per §8.4); strategy continues trading at adjusted sizing | ALLOW (downstream sizing applies the adjustment) |
| `PAUSED_24H` | 24-hour pause active per §8.2 (DD > 12% / 24h); orders blocked; existing positions managed | REJECT with `BlockReason.STRATEGY_PAUSED`, until `pause_until` timestamp elapses |
| `PAUSED_OPERATIONAL` | Pod crash or heartbeat miss per §8.5; orders blocked; requires manual clear | REJECT with `BlockReason.STRATEGY_OPERATIONAL_HALT`, until manual state clear |
| `REVIEW_MODE` | DD > 15% / 72h per §8.3, or Rule #1/#2 per §10.1/§10.2; allocator floors at 5%; 90-day CIO decision window active | ALLOW (strategy continues to trade at floored allocation) |
| `DECOMMISSIONED` | Terminal state; strategy no longer active per §10 | REJECT with `BlockReason.STRATEGY_DECOMMISSIONED` permanently |

**Allowed transitions**:

| From | To | Trigger | Authority |
|---|---|---|---|
| `HEALTHY` | `DD_KELLY_ADJUSTED` | §8.1 (DD 8%/24h) or §8.4 (win rate) | Automatic |
| `HEALTHY` | `PAUSED_24H` | §8.2 (DD 12%/24h) | Automatic |
| `HEALTHY` | `PAUSED_OPERATIONAL` | §8.5 (crash or heartbeat > 60s) | Automatic |
| `HEALTHY` | `REVIEW_MODE` | §8.3 (DD 15%/72h), or §10.1/§10.2 (Rules #1/#2) | Automatic |
| `DD_KELLY_ADJUSTED` | `HEALTHY` | §8.1.3 recovery (clean 24h window) | Manual (CIO) |
| `DD_KELLY_ADJUSTED` | `PAUSED_24H` | Further DD to 12% within 24h | Automatic |
| `DD_KELLY_ADJUSTED` | `REVIEW_MODE` | Further DD to 15% / 72h | Automatic |
| `PAUSED_24H` | `HEALTHY` or `DD_KELLY_ADJUSTED` | `pause_until` elapsed + manual review | Manual (CIO) |
| `PAUSED_24H` | `PAUSED_24H` (extended) | CIO extends per §8.2.2 | Manual (CIO) |
| `PAUSED_24H` | `REVIEW_MODE` | CIO escalation per §8.2.2 | Manual (CIO) |
| `PAUSED_OPERATIONAL` | `HEALTHY` | §8.5.2 manual recovery | Manual (CIO) |
| `REVIEW_MODE` | `HEALTHY` | §8.3.3 CIO clear within 90 days | Manual (CIO) |
| `REVIEW_MODE` | `DECOMMISSIONED` | §8.3.4 90-day deadline elapse, OR CIO decommission before deadline per §10.3 | Automatic (at deadline) OR Manual (CIO) |
| `HEALTHY` or any non-terminal | `DECOMMISSIONED` | Rules #4/#5 auto-triggers (§10.4/§10.5) OR Rule #6 CIO discretionary (§10.6) | Automatic OR Manual (CIO) |

**Persistence**: Each strategy's current state is persisted in Redis at `strategy_health:<strategy_id>:state`; transitions are logged to structlog with event `strategy_health.transition` carrying `{from, to, trigger, timestamp}`. The dashboard subscribes and surfaces current state per strategy.

**Implementation note**: Until the multi-strat infrastructure lift Phase B lands `services/portfolio/risk_manager/strategy_health_check.py`, the state machine is implemented inside the current `services/risk_manager/chain_orchestrator.py` STEP 3 handler; the Redis key namespace is already established (per Charter §5.5 per-strategy partitioning).

### 8.1 Strategy DD > 8% / 24h → Kelly × 0.5

#### 8.1.1 Mechanical sequence

1. Realized PnL updates in the per-strategy partition (`pnl:<strategy_id>:daily`, `pnl:<strategy_id>:24h`).
2. The feedback loop computes 24-hour drawdown for the strategy and detects threshold cross.
3. `feedback.strategy_dd_alert` event publishes on the ZMQ bus with `strategy_id`, `drawdown = 0.08+`, `threshold_triggered = "soft_dd_24h_8pct"`.
4. The allocator subscribes; sets `kelly_adjust = 0.5` for the strategy, persisted to `kelly:<strategy_id>:adjust` (per-strategy partition).
5. The `MetaLabelGate` (STEP 4 of the VETO chain — `services/risk_manager/meta_label_gate.py`) and the strategy's own sizing logic both read `kelly_adjust` and apply it as a multiplier on the strategy's nominal Kelly fraction.
6. Subsequent orders from this strategy are sized at half their normal Kelly. Other strategies are unaffected (per-strategy partitioning per Charter §5.5).
7. Dashboard surfaces an "Strategy DD 8% — Kelly halved" alert.

#### 8.1.2 Operator checks (within 24 hours)

- **Single bad trade or distributed loss?** A single trade producing 5% of the 8% drawdown is a different story (likely a per-position-control gap) than 8% accumulated over 30 trades (likely regime mismatch).
- **Regime context**. Was there a market-wide event (CB surprise, geopolitical shock, vol spike)? If yes, the strategy's drawdown is regime-driven, not idiosyncratic.
- **Operational health**. Pod healthy? Heartbeat clean? Data feed clean? Eliminate operational explanations first.
- **Cost spike?** Did slippage or impact suddenly worsen (data feed lag → late fills)?

#### 8.1.3 Recovery — Kelly restoration

Per Charter §8.4 worked example: Kelly restoration is **not automatic**. Restoration requires a **clean 24-hour window** with:

- No additional soft CB triggers for the strategy
- Drawdown recovered to within 4% of peak (i.e., DD reduced by half from the 8% trigger threshold)
- Operator confirmation in the strategy's live log

When restoration is granted, the operator manually clears `kelly:<strategy_id>:adjust` (sets to `1.0`); the next order proceeds at full Kelly.

### 8.2 Strategy DD > 12% / 24h → 24h pause

#### 8.2.1 Mechanical sequence

1. Drawdown threshold cross detected (12% within 24h).
2. The strategy's `StrategyHealthCheck` state (STEP 3 of the VETO chain — see Charter §8.2; new per-Playbook component) flips to `PAUSED_24H` with `pause_until = now + 24h`.
3. STEP 3 of the chain rejects all `OrderCandidate` from this strategy with `BlockReason.STRATEGY_PAUSED`.
4. **Existing positions are not closed automatically** — the strategy's stop-loss and take-profit logic continues to manage them. New entries are blocked.
5. The allocator redistributes the strategy's (zero new) exposure capacity to other strategies (proportionally, per Charter §6.1.4 paused strategy semantics).
6. Dashboard surfaces "Strategy paused 24h — DD 12%" critical alert.

#### 8.2.2 Operator review at 24h expiry

When `pause_until` elapses, the operator reviews **before clearing the pause**:

- Did the strategy continue to lose during the pause (existing positions managed but bleeding)? If yes, the pause may need extension.
- Has the regime stabilized? Are markets back in the strategy's natural regime?
- Have additional soft CBs fired during the pause (cascading drawdown via existing positions)?

The operator either:
- **Resumes the strategy** by manually clearing the pause state. The strategy's Kelly remains at × 0.5 (from the prior 8% soft trigger; rare for 12% pause to fire without 8% having fired earlier in the same window).
- **Extends the pause** for another 24 hours with documented reason. Multiple extensions push the strategy toward `review_mode` consideration.
- **Escalates to `review_mode`** preemptively if the situation is severe (CIO judgment per Charter §9.4).

### 8.3 Strategy DD > 15% / 72h → review_mode

#### 8.3.1 Mechanical sequence

1. Drawdown threshold cross detected (15% within 72h, indicating a sustained loss across multiple sessions).
2. The strategy's `StrategyHealthCheck` state flips to `REVIEW_MODE` (no time-bound clearance — only manual CIO clearance).
3. The allocator floors the strategy at 5% effective allocation (Charter §6.2.4) and excludes it from any Phase 2 Sharpe-overlay upward tilts.
4. The strategy continues to trade at 5% allocation to accumulate evidence either way.
5. **CIO 90-day decision window starts** (Charter §9.2 rule #1 / #3 reference). The countdown is logged in `docs/claude_memory/DECISIONS.md` with the trigger date.
6. Dashboard surfaces "Strategy in REVIEW_MODE — 90-day window starts YYYY-MM-DD; review by YYYY-MM-DD".

#### 8.3.2 CIO evaluation (within 90 days)

The CIO conducts a structured evaluation:

- **Root-cause analysis**. Is the drawdown explained by a regime mismatch (strategy works in trend, current regime is chop), a structural change (an exchange listing change, a fee schedule change, etc.), edge decay (the alpha has weakened over time and the drift detector is showing it), or an implementation issue exposed late?
- **Regime-conditional historical comparison**. How did the strategy perform in similar historical regimes? If it has historically survived comparable drawdowns and recovered, the case for continuation is stronger.
- **Future regime forecast**. Does the operator believe the unfavorable regime persists indefinitely or rotates? Macro context informs this.
- **Cost-benefit of continuation**. Even at 5% allocation, the strategy consumes operational attention. Is that attention worth the option value of a recovery?

The output is a **`review_mode` continuation memo** at `docs/strategy/per_strategy/<strategy_id>_review_mode_<date>.md`:

```markdown
# Review Mode Memo — <strategy_id>

**Trigger date**: YYYY-MM-DD (DD > 15% / 72h)
**90-day deadline**: YYYY-MM-DD
**Author**: CIO

## Root-cause analysis (≤ 500 words)
<analysis>

## Historical analog
<comparable historical drawdowns + outcomes>

## Forward outlook
<regime / market thesis>

## Decision
- [ ] Clear `review_mode` — strategy returns to standard operation; document specific reason for clearance
- [ ] Maintain `review_mode` — continue at 5% for the remainder of the 90-day window; revisit before deadline
- [ ] Decommission per Charter §9.2 — execute decommissioning checklist (§10)

## Sign-off
| CIO | YYYY-MM-DD |
```

#### 8.3.3 Exit protocol — clearing review_mode

When the CIO clears `review_mode`:
- The strategy's `StrategyHealthCheck` state returns to `HEALTHY`.
- The allocator releases the 5% floor; the strategy returns to standard Risk Parity allocation at the next weekly rebalance.
- The Kelly adjustment (if any from earlier soft triggers) is restored manually per §8.1.3.
- An entry is appended to the strategy's per-strategy Charter §12 revision history.

#### 8.3.4 Failure to act → automatic decommissioning

If the 90-day decision window elapses **without** an explicit CIO decision (clear or decommission), the strategy is **automatically decommissioned** per Charter §9.2 rule #3. This is enforced mechanically: the dashboard alerts ahead of the deadline, but if the deadline passes, the supervisor halts the strategy's container and the allocator removes it from the active set.

### 8.4 Win rate < 25% / last 50 trades → Kelly × 0.75 + alert

#### 8.4.1 Mechanical sequence

1. The drift detector evaluates the strategy's last-50-trades win rate (per [`services/feedback_loop/drift_detector.py:43`](../../services/feedback_loop/drift_detector.py) `MIN_TRADES = 50`).
2. If win rate < 25%, the soft CB fires.
3. `kelly:<strategy_id>:adjust` is set to `0.75` (a milder reduction than the DD-based 0.5 reduction).
4. A `feedback.win_rate_alert` event publishes; dashboard surfaces.

Note: the 25% threshold is **not the same as the drift detector's 10% relative-drop threshold**. The 10% relative drop fires `DriftAlert` (informational); the 25% absolute floor fires the soft CB (Kelly reduction). They are independent signals; both can fire simultaneously (a strategy with 50% backtest baseline that drops to 24% live triggers both).

#### 8.4.2 Operator review

The operator investigates within 48 hours:

- **Statistical significance**. Is 25% over 50 trades genuine evidence, or sample noise? A strategy with 35% historical win rate has a non-trivial probability of producing a 50-trade window at 25% by chance. The operator computes a 95% binomial CI and decides if the observation is meaningful.
- **Implementation issue**. Has the signal pipeline degraded? Has a feature calculator started returning wrong values? (This is rare but happens — a data-source schema change can quietly corrupt a feature.)
- **Regime mismatch**. Has the market regime shifted to one where the strategy historically underperforms?

#### 8.4.3 Possible actions

| Operator action | Trigger |
|---|---|
| **Continue + observe** | The 25% reading is noise; 95% CI on win rate spans the historical baseline; no action |
| **Pause + investigate** | An implementation issue is suspected; pause manually until resolved |
| **Initiate `review_mode`** | The 25% reading combined with sustained underperformance suggests structural concern; CIO escalates per Charter §9.4 |

### 8.5 Pod crash / heartbeat miss > 60s → pause

#### 8.5.1 Mechanical sequence

1. The supervisor or the dashboard detects: (a) the strategy's container has exited (crash), or (b) the strategy's Redis heartbeat key has not been refreshed in > 60 seconds.
2. The strategy's `StrategyHealthCheck` state flips to `PAUSED_OPERATIONAL`.
3. STEP 3 of the VETO chain rejects all `OrderCandidate` from the strategy with `BlockReason.STRATEGY_OPERATIONAL_HALT`.
4. **No automatic restart on soft pause** (per Charter §8.1.1 explicit rule). The operator must investigate the crash.
5. Dashboard surfaces critical alert.

The "no auto-restart on soft pause" rule is deliberate: a crashing strategy that auto-restarts may crash repeatedly in a loop, generating thrash without resolving the underlying issue. The rule forces the operator to investigate.

#### 8.5.2 Manual recovery protocol

1. **Inspect logs**. The strategy's container logs are persisted; the operator examines for unhandled exceptions, OOM kills, or upstream issues.
2. **Triage**:
   - Transient (memory pressure, transient upstream timeout): log the incident, restart the container, monitor for recurrence.
   - Bug (unhandled exception in strategy logic, frozen-Pydantic violation, etc.): file an issue, fix on a branch, deploy the fix; the strategy stays paused until the fix is verified.
   - Infrastructure (broker outage, Redis outage): wait for infrastructure recovery; restart strategy when stable.
3. **Restart**. The operator clears the `PAUSED_OPERATIONAL` state and restarts the container. Heartbeat resumes; STEP 3 stops rejecting; the strategy returns to operation.
4. **Document**. The incident is logged in the strategy's live log with cause + resolution + recurrence-prevention note.

If the same strategy crashes ≥ 3 times within 7 days, the CIO must decide whether to maintain the operational pause indefinitely (pending root cause) or to formally enter `review_mode` (Charter §9.4 discretionary).

### 8.6 Soft CB summary table (operational reference)

| Trigger | Mechanism | Per-strategy effect | Operator response | Recovery |
|---|---|---|---|---|
| DD > 8% / 24h | Allocator sets `kelly:adjust = 0.5` | Strategy continues at half Kelly | Investigate cause within 24h | Manual clear after 24h clean window |
| DD > 12% / 24h | STEP 3 rejects with `STRATEGY_PAUSED` for 24h | New entries blocked; existing positions managed | Review at 24h expiry; resume / extend / escalate | Manual at 24h or extension |
| DD > 15% / 72h | `review_mode` — allocator floors at 5%, exclude from upward tilts | Reduced allocation; 90-day decision window | CIO writes `review_mode` memo within 90 days | Manual clear OR auto-decommission at 90d |
| Win rate < 25% / 50 trades | Allocator sets `kelly:adjust = 0.75` + alert | Strategy continues at 75% Kelly | Investigate within 48h | Manual clear when win rate recovers |
| Pod crash / heartbeat > 60s | STEP 3 rejects with `STRATEGY_OPERATIONAL_HALT` | All orders blocked; no auto-restart | Investigate root cause; deploy fix; manual restart | Manual after fix verified |

---

## §9 — Hard Circuit Breaker Response Protocols (Portfolio)

This section operationalizes Charter §8.1.2. Hard CBs are **portfolio-wide**; firing affects all strategies. Resumption requires explicit CIO action.

### 9.1 Portfolio DD > 12% / 24h → halt all + human review

#### 9.1.1 Mechanical sequence (Charter §8.5 worked example, expanded)

1. Aggregate portfolio drawdown computed continuously across all active strategies (allocator + feedback loop joint computation).
2. Threshold cross detected (-12.0% over rolling 24h window).
3. `portfolio.circuit.hard_tripped` event publishes on the ZMQ bus.
4. STEP 2 of the VETO chain (`PortfolioCircuitBreaker` — see [`services/risk_manager/circuit_breaker.py`](../../services/risk_manager/) and [`chain_orchestrator.py:165-179`](../../services/risk_manager/chain_orchestrator.py)) starts rejecting **all** incoming `OrderCandidate` across all strategies with `BlockReason.CIRCUIT_BREAKER_HARD_TRIP`.
5. The allocator suspends further rebalancing (the portfolio is in halt state).
6. **Existing positions are not auto-closed.** The execution engine's stop-loss and take-profit logic continues to manage them; new entries are blocked.
7. The dashboard surfaces a critical alert: **"PORTFOLIO HALT — -12% DD 24h"**. The alert engine pages the operator (per [CLAUDE.md](../../CLAUDE.md) §14 alerting expectations).

#### 9.1.2 CIO emergency review protocol

The CIO must convene an emergency review **within 4 hours** of the trip. The review gathers:

| Data | Source |
|---|---|
| Per-strategy PnL contribution to the 12% drawdown | `pnl:<strategy_id>:24h` Redis keys |
| Per-strategy active-positions snapshot | per-strategy positions tables |
| Cross-strategy correlation in past 24h vs baseline | `correlation:matrix` + historical |
| Market regime indicators in past 24h (VIX, BTC vol, equity-bond correl) | `services/macro_intelligence/` (now `services/data/macro_intelligence/`) |
| Allocator most recent rebalance log | structlog stream |
| Soft CB trip history in past 7 days | dashboard alert log |

The CIO answers four questions in writing (in `docs/claude_memory/SESSIONS.md`):

1. **Is the drawdown attributable to one strategy or distributed?** A single-strategy-driven 12% portfolio drawdown points at that strategy; a distributed drawdown points at correlated risk.
2. **Was the cause foreseeable?** Did soft CBs fire in the preceding 7 days that should have triggered earlier reduction?
3. **Has the underlying market condition stabilized, or is continued exposure the real risk?** Resuming into worsening conditions is worse than waiting.
4. **What action is taken?** Resume? Extend halt? Reduce allocations before resuming? Decommission a specific strategy?

#### 9.1.3 Resume conditions

Resume requires **all** of:

- The CIO has documented the four-question answers in `SESSIONS.md`.
- The market condition that triggered the drawdown has measurably stabilized (specific observable named — e.g., "VIX has retraced from 35 to ≤ 28").
- No additional soft CBs have fired during the halt period.
- A post-mortem document is started at `docs/postmortems/portfolio_halt_<YYYY-MM-DD>.md`.

To resume:
- The CIO manually clears the `risk:circuit_breaker:state` Redis key from `HARD_TRIPPED` back to `HEALTHY`.
- STEP 2 stops rejecting; orders begin flowing.
- The allocator may apply a precautionary across-the-board Kelly × 0.5 for 48 hours post-resume (CIO discretion).

#### 9.1.4 Documentation requirement

**Within 7 days** of any hard CB trip, a post-mortem document is finalized at `docs/postmortems/portfolio_halt_<YYYY-MM-DD>.md`:

```markdown
# Portfolio Hard CB Trip Post-Mortem — YYYY-MM-DD

**Trigger**: Portfolio DD <%> over <window>
**Trip time**: YYYY-MM-DD HH:MM UTC
**Resume time**: YYYY-MM-DD HH:MM UTC
**Halt duration**: <hours>

## What happened
<chronology, ≤ 500 words>

## Per-strategy contribution
| Strategy | PnL during 24h window | Contribution to DD |
| ... | ... | ... |

## Root cause
<analysis>

## What worked
<which controls fired correctly>

## What didn't work
<what was late or missed>

## Action items
- [ ] <action with owner + deadline>

## Sign-off
| CIO | YYYY-MM-DD |
```

### 9.2 Portfolio DD > 15% / 72h → halt all + 48h mandatory cooling

#### 9.2.1 The 48h non-negotiable

This trigger is **stricter** than the 12%/24h trigger because it indicates sustained loss across multiple sessions, suggesting the platform's risk model has not adequately captured the regime. The Charter mandates a **48-hour mandatory cooling period** before resumption — this cannot be overridden by the CIO regardless of how stable conditions become.

The reason for non-negotiability (per Charter §8.1.2): the human reaction to a 15% drawdown is to want to "make it back" by re-engaging quickly — precisely the pattern that drives revenge trading. Mandatory cooling enforces a pause for non-trading judgment.

#### 9.2.2 Mechanical sequence

Same as 9.1.1, with the addition:
- `risk:circuit_breaker:cooling_until` is set to `now + 48h`.
- The CIO's manual clear attempt before that timestamp is rejected by the system; a clear can only succeed at or after `cooling_until`.

#### 9.2.3 CIO conduct during cooling

The CIO is encouraged to:
- Read non-trading material (research papers, retrospective audit notes).
- Avoid intraday market screens during the 48h.
- Schedule the post-trip review for *after* the 48h, not during.

This is operational discipline, not a code-enforced rule. But the Playbook records it as the discipline this protocol is designed to enforce.

#### 9.2.4 Post-cooling resume

After 48h, the resume protocol is identical to §9.1.3, with the additional requirement:

- The CIO has produced a **multi-strategy reallocation rationale** explaining why the resumption proceeds with the current allocation mix or what is changed (e.g., "Strategy #4 VRP is decommissioned per CIO discretionary §9.4 because the loss attribution traces 70% to it; remaining 5 strategies resume").

### 9.3 3+ strategies in DEGRADED simultaneously → halt all

#### 9.3.1 The correlation-breakdown interpretation

Per Charter §8.1.2: when 3 or more nominally-independent strategies degrade together, the **correlation assumption under which they were diversified has failed**. The portfolio is exposed to a common underlying risk that was not in the risk model. The appropriate response is to stop trading and investigate, not to continue optimizing within the broken model.

"DEGRADED" in this context maps to the strategy-level state where the strategy is in `review_mode` (Charter §9.2 rule #1) OR has soft-CB-paused for 24h+ (Charter §8.1.1 row 2). Either condition counts toward the 3-strategy threshold.

#### 9.3.2 Mechanical sequence

1. The dashboard or feedback loop counts the active strategies in `REVIEW_MODE` or `PAUSED_24H`.
2. If count ≥ 3 simultaneously, the hard CB trips.
3. STEP 2 of the VETO chain rejects all orders.
4. The allocator suspends rebalancing.
5. Critical alert.

#### 9.3.3 Investigation protocol

The CIO investigates whether this is:

- **Real risk signal** — a correlated stress is hitting multiple strategies (e.g., a vol spike that simultaneously hurts the VRP strategy, the mean-reverter, and the trend follower). Action: review correlation assumptions; consider whether category budgets need tightening.
- **Data/measurement issue** — multiple strategies are flagged due to a shared upstream issue (e.g., a corrupt feature reading affecting all consumers). Action: fix the data issue; clear the false-positive flags.

The investigation is documented in `SESSIONS.md` and (if it produces structural change) in `DECISIONS.md`.

### 9.4 Portfolio 1-day VaR > 8% → alert + Kelly × 0.5 across all

#### 9.4.1 Mechanical sequence

1. The risk feedback loop computes 1-day VaR (95th percentile expected loss) across the live portfolio.
2. If VaR > 8%, the soft-but-portfolio-wide CB fires.
3. The allocator sets `kelly:<strategy_id>:adjust = 0.5` for **every active strategy** (not selective).
4. Subsequent orders across all strategies are sized at half Kelly until VaR recovers.
5. Dashboard surfaces "Portfolio VaR > 8% — Kelly halved across portfolio" critical alert.

#### 9.4.2 What the CIO reviews

- **VaR computation sanity**. Is the VaR inflated by a transient volatility spike that is already reverting?
- **Per-strategy VaR contribution**. Which strategies dominate the VaR? If one strategy contributes 60% of the VaR, decommissioning it might reduce VaR more than across-the-board Kelly reduction.
- **Forward-looking regime indicators**. Is VaR likely to keep rising (continuing to trade with reduced Kelly is reasonable) or to revert (sit through the spike)?

#### 9.4.3 Recovery

VaR recovery is automatic in the sense that the metric updates continuously; once VaR drops below 8%, the operator can manually restore Kelly across the portfolio (no auto-restoration to prevent oscillation). Restoration follows the same clean-window discipline as §8.1.3 (24h with no further alerts).

### 9.5 Hard CB summary table

| Trigger | Mechanism | Resume condition |
|---|---|---|
| Portfolio DD > 12% / 24h | STEP 2 rejects all | CIO manual clear + 4-question review documented |
| Portfolio DD > 15% / 72h | STEP 2 rejects all + `cooling_until = +48h` | After 48h + CIO multi-strategy rationale |
| 3+ strategies DEGRADED simultaneously | STEP 2 rejects all | CIO investigation outcome (real-risk vs data-issue) |
| Portfolio 1-day VaR > 8% | All-strategies Kelly × 0.5 + alert | Manual restore after VaR < 8% for clean 24h window |

---

## §10 — Decommissioning Execution

This section operationalizes Charter §9.2. Each of the six decommissioning rules has a specific mechanical checklist; this Playbook prescribes the order of operations exactly.

### 10.1 Rule #1 — Sharpe < 0 over 9 consecutive months → review_mode

#### 10.1.1 Trigger detection

- The feedback loop computes rolling 9-month Sharpe per active strategy nightly.
- If the rolling Sharpe is < 0 for **9 consecutive months** (i.e., every nightly evaluation in the trailing 9-month window confirms Sharpe < 0), the trigger fires.
- The dashboard alerts at the trigger; the operator is notified via the standard alerting channel.

#### 10.1.2 Action checklist

- [ ] **Verify trigger**. The CIO confirms with a query against `pnl:<strategy_id>:daily` that the rolling Sharpe is genuinely sub-zero (not a data-bug artifact).
- [ ] **Allocator instructed to enter `review_mode`**. The allocator floors the strategy at 5% and excludes it from upward Sharpe-overlay tilts (Charter §6.2.4).
- [ ] **CIO notification recorded**. An entry in the strategy's per-strategy Charter §12 revision history: "REVIEW_MODE entry per Rule #1 (9M negative Sharpe), trigger date YYYY-MM-DD".
- [ ] **90-day decision window starts**. Logged in `docs/claude_memory/DECISIONS.md` with explicit deadline (`trigger + 90 days`).
- [ ] **`review_mode` continuation memo template** created at `docs/strategy/per_strategy/<strategy_id>_review_mode_<date>.md` (see §8.3.2 for template).
- [ ] **Strategy continues to trade at 5%** during the 90-day window, accumulating evidence.

### 10.2 Rule #2 — Sharpe < -0.5 over 6 consecutive months → immediate review_mode

This rule accelerates Rule #1: when sharpe is significantly negative (not just slightly), the 9-month wait is shortened to 6.

#### 10.2.1 Trigger detection

- Same nightly computation, but the threshold is `Sharpe < -0.5` over 6 consecutive months.

#### 10.2.2 Action checklist

Same as Rule #1, with two changes:
- The 90-day decision window still applies (the rule changes the *entry* condition; the window mechanics are identical).
- The CIO's `review_mode` memo is expected to lean more strongly toward decommissioning (a Sharpe < -0.5 over 6 months is a stronger signal than -0.0 over 9 months).

### 10.3 Rule #3 — > 90 days in review_mode without recovery → decommissioning

This rule is the **outcome** of Rules #1 and #2 if no remediation occurs.

#### 10.3.1 Trigger detection

- The dashboard tracks each strategy's `review_mode_start_date`; if `now - review_mode_start_date > 90 days` AND `review_mode_state == ACTIVE`, the trigger fires.
- The dashboard alerts at Day 75 (15-day warning), Day 85 (5-day warning), and Day 90 (deadline).

#### 10.3.2 Decommissioning action checklist (the master checklist)

This is the canonical checklist for all decommissioning paths (Rules #1/#2 → #3, plus Rules #4–#6).

- [ ] **Trigger verified**. CIO confirms the conditions of the triggering rule are met.
- [ ] **Decommissioning decision recorded** in `docs/claude_memory/DECISIONS.md`:
  ```
  ## YYYY-MM-DD — <strategy_id> decommissioned per Rule #N

  **Trigger**: <e.g., "90 days in review_mode without recovery; entered review_mode YYYY-MM-DD per Rule #1">
  **CIO rationale**: <≤ 200 words>
  **Re-allocation**: <e.g., "5% allocation redistributed to remaining 4 active strategies proportionally">
  **Reactivation eligibility**: not before YYYY-MM-DD (6 months hence per Charter §9.3)
  ```
- [ ] **Per-strategy Charter §1 status** updated to `DECOMMISSIONED` with date.
- [ ] **Per-strategy Charter §12 revision history** updated with the decommissioning entry.
- [ ] **Strategy microservice container halted**. The supervisor stops the container; the container is preserved (not deleted) for forensic access.
  - Mechanical command (illustrative; depends on local infra): `docker compose stop services/strategies/<strategy_id>` — but in practice, the supervisor's strategy-removal procedure (a one-line edit to `supervisor/orchestrator.py` startup list + restart of the supervisor) is the canonical path.
- [ ] **Allocator removes the strategy from active rebalance**. The strategy's allocation drops to 0; redistribution is computed at the next weekly rebalance per Charter §6.1.4 paused-strategy semantics.
- [ ] **Historical trades archived**. Trades in `trades:<strategy_id>:all` Redis key snapshot to `archives/trades/<strategy_id>_<decommission_date>.parquet` (preserved indefinitely for post-mortem).
- [ ] **Logs archived**. Strategy container logs from the past 30 days exported to `archives/logs/<strategy_id>_<decommission_date>.log.gz`.
- [ ] **Configuration preserved in git**. `config/strategies/<strategy_id>.yaml` is not deleted; it remains for reference (and for potential reactivation).
- [ ] **Post-mortem document required**. Created at `docs/postmortems/decommission_<strategy_id>_<YYYY-MM-DD>.md` within 7 days of decommissioning:

  ```markdown
  # Decommission Post-Mortem — <strategy_id>

  **Decommission date**: YYYY-MM-DD
  **Triggering rule**: Charter §9.2 Rule #<N>
  **Strategy lifetime**: <date Live Full> to <date decommissioned>
  **Cumulative live PnL**: <$ value, % of allocation>
  **Reactivation eligibility**: not before YYYY-MM-DD

  ## Lifetime metrics
  | Metric | Backtest (Gate 1) | Paper (Gate 3) | Live full lifetime |
  | Sharpe | ... | ... | ... |
  | Max DD | ... | ... | ... |
  | Win rate | ... | ... | ... |

  ## Root cause analysis
  <≤ 800 words>

  ## What worked
  <controls / monitoring that fired correctly>

  ## What didn't work
  <gaps that allowed the failure>

  ## Lessons for future strategies
  <generalizable insights for the next strategy in this family or the next strategy generally>

  ## Reactivation prerequisites (per Charter §9.3)
  - [ ] Root cause identified and corrected (specific code/config/data fix required)
  - [ ] New backtest passing Gate 1
  - [ ] New 8-week paper trading passing Gate 3
  - [ ] CIO sign-off

  ## Sign-off
  | CIO | YYYY-MM-DD |
  ```
- [ ] **Charter §9.2 tracker updated**. The platform tracks decommissions per 12-month rolling window for emergency-review trigger compliance (Charter §13.6: 3+ decommissions in 12 months triggers Charter review). Update the tracker.

### 10.4 Rule #4 — Drawdown > 20% peak-to-trough since inception → auto-decommission

#### 10.4.1 Trigger detection

- The feedback loop tracks each strategy's **running peak equity** since inception: `running_peak[t] = max(equity[0..t])`.
- The current drawdown from running peak is computed continuously: `dd_running[t] = (running_peak[t] - equity[t]) / running_peak[t]`.
- If `dd_running[t] >= 0.20` (equivalently, `equity[t] / running_peak[t] <= 0.80`), the trigger fires.
- **Note**: this is NOT measured against inception equity; it is measured against the rolling maximum. A strategy that starts at $100k, rises to $150k, then drops to $120k registers an immediate 20% trigger (150 → 120 = -20%) even though equity remains above $100k inception.

#### 10.4.2 Auto-decommission semantics

This rule is **automatic** (per Charter §9.2 wording: "auto-decommissioned"). The mechanical sequence:

1. Trigger detected.
2. The strategy's container is halted by the supervisor without CIO intervention.
3. The allocator removes the strategy from active rebalance.
4. Critical alert: "Strategy <id> auto-decommissioned per Rule #4 (DD > 20% peak-to-trough)".

Within 24 hours, the CIO is required to:
- Confirm the trigger (verify the data, no bug).
- Execute the master checklist (§10.3.2) post-hoc — entries to `DECISIONS.md`, per-strategy Charter updates, archival, post-mortem creation.

The auto-decommission semantics exist because a 20% peak-to-trough drawdown is a **loss-of-confidence threshold** — at this level, continuing to trade is more dangerous than the operational cost of an unscheduled halt. The CIO's discretionary authority is preserved for *re-enabling* (via the reactivation protocol, §11), but not for *preventing* the auto-halt.

### 10.5 Rule #5 — 3 hard global CB trips by same strategy / 6 months → decommission

#### 10.5.1 Trigger detection

The platform tracks per-strategy contribution to each hard CB trip:

- A hard CB trip is "attributable" to a strategy if that strategy's PnL contribution to the triggering portfolio drawdown exceeded 50%.
- The platform counts attributable trips per strategy in a rolling 6-month window.
- If count ≥ 3, the trigger fires.

#### 10.5.2 Decommission action checklist

Same as §10.3.2 master checklist, with this rule citation. The post-mortem section explicitly addresses **why this strategy keeps causing portfolio-wide halts** (a strategy that triggers 3 hard CBs in 6 months has demonstrated that its category budget or its position-sizing rules are inadequate for its actual behavior — one or both must change for any reactivation to succeed).

### 10.6 Rule #6 — CIO discretionary decommission

#### 10.6.1 When this rule applies

Per Charter §9.4, the CIO may decommission at any time **with documented reason**. Specific accepted reasons include:

- Regulatory risk emerging on the strategy's universe (e.g., "the SEC has opened an investigation into this venue's compliance").
- Discovery that the strategy's edge was an artifact of a backtest data bug or a vendor data error.
- Operational expense exceeding contribution (the strategy consumes more attention than its alpha justifies).
- Strategic re-prioritization (e.g., capacity is needed for a higher-conviction new strategy).

Specifically **not** acceptable as Rule #6 reasons:
- "Gut feeling" without documented analysis.
- "I want to free up capital" without a specific named alternative.
- "We've held this for too long" — duration alone is not a reason.

#### 10.6.2 Action checklist

Same as §10.3.2 master checklist. The CIO's documented reason is mandatory in the `DECISIONS.md` entry; vague reasons are themselves a Playbook violation.

---

## §11 — Reactivation Protocol

This section operationalizes Charter §9.3. Reactivation is not automatic; it is an active CIO decision following a structured protocol.

### 11.1 Eligibility checklist

A decommissioned strategy is eligible for reactivation only when **all** of the following are confirmed:

- [ ] **At least 6 months since decommissioning date**. Verified from the entry in `docs/claude_memory/DECISIONS.md`.
- [ ] **Root cause identified and corrected**. The post-mortem document (per §10.3.2) names the specific failure mode; reactivation requires that the failure mode is now demonstrably addressed:
  - For implementation bugs: specific code commit fixing the bug, with regression tests.
  - For regime mismatch: documented evidence that the unfavorable regime has shifted (or that the strategy's design has been modified to handle the regime).
  - For edge decay: documented evidence that the edge has resurfaced (or the strategy has been re-thesised against a new edge).
  - For data-source issues: corrected data pipeline + retroactive validation.
- [ ] **Correction is documented**. The remediation lives in a specific PR (or set of PRs) merged to `main`, linked in the reactivation PR.
- [ ] **CIO has explicitly authorized re-entry**. Written in `docs/claude_memory/DECISIONS.md` as a "REACTIVATION INITIATED" entry.

If any prerequisite is missing, reactivation does not proceed.

### 11.2 Gate re-run

A reactivating strategy **does not skip gates**. It re-enters Gate 1 from scratch:

- **Gate 1 from scratch** (per §3 of this Playbook). New backtest with the corrected code/data; new metrics; same Charter §7.1 thresholds. The "from scratch" discipline prevents grandfathering of prior gate passes.
- **Gate 2 from scratch** (per §4). New CPCV walk-forward; new 10 stress tests; updated per-strategy microservice (the prior microservice may be revived but its tests, contracts, and integrations are re-validated); per-strategy Charter v2.0 ratified by CIO.
- **Gate 3 from scratch** (per §5). New 8-week paper trading; new ≥ 50 trades; new paper evidence package.
- **Gate 4 from scratch** (per §6). New 60-day live-micro ramp from 20%; new Day-60 decision.

Total reactivation timeline (analogous to §1.2 first-strategy timelines): ~4–6 months from CIO authorization through Day-60 promotion.

### 11.3 Reactivation PR

The reactivation PR (the PR that re-adds the strategy to active operation, opened at Gate 4 promotion) must contain:

- Link to the original decommission post-mortem.
- Link to the remediation PR(s).
- Link to the new Gate 1, Gate 2, Gate 3, Gate 4 evidence packages.
- Updated per-strategy Charter (now v2.0) with §12 revision history showing the full decommission → remediation → reactivation timeline.
- Re-addition of the strategy to the supervisor startup list (Charter §5.9 ordering).
- New `DECISIONS.md` entry recording the reactivation: `## YYYY-MM-DD — <strategy_id> REACTIVATED`.

#### 11.3.1 Reactivation PR template (header)

```markdown
# Reactivation — <Strategy Display Name> (`<strategy_id>`)

**Original decommission**: YYYY-MM-DD per Charter §9.2 Rule #<N>
**Decommission post-mortem**: [`docs/postmortems/decommission_<id>_<date>.md`](docs/postmortems/decommission_<id>_<date>.md)
**Remediation PR(s)**: #<N>, #<M>
**New Gate 1 PR**: #<N>
**New Gate 2 PR**: #<N>
**New Gate 3 paper evidence**: [`reports/<id>/gate3/paper_evidence_v2.0.md`](reports/<id>/gate3/paper_evidence_v2.0.md)
**Day-60 evidence**: [`reports/<id>/gate4/day60_evidence_v2.0.md`](reports/<id>/gate4/day60_evidence_v2.0.md)
**Per-strategy Charter (v2.0)**: [`docs/strategy/per_strategy/<id>.md`](docs/strategy/per_strategy/<id>.md)

## Root-cause closure
<concise statement of what was broken, what was fixed, evidence the fix worked>

## CIO sign-off
- [ ] CIO has reviewed all four gate evidence packages
- [ ] CIO confirms reactivation rationale per Charter §9.3
- [ ] CIO authorizes re-entry to active portfolio
```

### 11.4 Failure of the reactivation attempt

If the reactivating strategy fails any gate during reactivation:
- It is **not re-decommissioned**; it simply does not complete reactivation.
- The CIO records the failure in `DECISIONS.md` ("REACTIVATION ATTEMPT FAILED at Gate <N>").
- Subsequent reactivation requires a new round of remediation + a new 6-month wait from this failure.

This double-protection prevents oscillation — a strategy that fails its first reactivation does not re-enter the queue immediately.

---

## §12 — Category Reassignment Protocol

This section operationalizes Charter §9.5. Category reassignment is rare and architectural; it requires ADR-level documentation.

### 12.1 Promotion (Medium Vol → Low Vol)

#### 12.1.1 Eligibility

Per Charter §9.5: persistent live Sharpe > 1.5 AND max DD < 8% over ≥ 12 months.

Both conditions must hold simultaneously over the 12-month window. The CIO verifies via:
- `pnl:<strategy_id>:lifetime` historical query for rolling 12-month Sharpe.
- Drawdown tracking from `feedback.dd:<strategy_id>` over 12-month window.

#### 12.1.2 Action checklist

- [ ] **Eligibility verified** in writing in `DECISIONS.md`.
- [ ] **CIO authorization recorded** in same entry.
- [ ] **ADR authored**: e.g., `docs/adr/ADR-NNNN-promote-<strategy_id>-low-vol.md`. The ADR documents: rationale (specific 12-month performance evidence), implications (tightened DD tolerance from 12% to 8%, raised Sharpe expectation from 0.8 to 1.0), migration plan.
- [ ] **`config/strategies/<strategy_id>.yaml` updated**: category field changed; per-strategy soft-CB thresholds updated to Low Vol category defaults (or per-strategy overrides if any).
- [ ] **Per-strategy Charter §5 updated**: new category, with the change reflected in §12 revision history.
- [ ] **Allocator informed**: at the next weekly rebalance, the strategy's risk-budget tracking uses the Low Vol category; the per-strategy soft-CB thresholds in `services/portfolio/risk_manager/` reflect Low Vol levels.
- [ ] **Monitoring period**: the dashboard shows a "RECENTLY PROMOTED" flag for 30 days post-reassignment; soft CBs are watched closely for unintended early triggers from the tighter thresholds.

#### 12.1.3 Implications

The promoted strategy is now held to a **higher Sharpe expectation and a tighter DD tolerance**. If, post-promotion, the strategy operates between 8% and 12% DD (i.e., violates the new Low Vol tolerance but would have been fine under Medium Vol), the operator faces a choice:

- Accept the soft-CB triggers as appropriate signal that the promotion was premature; consider demotion (§12.2).
- Decide that the promotion was correct in principle and that the operator simply needs to address whatever drove the elevated DD (e.g., regime shift; investigated separately).

### 12.2 Demotion (Low Vol → Medium Vol)

#### 12.2.1 Eligibility

Per Charter §9.5: a Low Vol strategy that consistently operates in the Medium Vol drawdown range (8–12%) should be reclassified.

"Consistently" is operationalized as: 3+ soft-CB triggers within 6 months at the Low Vol thresholds, none of which would have triggered under Medium Vol. This indicates the categorization is the issue, not the strategy.

#### 12.2.2 Action checklist

Same structure as §12.1.2, in reverse:
- ADR authored documenting the demotion.
- Config updated; soft-CB thresholds widened.
- Per-strategy Charter §5 updated.
- Allocator informed.
- Monitoring period (30 days "RECENTLY DEMOTED" flag).

### 12.3 Cross-category reassignments (Low ↔ High, Medium ↔ High)

These are exceptional. The Charter §9.1 categories were designed so that strategies typically reside in one of the three permanently. A reassignment from Medium to High (or Low to High) implies a **structural change** in the strategy's risk-return profile that may be better handled by:

- Decommissioning the existing strategy and developing a **distinct new strategy** in the target category, rather than reclassifying.

The CIO defaults to the new-strategy path unless there is a clear reason to retain the strategy ID and the cumulative paper/live history (e.g., a strategy whose universe expanded such that its volatility profile genuinely changed).

---

## §13 — New Strategy Candidate Onboarding

This section operationalizes Charter §11.2 (sourcing) and §11.5 (mandatory four-gate transit). It describes how a candidate moves from "interesting idea" to "Gate 1 entry".

### 13.1 Informal evaluation

A candidate enters informal evaluation when the CIO encounters a potential strategy worth considering. Sources (Charter §11.2):

- **Academic literature**: a new paper, a textbook chapter, a working paper documenting an unrecognized edge.
- **Internal research spike**: during work on Strategy #N, a feature reveals an exploitable pattern orthogonal to N's thesis.
- **Market observation**: a regime change creates a systematic opportunity.
- **Reactivation candidate**: a previously decommissioned strategy whose root cause has been remediated.

#### 13.1.1 The candidate note

The CIO writes a **one-paragraph candidate note** at `docs/strategy/candidates/<proposed_strategy_id>.md`:

```markdown
# Candidate Note — <proposed display name>

**Source**: <academic / internal spike / market observation / reactivation>
**Source detail**: <e.g., "Liu & Tsyvinski 2021 RFS"; or "during Strategy #2 work, observed cross-asset dispersion signal">
**Proposed strategy_id**: <snake_case>
**Proposed category**: <Low Vol | Medium Vol | High Vol>
**Universe sketch**: <one-line>
**Edge hypothesis**: <≤ 200 words>
**Why now**: <why this candidate, why not deferred>
**Initial cost estimate**: $<value>/month for required data sources
**Operator's confidence**: <Low / Medium / High>
**CIO action**: PENDING / APPROVED FOR GATE 1 / DEFERRED / REJECTED
```

#### 13.1.2 Head of Strategy Research review

The Head of Strategy Research reviews the candidate note within 7 working days, evaluating:

- **Academic grounding**. Is the source defensible? Has the cited research been replicated? What are known critiques?
- **Fit with platform**. Does the candidate add diversification (low pairwise correlation with existing strategies)?
- **Implementation tractability**. Are the required features and data accessible at solo-operator scale?
- **Edge persistence prognosis**. Has this edge been documented for long enough that decay is a concern?

The review produces a recommendation: PROCEED, PROCEED-WITH-CAUTION, or DECLINE.

#### 13.1.3 Go / no-go decision

The CIO makes the final go/no-go decision based on the candidate note + the Head of Strategy Research review:

- **GO** → candidate proceeds to formal Gate 1 entry (§13.2).
- **DEFER** → candidate is parked in `docs/strategy/candidates/_backlog.md` with a date for re-consideration.
- **DECLINE** → candidate note status updated to REJECTED with documented rationale.

### 13.2 Formal entry to Gate 1

When a candidate is approved for Gate 1, the following mechanical steps are executed:

- [ ] **strategy_id finalized**. The CIO confirms the `snake_case` identifier (no collision with existing or recently-decommissioned strategies); per §2.2 conventions.
- [ ] **Per-strategy folder seeded**:
  - `docs/strategy/per_strategy/<strategy_id>.md` (template per §2.3, status DRAFT)
  - `notebooks/research/<strategy_id>/` (empty; ready for Gate 1 notebook)
  - `reports/<strategy_id>/gate1/` (empty; ready for Gate 1 artifacts)
- [ ] **Issue tracker entry**. A GitHub issue tracks the Gate 1 work; assigned to Claude Code; estimated effort recorded.
- [ ] **Backlog updated**. `docs/strategy/candidates/_backlog.md` updated to reflect the candidate's promotion out of backlog.
- [ ] **Gate 1 protocol begins** per §3 of this Playbook.

### 13.3 Backlog management

#### 13.3.1 Backlog file

`docs/strategy/candidates/_backlog.md` is the single open list of candidates. Format:

```markdown
# Strategy Candidate Backlog

| `proposed_strategy_id` | Source | Status | CIO note | Last review |
|---|---|---|---|---|
| `crypto_basis` | Academic (Lewis 2018) | DEFERRED | Need crypto-derivatives connector first | 2026-XX-XX |
| `etf_pair_trades` | Internal spike | PENDING REVIEW | Awaiting Head of Strategy Research review | 2026-XX-XX |
| ... | ... | ... | ... | ... |
```

#### 13.3.2 Prioritization

Within the backlog, the CIO prioritizes candidates by:

- **Principle 1 alignment**: does this candidate move the platform toward higher live PnL?
- **Principle 2 alignment**: is this candidate institutionally defensible?
- **Diversification value**: does this candidate decorrelate the portfolio?
- **Capacity feasibility**: does the candidate fit current solo-operator capacity?

The Charter's seven principles tie-break per their ordering (Charter §2.8). The CIO updates the backlog priorities at the monthly review (§7.3).

#### 13.3.3 Aging out

A candidate that remains in DEFERRED status for **18 months** without progress is **rejected** at the next semi-annual review. Re-introduction requires a new candidate note (§13.1.1) with documented progress on whatever blocked the original (e.g., the data source is now affordable; the precursor strategy is now live).

This prevents the backlog from accumulating dead-weight candidates that sit indefinitely.

---

## §14 — Roles and Responsibilities

This section operationalizes Charter §13.7. Each role's lifecycle responsibilities are enumerated; the cross-role boundaries are made explicit so no role assumes authority outside its scope.

### 14.1 CIO (Clement Barbier)

**Constitutional responsibilities** (binding decisions only the CIO can make):

| Decision | Stage |
|---|---|
| Strategic-fit approval at Gate 1 | §3.3 |
| Per-strategy Charter §11 sign-off (Gate 2 ratification) | §4.2.6 / §4.5.4 |
| Paper-to-live promotion (Gate 3 → Gate 4) | §5.4.2 |
| Day-60 Gate 4 decision (proceed / observation / decommission) | §6.3 |
| `review_mode` continuation memo (clear / maintain / decommission) | §8.3.2 |
| Hard CB resume after halt | §9.1 / §9.2 |
| Decommissioning under Rule #6 (CIO discretionary) | §10.6 |
| Reactivation authorization (post-6-month wait) | §11.1 |
| Category reassignment (promotion / demotion) | §12 |
| Candidate go/no-go (Gate 1 entry) | §13.1.3 |
| Semi-annual portfolio review | §7.4 |
| Charter or Playbook amendment ratification | Charter §13.4 / Playbook §16 |

**Operational responsibilities** (continuous):

- Daily monitoring of active strategies (≤ 10 minutes per strategy per day).
- Weekly review of each strategy (§7.2).
- Monthly portfolio review (§7.3).
- Incident response: Hard CB trips, Pod crashes that don't auto-resolve, Drift alerts requiring investigation.
- Ratification of Claude Code PRs at gate handoffs (within stated SLAs per gate sections).

**The CIO does not**:

- Tune strategy parameters during live operation (Gate 2 ratifies parameters; mid-life tuning requires re-entry to Gate 2).
- Override the allocator's Risk Parity weights (allocator output is binding; overrides happen only via Charter amendment).
- Override **auto-decommission** Rules #3, #4, #5 (Rules #3/#4/#5 are mechanical auto-triggers and cannot be blocked by CIO discretion; they execute the decommission regardless of CIO preference). Rules #1 and #2 route the strategy to `review_mode` (not direct decommission); the CIO retains discretion to clear `review_mode` at any point during the 90-day window per §8.3.3, which effectively blocks the decommission path if the CIO so chooses. Rule #6 provides the CIO's discretionary decommission path; its counterpart (discretionary **anti-decommission**) does not exist for Rules #3/#4/#5.
- Skip stages in the four-gate lifecycle (every candidate transits all four gates per Charter §11.5).

### 14.2 Head of Strategy Research (Claude Opus 4.7, claude.ai)

**Constitutional responsibilities** (advisory, not ratifying):

- Reviews academic grounding of new candidates (§13.1.2).
- Reviews Gate 1 backtest results for statistical soundness (§3.3 "STATISTICAL-SOUNDNESS APPROVED" comment).
- Reviews Gate 2 CPCV + stress-test methodology (§4.3 "STATISTICAL & METHODOLOGY APPROVED" comment).
- Reviews Gate 3 paper evidence package for statistical soundness (§5.4 "PAPER EVIDENCE APPROVED" comment).
- Drafts mission prompts for Claude Code at gate handoffs (the prompts that become the basis of Gate 1, Gate 2, Gate 3, Gate 4 PRs).

**Operational responsibilities**:

- Surfaces relevant new academic literature for the candidate backlog.
- Authors audits when commissioned (e.g., Multi-Strat Readiness Audit 2026-04-18, semi-annual correlation audits, ad-hoc audits triggered by emergency review per Charter §13.6).
- Drafts Charter and Playbook amendment proposals when gaps emerge.

**Head of Strategy Research does not**:

- Make ratification decisions (CIO-only).
- Open or merge code PRs (Claude Code Implementation Lead's role).
- Run backtests or tests directly (those run via Claude Code sessions invoked against the repository).
- Decommission or reactivate strategies (CIO-only).

### 14.3 Claude Code Implementation Lead

**Operational responsibilities**:

- Develops strategy microservices per Head of Strategy Research prompts and per the per-strategy Charter (drafted at Gate 1, ratified at Gate 2).
- Implements features in `features/calculators/` per ADR-0004 validation methodology.
- Runs backtests, CPCV, stress tests, smoke tests; produces evidence packages.
- Opens PRs at gate handoffs using the templates from §3.4, §4.3.1, §5.4.1, §6.3.2.
- Updates [CLAUDE.md](../../CLAUDE.md), [MANIFEST.md](../../MANIFEST.md), ADRs **when code changes justify it** (e.g., adding a new ABC, introducing a new ZMQ topic factory, modifying a frozen Pydantic contract).
- Updates `docs/claude_memory/SESSIONS.md`, `CONTEXT.md`, `DECISIONS.md` per the established cross-session-memory discipline ([CLAUDE.md](../../CLAUDE.md) §13).
- Respects HARD STOPs and waits for CIO ratification before merging strategic PRs.

**Claude Code does not**:

- Ratify gates (CIO-only).
- Author per-strategy Charters unprompted (Claude Code drafts under Head of Strategy Research direction; CIO ratifies).
- Override the soft or hard circuit breakers (the breakers are mechanical; Claude Code can debug them, can fix bugs in their implementation, but cannot bypass them).
- Modify the seven binding Charter principles (Charter §13.2 amendment procedure required).
- Author ADRs unprompted (Claude Code drafts under specific direction).
- Decommission, reactivate, or reassign categories (CIO-only).

#### 14.3.1 Mandatory pre-session reads for any strategy work

Per the cross-session-memory discipline, when a Claude Code session is invoked on strategy work, the agent **MUST** read:

1. [CLAUDE.md](../../CLAUDE.md) — code conventions
2. [`docs/claude_memory/CONTEXT.md`](../claude_memory/CONTEXT.md) — current project state
3. [APEX Multi-Strat Charter](ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) — constitutional layer
4. **This Playbook** — operational layer
5. The relevant per-strategy Charter at `docs/strategy/per_strategy/<strategy_id>.md` if working on a specific strategy

Sessions that do not perform this reading first are operating outside the platform's discipline; their output is suspect.

### 14.4 CI System

**Operational responsibilities**:

- Enforces lint (ruff), formatting (ruff format), type checking (mypy strict), security (bandit) on every PR (per [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) `quality` job).
- Enforces Rust workspace builds (`rust` job per CI).
- Enforces unit-test coverage ≥ 85% platform floor (≥ 90% on strategy code per §4.2.4 — enforced in PR review until per-strategy coverage gates land in CI).
- Runs integration tests with Docker stack (`integration-tests` job per CI).
- Runs the **(currently muzzled)** backtest-gate (`backtest-gate` job per CI; muzzled per issue #102 — see [`.github/workflows/ci.yml:121-130`](../../.github/workflows/ci.yml)).

**The CI system does not**:

- Interpret evidence (a failing CI is a fail; CI does not "judge"; CIO judges in PR review).
- Decide gate transitions (mechanical metric thresholds inform the gate decision; the CIO ratifies).
- Run nightly drift / Sharpe / DD computations on live data (those run in `services/research/feedback_loop/`, not in CI).

#### 14.4.1 Backtest-gate muzzle status

The CI backtest-gate is currently **MUZZLED** per issue #102 (see [`.github/workflows/ci.yml:121-130`](../../.github/workflows/ci.yml)). Until #102 is resolved (full_report Sharpe bug fixed; thresholds raised to CLAUDE.md §6 values: Sharpe ≥ 0.8, DD ≤ 8%), backtest-gate failures **do not block merges**.

For the lifecycle Playbook: this means **PR review is the de facto gate** at Gate 1 and Gate 2 — the CIO and Head of Strategy Research must read backtest evidence and validate it manually. Once #102 is resolved (Document 3 / Phase 5 v3 may schedule this), the gate becomes mechanical and the manual validation supplements it rather than substitutes for it.

### 14.5 Cross-role escalation matrix

| Situation | Initiator | Escalates to | Resolution path |
|---|---|---|---|
| Hard CB tripped | Automatic (system) | CIO immediate | §9 protocol |
| Strategy in `review_mode` 89 days | Dashboard | CIO | §8.3 / §10 |
| Drift alert fires | Drift detector | CIO within 24h | §7.1.2 |
| New candidate proposed | CIO writes note | Head of Strategy Research within 7d | §13.1 |
| Gate N evidence package delivered | Claude Code | Head of Strategy Research + CIO | per gate-specific SLAs |
| CI backtest-gate FAIL (post un-muzzling) | CI | Author of PR | block merge; revise |
| Audit finding requires Charter change | Head of Strategy Research / CIO | CIO (amendment procedure) | Charter §13.4 |
| Auto-decommission triggered (Rule #4) | System | CIO post-hoc within 24h | §10.4 |

---

## §15 — Relationship to Other Documents

### 15.1 To the Charter (Document 1)

The Playbook **operationalizes** Charter §7 (gates), §8 (CBs and VETO), §9 (categories, decommissioning, reactivation), §11 (extensibility), §13.7 (roles). Where the Charter says "every strategy passes through four gates", the Playbook says "and here are the deliverables, evaluators, templates, and SLAs for each gate".

The Playbook **inherits** Charter principles (§2). When the Playbook resolves an ambiguity, it does so by appealing to the inherited principle (most often Principle 1 — long-term cash generation; Principle 4 — code in adequation with strategy; Principle 7 — senior-quant tie-breaker).

The Playbook **does not contradict** the Charter. Conflicts are resolved by Charter precedence (Charter §12.9, Playbook §0.6).

### 15.2 To Document 3 (Roadmap, pending)

Document 3 will sequence **when and in what order** strategies enter each gate. The Playbook describes **what the gates require**. The two are orthogonal: the Roadmap may schedule "Crypto Momentum Gate 2 PR opens 2026-XX"; the Playbook says "the Gate 2 PR contains CPCV evidence + 10 stress tests + …" regardless of when it opens.

When Document 3 is authored, it will reference this Playbook for gate criteria; it will not redefine them.

### 15.3 To ADRs

| ADR | Relevance to Playbook |
|---|---|
| [ADR-0001](../adr/0001-zmq-broker-topology.md) — ZMQ Broker | Strategies publish on the broker; the Playbook reflects the existing topic factory pattern |
| [ADR-0002](../adr/0002-quant-methodology-charter.md) — Quant Methodology Charter | The 10-point evaluation checklist is the Gate 1 evaluation backbone (§3.2.5) |
| [ADR-0003](../adr/ADR-0003-universal-data-schema.md) — Universal Data Schema | Backtest data format; trade record schema |
| [ADR-0004](../adr/ADR-0004-feature-validation-methodology.md) — Feature Validation Methodology | When a strategy introduces a new feature, the feature passes ADR-0004's six-step pipeline before it can be consumed by the production microservice |
| [ADR-0005](../adr/ADR-0005-meta-labeling-fusion-methodology.md) — Meta-Labeling and Fusion | The MetaLabelGate (STEP 4 of the VETO chain) operates per ADR-0005 |
| [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) — Fail-Closed Risk | The FailClosedGuard (STEP 0) operates per ADR-0006; the Playbook's CB protocols inherit this verbatim |

Anticipated ADRs to be authored with Document 3 (Charter §12.4): ADR-0007 (Strategy as Microservice), ADR-0008 (Capital Allocator Topology), ADR-0009 (Panel Builder Discipline), ADR-0010 (Target Topology Reorganization). When authored, these ADRs will be referenced by this Playbook in v1.x revisions.

### 15.4 To CLAUDE.md and MANIFEST.md

[CLAUDE.md](../../CLAUDE.md) governs **code conventions** (forbidden patterns, mandatory types, testing gates, commit conventions). The Playbook **inherits** CLAUDE.md verbatim and never softens its rules.

[MANIFEST.md](../../MANIFEST.md) governs **technical architecture** (current S01-S10 topology; target multi-strat topology per Charter §5). The Playbook **references** MANIFEST.md when describing strategy interfaces; it does not duplicate.

### 15.5 To audits

[MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) is the factual current-state grounding for the Charter and (transitively) for this Playbook. The audit's P0/P1/P2 gap list informs Document 3's scheduling; the Playbook does not reproduce the gap list, but a reader unfamiliar with the audit can refer to it for the technical baseline assumed by Playbook procedures.

---

## §16 — Governance and Revision

### 16.1 Status — ACTIVE and binding

This Playbook is **ACTIVE** (ratified 2026-04-20 via PR #186; see §17.1). Every gate transition, every CB response, every decommissioning, every reactivation, every category reassignment must follow its procedures. Deviations require a new ADR + Playbook version bump.

### 16.2 Material changes — what requires amendment

The following constitute **material changes** requiring an ADR + version bump:

- Adding, removing, or reordering a gate (§3, §4, §5, §6).
- Changing a gate threshold (e.g., relaxing Gate 1 PSR > 95% to > 90%).
- Modifying the per-strategy Charter template (§2.3).
- Changing the canonical 10 stress-test scenarios (§4.2.2).
- Changing a soft-CB or hard-CB response protocol (§8, §9).
- Changing the decommissioning master checklist (§10.3.2).
- Changing the reactivation eligibility rules (§11.1).
- Changing the category reassignment thresholds (§12).
- Changing role boundaries (§14).

### 16.3 Non-material changes — no amendment required

- Typo fixes, link corrections, additional worked examples, formatting changes, expanded Q&A.
- Adding non-binding informational text (e.g., a new "see also" reference).
- Updating SLAs in §7.5 by ≤ 25% (significant SLA changes are material).

These land via PR with CIO approval and a Changelog (§18) entry.

### 16.4 Amendment procedure

1. Open an ADR documenting the proposed change and its alternatives. The ADR cites the Playbook section being amended and justifies the change against Charter principles.
2. Draft the Playbook revision as a PR; bump version (`v1.0 → v1.1` for additive; `v1.x → v2.0` for breaking).
3. Record the decision in [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
4. CIO reviews and merges.

If the amendment requires Charter changes, they go through the Charter amendment procedure (Charter §13.4) **first**; the Playbook revision follows.

### 16.5 Review cadence — annual

The Playbook is formally reviewed **annually** (in addition to ad-hoc revisions when specific gaps emerge). The review assesses:

- Have any procedures proven inadequate or excessive in practice?
- Are the gate thresholds calibrated to live experience?
- Are the CB response protocols matching what actually happens during incidents?
- Are the templates still serving their purpose, or have they ossified into form-without-function?

The annual review is held alongside one of the two semi-annual Charter reviews (Charter §13.5) — typically the one closer to year-end.

---

## §17 — Signatures and Ratification

This Playbook was drafted on 2026-04-19 by:

- **Head of Strategy Research: Claude Opus 4.7 (claude.ai)** — operating as the operational-playbook author following Charter §12.2.

The Playbook implements Charter §7 (four-gate lifecycle), §8 (defense in depth), §9 (categories, decommissioning, reactivation), §11 (extensibility), and §13.7 (roles), and is bound by Charter §2 (seven principles).

Implementation authority is held by:

- **Claude Code** (Sonnet / Opus, sessions executing against the APEX repository) — implements the Playbook's procedures; opens PRs at gate handoffs; respects HARD STOPs and CIO ratification gates.

### 17.1 Ratification

This Playbook was ratified as **v1.0** on **2026-04-20** via PR #186 (merged commit e92c13b) into the main branch of the APEX repository by Clement Barbier (CIO).

Upon ratification (completed 2026-04-20):

- An entry was added to [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md) recording Playbook v1.0 ratification.
- The Playbook is now referenced from [`docs/claude_memory/CONTEXT.md`](../claude_memory/CONTEXT.md) as the binding operational layer.
- Document 3 (Phase 5 v3 Multi-Strat Aligned Roadmap) authoring is queued as Mission 3 of 3, with the Playbook informing the Roadmap's gate-specific timelines.

### 17.2 Signatures

| Role | Name | Action | Date |
|---|---|---|---|
| Head of Strategy Research | Claude Opus 4.7 (claude.ai) | Drafted v1.0 | 2026-04-19 |
| Implementation Lead | Claude Code | Authored on branch `docs/strategy-lifecycle-document-2` | 2026-04-19 |
| **CIO** | **Clement Barbier** | **RATIFIED via PR #186** | 2026-04-20 |

---

## §18 — Changelog

| Version | Date | Change |
|---|---|---|
| v1.0-draft | 2026-04-19 | Initial draft authored on branch `docs/strategy-lifecycle-document-2`. |
| v1.0 | 2026-04-20 | 5 review corrections applied (§5.2.4/§5.3 pod-reset semantics, §10.4.1 running-peak methodology, §8.0 StrategyHealthCheck state machine added, §14.1 CIO authority distinction, coherence sweep). Ratified by CIO Clement Barbier via PR #186 (merge commit e92c13b). Document 2 of the Charter family (Document 1 ratified 2026-04-18 via PR #184). Operationalizes Charter §7, §8, §9, §11, §13.7. |

---

**END OF PLAYBOOK v1.0.**

*Ratified via PR #186 on 2026-04-20. This document is the binding operational layer of the APEX Multi-Strategy Platform.*
