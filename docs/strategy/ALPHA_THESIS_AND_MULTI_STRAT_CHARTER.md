# APEX Multi-Strategy Platform — Alpha Thesis and Charter

**Document 1 of 3** (constitutional layer)
**Version**: v1.0 (DRAFT — awaiting CIO ratification)
**Status**: ACTIVE once merged
**Ratification date (proposed)**: 2026-04-18
**Last updated**: 2026-04-19
**Supersedes**: None (this is the founding constitutional document of the multi-strategy platform)
**Binding authority**: Every engineering, research, and deployment decision taken on the APEX platform is bound by the principles and rules in this Charter. Deviations require a new ADR and a version bump of this document.

---

## §0 — Preamble and Scope

### 0.1 Purpose

This document is the **Charter** of the APEX multi-strategy quantitative trading platform. It codifies, for the next 12 to 24 months of development, the vision, the seven binding principles, the architectural foundations, the capital allocation framework, the strategy lifecycle, the defense-in-depth risk model, the performance budgets, and the benchmarks against which the platform and its strategies will be judged.

It is not a technical specification. It is not an implementation plan. It is the **constitutional layer** that all specifications and plans must remain consistent with. Phase specs, ADRs, and operational runbooks inherit their authority from this Charter and must cite it when introducing material change.

### 0.2 Audience

The Charter is written for two audiences that must remain aligned across time and across sessions:

1. **Clement Barbier**, founder and sole operator, acting in the capacity of **Chief Investment Officer** of the APEX platform. The Charter is his written articulation of what the platform is, what it is not, and how strategies will be built, deployed, monitored, and retired.

2. **Every future Claude Code agent** invoked on this repository. The Charter is the single file that, read at the start of any session, provides complete context on the strategic direction of the platform. When conflicts arise between short-term convenience and long-term Charter intent, the Charter prevails.

It is explicitly **not** an external investor document, not a marketing brief, and not a pitch deck. It is an internal, binding, technical-strategic charter written in the tone and register of a founding document at a multi-strategy quantitative firm.

### 0.3 Relationship to the rest of the documentation corpus

The APEX documentation corpus is layered. This Charter sits at the top.

| Layer | Purpose | Example |
|---|---|---|
| **Charter** (this document) | What and why — the constitutional layer | `docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md` |
| **Lifecycle Playbook** (Doc 2, pending) | How — operational playbook for building, testing, deploying, retiring a strategy | `docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md` (to be written) |
| **Roadmap** (Doc 3, pending) | When and in what order — current execution plan | `docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md` (to be written) |
| **ADRs** | Binding architectural decisions — irreversible without supersession | `docs/adr/ADR-XXXX-*.md` |
| **Phase specs** | Scope of a specific execution phase | `docs/phases/PHASE_5_SPEC_v2.md` |
| **Audits** | Read-only evidence gathered at a point in time | `docs/audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md` |
| **Claude memory** | Persistent cross-session notes | `docs/claude_memory/CONTEXT.md` |
| **MANIFEST.md** | Technical source of truth for architecture and data models | [MANIFEST.md](../../MANIFEST.md) |
| **CLAUDE.md** | Non-negotiable development conventions | [CLAUDE.md](../../CLAUDE.md) |

The Charter does not duplicate content in these files; it references them. Where the Charter and another document conflict, the Charter prevails until superseded by a new ADR.

### 0.4 Status and revision model

The Charter is **versioned**. Any material change — the introduction of a new binding principle, a change to the list of boot strategies, a modification of the capital allocation framework, an addition or removal of a circuit-breaker tier, a change to the decommissioning rules — requires:

1. A new ADR documenting the rationale for the change and its alternatives.
2. A version bump of this Charter (`v1.0 → v1.1` for additive clarifications, `v1.x → v2.0` for breaking changes).
3. An entry in [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
4. A pull request reviewed by the CIO before merge.

Cosmetic edits (typo fixes, clarifications that do not alter meaning) may be landed without version bump, but the change log at the bottom of this document must be updated.

### 0.5 Scope — what the Charter governs, and what it does not

The Charter governs:

- The vision and strategic objectives of the APEX multi-strategy platform.
- The seven binding principles that break ties on every downstream decision.
- The architectural foundations of the multi-strategy topology (microservice-per-strategy, dedicated allocator, panel builder).
- The six boot strategies — their theses, universes, edge mechanisms, budget categories, and deployment order.
- The capital allocation framework (Phase 1 Risk Parity → Phase 2 Sharpe overlay).
- The four validation gates that govern strategy progression (Research → Backtest → Paper → Live Micro → Live Full).
- The two-tier circuit breaker model and the seven-step VETO Chain of Responsibility.
- The three risk/performance categories (Low Vol / Medium Vol / High Vol) and the tolerant decommissioning rules.
- The three-level benchmark ladder (Survival / Legitimacy / Institutional).
- The extensibility principle — the backlog is open; new strategies may be added at any time following the lifecycle.
- The governance model — who may change what, when, and how.

The Charter does **not** govern:

- Detailed implementation (belongs in phase specs, not here).
- Specific ZMQ topic names or Redis keys beyond architectural shape (belongs in `core/topics.py` and the relevant service spec).
- Individual strategy tuning parameters (belongs in `config/strategies/{strat_id}.yaml` once that mechanism lands — see §5.5).
- Code conventions (those are locked in [CLAUDE.md](../../CLAUDE.md) and are inherited, not restated, here).
- Operational runbooks for on-call responses (belong in a future `docs/runbooks/` tree).

If an implementation question cannot be answered from the Charter, it is **by design** delegated to a lower document. The Charter stays thin on the *how* and hard on the *what* and *why*.

---

## §1 — Vision and Strategic Objectives

### 1.1 What APEX is

APEX is an **autonomous, multi-strategy, institutional-grade quantitative trading platform** built by a solo operator for personal capital, holding itself to the engineering and research standards of the industry's leading multi-strategy firms: **Millennium Management**, **Citadel Multi-Strategy**, **DE Shaw Composite**, **AQR Multi-Strategy Alternative**, **Man AHL**, **Two Sigma**, **Renaissance Institutional Equities**, and **Bridgewater All Weather** as the reference points for systematic, diversified, multi-bet portfolios.

Two words in that sentence carry load:

- **Multi-strategy**. APEX is not a single-signal bot wrapped in a nice UI. It is a portfolio of **independent, academically-grounded, risk-budgeted strategies**, each generating alpha from its own edge, each running in its own container, each monitored separately, and each combined at the portfolio level via a disciplined capital allocation framework.
- **Institutional-grade**. Every design decision is evaluated against the standard a senior quantitative researcher at one of the firms above would accept. Where constraints (solo dev, no Bloomberg terminal, no co-location, no paid data vendors for non-essential feeds) force compromise, the compromise is made *consciously*, documented, and replaced with the best open-source or low-cost alternative that preserves the institutional substance — never a retail shortcut in disguise.

### 1.2 Primary objective — long-term cash generation

The primary objective of APEX is **the generation of long-term, risk-adjusted cash returns on the founder's personal capital**, measurable in dollars withdrawn from the platform over years, not in backtest Sharpe ratios printed on dashboards.

This framing is deliberate. Everything downstream — strategy selection, capital allocation, circuit breakers, decommissioning rules, even the choice to run six strategies rather than one — is subordinated to this objective. A design choice that improves short-term research aesthetics at the cost of long-term compounding is a regression and will be rejected.

### 1.3 Inspirational references — "what would a senior quant at [firm] do here?"

When a design question admits more than one defensible answer, the Charter's tie-breaker is the **senior-quant test**:

> *Given the constraints of the APEX platform (solo dev, no HFT, limited data budget), what would a senior quantitative researcher at AQR, Man AHL, or Two Sigma do here?*

The firms chosen for this tie-breaker share specific traits APEX aspires to:

- **AQR Capital Management** — factor-based, academically rigorous, publishes its reasoning, disciplined about out-of-sample validation. Model for: research methodology, statistical hygiene, capital allocation frameworks (risk parity).
- **Man AHL** — systematic trend-following and multi-strategy, strong in machine-learning discipline, scientific culture. Model for: walk-forward validation, meta-labeling, drift monitoring.
- **Two Sigma** — technology-first, multi-asset, multi-signal, panel-based data representation. Model for: data architecture, panel builder pattern, feature store discipline.
- **Millennium Management** — pod-based multi-strategy, strict per-pod risk budgets, ruthless decommissioning of underperforming pods. Model for: per-strategy risk budgets, tolerant-but-firm decommissioning rules.
- **Citadel Multi-Strategy** — isolated strategy teams, centralized risk and allocation, rigorous operational discipline. Model for: microservice-per-strategy topology, centralized allocator, VETO-style risk layer.
- **DE Shaw Composite** — quantitative plus discretionary overlay, technology-heavy, long-horizon focus. Model for: balancing systematic pods with discretionary CIO overrides (decommissioning §9.3, circuit breaker §8).
- **Bridgewater All Weather** — macro-aware, regime-conditional, diversified across risk premia. Model for: regime overlays, macro catalyst handling, long-horizon capital preservation.
- **Renaissance Institutional Equities (RIEF)** — relentless empiricism, short-horizon microstructure plus longer-horizon patterns, massive statistical firepower. Model for: statistical rigor, ensemble thinking, edge decay awareness.

APEX does not claim equivalence with these firms. It claims to inherit their **standards of evidence, discipline, and humility** in the face of markets.

### 1.4 What APEX is not

- **Not a single-strategy fund.** APEX is structurally a portfolio of edges; designing as if a single strategy will carry the platform is a category error.
- **Not a high-frequency trading system.** Co-location, sub-millisecond latency, kernel-bypass networking are explicitly out of scope. The operator has no access to co-located infrastructure, and the Charter makes no pretense otherwise. APEX operates at **mid-frequency cadence**: sub-second to multi-hour decision horizons, tolerant of single-digit-millisecond end-to-end latency.
- **Not a retail bot.** APEX is not "RSI < 30 → buy"; it is not a reproduction of a YouTube strategy; it is not an algorithmic wrapper around discretionary gut feel. Retail shortcuts are explicitly forbidden (see Principle 2).
- **Not a SaaS product.** There are no external clients, no managed accounts, no third-party capital. The platform is personal infrastructure, built to institutional standards so that the single operator does not make amateur mistakes.
- **Not a macro-news-driven system.** Public macro information is already priced by the time it reaches the tape. Macro, in APEX, is a **context filter** that modulates aggressiveness, never a directional signal source.
- **Not a discretionary system.** The CIO holds discretionary overrides only at the decommissioning and emergency-halt levels (see §9.3 and §8.3). Day-to-day trading is fully systematic; there is no "I have a feeling about this" channel into live execution.

### 1.5 Target outcomes over the 12–24 month horizon

The Charter binds the platform to three measurable outcomes, aligned with the three-level benchmark ladder formalized in §10:

1. **Months 0–9 — Survival.** Execute the multi-strat infrastructure lift, develop and validate Strategy #1 (Crypto Momentum), achieve the Survival benchmark (net annualized return > 15%, Sharpe > 1.0, max DD < 15%, simultaneously) on Strategy #1 in paper trading. Avoid catastrophic engineering mistakes.
2. **Months 9–15 — Legitimacy.** Live-micro deploy Strategy #1; develop and deploy Strategy #2 (Trend Following multi-asset) through paper to live. Achieve the Legitimacy benchmark (alpha > 10% annualized vs equal-weight BTC+ETH+SPY, beta < 0.5, Sharpe > 1.5) on the combined live portfolio. Prove that the multi-strategy architecture generates measurable value beyond passive exposure.
3. **Months 15–24 — Institutional.** Live-trade at least three uncorrelated strategies under the Risk-Parity-plus-Sharpe-overlay allocator. Achieve the Institutional benchmark (net Sharpe > 2.0 over rolling 12 months, max DD < 10%, cross-strategy correlation < 0.3). Establish platform credibility such that the sixth boot strategy and any new candidates slot in without rework.

These outcomes are targets, not guarantees. Markets may not cooperate. The Charter's job is not to promise them but to **ensure that, if the edges are real, the platform converts them into compounding cash**, and that, if the edges are not real, the platform detects this cleanly and reallocates capital before damage compounds.

---

## §2 — The Seven Binding Principles

The Charter is governed by seven principles. They are **binding**: any design decision, implementation choice, or strategy deployment must be defensible under all seven. They are **ordered** — earlier principles break ties over later ones when genuine conflict arises, though conflict is rare because the principles are largely reinforcing.

Each principle is stated, motivated, and accompanied by an operational rule: *when in doubt, this principle breaks the tie by asking the following question*.

### 2.1 Principle 1 — Long-term cash generation is the goal

**Statement.** The purpose of the APEX platform is to compound the founder's personal capital over years. Every design, research, or deployment decision must be defensible against this goal.

**Motivation.** Quantitative trading is dense with local optima that look like progress but are not: chasing Sharpe in a backtest without out-of-sample validation, adding signals to a tired strategy, deploying before validation gates are passed, holding a dying strategy out of sunk-cost attachment. Principle 1 is the anchor against these drifts.

**Operational rule — the tie-breaker question.**

> *Does this decision, measured over a 12–24-month horizon, make live PnL larger or more robust? If not, it is not on the critical path.*

**Implications.**
- Research quality beats research quantity. A deeply validated strategy is worth more than three shallow ones.
- Safety infrastructure (fail-closed risk controls, drift monitoring, circuit breakers) ships **before** alpha extensions that rely on it. This is why Phase 5.5 Drift Monitoring was promoted ahead of Phase 5.4 Short-Side in the current roadmap ([PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) §3.4).
- Features designed for "future flexibility" without a concrete near-term alpha use case are deferred.

### 2.2 Principle 2 — Institutional standards over retail shortcuts

**Statement.** The platform holds itself to the standards of the leading systematic and multi-strategy firms — Renaissance, Two Sigma, Citadel, AQR, Man AHL, DE Shaw, Bridgewater, Millennium — even where the operator is solo. No retail shortcut, no heuristic substitute for rigorous statistical testing, no "it worked in the backtest" as evidence.

**Motivation.** Harvey, Liu & Zhu (2016, "…and the Cross-Section of Expected Returns") estimate that the majority of published factor research fails out-of-sample. The gap between "positive backtest" and "real edge" is where 95% of retail quantitative attempts die. The only antidote is institutional-grade methodology: PSR, DSR, PBO, CPCV walk-forward, regime-conditional validation, multiple-testing correction, meta-labeling, drift monitoring.

**Operational rule — the tie-breaker question.**

> *What would a senior researcher at AQR or Man AHL accept here? If they would push back, so must we.*

**Implications.**
- `backtesting/metrics.py:full_report` is already locked to ADR-0002's 10-point evaluation checklist (PSR, DSR, PBO, regime decomposition, cost sensitivity, turnover, capacity, slippage). See [ADR-0002](../adr/0002-quant-methodology-charter.md). No strategy advances to live without passing this checklist.
- Float arithmetic on prices, naive datetimes, `print` logging, and `except Exception: pass` are all forbidden in production code (see [CLAUDE.md](../../CLAUDE.md) §10). These are not stylistic choices; they are the **code-level expression** of institutional discipline.
- Academic references are mandatory for every new signal or strategy. If it cannot be traced to a peer-reviewed paper or an established quantitative-research lineage, it does not ship.

### 2.3 Principle 3 — Acknowledged constraints, intelligent substitutes

**Statement.** The platform operates under real constraints — one full-time developer, no access to HFT infrastructure, no institutional data vendors beyond what can be obtained free or at low cost, no back-office team. These constraints are not pretended away. Instead, the Charter commits to **intelligent substitutes** that preserve the institutional substance at accessible cost.

**Motivation.** Pretending the constraints do not exist leads to scope collapse. Accepting them as permanent inferiority leads to retail-grade output. The third way — identifying, for each institutional capability, the best open-source or low-cost equivalent — is the only viable path for a solo operator targeting institutional quality.

**Operational rule — the tie-breaker question.**

> *If we cannot afford the institutional tool, what is the best open-source or low-cost substitute that preserves the same analytical function? If no substitute exists, what smaller-scope version retains most of the value?*

**Implications.**
- **Data**: Binance WebSocket and Alpaca replace paid L2 vendors for the boot universe. GDELT 2.0 plus FinBERT replace the proprietary `WorldMonitor` gRPC spec referenced in early Phase 5 thinking ([PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) §3.6).
- **Compute**: Rust via PyO3 (`apex_mc`, `apex_risk`) delivers institutional-grade Monte Carlo and risk computation without buying a GPU cluster.
- **Research lineage**: Lopez de Prado (2018) *Advances in Financial Machine Learning*, Gatheral, Jaisson & Rosenbaum (2018) "Volatility is rough", Cont-Kukanov-Stoikov (2014) OFI — academic literature replaces the proprietary research libraries of the big shops.
- **Infrastructure**: One host with Docker Compose, supervised by the project's `supervisor/orchestrator.py`, replaces the Kubernetes-plus-Consul estate a multi-pod firm would run. Phase 7.5 ([PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md](../phases/PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.md), referenced in [PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) §1) exists precisely to revisit this trade-off when live benchmarks demand it.

### 2.4 Principle 4 — Code in adequation with strategy

**Statement.** Every strategic intention encoded in this Charter must be matched by code that enforces it. If the Charter says "risk parity allocation with a 5% per-strategy floor," the code must mechanically enforce that floor — not as a configuration hope, but as a hard constraint the system cannot bypass. If the Charter says "strategies are isolated microservices," the code must prevent two strategies from sharing a process. Discipline lives in code, not in intention.

**Motivation.** A Charter without code enforcement is a wishlist. The difference between a platform that survives five years of live trading and one that blows up in six months is the translation of written intent into mechanical guardrails — frozen Pydantic contracts, VETO-style risk guards, fail-closed states, circuit breakers, type checking.

**Operational rule — the tie-breaker question.**

> *Is this intention enforced by code that the system cannot bypass? If it lives only in documentation, it does not yet exist.*

**Implications.**
- Pydantic v2 models are **frozen** (`ConfigDict(frozen=True)`). Mutation at runtime is structurally impossible. See [Multi-Strat Readiness Audit §2.3](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) for the current list of frozen contracts.
- Risk Manager (S05, soon to be `services/portfolio/risk_manager/`) is a **VETO** — it cannot be bypassed. [CLAUDE.md](../../CLAUDE.md) §2 codifies this; [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) hardens it against the Knight-Capital-class fail-open failure mode.
- All financial arithmetic uses `Decimal`; all timestamps are `datetime` with `timezone.utc`; all logging is `structlog`; all concurrency is `asyncio`. [CLAUDE.md](../../CLAUDE.md) §10 enumerates the forbidden patterns.
- mypy strict, ruff, bandit, and coverage gates run on every commit. CI is the referee; no strategy or platform change advances on a red pipeline.

### 2.5 Principle 5 — Action on documentation, not just observation

**Statement.** Writing the Charter, the audits, and the phase specs is a form of action, not a substitute for it. Once a decision is documented — by this Charter or a downstream spec — it **binds implementation** and is expected to be executed. The Charter itself is the first action on the multi-strategy platform vision.

**Motivation.** In solo development, a persistent failure mode is the perpetual research loop — reading, auditing, reasoning, without ever committing to binding text. The Charter inverts that: it forces the founder to decide in writing, and then holds all subsequent work accountable to that written decision.

**Operational rule — the tie-breaker question.**

> *Is the intention in binding written form? If not, write it before implementing. If it is, then execute it — audits are for revision, not for indefinite postponement.*

**Implications.**
- The Charter is itself the action on the multi-strategy platform vision. Documents 2 and 3 (lifecycle playbook, roadmap) are subsequent actions flowing from it.
- Audits are read-only evidence-gathering events, not work products; the actionable consequences of an audit are encoded in ADRs, phase specs, or Charter revisions.
- A decision captured only in chat is not a decision. Chat is ephemeral; the Charter, ADRs, and specs are durable.

### 2.6 Principle 6 — Functional things stay functional

**Statement.** Existing working infrastructure — the core/ foundations, the Pydantic contracts, the ZMQ broker, the Phase 1–5.1 services, the feature layer, the CPCV validation harness, the Rust extensions — is preserved through the multi-strategy transition. The multi-strategy lift is **additive**. Nothing that currently works is unwritten.

**Motivation.** The Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) §0) verified that the codebase is in excellent single-strategy engineering health: frozen Pydantic contracts, centralized ZMQ topics, `FeatureCalculator` ABC with dependency injection, CPCV walk-forward, Chain-of-Responsibility risk guards, asyncio-only, Decimal-only, UTC-only, structured logging throughout. A green-field rewrite would destroy months of validated engineering to solve problems that can be addressed additively.

**Operational rule — the tie-breaker question.**

> *Can this multi-strategy change be made additively — new classes, new services, new topic suffixes, new Redis partitions — without breaking existing single-strategy code paths? If yes, that is the mandated path. If no, explain why rewriting is necessary before touching anything.*

**Implications.**
- The target topology (classification by domain, see §5.3) is a **folder reorganization plus new services**, not a rewrite. The existing service implementations (S01–S10) move to their new folders, keep their core logic, and gain `strategy_id` as an additive field where relevant.
- The hardcoded single-strategy signal path in S02 is wrapped, not deleted. Current behavior is preserved as `LegacyConfluenceStrategy` — a concrete `StrategyRunner` subclass — so that the transition does not regress any existing validation.
- The `_safe()` heuristic fallback was removed in 5.1 ([ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) D4) — that was a **correctness** removal justified by Principle 1 safety, not a violation of Principle 6.

### 2.7 Principle 7 — Senior-quant tie-breaker

**Statement.** When the first six principles leave a question genuinely underdetermined — typically a trade-off between simplicity, generality, and institutional cleanliness — the tie is broken by asking: *what would a senior quant at AQR, Man AHL, Two Sigma, Citadel Multi-Strategy, or Millennium do here, given these same constraints?*

**Motivation.** Real decisions have residual ambiguity even under clear principles. The senior-quant standard provides a concrete, imaginable person to whom the decision must be defensible. It prevents the drift toward "what is easiest to code today" and anchors ambiguity in professional practice.

**Operational rule — the tie-breaker question.**

> *If I were presenting this decision to a senior researcher at [firm], would they see it as professionally defensible? If they would push back with "why not the cleaner alternative?", do the cleaner alternative unless cost is prohibitive.*

**Implications.**
- When Q1 of the interview offered microservices-per-strategy vs plug-in, Principle 7 pushed toward microservices (Citadel / Millennium pod model) over the simpler plug-in path, despite the +20% operational overhead. The operational cost is real, but the professional credibility and crash-isolation gain is larger.
- When Q2 offered "allocator inside S04" vs "dedicated service," Principle 7 pushed toward the dedicated service (`services/portfolio/strategy_allocator/`): Single Responsibility, institutional cleanliness, future-proof against the allocator algorithm being swapped from Risk Parity to Black-Litterman.
- When Q3 offered "each strategy subscribes to ticks" vs "panel builder," Principle 7 pushed toward the panel builder (Two Sigma pattern), even if the first strategy does not strictly need it — because strategies #3 and #5 will, and DRY compounds.

### 2.8 Ordering and conflict resolution

The seven principles are largely reinforcing, but genuine conflicts will arise. Conflict resolution follows their ordering:

- Principle 1 (long-term cash generation) **always** dominates. A decision that improves institutional cleanliness (Principle 2) at the cost of never shipping live (violating Principle 1) is rejected.
- Principle 2 (institutional standards) dominates Principles 3–7 when they would justify a retail shortcut. A decision to skip PSR/DSR validation "because it is slow" is rejected even if Principle 3 (acknowledged constraints) could be twisted to defend it.
- Principle 6 (preserve what works) dominates Principle 7 (senior-quant elegance) when the senior-quant answer would require a rewrite of functional code. Rewriting is a last resort.

In practice, a decision that cannot be defended under **all seven** principles simultaneously is usually the wrong decision. The principles flag it; the CIO decides.

---

## §3 — Multi-Strategy Philosophy

### 3.1 Why multi-strategy — the portfolio argument

A single strategy, no matter how well-researched, is exposed to **strategy-specific** risks that diversification of bets can reduce:

- **Edge decay** — the mechanism generating alpha fades as more participants exploit it (Jegadeesh & Titman 1993 momentum has decayed meaningfully since the 1990s; Medallion's internal signals are rotated continuously).
- **Regime incompatibility** — a trend-follower that excelled in 2010–2011 suffered during the chop of 2015–2016; a mean-reverter that excelled in low-vol regimes hemorrhaged during the 2020 crisis.
- **Capacity limits** — a strategy with a specific microstructural edge (e.g., OFI-based crypto scalping) has finite capacity; scaling it up beyond capacity destroys the edge.
- **Operational single points of failure** — a bug in the single strategy's code halts the entire platform; a data outage on its single feed stops all trading.

Diversifying across **multiple, structurally independent** strategies addresses each of these:

- Edge decay of one strategy does not impair the others.
- Regime incompatibility of one strategy is offset by regimes favorable to others.
- Capacity limits of one strategy free capital to flow to others.
- Operational failure of one strategy pod does not halt the platform.

This is the foundational argument for multi-strategy architecture — the same argument made by Markowitz (1952) for portfolio diversification, translated from individual securities to entire strategies. The diversification math is cleanest when the strategies have **low pairwise correlation** in their return streams. The third-level benchmark (§10.3) enforces cross-strategy correlation < 0.3 as an explicit Institutional target.

### 3.2 The pod model — Millennium and Citadel as reference

The institutional reference for APEX's architecture is the **pod model** pioneered at Millennium Management and refined at Citadel Multi-Strategy:

- Each pod runs a single, coherent strategy.
- Pods are **isolated** — separate teams, separate risk budgets, separate P&L accounting.
- A central allocator sizes each pod based on historical performance, market conditions, and a risk-budgeting framework (typically risk parity with Sharpe overlays, or more sophisticated variants).
- Pods that breach their risk budget are **halted** (Millennium's famous discipline — a trader losing 5% of their capital allocation is shut down, no exceptions).
- Pods that underperform over an extended period are **decommissioned**; pods that consistently outperform are given more capital.
- The firm absorbs the cost of redundant infrastructure and cross-pod coordination in exchange for crash isolation, specialization, and the ability to deploy new strategies without rewriting the whole system.

APEX encodes this pattern at a solo-operator scale. Each strategy is a microservice in its own container under `services/strategies/<strategy_name>/`. A dedicated `services/portfolio/strategy_allocator/` service performs the central allocation. The Risk Manager (`services/portfolio/risk_manager/`) enforces soft per-strategy and hard global circuit breakers. The lifecycle rules (§7, §9) encode Millennium-style tolerant-but-firm decommissioning.

### 3.3 The platform argument — why the firm is worth more than its strategies

A collection of six isolated strategies sharing no infrastructure is not a platform; it is a folder of scripts. A **platform** adds:

- **Shared data ingestion** — one connector per venue, feeding all strategies (cost amortized).
- **Shared feature library** — HAR-RV, OFI, GEX, Amihud, VPIN, Hawkes, etc., computed once, consumed by any strategy that needs them. The [features/](../../features/) tree already embodies this via the `FeatureCalculator` ABC.
- **Shared statistical testing harness** — PSR, DSR, CPCV, PBO, IC, VIF computed uniformly for every strategy. Strategies pass the same gates; results are comparable.
- **Shared risk layer** — one VETO rejects orders from any strategy that would breach global limits; one fail-closed guard protects the whole platform.
- **Shared observability** — one dashboard shows every strategy's PnL, one alerting pipeline escalates across all pods.
- **Shared governance** — one Charter, one set of ADRs, one review cadence.

The platform multiplies the value of each individual strategy. Strategy #6, deployed on Day 450, inherits everything the first five have already built. This compounding of infrastructure investment is a central economic argument for the multi-strategy approach at solo-operator scale.

### 3.4 The Fundamental Law of Active Management

Grinold & Kahn (1999, *Active Portfolio Management*, 2nd ed., McGraw-Hill) formalize the alpha of an active portfolio as:

> **Information Ratio ≈ Information Coefficient × √(Breadth)**

where Information Coefficient (IC) is the correlation between forecasts and realized returns, and Breadth is the number of independent bets made per year. The relation is stated more carefully by Clarke, de Silva & Thorley (2002) as the "transfer coefficient"-adjusted Fundamental Law, but the core insight holds: **the Information Ratio scales with the square root of Breadth**.

This mathematics drives the multi-strategy architecture at an even deeper level than diversification:

- Six strategies, each making independent bets, produce roughly **√6 ≈ 2.45×** the Information Ratio of a single strategy holding all other things equal.
- Adding an uncorrelated strategy with mediocre IC can still dominate adding more bets to an existing strategy with strong IC — because breadth compounds.
- This justifies accepting strategies with Sharpe in the [0.8, 1.2] range individually if they are **uncorrelated** with the existing portfolio — at the platform level, they contribute materially.

The implication: the platform is not built to find one perfect strategy; it is built to accumulate a portfolio of imperfect-but-independent bets whose aggregate is stronger than any single one.

### 3.5 The 151-Strategies reference

Kakushadze & Serur (2018, *151 Trading Strategies*, Palgrave Macmillan) catalog 151 academically documented trading strategies across six families — momentum, mean reversion, carry, volatility, event-driven, and alternative — with explicit formulas, universes, and expected behavior. The six boot strategies of APEX are selected as a **compact, representative sample** of five of these families (the sixth, event-driven, is represented by the news-driven strategy).

This is a deliberate design decision: rather than picking six strategies from a single family (e.g., six momentum variants), APEX spans **orthogonal edge families**, maximizing structural independence and driving cross-strategy correlation toward the < 0.3 Institutional target. See §4 for the specific strategies and their academic lineage.

### 3.6 How strategies combine — the allocator as the second alpha layer

Strategies produce `OrderCandidate` messages; the allocator combines them into a **portfolio position**. The allocator is a second alpha layer, not a passive aggregator:

- It solves a capital allocation optimization (Risk Parity in Phase 1, Risk Parity + Sharpe overlay in Phase 2 — see §6).
- It respects per-strategy risk budgets (from the category system, §9.1) and portfolio-level constraints (cross-strategy correlation, total exposure).
- It handles cold starts (linear ramp for new strategies, §6.2.3).
- It can respond to regime changes (future extension; the current Charter specifies regime-conditional allocation as a Phase 6 candidate, not a boot requirement).

The allocator is architected as its own microservice (`services/portfolio/strategy_allocator/`, Q2 decision) precisely because it is a serious research object with its own evolution path. Absorbing it into S04 Fusion Engine would conflate signal fusion with capital allocation — two distinct concerns requiring different mathematics.

### 3.7 Why isolation matters — crash independence and parallel development

Isolation — each strategy running in its own container, its own Python process, its own resource budget — is not a purity exercise. It serves three concrete goals:

1. **Crash independence.** A bug in Strategy #3 that produces an unhandled exception, a memory leak, or a hang does not affect Strategies #1, #2, #4, #5, #6. Container-level isolation is the only reliable way to guarantee this at the operating-system level.
2. **Parallel development.** Two Claude Code agents, or one operator working across weeks, can develop Strategy A and Strategy B in parallel without Git-conflicting on the same files. The Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q1) flagged exactly this as a current blocker: three files (`services/s02_signal_engine/pipeline.py`, `signal_scorer.py`, `services/s04_fusion_engine/strategy.py`) would become merge hot-spots under the current architecture.
3. **Independent deployment.** Strategy #4 can be restarted, reconfigured, or rolled back without disrupting the other five. In a monolithic architecture, any strategy change requires restarting the whole signal path.

The cost is the operational overhead of more containers and the coordination surface at the allocator. This cost is quantified at approximately **+20%** operational maintenance effort vs a plug-in approach. The Charter accepts this cost because Principles 2 and 7 both favor the institutional pod model at the inflection point where the second strategy arrives.

---

## §4 — The Six Boot Strategies

The platform launches with six strategies, selected to span orthogonal edge families and asset classes while remaining tractable for a solo developer. Each is described below with a thesis, universe, edge mechanism, expected Sharpe range, required feature inputs (from the existing `features/` tree), data sources, budget category, deployment priority, and known risk factors.

The strategies are listed in **deployment order**: Strategy 1 is built and deployed first; Strategy 6 is last. The order is chosen to maximize **early infrastructure coverage** — the first strategy exercises crypto-only data and short horizons, the second extends to multi-asset, the third to equities and intraday, the fourth to volatility surfaces, the fifth to FX, and the sixth to alternative data — so that by the time Strategy 6 deploys, nearly all platform primitives have been validated.

### 4.1 Strategy #1 — Crypto Momentum

| Field | Value |
|---|---|
| **Category** | Medium Vol (§9.1) |
| **Universe** | Crypto top-20 by market cap, USDT-quoted, Binance (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, ADAUSDT, etc.) |
| **Timeframes** | 4h → 24h (signal horizon); 5min execution bars |
| **Deployment order** | 1 of 6 |
| **Expected Sharpe (academic baseline)** | 0.8 – 1.4 |

**Thesis.** Liu & Tsyvinski (2021, "Risk and Return of Cryptocurrency", *Review of Financial Studies* 34, 2689-2727) document that cryptocurrency returns exhibit a strong **momentum effect** at short-to-medium horizons that is not explained by traditional asset pricing factors. Assets that have outperformed over the past 3-14 days continue outperforming at statistically significant magnitudes through the next week. The mechanism is a combination of under-reaction to novel information in a young, volatile asset class and a self-reinforcing feedback loop between price momentum and retail sentiment (funding rates, social-media velocity). The effect is stronger in crypto than in equities (Jegadeesh & Titman 1993 baseline) because of market immaturity, retail dominance of order flow, and the absence of a well-developed long-short institutional presence to arbitrage it away.

A cross-sectional long-short momentum portfolio — long the top-quintile performers of the past N days, short the bottom quintile — captures this edge while partially neutralizing broad market beta, which is especially important in a regime where BTC dominance shifts rapidly.

**Edge mechanism.** Under-reaction + feedback loop + immature institutional arbitrage presence = persistent serial correlation in returns at weekly horizons.

**Required features** (from existing [features/](../../features/) tree):
- Momentum factor: simple cumulative return over 3/7/14/30-day lookback.
- OFI (Cont, Kukanov & Stoikov 2014) — implemented in [features/calculators/ofi.py](../../features/calculators/ofi.py) — for entry timing on 5min–1h bars.
- CVD / Kyle's Lambda — implemented in [features/calculators/cvd_kyle.py](../../features/calculators/cvd_kyle.py) — for liquidity-aware sizing.
- Rough-volatility estimator (Gatheral, Jaisson & Rosenbaum 2018) — implemented in [features/calculators/rough_vol.py](../../features/calculators/rough_vol.py) — for regime-aware conviction scaling.
- Funding-rate proxy from Binance perpetuals (sentiment indicator).

**Data sources.** Binance WebSocket (ticks, order book L2, funding rate), Binance REST (historical bars, OI, funding history). Cost: **$0/month**.

**Budget inheritance.** Medium Vol category: max DD 12%, min Sharpe 0.8, max leverage 1×. Overrides: none at boot; Charter permits documented overrides in Document 2.

**Risk factors.** (a) Regulatory — crypto venues are exposed to jurisdiction-specific enforcement action; mitigated by trading only Binance top-20 spot, avoiding derivatives with regulatory tail risk. (b) Exchange outage — Binance has suffered multi-hour outages; mitigated by the platform's fail-closed risk state and by not holding cross-exchange arbitrage positions. (c) Edge decay — crypto momentum is well-documented and increasingly exploited; mitigated by drift monitoring (Phase 5.5) that will flag IC degradation and trigger Kelly reduction before capital damage compounds.

**Why it is Strategy #1.** Single-asset-class, single-venue, short to medium horizon, well-documented academically, requires only a subset of the existing feature library. It exercises the end-to-end pipeline (tick → signal → allocator → risk → execution → feedback) without demanding multi-asset panel coordination, which lands later.

### 4.2 Strategy #2 — Trend Following (Multi-Asset)

| Field | Value |
|---|---|
| **Category** | Medium Vol (§9.1) |
| **Universe** | BTC, ETH, SPY, GLD (daily bars across crypto, US equities, gold ETF) |
| **Timeframes** | 1d → 5d (signal horizon); daily bars for entries |
| **Deployment order** | 2 of 6 |
| **Expected Sharpe (academic baseline)** | 0.8 – 1.2 per asset; portfolio 1.0 – 1.5 |

**Thesis.** Moskowitz, Ooi & Pedersen (2012, "Time Series Momentum", *Journal of Financial Economics* 104, 228-250) document a robust time-series momentum effect across 58 liquid instruments spanning equity indices, fixed income, currencies, and commodities: a past 12-month return positively forecasts the next month's return, net of standard risk factors, with consistent significance across asset classes. The pattern is consistent with behavioral under-reaction followed by delayed over-reaction, and with Man AHL's / Winton's / AQR Managed Futures' published understanding of the trend-following premium. It is a foundational multi-asset premium strategy.

APEX implements a simplified multi-asset trend follower on the four most liquid instruments accessible to the operator: BTC and ETH (crypto, via Binance), SPY (US equities, via Alpaca), and GLD (gold ETF, via Alpaca). Daily returns over 1-day to 5-day horizons drive position direction; volatility targeting drives position size.

**Edge mechanism.** Cross-asset behavioral momentum premium, structurally distinct from crypto-specific momentum (Strategy #1) because the asset-class diversification decorrelates the return streams.

**Required features.**
- Cumulative return over 10/20/60/120-day lookback per asset.
- Realized volatility (HAR-RV per Corsi 2009) — implemented in [features/calculators/har_rv.py](../../features/calculators/har_rv.py) — for volatility-targeting position sizing.
- Cross-asset correlation matrix — needed by the allocator for portfolio sizing; also used as a regime signal (correlation spikes = crisis regime).

**Data sources.** Binance (BTC, ETH daily bars), Alpaca (SPY, GLD daily bars — commission-free equity access). Cost: **$0/month**.

**Budget inheritance.** Medium Vol. Overrides: none at boot.

**Risk factors.** (a) Trend-following premium decay — the strategy has been capacity-absorbed in recent decades; mitigated by the small AUM of a personal account (capacity is not a solo-operator constraint). (b) Regime mismatch — choppy markets produce whipsaws; mitigated by the Sharpe overlay (Phase 2 allocator) that reduces allocation when rolling Sharpe degrades. (c) Cross-asset correlation breakdowns — when correlations spike in crisis, diversification fails; mitigated by the hard global circuit breaker (§8.3) triggered by 3+ strategies DEGRADED simultaneously.

**Why it is Strategy #2.** It stresses the **multi-asset panel builder** (new `services/data/panels/`, Q3) and forces the platform to operate across exchanges (Binance + Alpaca). These capabilities are platform-level investments; validating them with Strategy #2 pays forward to Strategies #3–#6.

### 4.3 Strategy #3 — Mean Reversion Intraday Equities

| Field | Value |
|---|---|
| **Category** | Low Vol (§9.1) |
| **Universe** | S&P 500 liquid names (average daily volume > 5M shares, spread < 5bps), top-100 by liquidity |
| **Timeframes** | 5min → 1h (signal horizon); 1min execution bars |
| **Deployment order** | 3 of 6 |
| **Expected Sharpe (academic baseline)** | 1.0 – 1.8 |

**Thesis.** Avellaneda & Lee (2010, "Statistical Arbitrage in the U.S. Equities Market", *Quantitative Finance* 10, 761-782) formalize a **short-horizon mean-reversion** strategy on liquid US equities where a stock's residual return (after decomposing market and industry factors) exhibits statistically significant mean-reversion over 1-hour to multi-day horizons. The mechanism is **temporary liquidity demand** from uninformed order flow, which pushes price away from fair value; market makers earn the compensation for providing the opposing liquidity, and a systematic strategy can replicate this risk-adjusted at reasonable holding periods. Intraday, the effect is most pronounced in the 10:30 ET – 15:00 ET window after the open has absorbed overnight information.

APEX implements a simplified single-name (not pairs-based) version: identify short-horizon over-extensions via Bollinger Bands, RSI divergence, and VWAP deviation, enter against the move with tight stops and profit-targets scaled to realized volatility.

**Edge mechanism.** Liquidity-provision premium at short horizons in liquid equities; a natural short-vol strategy.

**Required features.**
- Bollinger Bands (standard 20-period, 2σ) on 5min and 15min bars.
- RSI(14) divergence on 5min and 15min.
- VWAP deviation — `(price - vwap) / session_ATR`.
- OFI — for entry filtration (only enter mean-reversion against imbalanced flow).
- Realized volatility (1-day HAR-RV) — for position sizing.
- [Phase 2 optional] GEX-adjusted pinning level — implemented in [features/calculators/gex.py](../../features/calculators/gex.py) — as a reinforcement signal near OpEx. Requires options-chain data (CBOE DataShop ~$200/month, ORATS ~$300/month, or Polygon Options ~$199/month); NOT included in boot configuration. Strategy #3 operates at full intended edge without GEX; this feature is a Phase 2 enhancement evaluated only if live evidence shows GEX would add statistically significant alpha justifying the data subscription cost.

**Data sources.** Alpaca (US equity ticks, L1 quotes, 1min bars), Yahoo (daily bars for volatility normalization). Optional Phase 2 upgrades: Polygon.io for enriched L2 (~$29-79/month); CBOE DataShop / ORATS / Polygon Options for GEX (~$200-300/month) — only if live validation justifies. Cost at boot: **$0/month**.

**Budget inheritance.** Low Vol category: max DD 8%, min Sharpe 1.0, max leverage 1×. This is the tightest budget of the six strategies, reflecting the relatively high Sharpe expectation and low DD tolerance of a liquidity-provision strategy in liquid equities.

**Risk factors.** (a) Regime incompatibility — mean-reversion fails in strong trending regimes; mitigated by the regime overlay reducing allocation when HMM flags trending-high-vol (forthcoming Phase 6). (b) Flash crashes — mean-reverters suffer during flash crashes (buying into accelerating selloffs); mitigated by the hard global circuit breaker and by ATR-based stops. (c) Ex-dividend / earnings-release distortions — mitigated by excluding names within 24h of a scheduled event (requires Alpaca calendar + SEC EDGAR integration, both already wired in S01).

**Why it is Strategy #3.** It stresses the **intraday data path** (1min bars, US session clock), the **equity venue integration** (Alpaca), and the **Low Vol budget category** — three capabilities that must work before higher-vol equity strategies can deploy.

### 4.4 Strategy #4 — Volatility Risk Premium

| Field | Value |
|---|---|
| **Category** | High Vol (§9.1) |
| **Universe** | VIX (via VXX / UVXY ETFs), crypto implied vol (via Deribit options RV/IV spread, Phase 2 extension) |
| **Timeframes** | 1d → 7d (signal horizon); daily bars |
| **Deployment order** | 4 of 6 |
| **Expected Sharpe (academic baseline)** | 0.6 – 1.0 (before tail-risk management); 0.8 – 1.4 with systematic tail hedging |

**Thesis.** Carr & Wu (2009, "Variance Risk Premiums", *Review of Financial Studies* 22, 1311-1341) document a large and statistically robust **volatility risk premium** (VRP): implied volatility systematically exceeds subsequent realized volatility across equity indices, and the spread is economically meaningful (on S&P 500 options, the gap averages roughly 3–4 vol points across multiple decades). Harvesting the VRP is a foundational institutional strategy (short variance swaps, short VIX futures, short iron condors), constrained by the characteristic "pennies in front of a steamroller" risk: when realized vol explodes, the short VRP position suffers severe drawdowns. Rigorous risk-management is therefore intrinsic to the strategy, not a wrapper around it.

APEX implements a conservative version: systematically short VIX exposure (via VXX / UVXY) with VIX term-structure–conditional sizing (reduce short when VIX spot > 20 or VIX 1M/3M contango inverts to backwardation), hard stop-outs on -15% move, and disciplined exit rules. The crypto-IV extension (via Deribit option data) is deferred to Phase 2 of the strategy, after equity VRP validates.

**Edge mechanism.** Volatility risk premium — buyers of options are typically demand-side (hedgers, levered longs) while sellers are supply-side (liquidity providers) who require compensation for bearing tail risk. This compensation exceeds the cost of tail risk in expectation, over long horizons, because the tail is infrequent.

**Required features.**
- VIX spot + VIX term structure (VIX / VIX3M, VIX / VIX6M) — from FRED or Yahoo.
- Realized volatility of the S&P 500 (HAR-RV on SPY).
- VIX term-structure slope — a well-established regime indicator.
- RV/IV spread per day — the direct measure of the carry.

**Data sources.** Yahoo (VIX, VIX3M, VIX6M historical), FRED (VIX daily), Alpaca (VXX / UVXY for execution), optional Deribit (crypto options, Phase 2). Cost: **$0/month** at boot.

**Budget inheritance.** High Vol category: max DD 20%, min Sharpe 0.6, max leverage 1.5×. The Charter permits this category's elevated leverage specifically because VRP's Sharpe is meaningful only with moderate leverage, and the elevated DD tolerance recognizes that VRP strategies take drawdowns from tail events but recover over time if risk management is disciplined.

**Risk factors.** (a) Volatility spike (Aug 2015, Feb 2018 "Volmageddon", Mar 2020, etc.) — the dominant risk; mitigated by hard stops, VIX-backwardation kill-switch, and the hard global circuit breaker (§8.3) on -12% portfolio DD. (b) Roll cost in contango — VXX's known decay; mitigated by sizing based on VRP magnitude, not passive short. (c) Regulatory action on VIX products (SEC has flagged this market segment historically) — mitigated by the ability to rotate to crypto-IV as a substitute.

**Why it is Strategy #4.** It is the **stress test** of the platform's risk controls. A VRP strategy that survives a volatility spike because the circuit breakers activated correctly is proof that the infrastructure is institutional-grade. Deploying it fourth, after the tighter Low Vol mean-reversion strategy, ensures the platform has validated circuit-breaker behavior under milder conditions first.

### 4.5 Strategy #5 — Macro Carry (FX G10)

| Field | Value |
|---|---|
| **Category** | Low Vol (§9.1) |
| **Universe** | G10 FX pairs (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) |
| **Timeframes** | 1d → 30d (signal horizon); daily bars |
| **Deployment order** | 5 of 6 |
| **Expected Sharpe (academic baseline)** | 0.6 – 1.2 (before crisis-period drawdowns); 0.8 – 1.5 with carry-crash protection overlays |

**Thesis.** Lustig, Roussanov & Verdelhan (2011, "Common Risk Factors in Currency Markets", *Review of Financial Studies* 24, 3731-3777) document the **FX carry premium**: sorting currencies by interest rate differentials and going long high-yield while short low-yield produces a persistent positive return, explained by exposure to a "global carry risk factor" that compensates for rare-disaster risk. The strategy is foundational at AQR's Managed Futures, at Man AHL, and across most macro-hedge-fund books; it has behaved consistently for decades with well-documented crisis-period drawdowns (August 2007, 2008, 2015 CHF unpeg).

APEX implements a simplified G10 carry basket: long the top-3 high-yield currencies against short the bottom-3 low-yield currencies, rebalanced monthly, with a vol-targeted position sizing and a regime overlay that reduces exposure when global risk-aversion proxies (VIX, credit spreads) spike.

**Edge mechanism.** Compensation for rare-disaster risk in FX markets; persistent cross-country interest rate differentials that are not fully arbitraged due to frictions and risk-premia.

**Required features.**
- Central bank policy rates (from FRED for USD, from ECB/BoE/BoJ APIs for major non-USD) — the direct input to carry ranking.
- FX spot prices — from Yahoo (daily) or ideally OANDA (Phase 3 broker extension).
- Realized volatility of each pair — for volatility-targeting sizing.
- Global risk indicator — VIX as a proxy, or a composite of VIX + HY credit spreads (HYG).

**Data sources.** Yahoo Finance (G10 FX daily bars — limited but sufficient for daily carry), FRED (US rates), ECB / BoE / BoJ scrapers (already in [services/s01_data_ingestion/connectors/](../../services/s01_data_ingestion/) per audit §1). Cost: **$0/month** at boot; upgrade to OANDA (~$0/month retail API) or IBKR (~$10/month) for execution in Phase 3.

**Budget inheritance.** Low Vol category: max DD 8%, min Sharpe 1.0, max leverage 1×. The Sharpe bar is tight for a strategy known to suffer 15%+ drawdowns in crisis; this is **intentional** — the Charter is forcing the regime overlay to be active and effective, otherwise the strategy will not clear the Low Vol budget.

**Risk factors.** (a) Carry crash — sudden reversal of carry trades in risk-off regimes; the dominant historical risk; mitigated by the regime overlay. (b) Central bank surprise (SNB January 2015 CHF unpeg as the canonical example) — mitigated by the central-bank blackout protocol (Guard STEP 1 of the VETO chain; see §8.2) and by caps on single-currency exposure. (c) Thin liquidity during weekend / holiday regimes — mitigated by the daily bar cadence (not intraday).

**Why it is Strategy #5.** It extends the platform to **FX** as an asset class, exercising new data integrations (central bank rate feeds), and it validates the **regime overlay** under a strategy whose edge *depends* on the overlay working. Deploying it after the core Medium-Vol strategies gives the platform enough live evidence to calibrate the overlay reliably.

### 4.6 Strategy #6 — News-Driven Short-Horizon

| Field | Value |
|---|---|
| **Category** | Medium Vol (§9.1) |
| **Universe** | Liquid US equities (S&P 500 subset), BTC, ETH |
| **Timeframes** | 15min → 4h (signal horizon); 5min execution bars |
| **Deployment order** | 6 of 6 |
| **Expected Sharpe (academic baseline)** | 0.8 – 1.5 |

**Thesis.** Tetlock (2007, "Giving Content to Investor Sentiment: The Role of Media in the Stock Market", *Journal of Finance* 62, 1139-1168) documents that **news sentiment predicts short-horizon returns**: high pessimism in Wall Street Journal columns is followed by lower returns over subsequent days, with a mean-reverting pattern over 1-3 weeks. Subsequent research (Tetlock, Saar-Tsechansky & Macskassy 2008; Kelly, Malamud & Zhou 2023 on machine-read news) has refined this into a **text-as-data** program where systematic NLP over news and event feeds produces real-time sentiment scores with predictive content at intraday horizons.

APEX implements a simplified version using **GDELT 2.0** (free, public, event-coded, 15-minute cadence, 300 languages — see [PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) §3.6 for the existing Phase 5.8 overlay) for event detection and **FinBERT** (open-source, ONNX-compilable, CPU-inferable) for financial-text sentiment scoring. The strategy trades short-horizon momentum following high-impact news events, with direction determined by the sentiment score and conviction scaled to the magnitude of the GDELT "Goldstein-scaled" event impact score.

**Edge mechanism.** Under-reaction to genuinely new information at the 15-minute to 4-hour horizon, before broad market participants fully incorporate the news.

**Required features.**
- GDELT event stream (polled every 15min) — consumed via the connector specified in [PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) §3.6.
- FinBERT sentiment score over rolling 4-hour news window per symbol.
- OFI and CVD — for entry-timing filtration after the event.
- Realized volatility (HAR-RV) — for sizing.

**Data sources.** GDELT 2.0 (free), FinBERT (open-source, ONNX Runtime, CPU inference), Binance (crypto ticks), Alpaca (equity ticks). Cost: **$0/month** (Phase 3 premise per Principle 3).

**Budget inheritance.** Medium Vol. Overrides: none at boot; the Charter notes that Strategy #6 is the most **infrastructure-heavy** of the six and may require Budget-category-override discussion in Document 2 once live evidence is available.

**Risk factors.** (a) FinBERT hallucination / false-positive sentiment — mitigated by confidence thresholds, manual review panel in S10, and asymmetric allocation (sentiment reinforces a negative signal more readily than it creates a positive one). (b) Event mis-categorization (e.g., a minor event over-scored by GDELT) — mitigated by requiring confluence with price action (OFI + volume spike within 10min of the event). (c) Latency — news-driven strategies are notoriously sensitive to execution speed; APEX accepts that institutional HFTs will beat it to the shortest-horizon trades and focuses on the 15min–4h window where execution-speed arbitrage is less decisive.

**Why it is Strategy #6.** It is the **capstone** — requires NLP infrastructure (FinBERT + GDELT, Phase 5.8), cross-asset coordination (equities + crypto), and the most sophisticated signal integration of any boot strategy. Deploying it last lets the platform accumulate the maximum amount of learning before tackling the most operationally demanding edge.

### 4.7 Cross-strategy correlation expectations

The six strategies are chosen to span structurally independent edge families. Expected pairwise correlations, rough academic estimates:

| Pair | Expected correlation (return streams) |
|---|---|
| Crypto Momentum ↔ Trend Following | 0.3 – 0.5 (both momentum-family; crypto assets are in both universes) |
| Crypto Momentum ↔ Mean Rev Equities | -0.1 – 0.2 (different asset classes, opposite edges) |
| Crypto Momentum ↔ VRP | 0.0 – 0.2 (different risk premia) |
| Crypto Momentum ↔ Macro Carry | -0.1 – 0.1 (near-orthogonal) |
| Crypto Momentum ↔ News-driven | 0.2 – 0.4 (both short-horizon, some venue overlap) |
| Trend Following ↔ Mean Rev Equities | -0.2 – 0.1 (opposite edges by construction) |
| Trend Following ↔ VRP | 0.1 – 0.3 (both suffer in volatile regimes; though different mechanisms) |
| Trend Following ↔ Macro Carry | 0.1 – 0.3 (both suffer in carry crashes) |
| Mean Rev Equities ↔ VRP | 0.1 – 0.3 (both liquidity-provision) |
| Mean Rev Equities ↔ Macro Carry | -0.1 – 0.1 (near-orthogonal) |
| Mean Rev Equities ↔ News-driven | 0.0 – 0.2 (different horizons) |
| VRP ↔ Macro Carry | 0.2 – 0.4 (both suffer in crisis regimes) |
| VRP ↔ News-driven | 0.1 – 0.3 (both event-sensitive) |
| Macro Carry ↔ News-driven | 0.0 – 0.2 (different time scales) |

The Institutional benchmark (§10.3) requires the **aggregate** cross-strategy correlation matrix (average off-diagonal pairwise correlation) to be < 0.3. The table above suggests this is achievable **if** Crypto Momentum ↔ Trend Following and VRP ↔ Macro Carry are the highest-correlated pairs and the rest remain near-orthogonal. Reality will deviate from these academic priors; the platform's job is to measure the realized correlation matrix live and — if a pair exceeds expectations persistently — to either reduce the allocation to the redundant strategy or to retire one of them.

### 4.8 Strategy comparison table (for allocator consumption)

| # | Name | Category | Universe | Horizon | Leverage | Primary data | Edge family |
|---|---|---|---|---|---|---|---|
| 1 | Crypto Momentum | Medium Vol | Crypto top-20 | 4h–24h | 1× | Binance | Cross-sectional momentum |
| 2 | Trend Following | Medium Vol | BTC, ETH, SPY, GLD | 1d–5d | 1× | Binance + Alpaca | Time-series momentum |
| 3 | Mean Rev Equities | Low Vol | S&P 500 liquid | 5min–1h | 1× | Alpaca | Liquidity provision |
| 4 | VRP | High Vol | VIX / VXX | 1d–7d | 1.5× | Yahoo + FRED + Alpaca | Variance risk premium |
| 5 | Macro Carry | Low Vol | G10 FX | 1d–30d | 1× | Yahoo + FRED + CB scrapers | Carry premium |
| 6 | News-driven | Medium Vol | Equities + crypto | 15min–4h | 1× | GDELT + FinBERT + Binance + Alpaca | Event sentiment |

---

## §5 — Architectural Foundations

The multi-strategy platform rests on three architectural decisions that together define the shape of the codebase for the next 12–24 months. These decisions are drawn directly from the 1-hour Charter interview (Q1, Q2, Q3) and are non-negotiable once ratified. They require no rewrite of existing functional code; they require **additions** (new services, new folder hierarchy, new ABCs) that the Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) §3 Q1–Q10) has already scoped in effort and prioritized in the P0/P1/P2 list.

### 5.1 Strategy isolation — microservices per strategy (Q1)

**Decision.** Each strategy is implemented as a **complete, isolated microservice** with its own Docker container, Python process, dedicated resources (CPU / memory budget), and a location under `services/strategies/<strategy_name>/`.

**Rationale.**

- **Crash isolation**, absolute and at the operating-system level. A segfault, an unhandled exception, a memory leak in Strategy #3 cannot corrupt the state of Strategies #1, #2, #4, #5, #6. This is the guarantee that the pod model is built around at Citadel and Millennium.
- **Resource isolation** — each strategy has its own CPU / memory budget; noisy strategies cannot starve quiet ones.
- **Independent deployment** — a change to Strategy #4 is deployed by restarting one container; the other five keep trading.
- **Parallel development** — two agents (human or Claude Code) can work on Strategy A and Strategy B without Git-conflicting on shared source files. The Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q1) identifies the current single-path S02 `pipeline.py` as a concrete blocker; the microservice topology resolves this.
- **Specialization** — each strategy's microservice can include strategy-specific logic, configuration files, feature computations, and custom connectors without polluting the shared codebase. `services/strategies/crypto_momentum/` is the right home for crypto-momentum-specific ranking logic; that logic does not belong in a shared S02.

**Accepted cost.** The operational maintenance effort increases by approximately **+20%** vs a plug-in-in-single-process approach: more containers to orchestrate, more health checks, more startup coordination. This cost is accepted by Principle 7 (senior-quant tie-breaker, pod model precedent) and Principle 2 (institutional standards).

**Current state (evidence).** The existing 10 services live under [`services/s01_data_ingestion/`](../../services/) through [`services/s10_monitor/`](../../services/). The multi-strat target topology reorganizes these and **adds** the `services/strategies/` tree. No existing service is deleted.

**Target folder structure**:

```
services/strategies/
├── crypto_momentum/
│   ├── service.py            # inherits BaseService; subscribes to panels; publishes order.candidate with strategy_id
│   ├── signal_generator.py   # concrete StrategyRunner subclass
│   ├── config.yaml           # per-strategy config (universe, timeframes, thresholds)
│   └── tests/
├── trend_following/
├── mean_rev_equities/
├── volatility_risk_premium/
├── macro_carry/
└── news_driven/
```

**What Principle 6 preserves.** The existing S01–S10 code continues to work unchanged. The strategies' microservices **consume** shared data (via panels), **emit** `OrderCandidate` with `strategy_id`, and **respect** the VETO chain. They do not replace the existing pipeline; they extend it.

### 5.2 Capital allocator — dedicated microservice (Q2)

**Decision.** Capital allocation is performed by a **dedicated microservice** located at `services/portfolio/strategy_allocator/`. It is distinct from both the Fusion Engine (which handles per-signal fusion within a strategy) and the Risk Manager (which handles VETO-style hard risk rules).

**Rationale.**

- **Single Responsibility** (Principle 4, SOLID-S). Capital allocation is a distinct concern from signal fusion and from risk VETO. Conflating it into S04 or S05 would couple two or three evolutionary paths that should remain independent.
- **Swappable allocation algorithm.** Phase 1 uses Risk Parity (Maillard, Roncalli & Teiletche 2010); Phase 2 adds a Sharpe overlay; Phase 6+ may introduce Black-Litterman or regime-conditional variants. Keeping the allocator as its own service means the algorithm can evolve without touching the services around it.
- **Institutional precedent** — every multi-strategy firm runs a centralized capital allocator distinct from its signal generation and its risk veto. Principle 7 points here.
- **Observability** — a dedicated service emits its own logs, metrics, and decisions to the dashboard; a black-box allocator buried inside S04 would be operationally opaque.

**Architectural position.** The allocator sits **between** per-strategy signal generation and the risk VETO:

```
[Strategy Microservices]  →  order.candidate (strategy_id tagged)
                                    │
                                    ▼
                    [services/portfolio/strategy_allocator/]
                                    │
                                    ▼
                           order.candidate.allocated
                                    │
                                    ▼
                      [services/portfolio/risk_manager/]
                                    │
                                    ▼
                            order.approved / order.blocked
                                    │
                                    ▼
                       [services/execution/engine/]
```

**Current state (evidence).** The Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q2) records zero grep hits for `StrategyAllocator`, `PortfolioAllocator`, `RiskParity`, or `BlackLitterman` anywhere in the codebase. This is a **new service** on the critical path; the Charter formally requires it to exist before Strategy #2 deploys live. Phase 5 v3 (Document 3, pending) will schedule its build.

**Algorithmic content (Phase 1).** See §6 for the full Risk Parity specification.

### 5.3 Multi-asset data — disciplined panel builder (Q3)

**Decision.** A new microservice, `services/data/panels/`, aggregates individual tick and bar streams into multi-asset **snapshot panels** consumed by strategies. Every strategy subscribes to panels, not to raw tick streams. This discipline is enforced uniformly, including for strategies that could in principle operate on a single asset.

**Rationale.**

- **DRY across strategies.** Cross-sectional strategies (momentum Top-N, multi-asset trend, carry basket) need panels by construction. Without a shared panel builder, each strategy reinvents the same snapshot logic, with the same bugs.
- **Two Sigma standard pattern.** Multi-asset panels are the canonical data representation at Two Sigma's research layer and at most systematic shops. Principle 7 points here.
- **Point-in-time correctness.** The panel builder is the natural home for point-in-time synchronization — ensuring that a cross-sectional momentum signal at time T does not accidentally use Strategy A's tick from T+1ms and Strategy B's tick from T-500ms. This is a subtle source of look-ahead bias the panel pattern eliminates by construction.
- **Feature coherence.** Features that span multiple assets (cross-sectional rank, dispersion, cross-asset correlation) are cheaper to compute once from the panel than ad-hoc per strategy.

**Accepted cost.** Strategies that only consume a single asset (single-symbol crypto momentum on BTC, for example) still go through the panel builder. This adds a trivial layer of ceremony for those cases in exchange for architectural uniformity.

**Current state (evidence).** [Multi-Strat Readiness Audit](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) Q3 and Q6 confirm the **feature layer is multi-strategy-ready** — `FeatureCalculator` ABC, `FeaturePipeline` accepts `calculators: list[FeatureCalculator]` via DI, each calculator is a pure function, point-in-time `FeatureStore` and `FeatureRegistry` already exist. What is missing is the **panel aggregator** sitting between raw ticks and the feature pipeline. That is a **new microservice** on the P1 list (P1-4 in audit §5).

### 5.4 Topology — classification by domain (Option B)

**Decision.** The linear S01–S10 numbering scheme is retired as the organizing principle. The new topology classifies services by **domain**: data, signal, portfolio, execution, research, ops, strategies.

**Rationale.** The S01–S10 numbering encodes a Phase-1 linear pipeline view that does not scale to the multi-strategy world. The new grouping reflects architectural roles directly. It is also the organizing pattern used at every institutional firm the Charter references — data teams, research teams, execution teams, risk teams.

**Target topology.**

```
services/
├── data/
│   ├── ingestion/           (ex-S01)
│   ├── panels/              (NEW — §5.3)
│   └── macro_intelligence/  (ex-S08)
├── signal/
│   ├── engine/              (ex-S02 — legacy single-strategy confluence, preserved as a strategy)
│   ├── regime_detector/     (ex-S03)
│   ├── fusion/              (ex-S04 — becomes per-strategy fusion)
│   └── quant_analytics/     (ex-S07)
├── portfolio/
│   ├── strategy_allocator/  (NEW — §5.2)
│   └── risk_manager/        (ex-S05)
├── execution/
│   └── engine/              (ex-S06)
├── research/
│   └── feedback_loop/       (ex-S09)
├── ops/
│   └── monitor_dashboard/   (ex-S10)
└── strategies/
    ├── crypto_momentum/
    ├── trend_following/
    ├── mean_rev_equities/
    ├── volatility_risk_premium/
    ├── macro_carry/
    └── news_driven/
```

**Current state.** This reorganization is **planned but not executed** at the time of this Charter. The current layout under [`services/`](../../services/) keeps the S01–S10 naming. The Charter documents the **target state**; Document 3 (Phase 5 v3 roadmap) will schedule the reorganization as an early, mechanical, refactor-only step.

### 5.5 Cross-cutting: per-strategy identity and config

**`strategy_id` as a first-class field.** The Multi-Strat Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) P0-1) records that no Pydantic model in the codebase currently carries a `strategy_id` field. The Charter requires this to be added to `Signal`, `OrderCandidate`, `ApprovedOrder`, `ExecutedOrder`, `TradeRecord`. Default value `"default"` preserves backward compatibility with the single-strategy codebase during transition.

**Per-strategy configuration.** Each strategy's parameters (universe, timeframes, thresholds, Kelly fraction, stop multipliers) live in `config/strategies/{strategy_id}.yaml`, loaded and validated by Pydantic at service startup. This replaces the current pattern of hardcoded Python constants in `services/s04_fusion_engine/strategy.py:STRATEGY_REGISTRY`.

**Per-strategy Redis partitioning.** Keys that are per-strategy get a `{strategy_id}` dimension: `trades:{strategy_id}:all`, `kelly:{strategy_id}:{symbol}`, `pnl:{strategy_id}:daily`, `portfolio:allocation:{strategy_id}`, etc. Keys that are genuinely global (portfolio-level: `portfolio:capital`, `risk:circuit_breaker:state`, `risk:heartbeat`, `correlation:matrix`) remain global.

**Per-strategy topic factories.** A new helper `Topics.signal_for(strategy_id, symbol)` produces `signal.technical.{strategy_id}.{symbol}`. This allows strategy microservices to publish without interfering, and downstream consumers to subscribe per-strategy or broadly via prefix match. See [`core/topics.py`](../../core/topics.py) for the current factory pattern.

### 5.6 ABCs required by the multi-strategy topology

The following abstract base classes are introduced (see also [MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) §2.4 for the current ABC inventory):

| ABC | Location (target) | Purpose |
|---|---|---|
| `StrategyRunner` | `features/strategies/base.py` or `services/strategies/_base.py` | Defines how a strategy consumes panels and emits Signals / OrderCandidates |
| `StrategyAllocator` | `services/portfolio/strategy_allocator/base.py` | Defines how a capital allocation algorithm maps input (strategy performance, risk budgets) to output (per-strategy weights) |
| `RiskGuard` | `services/portfolio/risk_manager/base.py` | Defines the contract for a step in the VETO chain — supersedes the current duck-typed `RuleResult` convention |

All three ABCs inherit from Python's `abc.ABC` and are `Protocol`-friendly (type-checkable). `StrategyRunner` is the most central: every boot strategy is a concrete `StrategyRunner` subclass. The **legacy single-strategy confluence signal path currently in [`services/s02_signal_engine/pipeline.py`](../../services/s02_signal_engine/pipeline.py)** is wrapped as a concrete `StrategyRunner` called `LegacyConfluenceStrategy`, preserving current behavior (Principle 6) while enabling the multi-strategy topology.

### 5.7 ZMQ broker — ADR-0001 continues to govern

The ZMQ XSUB/XPUB broker topology ratified in [ADR-0001](../adr/0001-zmq-broker-topology.md) continues to govern all inter-service messaging in the multi-strategy architecture. No change. The broker supports any number of publishers and subscribers; adding six strategy microservices is mechanically free. The topic factory extension (`Topics.signal_for`) is fully backward compatible with the current factories (`Topics.tick`, `Topics.signal`, `Topics.health`, `Topics.catalyst`).

### 5.8 Fail-closed risk state — ADR-0006 continues to govern

[ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) — the fail-closed pre-trade risk controls contract — continues to govern the Risk Manager (now `services/portfolio/risk_manager/`). It defines the global `SystemRiskState` (`HEALTHY` / `DEGRADED` / `UNAVAILABLE`), the single `risk:heartbeat` Redis key, and the all-or-nothing admission rule: in any non-`HEALTHY` state, 100% of incoming `OrderCandidate` messages are rejected. This is STEP 0 of the seven-step VETO chain (see §8.2). Per-strategy concerns live at STEPS 3–6; STEP 0 remains global and overrides everything.

### 5.9 Supervisor / orchestrator — extended, not replaced

The existing `supervisor/orchestrator.py` continues to handle ordered startup and shutdown of services. The multi-strategy topology extends its responsibility to include the six strategy microservices. Startup order is amended to:

```
1.  Redis
2.  ZMQ broker (XSUB/XPUB)
3.  services/ops/monitor_dashboard/          (observe startup itself)
4.  services/data/ingestion/
5.  services/data/panels/                    (NEW)
6.  services/data/macro_intelligence/        (data-domain cluster complete)
7.  services/signal/quant_analytics/
8.  services/signal/regime_detector/
9.  services/signal/engine/                  (legacy confluence as StrategyRunner)
10. services/signal/fusion/                  (per-strategy fusion)
11. services/portfolio/strategy_allocator/   (NEW)
12. services/portfolio/risk_manager/
13. services/execution/engine/
14. services/research/feedback_loop/
15. services/strategies/crypto_momentum/     (deploy when Strategy #1 passes Gate 2)
16. services/strategies/trend_following/     (deploy when Strategy #2 passes Gate 2)
…   (strategies added as they clear gates)
```

This ordering clusters by domain: all `data/` services (steps 4–6) start consecutively before any `signal/` service, all `signal/` services (steps 7–10) complete before `portfolio/` (steps 11–12), and `execution/` (step 13) and `research/` (step 14) follow. Strategy microservices deploy last (step 15+) as each clears its gates. `ops/monitor_dashboard/` starts at step 3 to observe the rest of the startup sequence itself.

Existing supervisor health-check semantics (5-second ping cadence, auto-restart, watchdog escalation) are preserved.

### 5.10 Summary — what must be built, what must be preserved

**To be built additively** (documented scope, to be scheduled in Document 3):

- `strategy_id` as a frozen field on the five Pydantic order-path models + `Topics.signal_for` factory.
- `StrategyRunner`, `StrategyAllocator`, `RiskGuard` ABCs.
- `services/data/panels/` microservice (Q3).
- `services/portfolio/strategy_allocator/` microservice (Q2, §5.2, §6).
- `services/strategies/{six_strategies}/` microservices (one at a time, per lifecycle §7).
- Refactor of [`services/s02_signal_engine/pipeline.py`](../../services/s02_signal_engine/pipeline.py) to wrap the current hardcoded pipeline as `LegacyConfluenceStrategy` implementing `StrategyRunner`.
- Data-driven `RiskChainOrchestrator(guards: list[RiskGuard])` that admits `PerStrategyExposureGuard`, `StrategyHealthCheck`, and `PortfolioExposureMonitor` per §8.2.
- Per-strategy Redis partitioning in `services/research/feedback_loop/` and per-strategy dashboards in `services/ops/monitor_dashboard/`.
- Per-strategy backtest harness (`backtesting/run_portfolio`) and per-strategy breakdowns in `full_report`.
- Target topology folder reorganization (§5.4).
- New ADR(s): ADR-0007 "Strategy as Microservice", ADR-0008 "Capital Allocator Topology", ADR-0009 "Panel Builder Discipline" — to be authored as Document 3 is written.

**To be preserved verbatim** (Principle 6):

- All frozen Pydantic contracts (additive `strategy_id` only).
- The ZMQ XSUB/XPUB broker ([ADR-0001](../adr/0001-zmq-broker-topology.md)).
- The fail-closed risk state contract ([ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md)).
- The quant methodology charter ([ADR-0002](../adr/0002-quant-methodology-charter.md)).
- The meta-labeling and fusion methodology ([ADR-0005](../adr/ADR-0005-meta-labeling-fusion-methodology.md)).
- The feature validation harness (ADR-0004).
- The universal data schema (ADR-0003).
- The existing 1,833+ unit tests and the integration test harness.
- The Rust extensions (`apex_mc`, `apex_risk`).
- The CPCV walk-forward validator.
- All current connectors in `services/s01_data_ingestion/connectors/`.

---

## §6 — Capital Allocation Framework

The `services/portfolio/strategy_allocator/` microservice implements capital allocation across the live strategies. The Charter ratifies a **two-phase** approach: Phase 1 uses pure Risk Parity; Phase 2 (activated only when empirical evidence justifies it) layers a Sharpe overlay on top of the Risk Parity base. The allocation framework is mathematically specified below with enough precision that the implementation is unambiguous.

### 6.1 Phase 1 — Risk Parity Pure (months 1–12)

#### 6.1.1 Definition

The target allocation `w_i` for strategy `i` (across `N` active strategies) equalizes the **ex ante risk contribution** of each strategy to the portfolio:

> `w_i × σ_i = (1/N) × Σ_j (w_j × σ_j)`

In the diagonal-covariance approximation (which the Charter adopts as Phase 1 default; see §6.1.5 for the rationale):

> `w_i ∝ 1 / σ_i`, normalized so that `Σ_i w_i = 1.0`

where `σ_i` is the annualized realized volatility of strategy `i`, computed on a rolling window of recent daily returns.

This is the **inverse-volatility** heuristic — the canonical simplification of Risk Parity under a diagonal covariance assumption — formalized in Maillard, Roncalli & Teiletche (2010, "The Properties of Equally Weighted Risk Contribution Portfolios", *Journal of Portfolio Management* 36, 60-70).

#### 6.1.2 Parameters

| Parameter | Value | Justification |
|---|---|---|
| Sigma estimation window | **60 days rolling** | Long enough for a stable estimate (noise ~ 1/√60 ≈ 13%); short enough to adapt within a quarter. |
| Rebalancing frequency | **Weekly** (Sunday evening UTC, before Asia open) | Daily is excessively noisy; monthly is too slow to respond to regime changes. Weekly is AQR's published cadence for Risk Parity products. |
| Floor per active strategy | **5%** | Prevents a strategy from being starved to irrelevance by a transient volatility spike; ensures drift-monitor learnability (a 1% allocation produces too few trades for clean attribution). |
| Ceiling per strategy | **40%** | Prevents a single strategy from dominating the portfolio; preserves diversification benefit even when one strategy has recently-low volatility. |
| Turnover dampening | **±25% max rebalance move per week per strategy** | Reduces transaction cost churn when weekly volatility estimates jitter. |

#### 6.1.3 Cold start — linear ramp for a new strategy

When a new strategy passes Gate 3 (Paper → Live Micro, §7) and enters the active portfolio, its allocation ramps linearly from **20% of target to 100% of target over 60 calendar days**.

Formally, on day `d` post-entry (where `d = 0` is the first day of live allocation):

> `ramp_factor(d) = min(1.0, 0.20 + (0.80 × d / 60))`
>
> `w_i_effective = ramp_factor(d) × w_i_target`

The undersized fraction (`1 - ramp_factor(d)`) is redistributed to the other active strategies proportionally to their own target weights.

This cold-start ramp is Millennium-style — new pods earn their allocation over time; a 60-day ramp corresponds to approximately 50 trading-day observations, enough to begin accumulating live IC evidence for the drift monitor before full capital is at risk.

#### 6.1.4 Edge cases

- **Strategy in `review_mode` (§9.2)**: floor drops to 5%, and the strategy is **excluded** from the weekly rebalance upward adjustment. It can lose allocation but cannot gain it until `review_mode` is cleared.
- **Strategy paused** (for operational reasons, not decommissioned): excluded from the allocation; its share is redistributed proportionally to the other active strategies.
- **Only one active strategy**: that strategy receives **100%** of capital (bypassing the 40% ceiling since the ceiling is meaningless with N=1). This is the degenerate case during Strategy #1 solo operation prior to Strategy #2's live-micro deploy.
- **Zero active strategies** (e.g., all halted by a global circuit breaker): no allocation decision; capital sits in the operator's preferred cash reserve. The allocator publishes `portfolio.allocation.suspended` on every rebalance tick until strategies come back online.

#### 6.1.5 Why diagonal covariance (not full covariance) in Phase 1

Full-covariance Risk Parity — solving `w_i × (Σ w)_i = (1/N) × w' Σ w` with `Σ` the full covariance matrix — is mathematically cleaner and matches the AQR Risk Parity product implementation. The Charter adopts the diagonal approximation for Phase 1 specifically because:

1. **Sample-size constraint.** With six strategies and 60 days of returns, the full covariance estimate has 21 independent parameters; the data covers 6×60 = 360 observations, producing a noisy covariance matrix especially along off-diagonals.
2. **Live tracking-error gain is minimal.** When cross-strategy correlations are targeted at < 0.3 (§10.3) and roughly uniform, the diagonal and full-covariance Risk Parity solutions differ by a few percent at most — within the noise of the volatility estimate itself.
3. **Interpretability.** `w_i ∝ 1/σ_i` is auditable in one glance; full-covariance requires inverting a matrix whose estimation error is hard to reason about operationally.

Phase 2 (§6.2) introduces a Sharpe overlay on top of the diagonal base. If, by month 12, live evidence demonstrates that cross-strategy correlations are persistently non-zero and not well-approximated by diagonal, the Charter authorizes a **future** ADR upgrade to full-covariance Risk Parity. This is a deliberate evolution path, not a regression.

### 6.2 Phase 2 — Risk Parity + Sharpe overlay (months 12+)

#### 6.2.1 Activation trigger

Phase 2 activates only when **both** of the following hold:

- **≥ 6 months of live trading** on at least three active strategies, i.e., at least three strategies with ≥ 6 months of live Sharpe evidence.
- **Live Sharpe estimates have stabilized** — the 95% bootstrap CI on the rolling 6-month Sharpe is within ±0.3 of the point estimate for at least three consecutive weeks.

Until both conditions hold, the allocator operates strictly in Phase 1 (Risk Parity pure).

#### 6.2.2 Specification

Phase 2 tilts the Phase 1 base allocation by a **Sharpe-based multiplier**:

> `w_i_phase2 = w_i_phase1 × tilt_i`
>
> `tilt_i = 1.0 + clip(β × (S_i - S_mean), -0.20, +0.20)`

where:

- `S_i` is the EMA-smoothed 6-month rolling Sharpe of strategy `i` (EMA weight on the most recent 3 months ~ 2/3, on months 4–6 ~ 1/3, approximately a half-life of 2 months).
- `S_mean` is the weighted average Sharpe across active strategies (weighted by current `w_i_phase1`).
- `β` is a calibration constant, set initially to `0.5 / (max_sharpe_spread / 2)` so that a 1-unit-Sharpe lead over the mean produces a roughly +10% tilt; fine-tuned empirically in live.
- `clip(x, -0.20, +0.20)` enforces the **±20% maximum tilt per strategy** constraint.

After tilting, weights are re-normalized to sum to 1.0 and the per-strategy floor (5%) and ceiling (40% or 45% when elevated per below) are re-applied, with any overflow redistributed.

#### 6.2.3 Elevated ceiling for exceptional performers

If a strategy's rolling 6-month Sharpe is **> 2.0 stable for ≥ 6 months** (the 95% bootstrap CI lower bound stays above 2.0 over that window), its ceiling is elevated from 40% to **45%**. Elevation requires CIO ratification (a single commit to the strategy's config) — the Charter does not auto-elevate.

#### 6.2.4 Review mode on persistent underperformance

If a strategy's rolling 6-month Sharpe is **< 0** and the 95% bootstrap CI upper bound stays below 0 for ≥ 3 consecutive weekly rebalances, the strategy enters **`review_mode`**: allocation floor drops to 5%, the strategy is excluded from Sharpe-overlay upward tilts, and the CIO must ratify a continuation decision. See §9.2 for the full `review_mode` protocol.

#### 6.2.5 Why ±20% and not larger

The ±20% tilt cap is deliberately conservative. Large Sharpe overlays are a well-known overfit trap — recent Sharpe is a noisy estimator of future Sharpe (Lo 2002, "The Statistics of Sharpe Ratios", *Financial Analysts Journal* 58, 36-52, formalizes the estimation uncertainty; bootstrap confidence intervals for Sharpe over 6-month windows are typically ±0.5 to ±1.0 wide). A 20% cap prevents the allocator from over-reacting to what may be pure noise in the Sharpe estimate. Phase 1's Risk Parity remains the **dominant** contributor to the allocation; the Sharpe overlay is a **marginal** adjustment.

### 6.3 Risk-taker profile — separate from allocation

The Charter explicitly **decouples** two concerns that solo operators routinely conflate:

1. **Capital allocation across strategies** — the allocator's job; Risk Parity then Sharpe-tilted.
2. **Aggressiveness within a strategy** — each strategy's own Kelly fraction, stop-loss multipliers, and position-sizing discipline.

Risk-taker profile encoding (each strategy configures its own aggressiveness):

| Parameter | Default | Range |
|---|---|---|
| Kelly fraction (per strategy, in [`features/meta_labeler/`](../../features/meta_labeler/) / Fusion Engine sizing) | **0.4** (moderate-aggressive) | 0.10 – 0.50 |
| Portfolio-level hard circuit breaker | **-12% drawdown** (§8.3) | non-configurable |

Individual strategies may override their Kelly fraction in `config/strategies/{strategy_id}.yaml` with documented justification. The allocator does not see Kelly; it sees only per-strategy capital allocations.

### 6.4 Concrete example — Phase 1 allocation with six active strategies

Suppose all six boot strategies are live, with the following 60-day rolling annualized volatilities:

| # | Strategy | σ (annualized) |
|---|---|---|
| 1 | Crypto Momentum | 35% |
| 2 | Trend Following | 18% |
| 3 | Mean Rev Equities | 10% |
| 4 | VRP | 28% |
| 5 | Macro Carry | 8% |
| 6 | News-driven | 22% |

Raw inverse-volatility weights `1/σ_i`:

| # | `1/σ_i` |
|---|---|
| 1 | 2.857 |
| 2 | 5.556 |
| 3 | 10.000 |
| 4 | 3.571 |
| 5 | 12.500 |
| 6 | 4.545 |

Sum: 39.03. Normalized raw weights:

| # | Raw weight |
|---|---|
| 1 | 7.3% |
| 2 | 14.2% |
| 3 | 25.6% |
| 4 | 9.1% |
| 5 | 32.0% |
| 6 | 11.6% |

Apply the **5% floor** — Strategy #1 is borderline but above the floor, no adjustment needed. Apply the **40% ceiling** — no strategy is at the ceiling. Final allocations match raw weights above.

Observation: **the Low Vol strategies (#3 Mean Rev, #5 Carry) dominate the allocation** because their low volatility translates to large weight under Risk Parity. This is the *design intent* of Risk Parity — to equalize risk contribution, which means low-vol assets carry more dollar weight. The High Vol VRP strategy (#4) receives only 9.1% despite its 1.5× leverage allowance, because its effective volatility (post-leverage) is high.

This example illustrates why the **three category system** (§9.1) and **Risk Parity allocation** work together: categories define per-strategy risk budgets; Risk Parity then allocates capital so that each strategy contributes approximately equally to portfolio risk, weighted by its realized volatility. The two mechanisms are complementary, not redundant.

### 6.5 Rebalancing mechanics

Every Sunday at 23:00 UTC (before Asia open Monday):

1. The allocator fetches per-strategy 60-day realized volatility from the research feedback loop (now in `services/research/feedback_loop/`).
2. For each active strategy, computes target `w_i` via Phase 1 formula (Phase 2 overlay if active).
3. Applies floors and ceilings; redistributes overflow.
4. Applies turnover dampening (±25% per strategy max weekly move).
5. Publishes the new weights to Redis key `portfolio:allocation:{strategy_id}` (per-strategy).
6. Publishes a `portfolio.allocation.updated` event on the ZMQ bus for observability.
7. The `PerStrategyExposureGuard` (STEP 6 of the VETO chain, §8.2) reads the new weights on subsequent orders.

The rebalance itself does not generate trades directly — it updates the **capacity envelope** each strategy trades within. Strategies then naturally drift toward the new envelope as they open and close positions.

### 6.6 Allocator observability

The allocator's decisions are fully logged and observable:

- Every rebalance publishes the full input (per-strategy sigma, current weights, target weights), output (post-floor/ceiling/damping weights), and algorithm metadata (Phase 1 vs Phase 2, overlay inactive / active, elevated ceilings) to `structlog` and the ZMQ bus.
- The `services/ops/monitor_dashboard/` exposes a per-strategy allocation timeline.
- Historical allocations are persisted to TimescaleDB for attribution analysis.
- Any deviation between computed weight and actual exposure > 5% triggers a reconciliation alert (stale positions, open orders, etc.).

---

## §7 — Strategy Lifecycle Overview

Every strategy deployed on APEX passes through a **four-gate lifecycle**. Progression is **trigger-based** — a strategy advances only when validation gates are passed. There are no calendar deadlines. A strategy that cannot pass Gate 2 does not deploy to paper regardless of how many weeks have elapsed; a strategy that fails Gate 4 does not return to full allocation regardless of how eager the operator is.

This section provides a **high-level overview** of the gates and the criteria. The **full operational playbook** — who does what, how the evidence is gathered, what the handoff looks like between gates, which Claude Code agents are invoked at which step — lives in Document 2 (`docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`, to be written). This Charter defines **what** the gates require; Document 2 defines **how** they are operated.

### 7.1 Gate 1 — Research → Approved Backtest

A candidate strategy is promoted from research (idea, prototype, informal backtest) to a formal backtest approved for the next gate only when **all** of the following criteria are satisfied:

- **Documented thesis** with ≥ 1 academic reference (peer-reviewed paper or equivalent standing — textbook, CFA research material).
- **Historical backtest** on **minimum 2 years of data**.
- **Historical Sharpe > 1.0** (in-sample; this is a minimum bar, not a license to deploy).
- **Historical max DD < 15%**.
- **PSR (Probabilistic Sharpe Ratio, Bailey & Lopez de Prado 2014) > 95%** — strong evidence the observed Sharpe is not a pure backtest artifact.
- **PBO (Probability of Backtest Overfitting, Bailey et al. 2014) < 0.5** — the backtest is not obviously over-fit.

Strategies failing any criterion are returned to the research pool with documented reasons. They may re-enter Gate 1 with modified specifications after substantive revision.

### 7.2 Gate 2 — Backtest → Paper Trading

A strategy is promoted from approved backtest to paper trading only when **all** of the following are satisfied:

- **CPCV walk-forward OOS Sharpe > 0.8** — the strategy has been validated on combinatorial purged cross-validation (Bailey, Borwein, Lopez de Prado & Zhu 2014; implemented at [`backtesting/walk_forward.py:374`](../../backtesting/walk_forward.py) as `CombinatorialPurgedCV`). OOS Sharpe below this floor means the strategy does not deploy, regardless of in-sample performance.
- **Stress tests — 10 scenarios passed.** Scenarios include: flash crash (-20% in 1 day), volatility spike (VIX × 2 in one session), major central-bank surprise (Fed ±100bps, SNB unpeg-equivalent), major geopolitical event (oil price ±15%), liquidity evaporation (bid-ask spread × 10), correlation breakdown (cross-asset correlation spike to 0.9). Each scenario is simulated ex-post on historical analog dates; "passed" means portfolio DD remains within category budget.
- **Human code review + Copilot auto-review** on the strategy microservice's pull request. Both must be cleared.
- **Unit and integration test coverage ≥ 90%** on the new strategy microservice (exceeds the platform's 85% floor — a higher bar for new-strategy code reflects its critical-path nature).
- **Operational deployment in the multi-strat infrastructure** is functional — the microservice starts, heartbeats, subscribes to panels, publishes `order.candidate` with `strategy_id`, and the allocator sees it.

Strategies failing any criterion return to research with specific remediation requirements.

### 7.3 Gate 3 — Paper Trading → Live Micro

A strategy is promoted from paper to live-micro capital deployment only when **all** of the following are satisfied:

- **Minimum 8 weeks paper trading** — a **floor**, not a ceiling. More is welcome; less is insufficient.
- **Minimum 50 trades** over the period for statistical significance. Lower trade counts produce too-wide confidence intervals on Sharpe and win rate.
- **Paper Sharpe > 0.8** over the period.
- **Paper max DD < 10%** over the period.
- **Win rate consistent with backtest (±10%)** — significant divergence from backtest expectations flags implementation issues or regime mismatch.
- **Zero pod crash** during the period — no container restarts, no unhandled exceptions, no heartbeat misses > 60s. This is a pure operational-discipline gate.
- **Observability green in the Monitor Dashboard** — per-strategy panels functional, no alerting anomalies, drift monitor baseline captured.

### 7.4 Gate 4 — Live Micro → Live Full

Live-micro deployment begins at **20% of target allocation** — the cold-start ramp specified in §6.1.3. Over 60 days, the allocation ramps linearly to 100% **unless** performance is insufficient, in which case Gate 4 demands:

- **After 60 days**: if **live Sharpe > 70% of paper Sharpe**, the strategy proceeds to full allocation and standard Risk-Parity-based sizing.
- **Otherwise**: the strategy stays at 20% in **observation mode** until the CIO makes a manual decision — continue in observation, return to paper, or decommission.

The 70% threshold encodes an expectation that live trading will show some **paper-to-live decay** (due to slippage, queue priority, and sub-millisecond frictions not fully captured in paper simulation) but not severe decay. A strategy whose live Sharpe is below 70% of its paper Sharpe is either structurally broken (a hidden implementation issue) or was paper-overfit (the paper environment was more generous than reality). Either way, scaling to full allocation is not justified.

### 7.5 Deployment order

The six boot strategies deploy in the sequence documented in §4:

1. Crypto Momentum
2. Trend Following multi-asset
3. Mean Reversion Intraday Equities
4. Volatility Risk Premium
5. Macro Carry
6. News-driven

Each strategy runs through all four gates independently. Strategies do **not** run in lockstep; Strategy #2 can be in Gate 3 (paper) while Strategy #1 is in Gate 4 (live full) and Strategy #3 is still in Gate 1 (backtest). The gates are per-strategy, not per-phase.

### 7.6 Extensibility — the backlog is open

The six boot strategies are not a closed set. The Charter explicitly permits additional strategies to be added at any time, following the same four-gate lifecycle. Candidates can be sourced from:

- Academic literature (new papers documenting previously unrecognized edges).
- Internal research spikes (features developed for one strategy revealing an edge that warrants its own strategy).
- Market observation (a regime change creating an opportunity that did not exist at Charter time).

New-strategy candidates are evaluated by the CIO against Principle 1 (does this improve long-term cash generation?), Principle 2 (is the thesis academically defensible?), and Principle 7 (would a senior quant take this seriously?). Candidates that clear the informal "worth building" bar then enter Gate 1 formally.

### 7.7 Failure modes and the research re-entry path

A strategy can fail at any gate. The failure modes are designed to be **recoverable** without destroying prior work:

- **Fail Gate 1 (backtest not compelling)**: return to research; the repository of research code and backtest infrastructure is preserved; re-enter when the thesis is sharpened.
- **Fail Gate 2 (CPCV OOS insufficient)**: return to research; the strategy may have been over-fit to in-sample; revision means reducing feature count, simplifying thresholds, or retiring the strategy.
- **Fail Gate 3 (paper underperforms backtest)**: return to research; significant divergence between backtest and paper usually indicates implementation issues or regime mismatch.
- **Fail Gate 4 (live underperforms paper)**: enter observation mode; the CIO decides whether to decommission or to hold at 20% for extended evaluation.

Strategies that have been decommissioned can be reactivated — see §9.2 for the reactivation protocol.

---

## §8 — Defense in Depth — Circuit Breakers and VETO

APEX operates on the principle that **no single failure should halt the whole platform, and no single success should be allowed to bypass platform-wide safety**. The defense-in-depth architecture consists of two complementary layers: a **two-tier circuit breaker** that manages in-flight drawdowns and operational-health triggers, and a **seven-step Chain of Responsibility VETO** that approves or blocks every candidate order.

Both layers operate continuously and automatically. Neither requires human intervention to fire; human intervention is required only to clear a tripped state.

### 8.1 The two-tier circuit breaker model (Q6)

The circuit breaker architecture distinguishes **per-strategy soft breakers** from **portfolio-wide hard breakers**.

#### 8.1.1 Per-strategy soft circuit breakers

These fire on a single strategy, do not affect the other strategies, and can be configured per-strategy (with documented category-based defaults). They are **soft** — they reduce or pause a strategy, they do not declare a platform-wide emergency.

| Trigger | Action |
|---|---|
| Drawdown strategy > 8% over 24h | Kelly fraction × 0.5 (halves position sizes) |
| Drawdown strategy > 12% over 24h | Pause strategy for 24h (no new orders; existing positions managed per stop/target logic) |
| Drawdown strategy > 15% over 72h | Strategy enters `review_mode` — allocation floors at 5%, CIO decision required to continue |
| Win rate < 25% over last 50 trades | Alert (to dashboard) + Kelly fraction × 0.75 |
| Pod crash / heartbeat miss > 60s | Pause strategy until manual recovery (no auto-restart on soft pause) |

These triggers are **per-strategy**. Crypto Momentum going to Kelly × 0.5 does not affect Mean Rev Equities or VRP. The allocator is informed of the pause/review-mode state and redistributes capital to the other active strategies proportionally.

#### 8.1.2 Portfolio-wide hard circuit breakers

These fire when portfolio-level conditions cross critical thresholds. They are **hard** — they halt all trading across all strategies until a human (the CIO) clears the state.

| Trigger | Action |
|---|---|
| Portfolio total drawdown > 12% over 24h | Halt **all** strategies. Human review required to resume. |
| Portfolio total drawdown > 15% over 72h | Halt all + **48-hour mandatory cooling period** (no resume before 48h elapsed, regardless of review completion) |
| 3+ strategies in DEGRADED simultaneously | Halt all (hidden correlations likely) |
| Portfolio 1-day VaR > 8% | Alert (critical) + aggressive Kelly reduction across board (all active strategies move to Kelly × 0.5 immediately) |

The third trigger — 3+ strategies DEGRADED simultaneously — is the Charter's institutional recognition that **correlation breakdowns are the failure mode most likely to destroy a multi-strategy portfolio**. When three or more nominally-independent strategies degrade together, the correlation assumption under which they were diversified has failed; the portfolio is exposed to a common underlying risk that was not in the risk model. The appropriate response is to stop trading and investigate, not to continue optimizing within the broken model.

The **48-hour mandatory cooling period** after a 15%-over-72h portfolio drawdown enforces a pause for human judgment. Re-enabling trading within 48h would typically be a psychological-reaction restart ("let me recover what I lost") — precisely the pattern that drives revenge trading and compounding losses. Mandatory cooling prevents this.

### 8.2 The seven-step VETO — Chain of Responsibility

Every `OrderCandidate` produced by a strategy microservice passes through a **seven-step chain** before it can become an `ApprovedOrder` consumed by the execution engine. The chain is designed so that earlier steps check **global** conditions (all-or-nothing rejection across strategies) and later steps check **per-strategy** conditions. Failure at any step rejects the candidate.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                Chain of Responsibility — VETO (7 steps)                      │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STEP 0: FailClosedGuard             [GLOBAL]  all-or-nothing (ADR-0006)     │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 1: CBEventGuard                [GLOBAL]  all-or-nothing (CB blackouts) │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 2: PortfolioCircuitBreaker     [GLOBAL]  all-or-nothing (hard CB)      │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 3: StrategyHealthCheck         [PER-STRAT]  is THIS strat paused?      │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 4: MetaLabelGate               [PER-STRAT]  uses strat's model card    │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 5: PerStrategyPositionRules    [PER-STRAT]  max size / correlation     │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 6: PerStrategyExposureGuard    [PER-STRAT]  budget allocation          │
│           │                                                                  │
│           ▼                                                                  │
│  STEP 7: PortfolioExposureMonitor    [GLOBAL]  portfolio-level threshold?    │
│           │                                                                  │
│           ▼                                                                  │
│      order.approved   or   order.blocked (with first failure reason)         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Notes:

- **Failure at STEP 0, 1, 2, or 7 → GLOBAL rejection** (affects all strategies for as long as the condition holds). For STEP 0–2, the rejection is the visible effect of a platform-wide state (fail-closed, blackout, halted). For STEP 7, the rejection is per-order but the reason is portfolio-level (e.g., this order would push total exposure past a shared threshold).
- **Failure at STEP 3, 4, 5, or 6 → PER-STRATEGY rejection**. Other strategies continue to submit and approve orders normally.
- STEP 0 (`FailClosedGuard`) is governed by [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md). The Charter inherits its three-state machine (HEALTHY / DEGRADED / UNAVAILABLE) verbatim.
- STEP 1 (`CBEventGuard`) blocks new trades in the 45-minute window before a scheduled central bank announcement (Fed, ECB, BoJ, BoE, SNB) for affected asset classes. Already implemented in [`services/s05_risk_manager/cb_event_guard.py`](../../services/s05_risk_manager/).
- STEP 2 (`PortfolioCircuitBreaker`) enforces the hard global circuit breakers from §8.1.2.
- STEP 3 (`StrategyHealthCheck`) — new, per-Charter — checks the strategy's own health: is it in `review_mode`, is it paused, is its soft circuit breaker tripped?
- STEP 4 (`MetaLabelGate`) — already present — uses each strategy's meta-labeler model card to veto low-confidence signals. With per-strategy model cards (`meta_label:latest:{strategy_id}:{symbol}`), this step becomes strategy-aware.
- STEP 5 (`PerStrategyPositionRules`) — new — enforces per-strategy max position size, max inter-position correlation within the strategy, max open positions.
- STEP 6 (`PerStrategyExposureGuard`) — new — enforces the per-strategy capital budget from the allocator. If this order would push the strategy's notional exposure past its current allocation, reject.
- STEP 7 (`PortfolioExposureMonitor`) — existing, extended — enforces portfolio-level exposure limits across all strategies (e.g., total long exposure, total leverage, total concentration per asset class).

The first failure wins — the chain short-circuits on the first rejection, records the `BlockReason`, and publishes on `order.blocked`. The audit trail records which guard fired, at which step, with what context.

### 8.3 Rationale — isolation within defense in depth

The chain's structure embodies a deliberate principle: **isolation where possible, global where necessary**. Per-strategy guards (STEPS 3–6) keep one strategy's issues from affecting the others. Global guards (STEPS 0–2 and 7) recognize that some conditions — a fail-closed state, a central bank blackout, a platform-wide drawdown — require platform-wide response regardless of any individual strategy's conviction.

This is the same structural principle that animates the circuit breakers themselves (soft per-strategy, hard global). Both layers — circuit breakers and the VETO chain — project the same isolation-within-defense-in-depth model onto their respective scales.

### 8.4 Worked example — Strategy X exceeds 8% drawdown

Strategy X = Crypto Momentum. It has been live for three weeks. Over a 24-hour period, it loses 8.5% of its allocated capital (BTC sold off hard; its long positions unwound at stops).

Sequence of events:

1. Realized PnL updates in the research feedback loop. Drawdown calculation: `strategy_dd_24h = 8.5%`.
2. The feedback loop publishes `feedback.strategy_dd_alert` on the ZMQ bus, with `strategy_id = "crypto_momentum"`, `drawdown = 0.085`, `threshold_triggered = "soft_dd_24h_8pct"`.
3. The allocator subscribes; it applies `kelly_adjust = 0.5` to the strategy's Kelly fraction for future orders. The strategy continues trading, but with half-sized positions.
4. The `services/ops/monitor_dashboard/` receives the alert and surfaces it to the dashboard.
5. Over the next 24h, the strategy either stabilizes (Kelly × 0.5 takes effect; new drawdowns are dampened) or continues to drawdown. If drawdown crosses 12% within 24h, the strategy pauses fully (new threshold → STEP 3 rejects all candidates for 24h).
6. Meanwhile, Strategies #2–#6 continue trading at normal Kelly, normal allocation. The allocator redistributes some of Strategy #1's reduced effective allocation to other strategies proportionally (because the Kelly halving reduces Strategy #1's *used* capital, freeing capacity to others within the ceiling constraints).
7. If the drawdown resolves (positions close profitably, drawdown recovers below 8%), the Kelly adjustment is **not** automatically restored. Restoration requires a clean 24-hour window with no soft-breaker triggers.

The worked example illustrates that a single strategy's drawdown does not halt the platform. The platform preserves optionality by reducing the affected strategy while letting the rest operate.

### 8.5 Worked example — portfolio drawdown hits 12%

Aggregate portfolio drawdown: losses across multiple strategies compound. Over a 24-hour window, portfolio drawdown reaches -12.1% (the hard trigger).

Sequence of events:

1. The portfolio drawdown calculation (in the research feedback loop or an `PortfolioPnLTracker` module) crosses the threshold.
2. A `portfolio.circuit.hard_tripped` event publishes on the bus.
3. STEP 2 of the VETO chain (`PortfolioCircuitBreaker`) starts rejecting **all** incoming `OrderCandidate` messages across all strategies immediately.
4. The `services/portfolio/strategy_allocator/` is informed; it suspends further rebalancing (the portfolio is in halt state).
5. The monitor dashboard surfaces a critical alert: "PORTFOLIO HALT — -12% DD 24h". The alert engine pages the operator (per [CLAUDE.md](../../CLAUDE.md) §14).
6. Existing open positions are **not** automatically closed — closing them is a separate human decision, informed by the nature of the drawdown (is the market stabilizing, or is continued exposure the real risk?). Strategies can still manage existing positions (stops, profit targets) via pre-authorized logic; they cannot open new ones.
7. The CIO reviews the halt. Documents the cause. Either clears the halt (trading resumes across all strategies simultaneously) or extends it. If the separate 72h drawdown condition is also tripped (> -15% over 72h), the 48h cooling period applies regardless of CIO wish.

### 8.6 Worked example — FailClosedGuard trips during normal trading

Normal trading day. The Redis `risk:heartbeat` key TTL (5s) expires because the heartbeat refresher task in `services/portfolio/risk_manager/` has hung (say, a rare scheduling issue).

Sequence of events:

1. The next incoming `OrderCandidate` triggers the `FailClosedGuard` at STEP 0 to read `risk:heartbeat`. Read returns absent / stale.
2. `SystemRiskState` transitions HEALTHY → DEGRADED.
3. A `risk.system.state_change` event publishes on the bus (per [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) D5).
4. 100% of incoming `OrderCandidate` messages are rejected from this moment on. Existing open positions are unaffected (they are managed by the execution engine's own stop/target logic, which does not run through the VETO chain).
5. The monitor dashboard surfaces the DEGRADED state; an alert pages the operator.
6. The operator investigates: typically, the heartbeat task has hung due to an unhandled exception in a dependency or a scheduler issue. The fix is to restart the risk manager service.
7. On restart, `SystemRiskMonitor` writes the first heartbeat eagerly inside `on_start()` (per [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) §3 Negative / Mitigation), transitioning the state back to HEALTHY before any `OrderCandidate` arrives. Trading resumes.

The worked example demonstrates the fail-closed principle in action: the platform declined to trade because it could not verify its inputs, exactly as designed. The alternative — fail-open — would have silently continued trading on stale state, Knight Capital-style. The visible cost (a brief period of rejected orders during the issue) is vastly preferable to the invisible cost of trading on unknown-state.

### 8.7 Interaction — circuit breakers and decommissioning rules

The circuit breakers are **in-trading** controls; they modulate live behavior on a minute-to-hour timescale. The decommissioning rules (§9.2) are **platform-level** controls; they make month-to-quarter decisions about whether a strategy stays in the platform at all.

The two interact as follows:

- A strategy in `review_mode` (having crossed a soft circuit-breaker threshold over 72h) that does not recover within 90 days triggers decommissioning rule #3 (§9.2).
- A strategy with Sharpe < 0 over 9 months triggers `review_mode` entry (from the Sharpe overlay side, §6.2.4) AND decommissioning rule #1 (§9.2).
- Decommissioning rules act on evidence; circuit breakers act on thresholds. Both are necessary; neither subsumes the other.

---

## §9 — Risk, Performance, and Operational Budgets

### 9.1 Three categories — Low Vol, Medium Vol, High Vol

Every strategy inherits risk and performance budgets from one of three categories. The category assignment is made when the strategy is accepted at Gate 2 (backtest → paper) and can be overridden per-strategy in `config/strategies/{strategy_id}.yaml` with documented justification in Document 2.

| Category | Strategies (at Charter) | Max DD | Min Sharpe | Max Leverage |
|---|---|---|---|---|
| **Low Vol** | Mean Rev Equities, Macro Carry | **8%** | **1.0** | **1×** |
| **Medium Vol** | Crypto Momentum, Trend Following, News-driven | **12%** | **0.8** | **1×** |
| **High Vol** | Volatility Risk Premium | **20%** | **0.6** | **1.5×** |

**Semantics:**

- **Max DD** is the strategy's **own** maximum allowable drawdown from its own peak. Breaching triggers soft circuit breakers (§8.1.1) and, if persistent, decommissioning (§9.2).
- **Min Sharpe** is the rolling 6-month Sharpe (EMA-smoothed) below which the strategy enters `review_mode`.
- **Max Leverage** is the maximum ratio of notional exposure to allocated capital for the strategy.

The categories encode a **Sharpe-drawdown tradeoff**: Low Vol strategies are held to tight drawdowns *because* the operator expects high Sharpe from them; High Vol strategies are permitted wide drawdowns *because* the operator expects lower Sharpe and wants to give the strategy room to breathe through vol spikes.

### 9.2 Tolerant decommissioning rules

The Charter adopts a **tolerant** (not aggressive) decommissioning model. Tolerance recognizes that strategies go through quiet periods, that 6-month Sharpe windows are noisy estimators, and that institutional practice does not decommission on the first bad quarter. The model also recognizes that extended underperformance is data, not merely noise, and must eventually trigger action.

| # | Rule | Action |
|---|---|---|
| 1 | Sharpe < 0 over **9 consecutive months** | Strategy enters `review_mode` (allocation floor 5%) |
| 2 | Sharpe < -0.5 over **6 consecutive months** | Strategy enters `review_mode` immediately |
| 3 | **> 90 days in `review_mode`** without recovery | Strategy is **decommissioned** |
| 4 | Drawdown **> 20% peak-to-trough since inception** | Strategy is **auto-decommissioned** |
| 5 | **3 hard global CB trips** triggered by the same strategy within 6 months | Strategy is **decommissioned** |
| 6 | CIO discretionary decision (with documented reason) — any time | Strategy is **decommissioned** |

`review_mode` semantics:

- Allocation floors at 5%. The allocator excludes the strategy from Phase 2 Sharpe-overlay upward tilts.
- The CIO is required to make a continuation decision within 90 days — either clear `review_mode` (with documented reason — e.g., "regime changed, edge is viable again") or accept decommissioning.
- The strategy continues to trade (at 5% allocation) during `review_mode` to accumulate evidence either way.

Decommissioning semantics:

- The strategy microservice is stopped. Its Docker container is halted. Allocation is redistributed to active strategies.
- Historical trades, logs, and configuration are preserved for post-mortem analysis.
- The strategy may be reactivated (§9.3) if the reactivation protocol is passed.

### 9.3 Reactivation protocol

A decommissioned strategy may be reactivated after **6 months** if **all three** of the following are satisfied:

- **Root cause identified and corrected.** The failure mode (regime mismatch, implementation bug, data-source issue, edge decay) is understood, documented, and remediated in code or configuration.
- **New backtest passed.** The strategy, in its corrected form, passes Gate 1 and Gate 2 again from scratch — no grandfathering from the pre-decommissioning history.
- **New 8-week paper trading passed.** Gate 3 is re-run from scratch.

Reactivation is not automatic. It is a CIO decision, ratified by a PR that updates the strategy's config, re-adds it to the supervisor startup list, and records the reactivation in `docs/claude_memory/DECISIONS.md`.

### 9.4 Discretionary CIO override

Rule #6 in §9.2 recognizes that the CIO may decommission a strategy at any time with documented reason, bypassing the tolerance thresholds. The documented reason must be specific (e.g., "regulatory risk emerging," "discovered that the edge is an artifact of a data vendor bug," "the strategy is operationally too expensive relative to its contribution"). "Gut feeling" is not acceptable; the CIO's discretion is bounded by the requirement to write down the reason.

Conversely, the CIO does **not** have discretionary power to *prevent* a decommissioning triggered by rules #1–#5. Those rules are mechanical and encode the platform's discipline. Overriding them would require a Charter amendment.

### 9.5 Category reassignment

A strategy may be reassigned to a different category during its operation based on live evidence:

- **Promotion**: a Medium Vol strategy with a persistent live Sharpe > 1.5 and max DD < 8% over ≥ 12 months may be reclassified as Low Vol — which tightens its DD tolerance but raises its Sharpe expectation. Promotion is CIO-ratified.
- **Demotion**: a Low Vol strategy that consistently operates in the Medium-Vol drawdown range (8–12%) should be reclassified as Medium Vol to avoid artificial `review_mode` triggers. Demotion is CIO-ratified with documented reason.

Category reassignments are rare and require ADR-level documentation (the category system is the platform's risk-budgeting backbone; changing a strategy's category is an architectural change).

### 9.6 Semi-annual review cadence

Every six months, the CIO conducts a **formal review** of the multi-strategy portfolio:

- Per-strategy Sharpe, DD, win rate, turnover, and cost breakdown.
- Allocator behavior — does the Risk Parity plus Sharpe overlay allocation appear to be tracking reality?
- Cross-strategy correlation matrix (targeted < 0.3, §10.3).
- Category assignments — are any strategies operating systematically outside their category bounds?
- Active `review_mode` strategies — path to exit or decommission?
- Emerging strategies in the backlog — any ready to enter Gate 1?
- Infrastructure — any Phase 7.5 work justified by live benchmarks?

Reviews are documented in `docs/claude_memory/SESSIONS.md` and, if they produce binding decisions, in `docs/claude_memory/DECISIONS.md` and a Charter version bump.

### 9.7 Emergency review triggers

Outside the semi-annual cadence, an immediate Charter review is triggered by:

- 3+ strategies decommissioned within 12 months (suggests the platform's discipline is mis-calibrated).
- Portfolio hard circuit breaker tripped 3+ times within 12 months (suggests the platform's risk model is mis-calibrated).
- Multi-strategy platform fundamentally blocking a desired strategy deployment (suggests the Charter has ossified).

Any of these triggers a special session to revisit principles, categories, gates, and allocator behavior.

---

## §10 — Benchmarks and Success Criteria

The platform is measured against three benchmark levels, ascending in ambition. Each level is defined by a small set of **simultaneous** criteria — all criteria in a level must hold for the level to be achieved. Levels are **not mutually exclusive**; a mature platform satisfies all three simultaneously. Failure to meet the **lower** levels is the strongest evidence that the platform should not be trading real capital at its current scale.

### 10.1 Level 1 — Survival Benchmark

The **absolute minimum** justifying live trading. If the platform cannot meet Survival, it should not be trading real capital; paper trading should continue until Survival is cleared.

| Criterion | Threshold |
|---|---|
| Net annualized return | **> 15%** |
| Sharpe ratio (net) | **> 1.0** |
| Maximum drawdown | **< 15%** |

All three must hold simultaneously.

**Rationale.** The CIO has stated 15% annualized as the personal-capital return target justifying the engineering investment. Sharpe > 1.0 distinguishes the returns from a pure momentum beta capture. Max DD < 15% ensures that a single drawdown does not wipe out the compounding accumulated from prior returns. These are the *defensive* benchmarks.

**Relationship to allocation.** Meeting Survival in paper trading is a prerequisite for Gate 3 → Live Micro on the first strategy. Meeting Survival in live trading after the first 90 days is a prerequisite for scaling the first strategy to full allocation and for beginning Gate 1 on the second strategy.

### 10.2 Level 2 — Legitimacy Benchmark

The **distinguishes-from-buy-and-hold** level. Reaching Legitimacy means the platform is generating genuine alpha, not levered beta dressed as sophistication.

| Criterion | Threshold |
|---|---|
| Alpha vs equal-weight BTC+ETH+SPY benchmark | **> 10% annualized** |
| Beta vs same benchmark | **< 0.5** |
| Sharpe (net) | **> 1.5** |

All three must hold simultaneously over a rolling 12-month window.

**Rationale.** A 15% return is impressive only if it exceeds what a trivial 1/3-1/3-1/3 rebalanced passive portfolio would have delivered. Legitimacy demands +10% alpha over that passive benchmark and a beta below 0.5 — decorrelated return, not levered crypto beta. Sharpe > 1.5 is the level at which a senior institutional reviewer at a family office or fund-of-funds would start taking an edge claim seriously.

**Target timeline**. Achievable at 12 months if Strategies #1–#3 are each meeting their Medium/Low Vol category requirements live.

### 10.3 Level 3 — Institutional Benchmark

The **target at 18–24 months**. Institutional-grade multi-strategy platform, defensible to a sophisticated allocator reviewer.

| Criterion | Threshold |
|---|---|
| Net Sharpe (rolling 12 months) | **> 2.0** |
| Maximum drawdown | **< 10%** |
| Average cross-strategy correlation (off-diagonal) | **< 0.3** |

All three must hold simultaneously.

**Rationale.** Sharpe > 2.0 is the level at which external capital allocators (if ever relevant) would take the platform seriously. Max DD < 10% is tighter than Survival's 15% — the platform has matured. Cross-strategy correlation < 0.3 is the mathematical statement that the multi-strategy design is *real*, not cosmetic — the strategies are genuinely independent contributors to the portfolio's return, and the Fundamental Law of Active Management (§3.4) is being fully leveraged.

**Target timeline**. Achievable at 18–24 months if four or more strategies are live, passing their category budgets, and contributing uncorrelated returns.

### 10.4 How the levels translate to allocation decisions

- **Sub-Survival**: the platform does not trade real capital. All six strategies operate in paper, or in deep-investigation mode. No live micro deploys until at least one strategy clears Survival in paper.
- **Survival achieved on Strategy #1**: Strategy #1 moves to live-micro (Gate 3 → Gate 4). Other strategies continue through the pipeline normally.
- **Legitimacy achieved**: the platform's multi-strategy thesis is validated. Deployment of Strategies #4–#6 proceeds with confidence; allocator Phase 2 Sharpe overlay can be considered if data supports it.
- **Institutional achieved**: the platform is mature. New-strategy additions are measured by their contribution to the platform, not just their own performance. Allocator considers Black-Litterman or regime-conditional variants (ADR-level decision).

### 10.5 Evolution expectation over 12, 18, 24 months

| Month | Active strategies | Benchmark target | Allocator |
|---|---|---|---|
| 0–9 | 1 (Crypto Momentum paper) | Survival in paper | None (100% Strategy #1 in paper) |
| 9–15 | 1–2 live (Crypto Momentum, Trend Following) | Survival in live micro; Legitimacy on rolling basis | Phase 1 Risk Parity |
| 15–20 | 3–4 live | Legitimacy; approaching Institutional | Phase 1 → Phase 2 Sharpe overlay (if data supports) |
| 20–24 | 4–6 live | Institutional | Phase 2 Sharpe overlay; regime-conditional variants under research |

These are *targets*, not *promises*. Markets will push some strategies forward faster than others; some strategies will fail Gate 2 and be returned to research. The Charter's job is to encode the framework within which the unpredictable details resolve — not to pretend the unpredictable is scheduled.

### 10.6 Relationship to CLAUDE.md §6 thresholds

[CLAUDE.md](../../CLAUDE.md) §6 enumerates CI backtest-gate thresholds (Sharpe ≥ 0.8, max DD ≤ 8%) and paper-to-live transition criteria (see MANIFEST.md §15 — paper Sharpe > 1.5, max DD < 5%, ≥ 3 consecutive months). These are **single-strategy** operational thresholds applied at the Gate level.

The Charter's benchmark ladder (§10.1–10.3) is **platform-level** aggregate — the combined performance of all live strategies under the allocator. The two are not redundant; they measure different things:

- Gate thresholds gate individual strategies' progression.
- Platform benchmarks gauge the whole portfolio's performance.

A strategy passing its Gate 3 Sharpe > 0.8 threshold is a precondition for it to contribute to the platform-level benchmarks. A platform achieving Institutional benchmark (Sharpe > 2.0) with strategies that each individually cluster around Gate-3-floor (0.8) is possible precisely because of diversification — the Fundamental Law of Active Management (§3.4) formalizes this.

---

## §11 — Extensibility Principle

### 11.1 The backlog is open

The Charter explicitly makes the strategy backlog **open**. The six boot strategies are not the end state; they are the launch set. The platform is built to host many more strategies over its lifetime, entering and leaving as edges are discovered and as edges decay.

### 11.2 Sourcing new candidates

Legitimate sources for new-strategy candidates:

- **Academic literature.** New papers documenting previously unrecognized edges (e.g., the recent wave of research on cryptocurrency microstructure, on options volatility surface alpha, on text-as-data signals). Every new candidate cites at least one peer-reviewed paper or equivalent.
- **Internal research spike.** During the work on Strategy #N, a feature or analysis reveals an exploitable pattern that is orthogonal to Strategy #N's thesis. The CIO decides whether to bolt the feature into Strategy #N or to spin it out as Strategy #(N+1).
- **Market observation.** A regime change creates a systematic opportunity that did not exist at Charter time (e.g., a new asset class becoming liquid, a new correlation regime opening a new carry).
- **Reactivation of a decommissioned strategy.** Per §9.3.

Speculative "what if..." ideas are not candidates until they satisfy at least **one** of the above.

### 11.3 Validation bar for new candidates

Regardless of source, every new candidate enters **Gate 1** and must satisfy the full criteria (§7.1): academic reference, 2+ years of data, Sharpe > 1.0, max DD < 15%, PSR > 95%, PBO < 0.5. No grandfathering, no "we know this will work" exceptions. Retail-style shortcutting at this gate (Principle 2) is the principal mechanism by which multi-strategy platforms accumulate low-quality strategies; the Charter's rigor here is non-negotiable.

### 11.4 Capacity considerations

The platform is designed at solo-operator scale to host up to approximately **10–15 concurrent strategies** before infrastructure burden becomes material. Beyond that, operational complexity (container orchestration, alerting triage, data-feed coordination) begins to exceed one operator's bandwidth. If the platform nears the capacity limit, the Charter explicitly authorizes **retiring low-contribution strategies** (rule #6 of §9.2, CIO discretion) in favor of higher-potential candidates. Slots are finite; the decommissioning protocol is the release valve.

### 11.5 Mandatory inclusion of the lifecycle

Every new-strategy candidate, regardless of source or of CIO enthusiasm, **must** transit through the four gates (§7). Skipping a gate is a Charter violation. The validation bar exists specifically because a solo operator is most tempted to skip gates precisely when excitement about a new idea is highest — which is when overfitting is most likely.

---

## §12 — Relationship to Other Documents

The Charter is one of three documents that jointly govern the multi-strategy platform. Each has a distinct role; together they cover what, how, and when.

### 12.1 The three-document structure

| Document | Role | Relationship |
|---|---|---|
| **Document 1: Charter** (this) | **Constitutional** — what the platform is and why | Binds all others |
| **Document 2: Strategy Development Lifecycle Playbook** | **Operational** — how to build, test, deploy, monitor, retire a strategy | Inherits from Charter |
| **Document 3: Phase 5 v3 Multi-Strat Aligned Roadmap** | **Executional** — when and in what order to ship | Inherits from Charter + Document 2 |

### 12.2 Document 2 — `docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`

Not yet written. Will be Mission 2 of 3 after this Charter is ratified.

**Purpose.** The operational playbook. For each of the four gates (§7), it will specify:

- Who performs each evaluation (CIO, Claude Code agent, CI system).
- What evidence must be gathered and in what form (notebook, backtest artifact, PR, ADR).
- Handoff mechanics between gates (the PR template, the dashboard panel, the session log entry).
- The per-strategy Charter — a one-page summary written by the CIO for each strategy at Gate 2, covering overrides from category defaults, specific risk concerns, expected behavior regimes.
- Decommissioning execution — the mechanical checklist when a strategy is decommissioned (stop service, archive logs, document cause, notify allocator).
- Reactivation protocol execution — the checklist when a decommissioned strategy re-enters Gate 1.

**Relationship to this Charter.** Document 2 implements Charter §7. It cannot contradict the Charter; it can only operationalize it. Any conflict means the Charter revises Document 2, not vice versa.

### 12.3 Document 3 — `docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`

Not yet written. Will be Mission 3 of 3 after this Charter is ratified.

**Purpose.** The current execution plan. Updates [PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) to reflect multi-strategy alignment. Sequences the specific multi-strategy infrastructure lift scoped in [MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) P0/P1/P2 items:

- Foundational contract changes (strategy_id field, topic factory, backtest gate un-muzzling).
- Pluggable signal layer (`StrategyRunner` ABC, legacy wrapping).
- Allocator + per-strategy risk.
- Observability + backtest harness.
- Strategy microservice deployment order.
- Phase 5 sub-phase resequencing if the multi-strat lift alters it.

**Relationship to this Charter and Document 2.** Document 3 implements Charter + Document 2's operational content as a time-ordered plan, scheduled against live-platform goals. Any conflict with Charter or Document 2 means Document 3 revises, not vice versa.

### 12.4 ADRs — binding architectural decisions

Each major architectural decision that the Charter relies on or that the infrastructure lift will introduce is captured in an ADR. ADRs are **irreversible without supersession**; a later ADR that supersedes an earlier one must explicitly cite and replace it.

**Existing ADRs (inherited by the Charter):**

- [ADR-0001 — ZMQ Broker (XSUB/XPUB) Topology](../adr/0001-zmq-broker-topology.md)
- [ADR-0002 — Quant Methodology Charter](../adr/0002-quant-methodology-charter.md)
- [ADR-0003 — Universal Data Schema](../adr/ADR-0003-universal-data-schema.md)
- [ADR-0004 — Feature Validation Methodology](../adr/ADR-0004-feature-validation-methodology.md)
- [ADR-0005 — Meta-Labeling and Fusion Methodology](../adr/ADR-0005-meta-labeling-fusion-methodology.md)
- [ADR-0006 — Fail-Closed Pre-Trade Risk Controls](../adr/ADR-0006-fail-closed-risk-controls.md)

**Anticipated new ADRs (to be authored with Document 3):**

- **ADR-0007 — Strategy as Microservice**. Formalizes Q1 (§5.1). Covers the `StrategyRunner` ABC, the per-strategy microservice topology, the `services/strategies/` tree.
- **ADR-0008 — Capital Allocator Topology**. Formalizes Q2 (§5.2). Covers `services/portfolio/strategy_allocator/`, Risk Parity Phase 1, Sharpe overlay Phase 2, trigger conditions for Phase 2 activation.
- **ADR-0009 — Panel Builder Discipline**. Formalizes Q3 (§5.3). Covers `services/data/panels/`, the strategy-subscribes-to-panels rule.
- **ADR-0010 (tentative) — Target Topology Reorganization**. Formalizes §5.4. Covers the migration from S01-S10 to domain-classified folder structure.

### 12.5 Phase specs — current execution scope

[PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) is the current Phase 5 canonical spec. It governs sub-phases 5.1 (DONE), 5.2, 5.3, 5.5, 5.4, 5.8, 5.10. The Charter is **consistent** with PHASE_5_SPEC_v2 in principle but does not duplicate its content; PHASE_5_SPEC_v2 remains the authoritative implementation spec for the in-flight Phase 5 work.

Once Document 3 is authored, it will supersede PHASE_5_SPEC_v2 as the current Phase 5 execution plan, explicitly citing it as the v2 predecessor.

### 12.6 Audits — evidence gathered at a point in time

Audits are read-only evidence-gathering exercises. They inform Charter and ADR decisions; they do not themselves bind the platform.

Key audits referenced by this Charter:

- [STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) — strategic basis for PHASE_5_SPEC_v2.
- [MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) — factual infrastructure readiness evidence, source of the P0/P1/P2 gap list referenced throughout the Charter.
- Redis-keys writer audit (`docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`) — orphan-read evidence that motivates Phase 5.2.

Future audits (semi-annual infrastructure audit, semi-annual correlation audit, ad-hoc audits triggered by emergency review) will follow the same pattern.

### 12.7 Claude memory files

[`docs/claude_memory/CONTEXT.md`](../claude_memory/CONTEXT.md), [`docs/claude_memory/SESSIONS.md`](../claude_memory/SESSIONS.md), [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md), and the phase-notes files ([`docs/claude_memory/PHASE_3_NOTES.md`](../claude_memory/PHASE_3_NOTES.md), forthcoming PHASE_5_NOTES.md) persist cross-session context. The Charter is the binding constitutional layer; the claude_memory tree is the ongoing operational record. On Charter ratification, an entry in `DECISIONS.md` records the ratification.

### 12.8 [MANIFEST.md](../../MANIFEST.md) and [CLAUDE.md](../../CLAUDE.md)

[MANIFEST.md](../../MANIFEST.md) is the technical source of truth for the codebase's architecture, data models, and service contracts. The Charter does not replace it; the Charter governs **what the platform is for** while MANIFEST.md governs **how the platform is built**. Both are binding; they do not conflict because they operate on different levels.

[CLAUDE.md](../../CLAUDE.md) is the non-negotiable development-conventions contract — forbidden patterns, mandatory types, testing requirements, commit conventions. The Charter inherits CLAUDE.md verbatim. No Charter content overrides or softens any CLAUDE.md rule.

### 12.9 Conflict resolution

When the Charter and a downstream document appear to conflict:

1. First, check whether the apparent conflict is actually a **scope difference** (Charter governing the what, downstream document governing the how). Most apparent conflicts are of this type and dissolve on closer reading.
2. If a genuine conflict exists: the Charter prevails, and the downstream document must be revised to align.
3. If the CIO concludes the Charter is the document that should change: a Charter amendment (new ADR + version bump) is opened.

This priority chain ensures that the constitutional layer remains the constitutional layer, and that changes to it are made explicitly rather than by stealth.

---

## §13 — Governance and Revision

### 13.1 Status — ACTIVE and binding

This Charter is **ACTIVE** once merged to main. From that moment forward, every engineering, research, and deployment decision on the platform is bound by it. Deviations require a new ADR and a Charter version bump.

### 13.2 Material changes — what requires a Charter amendment

The following constitute **material changes** and require an ADR plus a version bump:

- Change to any of the **seven binding principles** (§2).
- Change to the **list of six boot strategies** (§4) — addition, removal, replacement, reordering.
- Change to the **capital allocation framework** (§6) — moving from Risk Parity to a different algorithm, changing Phase 2 overlay mechanics, changing floor/ceiling values.
- Change to the **four-gate lifecycle criteria** (§7) — softening or hardening any gate threshold.
- Change to the **two-tier circuit breaker** thresholds (§8.1) or the **seven-step VETO chain** structure (§8.2).
- Change to the **three-category risk/performance budgets** (§9.1) or the **tolerant decommissioning rules** (§9.2).
- Change to any of the **three benchmark levels** (§10).
- Change to the **extensibility principle** (§11).

### 13.3 Non-material changes — no amendment required

Typographical fixes, clarifications that do not alter meaning, additional worked examples, updated cross-references, expanded bibliography — these do not require a version bump. They are landed as PRs with CIO approval and a brief note in the Changelog (§14) at the bottom of this document.

### 13.4 Amendment procedure

To amend the Charter:

1. Open an ADR documenting the proposed change and its alternatives. The ADR must explicitly cite the Charter section being amended and justify the change against the seven binding principles.
2. Draft the Charter revision as a PR modifying this document, with version bump (v1.x → v1.(x+1) for additive clarifications; v1.x → v2.0 for breaking changes).
3. Record the decision in [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
4. CIO reviews and merges.

If the amendment affects Document 2 or Document 3, those documents are revised in the same PR or a follow-up PR.

### 13.5 Review cadence — semi-annual

The Charter is formally reviewed every **six months** as part of the semi-annual portfolio review (§9.6). The review assesses:

- Has any principle proven inadequate or excessive in practice?
- Is the set of six boot strategies still the right set?
- Is the capital allocation framework tracking reality, or has it accumulated bias?
- Are the four gates calibrated correctly, or are strategies over- or under-pressurized?
- Are the circuit breakers catching the right failure modes?
- Are the categories' budgets consistent with live evidence?
- Are the benchmarks realistic given 6 months of live data?

The review produces a short report. If material change is warranted, the amendment procedure (§13.4) is invoked. If not, a no-amendment note is recorded and the Charter continues.

### 13.6 Emergency review triggers (out of cadence)

Three conditions trigger an immediate Charter review outside the semi-annual cadence:

- **≥ 3 strategies decommissioned within 12 months.** Suggests the platform's discipline is mis-calibrated, likely toward excessive pressure.
- **Portfolio hard circuit breaker tripped ≥ 3 times within 12 months.** Suggests the platform's risk model is under-capturing correlated downside.
- **Multi-strategy platform fundamentally blocks a desired strategy deployment.** Suggests the Charter has ossified and is preventing rather than enabling the platform's mission.

Any of these triggers an emergency session in which principles, categories, gates, and allocator behavior are revisited holistically. The outcome is either (a) a confirmation that the platform is working correctly and the external conditions are unusual (documented, no amendment), or (b) a Charter amendment following §13.4.

### 13.7 Roles

- **CIO — Clement Barbier**. Ratifies the Charter, owns every amendment, performs the semi-annual reviews, makes discretionary decisions (category reassignments, rule #6 decommissions, continuation decisions on `review_mode` strategies, emergency halt clearances).
- **Head of Strategy Research — Claude Opus 4.7 (claude.ai)**. Conducts interviews and drafts Charter content; responsible for the Q1–Q8 decisions captured in this document.
- **Head of Architecture Review — Claude Opus 4.7 (claude.ai, Multi-Strat Readiness Audit)**. Produces the read-only audits that ground the Charter in factual evidence.
- **Implementation Lead — Claude Code agents (Sonnet / Opus, executing sessions)**. Implement the Charter, the ADRs, the phase specs; open PRs, pass CI, ship features; operate inside the Charter's constraints and are bound by its principles.

### 13.8 Versioning

This Charter is **v1.0** at ratification.

- **v1.x** — additive clarifications, new worked examples, expanded cross-references.
- **v2.0** — breaking change to any binding element (principles, strategy list, allocation framework, gates, circuit breakers, categories, decommissioning rules, benchmarks, extensibility principle).

Each version is preserved in Git history; previous versions are not deleted.

---

## §14 — Signatures and Ratification

This Charter was drafted through a structured 1-hour interview on 2026-04-18, between:

- **CIO: Clement Barbier** (founder and operator of the APEX / CashMachine platform)
- **Head of Strategy Research: Claude Opus 4.7 (claude.ai)** — acted in the capacity of senior quantitative strategy research, conducting the interview and producing the draft Charter.

The interview produced the eight foundational architectural decisions (Q1–Q8) encoded verbatim in this document.

Factual grounding was provided by:

- **Head of Architecture Review: Claude Opus 4.7 (claude.ai)** — authored the Multi-Strategy Platform Readiness Audit ([MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md)) on 2026-04-18, providing the service inventory, contract surface, ABC inventory, SOLID scorecard, and prioritized gap list that this Charter relies on for evidence of current state.

Implementation authority is held by:

- **Claude Code** (Sonnet / Opus, sessions executing against the APEX repository) — implements the Charter, opens PRs, runs CI, ships features. Bound by the Charter; cannot deviate without triggering the amendment procedure.

### 14.1 Ratification

This Charter is proposed for ratification as of **2026-04-18** (the original interview date) and expected to be merged as **v1.0** into the main branch of the APEX / CashMachine repository upon Clement Barbier's review.

Upon merge:

- An entry is added to [`docs/claude_memory/DECISIONS.md`](../claude_memory/DECISIONS.md).
- The Charter is referenced from [`docs/claude_memory/CONTEXT.md`](../claude_memory/CONTEXT.md) as the binding constitutional document.
- Document 2 (Strategy Development Lifecycle Playbook) authoring begins as Mission 2 of 3.
- Document 3 (Phase 5 v3 Multi-Strat Aligned Roadmap) authoring begins as Mission 3 of 3 once Document 2 is ratified.

### 14.2 Changelog

| Version | Date | Change |
|---|---|---|
| v1.0-draft | 2026-04-18 | Initial draft authored in the docs/strategy-charter-document-1 branch, encoding Q1–Q8 decisions from the 2026-04-18 CIO interview. Awaiting CIO review and ratification. |

---

## §15 — References

### 15.1 Academic

- **Avellaneda, M. & Lee, J.-H.** (2010). "Statistical Arbitrage in the U.S. Equities Market." *Quantitative Finance* 10, 761-782. [Strategy #3 Mean Rev Equities]
- **Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J.** (2014). "The Probability of Backtest Overfitting." *Journal of Computational Finance*. [PBO, CPCV]
- **Bailey, D. H. & Lopez de Prado, M.** (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management* 40(5), 94-107. [PSR / DSR]
- **Bollerslev, T.** (1986). "Generalized Autoregressive Conditional Heteroskedasticity." *Journal of Econometrics*. [GARCH]
- **Carr, P. & Wu, L.** (2009). "Variance Risk Premiums." *Review of Financial Studies* 22, 1311-1341. [Strategy #4 VRP]
- **Clarke, R., de Silva, H. & Thorley, S.** (2002). "Portfolio Constraints and the Fundamental Law of Active Management." *Financial Analysts Journal* 58(5), 48-66. [Transfer coefficient]
- **Cont, R., Kukanov, A. & Stoikov, S.** (2014). "The price impact of order book events." *Journal of Financial Econometrics*. [OFI]
- **Corsi, F.** (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." *Journal of Financial Econometrics* 7, 174-196. [HAR-RV]
- **Easley, D. & O'Hara, M.** (1987). "Price, trade size, and information in securities markets." *Journal of Financial Economics*. [PIN model]
- **Engle, R. & Granger, C.** (1987). "Co-integration and error correction." *Econometrica*. [Cointegration for pair trading]
- **Gatheral, J., Jaisson, T. & Rosenbaum, M.** (2018). "Volatility is rough." *Quantitative Finance*. [Rough vol, Strategy #1 feature]
- **Grinold, R. C. & Kahn, R. N.** (1999). *Active Portfolio Management* (2nd ed.). McGraw-Hill. [Fundamental Law of Active Management]
- **Harvey, C. R., Liu, Y. & Zhu, H.** (2016). "…and the Cross-Section of Expected Returns." *Review of Financial Studies* 29, 5-68. [Multiple testing in factor research]
- **Hawkes, A.** (1971). "Spectra of some self-exciting and mutually exciting point processes." *Biometrika*. [Hawkes process]
- **Hurst, H. E.** (1951). "Long-term storage capacity of reservoirs." *Transactions of the American Society of Civil Engineers*. [Hurst exponent]
- **Jegadeesh, N. & Titman, S.** (1993). "Returns to buying winners and selling losers." *Journal of Finance*. [Momentum baseline]
- **Kakushadze, Z. & Serur, J. A.** (2018). *151 Trading Strategies*. Palgrave Macmillan. [Strategy taxonomy]
- **Kelly, B., Malamud, S. & Zhou, K.** (2023). "The Virtue of Complexity in Return Prediction." *Journal of Finance* — and related text-as-data research. [Strategy #6 foundation]
- **Kelly, J.** (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal* 35(4), 917-926. [Kelly criterion]
- **Kyle, A.** (1985). "Continuous auctions and insider trading." *Econometrica*. [Kyle's lambda]
- **Liu, Y. & Tsyvinski, A.** (2021). "Risk and Return of Cryptocurrency." *Review of Financial Studies* 34, 2689-2727. [Strategy #1 Crypto Momentum]
- **Lo, A. W.** (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal* 58, 36-52. [Sharpe estimation uncertainty]
- **Lopez de Prado, M.** (2018). *Advances in Financial Machine Learning*. Wiley. [Meta-labeling, CPCV, PBO]
- **Lustig, H., Roussanov, N. & Verdelhan, A.** (2011). "Common Risk Factors in Currency Markets." *Review of Financial Studies* 24, 3731-3777. [Strategy #5 Macro Carry]
- **Maillard, S., Roncalli, T. & Teiletche, J.** (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *Journal of Portfolio Management* 36, 60-70. [Risk Parity]
- **Markowitz, H.** (1952). "Portfolio Selection." *Journal of Finance* 7, 77-91. [Foundational diversification]
- **Moskowitz, T. J., Ooi, Y. H. & Pedersen, L. H.** (2012). "Time Series Momentum." *Journal of Financial Economics* 104, 228-250. [Strategy #2 Trend Following]
- **Shefrin, H. & Statman, M.** (1985). "The disposition to sell winners too early." *Journal of Finance*. [Disposition effect]
- **Tetlock, P. C.** (2007). "Giving Content to Investor Sentiment: The Role of Media in the Stock Market." *Journal of Finance* 62, 1139-1168. [Strategy #6 News-driven]
- **Tetlock, P. C., Saar-Tsechansky, M. & Macskassy, S.** (2008). "More Than Words: Quantifying Language to Measure Firms' Fundamentals." *Journal of Finance* 63, 1437-1467. [Text-as-data extension]

### 15.2 Industry / institutional

- **AQR Capital Management** — Risk Parity and Managed Futures publications; multi-asset factor research.
- **Man AHL** — Trend Following and Machine Learning in systematic trading publications.
- **Two Sigma** — technology-first multi-asset panel-based research framework.
- **Millennium Management** — pod model; per-pod risk budget and decommissioning discipline (publicly discussed in industry press).
- **Citadel Multi-Strategy** — isolated pods with centralized risk and allocation.
- **DE Shaw Composite** — systematic plus discretionary overlay in multi-strategy format.
- **Bridgewater All Weather** — macro-aware regime-conditional diversified multi-risk-premia allocation.
- **Renaissance Institutional Equities (RIEF)** — empiricism, microstructure plus longer-horizon patterns.
- **Nygard, M. T.** (2007). *Release It! Design and Deploy Production-Ready Software*. Pragmatic Bookshelf. [Stability patterns, circuit breaker]
- **SEC Rule 15c3-5** (Market Access Rule). 17 CFR § 240.15c3-5. [Pre-trade controls]
- **Knight Capital Group post-mortem** (2012-08-01). SEC Release No. 70694 (2013-10-16). [Fail-open failure mode]

### 15.3 Internal project references

- [MANIFEST.md](../../MANIFEST.md) — canonical technical architecture and data model specification.
- [CLAUDE.md](../../CLAUDE.md) — non-negotiable development conventions.
- [docs/PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md) — current roadmap (pre-Charter state).
- [docs/phases/PHASE_5_SPEC_v2.md](../phases/PHASE_5_SPEC_v2.md) — current Phase 5 canonical execution spec.
- [docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) — strategic basis for Phase 5 v2.
- [docs/audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](../audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md) — infrastructure readiness evidence; source of P0/P1/P2 gap list.
- [docs/adr/0001-zmq-broker-topology.md](../adr/0001-zmq-broker-topology.md) — ZMQ broker topology.
- [docs/adr/0002-quant-methodology-charter.md](../adr/0002-quant-methodology-charter.md) — quant methodology charter.
- [docs/adr/ADR-0003-universal-data-schema.md](../adr/ADR-0003-universal-data-schema.md) — universal data schema.
- [docs/adr/ADR-0004-feature-validation-methodology.md](../adr/ADR-0004-feature-validation-methodology.md) — feature validation methodology.
- [docs/adr/ADR-0005-meta-labeling-fusion-methodology.md](../adr/ADR-0005-meta-labeling-fusion-methodology.md) — meta-labeling and fusion methodology.
- [docs/adr/ADR-0006-fail-closed-risk-controls.md](../adr/ADR-0006-fail-closed-risk-controls.md) — fail-closed pre-trade risk controls.
- [core/topics.py](../../core/topics.py) — centralized ZMQ topic catalog.
- [features/](../../features/) — feature layer (calculators, validation harness, CPCV).
- [backtesting/walk_forward.py](../../backtesting/walk_forward.py) — CPCV walk-forward validator.
- [backtesting/metrics.py](../../backtesting/metrics.py) — `full_report` reporting harness.

### 15.4 External tools

- **GDELT Project 2.0** — https://www.gdeltproject.org/ [Strategy #6]
- **FinBERT** — https://github.com/ProsusAI/finBERT [Strategy #6]
- **ONNX Runtime** — https://onnxruntime.ai/ [FinBERT inference]

---

**END OF CHARTER v1.0-draft.**

*This document awaits CIO ratification. Once merged, it becomes the binding constitutional layer of the APEX Multi-Strategy Platform.*
