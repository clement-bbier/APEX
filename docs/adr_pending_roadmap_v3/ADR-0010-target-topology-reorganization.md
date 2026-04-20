# ADR-0010 — Target Topology Reorganization

> *This ADR is authored as part of Document 3 — [Phase 5 v3 Multi-Strat Aligned Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) (§10.4). It formalizes Charter §5.4 — the retirement of the S01-S10 numbering scheme and the migration to a domain-classified folder structure under `services/{data,signal,portfolio,execution,research,ops,strategies}/`.*
>
> **POST-MERGE ACTION**: on Roadmap v3.0 ratification, this file is moved from `docs/adr_pending_roadmap_v3/` to `docs/adr/` by the CIO (see Roadmap §16.1 note on path protection).

| Field | Value |
|---|---|
| Status | Accepted (on Roadmap v3.0 merge) — physical migration scheduled Phase D.5 (Roadmap §5.5) |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Related | Charter §5.4, §5.9; ADR-0001 (ZMQ broker — preserved); ADR-0007 (strategy microservice); ADR-0008 (allocator); ADR-0009 (panels) |

---

## 1. Context

The current APEX service layout uses a Phase-1 sequential numbering scheme:

```
services/
├── s01_data_ingestion/
├── s02_signal_engine/
├── s03_regime_detector/
├── s04_fusion_engine/
├── s05_risk_manager/
├── s06_execution/
├── s07_quant_analytics/
├── s08_macro_intelligence/
├── s09_feedback_loop/
└── s10_monitor/
```

This numbering reflects the **linear pipeline view** established at platform inception: tick → signal → regime → fusion → risk → execution → analytics → macro → feedback → monitor. At Phase 1 with one strategy, this topology is a reasonable organizing principle.

At the multi-strategy scale (Charter ratified 2026-04-18), the numbering becomes a liability:

- **New services do not fit the numbering**: `services/portfolio/strategy_allocator/` (Charter §5.2, ADR-0008) does not naturally fit at S11; it is a portfolio-domain service, not "the 11th sequential step". Similarly `services/data/panels/` (Charter §5.3, ADR-0009) is a data-domain service, not S11 or S01.5.
- **Strategies do not fit the numbering**: six strategy microservices under `services/strategies/` are not sequential pipeline stages; they are parallel tenants of the platform.
- **Domain reasoning is obscured**: "which services are data producers?" is not answerable from the numbering. Grouping by domain (`data/`, `signal/`, `portfolio/`, etc.) answers it directly.
- **Institutional precedent**: every multi-strategy firm referenced in Charter §1.3 organizes services by domain (data teams, research teams, execution teams, risk teams), not by pipeline position.

Charter §5.4 ratifies the **classification by domain** topology. This ADR formalizes the migration procedure: a staged sequence of `git mv` operations preserving file history, individually revertible, executed as Phase D.5 of the Roadmap (weeks 26-28, after substantive Phase D work completes).

**Principle 6 (functional preservation)** is strictly respected: no code is rewritten; every existing service is **moved** to its new path with its behavior unchanged. Shims at the old paths preserve imports during the transition.

---

## 2. Decision

### D1 — Target topology

The target `services/` tree, per Charter §5.4:

```
services/
├── data/
│   ├── ingestion/           (ex-s01_data_ingestion)
│   ├── panels/              (NEW — ADR-0009)
│   └── macro_intelligence/  (ex-s08_macro_intelligence)
├── signal/
│   ├── engine/              (ex-s02_signal_engine — legacy confluence strategy wrapper)
│   ├── regime_detector/     (ex-s03_regime_detector)
│   ├── fusion/              (ex-s04_fusion_engine)
│   └── quant_analytics/     (ex-s07_quant_analytics)
├── portfolio/
│   ├── strategy_allocator/  (NEW — ADR-0008)
│   └── risk_manager/        (ex-s05_risk_manager)
├── execution/
│   └── engine/              (ex-s06_execution)
├── research/
│   └── feedback_loop/       (ex-s09_feedback_loop)
├── ops/
│   └── monitor_dashboard/   (ex-s10_monitor)
└── strategies/
    ├── _base.py             (NEW — ADR-0007 StrategyRunner ABC)
    ├── legacy_confluence/   (Phase B LegacyConfluenceStrategy wrapper)
    ├── crypto_momentum/     (Strategy #1, Gate 2+)
    ├── trend_following/     (Strategy #2, Gate 2+)
    ├── mean_rev_equities/   (Strategy #3, Gate 2+)
    ├── volatility_risk_premium/  (Strategy #4, Gate 2+)
    ├── macro_carry/         (Strategy #5, Gate 2+)
    └── news_driven/         (Strategy #6, Gate 2+)
```

### D2 — Domain definitions

| Domain | Responsibility | Current services → target |
|---|---|---|
| `data/` | Ingestion, normalization, multi-asset panels, macro intelligence — "everything that produces input data" | s01 → ingestion; s08 → macro_intelligence; NEW panels |
| `signal/` | Per-strategy-agnostic signal and regime computation; legacy confluence pipeline; per-strategy fusion; quant analytics | s02 → engine; s03 → regime_detector; s04 → fusion; s07 → quant_analytics |
| `portfolio/` | Cross-strategy concerns: capital allocation and risk VETO | NEW strategy_allocator; s05 → risk_manager |
| `execution/` | Broker routing, order lifecycle, fill accounting | s06 → engine |
| `research/` | Post-trade: feedback loop, drift monitoring, attribution | s09 → feedback_loop |
| `ops/` | Observability, dashboards, alerting | s10 → monitor_dashboard |
| `strategies/` | One folder per strategy microservice; each inherits `StrategyRunner` | NEW tree; per-strategy at Gate 2 |

**Rationale**:

- `data/` groups the producers of authoritative market state.
- `signal/` groups the consumers of `data/` that produce unreusable strategy-agnostic computation (regime, quant analytics) plus the legacy single-strategy signal engine.
- `portfolio/` groups the concerns that operate **across** strategies: capital allocation (allocator) and risk VETO (risk manager). A senior risk manager at any institutional firm would recognize this grouping.
- `execution/` is its own domain because broker integration is a distinct expertise.
- `research/` separates post-trade analytics from pre-trade signal work.
- `ops/` is the observability domain.
- `strategies/` is the domain of individual strategy tenants — each strategy is a portfolio "pod" per Charter §3.2.

### D3 — Full mapping table (authoritative)

| # | Current path | Target path | Domain |
|---|---|---|---|
| 1 | `services/s01_data_ingestion/` | `services/data/ingestion/` | data |
| 2 | `services/s02_signal_engine/` | `services/signal/engine/` | signal (legacy confluence strategy wrapper post Phase B) |
| 3 | `services/s03_regime_detector/` | `services/signal/regime_detector/` | signal |
| 4 | `services/s04_fusion_engine/` | `services/signal/fusion/` | signal |
| 5 | `services/s05_risk_manager/` | `services/portfolio/risk_manager/` | portfolio |
| 6 | `services/s06_execution/` | `services/execution/engine/` | execution |
| 7 | `services/s07_quant_analytics/` | `services/signal/quant_analytics/` | signal |
| 8 | `services/s08_macro_intelligence/` | `services/data/macro_intelligence/` | data |
| 9 | `services/s09_feedback_loop/` | `services/research/feedback_loop/` | research |
| 10 | `services/s10_monitor/` | `services/ops/monitor_dashboard/` | ops |

**New services already in target topology** (born post-Charter, not migrated):

- `services/portfolio/strategy_allocator/` (Phase C, ADR-0008).
- `services/data/panels/` (Phase D, ADR-0009).
- `services/strategies/_base.py` + `services/strategies/<strategy_id>/` (Phase B+ per ADR-0007).

### D4 — Migration procedure (7 staged PRs)

The migration is executed as **Phase D.5** of the Roadmap (weeks 26-28) in a contained mini-phase. Each PR is individually CI-green and individually revertible. Ordering minimizes dependency cascades.

**PR 1 — `services/data/` domain migration**:

- `git mv services/s01_data_ingestion/ services/data/ingestion/`
- `git mv services/s08_macro_intelligence/ services/data/macro_intelligence/`
- Add import-path shim `services/s01_data_ingestion/__init__.py` and `services/s08_macro_intelligence/__init__.py` each containing:
  ```python
  # DEPRECATED: import redirect during Phase D.5 migration (ADR-0010).
  # Remove after PR 7. Consumers should import from services.data.ingestion
  # / services.data.macro_intelligence.
  import warnings
  warnings.warn(
      "services.s01_data_ingestion is deprecated; use services.data.ingestion",
      DeprecationWarning, stacklevel=2,
  )
  from services.data.ingestion import *  # noqa
  ```
- CI green; merge.

**PR 2 — `services/signal/` domain migration**:

- `git mv services/s02_signal_engine/ services/signal/engine/`
- `git mv services/s03_regime_detector/ services/signal/regime_detector/`
- `git mv services/s04_fusion_engine/ services/signal/fusion/`
- `git mv services/s07_quant_analytics/ services/signal/quant_analytics/`
- Add shims at each old path.
- CI green; merge.

**PR 3 — `services/portfolio/` domain migration**:

- `git mv services/s05_risk_manager/ services/portfolio/risk_manager/`
- Add shim at `services/s05_risk_manager/__init__.py`.
- `services/portfolio/strategy_allocator/` already exists (Phase C).
- CI green; merge.

**PR 4 — `services/execution/` domain migration**:

- `git mv services/s06_execution/ services/execution/engine/`
- Add shim at `services/s06_execution/__init__.py`.
- CI green; merge.

**PR 5 — `services/research/` domain migration**:

- `git mv services/s09_feedback_loop/ services/research/feedback_loop/`
- Add shim at `services/s09_feedback_loop/__init__.py`.
- CI green; merge.

**PR 6 — `services/ops/` domain migration**:

- `git mv services/s10_monitor/ services/ops/monitor_dashboard/`
- Add shim at `services/s10_monitor/__init__.py`.
- CI green; merge.

**PR 7 — remove shims; finalize**:

- Delete all `services/s0N/__init__.py` shim files.
- Update `supervisor/orchestrator.py` startup order to the target paths per Charter §5.9.
- Update `docker-compose.yml`: container names and build contexts reference target paths.
- Update `MANIFEST.md` to describe the target topology.
- Update `CLAUDE.md` top banner if it references specific service paths.
- Update all import statements in tests and scripts to target paths (CI fails if any remain).
- CI green; merge.

**Per-PR CI discipline**: each of the 7 PRs must pass:

- `ruff check .` + `ruff format --check .`
- `mypy . --strict`
- `bandit -r core supervisor services backtesting -c pyproject.toml`
- `pytest tests/unit/` (coverage gate unchanged)
- `pytest tests/integration/` (integration tests pass unchanged on old OR new paths via shims)
- `backtest-gate` (per Phase A un-muzzling; must remain green)

### D5 — Rollback procedure

**Pre-PR-7 (shims still in place)**:

- Any of PRs 1-6 can be reverted individually via `git revert <sha>`. The shim provides immediate binary compatibility.
- If a revert is required after subsequent PRs have merged, sequence: `git revert` the PR that introduced the regression, then any dependent subsequent PRs if necessary. Because each PR is domain-scoped, cross-domain dependency on the move itself is minimal.

**Post-PR-7 (shims removed)**:

- Revert of PR 7 re-adds shims; subsequent reverts of PR 1-6 reverse the moves. Test suite re-runs on each revert to confirm reversibility.

**Catastrophic revert** (everything back to pre-D.5 state): sequence `git revert <PR 7 sha> <PR 6 sha> <PR 5 sha> ... <PR 1 sha>` in that order. All services return to their S01-S10 paths.

**Git history preservation**: every move uses `git mv` exactly once. `git log --follow services/data/ingestion/` traces back through the move to the full history under `services/s01_data_ingestion/`. This is the **only** way to preserve blame and log continuity; manual `rm` + `add` would break history and is explicitly forbidden in this migration.

### D6 — Why Phase D.5 is a separate mini-phase

Phase D.5 is contained to weeks 26-28 of the Roadmap, explicitly **after** the substantive Phase D work (panel builder, per-strategy feedback loop, backtest portfolio runner) completes. Rationale:

- **Merge-conflict surface**: the migration touches every service in the repo. Doing it concurrently with in-flight strategy Gate 2 or Phase C-D substantive work would create massive conflicts. Containing it to a 2-week window with a feature freeze on other work minimizes the surface.
- **Phase D substantive work creates new services in target topology**: `services/data/panels/` is born at the target path; doing the migration after Phase D means the panel builder does not need shim compatibility.
- **Strategy #1 Gate 3 paper trading is in flight** during weeks 22-26; Strategy #1 is at `services/strategies/crypto_momentum/` (target topology from birth) — the migration does not touch it.
- **Strategy #1 Gate 4 starts week 27 and runs weeks 27-36** — Phase D.5 must complete (end of week 28) before live-micro reaches any critical decision point.

### D7 — Supervisor startup order update

Per Charter §5.9, the supervisor startup order post-migration:

```
1.  Redis
2.  ZMQ broker (XSUB/XPUB)
3.  services/ops/monitor_dashboard/
4.  services/data/ingestion/
5.  services/data/panels/
6.  services/data/macro_intelligence/
7.  services/signal/quant_analytics/
8.  services/signal/regime_detector/
9.  services/signal/engine/ (legacy confluence if still active)
10. services/signal/fusion/
11. services/portfolio/strategy_allocator/
12. services/portfolio/risk_manager/
13. services/execution/engine/
14. services/research/feedback_loop/
15+ services/strategies/<strategy_id>/
```

Clustering by domain: all `data/` services (4-6) start before any `signal/` service (7-10); all `signal/` complete before `portfolio/` (11-12); `execution/` (13) and `research/` (14) follow. Strategies (15+) deploy as their Gate 4 completes.

### D8 — Documentation updates on PR 7

PR 7 includes documentation updates reflecting the target topology:

- **MANIFEST.md**: service section rewritten per target topology.
- **CLAUDE.md**: §2 architectural constraints — update "10 microservices (S01-S10)" phrasing (currently the banner reads "10 microservices (S01–S10) communicating via ZeroMQ PUB/SUB and Redis"); new phrasing: "microservices organized by domain (`services/{data,signal,portfolio,execution,research,ops,strategies}/`) communicating via ZeroMQ PUB/SUB and Redis".
- **docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md**: §5.5 exit criteria confirmed checked.
- **docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md**: no change needed — Charter §5.4 already specifies the target topology; the migration executes it.
- **docs/adr_pending_roadmap_v3/ → docs/adr/**: the four ADRs authored alongside this Roadmap are moved to the canonical ADR directory by CIO per post-merge manual action (Roadmap §16.1).

### D9 — What this ADR does NOT do

- **Does not change CI job names**: `quality`, `rust`, `unit-tests`, `integration-tests`, `backtest-gate` remain named as-is.
- **Does not change ZMQ topic strings**: `tick.crypto.*`, `signal.technical.*`, `order.candidate`, etc., remain identical. Topics are ADR-0001 governed; the migration is about file organization, not wire protocol.
- **Does not change Redis key names**: `portfolio:capital`, `pnl:daily`, `kelly:<strategy_id>:<symbol>`, etc., remain identical. Key names are architectural data schema, not folder layout.
- **Does not rewrite service logic**: every migrated service retains its exact behavior. Principle 6 assertion verified by integration test suite running green on target paths.
- **Does not rename classes**: `SignalEngineService`, `RiskManagerService`, etc., retain their class names. Only the module path changes.

---

## 3. Consequences

### 3.1 Positive

- **Domain clarity**: new developers (or Claude Code agents on a cold session) can answer "which services produce data?" by grepping `services/data/`.
- **Charter §5.4 alignment**: target topology is the Charter's explicit §5.4 decision, ratified 2026-04-18.
- **Matches institutional precedent**: every multi-strategy firm in Charter §1.3 organizes by domain.
- **New services fit naturally**: `services/portfolio/strategy_allocator/`, `services/data/panels/`, `services/strategies/*/` all have natural homes without awkward S11/S01.5 numbering.
- **Git history preserved**: `git mv` means `git log --follow` continues to work across the move.

### 3.2 Negative

- **One-time disruption**: for ~2 weeks, PRs that cross the domain boundaries require rebase awareness. Mitigated by scheduling Phase D.5 in a contained window with feature-freeze on other service work.
- **Import-path updates required repository-wide**: every import statement that references `services.s0N` must be updated by the end of PR 7. Tools like `ruff --fix` + `python -m compileall` catch missed updates in CI.
- **External documentation references**: any external-facing reference (not currently present — the platform is private) would need updating.

### 3.3 Mitigations

- **Shims during transition**: PRs 1-6 add deprecation shims; migration is binary-compatible until PR 7.
- **Container name stability**: Docker Compose service names (`strategy-crypto-momentum`, etc.) are independent of Python module paths; container orchestration is unaffected.
- **Test suite unchanged**: pytest discovers tests at `tests/unit/` and `tests/integration/`; the test folder tree does not need migration.

---

## 4. Alternatives Considered

### 4.1 Keep S01-S10 numbering indefinitely

**Description**: no migration; new services added as `s11_strategy_allocator`, `s12_panel_builder`, `s13+ strategies/<id>/`.

**Pros**: zero migration work; existing docs and imports unchanged.

**Cons**:

- New services do not naturally fit the numbering. `s11_strategy_allocator` is a portfolio concern, not a pipeline step.
- Strategies as `s13+` misrepresents their parallel-tenant architecture.
- Charter §5.4 explicitly rejected this.
- Domain reasoning remains obscured.

**Rejected** per Charter §5.4.

### 4.2 Hybrid: keep S01-S10 numbering, add new domains only for new services

**Description**: existing services stay at `services/s0N/`; new services go under `services/{data,signal,portfolio,...}/`.

**Pros**: minimal disruption to existing code.

**Cons**:

- Asymmetric structure: "why is risk manager at `s05_` but the allocator at `portfolio/`?" — the split is arbitrary.
- Domain reasoning only partially achieved.
- Long-term the asymmetry compounds; every future refactor decision faces "migrate or not" question.

**Rejected**. A clean target topology is worth the one-time migration cost.

### 4.3 Rename to domains but keep a flat structure (`services/data_ingestion/`, etc.)

**Description**: rename `services/s01_data_ingestion/` → `services/data_ingestion/` (drop the s01 prefix, no nesting).

**Pros**: flatter tree; simpler imports.

**Cons**:

- Does not express the domain structure. `services/data_ingestion/` and `services/data_panels/` being sibling folders loses the "these are both data-domain services" grouping.
- Multiple domains would collide on some names (`services/engine/` could be signal-engine or execution-engine).

**Rejected**. Nested domain structure is the Charter §5.4 explicit choice.

---

## 5. Implementation Sketch

### 5.1 Phase D.5 tasks (Roadmap §5.5)

Executed in weeks 26-28, in order:

1. **PR 1 — data domain**: `git mv` s01 and s08 into `services/data/`; add shims; CI green; merge.
2. **PR 2 — signal domain**: `git mv` s02, s03, s04, s07 into `services/signal/`; add shims; CI green; merge.
3. **PR 3 — portfolio domain**: `git mv` s05 into `services/portfolio/`; add shim; CI green; merge.
4. **PR 4 — execution domain**: `git mv` s06 into `services/execution/`; add shim; CI green; merge.
5. **PR 5 — research domain**: `git mv` s09 into `services/research/`; add shim; CI green; merge.
6. **PR 6 — ops domain**: `git mv` s10 into `services/ops/`; add shim; CI green; merge.
7. **PR 7 — shim removal + documentation**: delete shims; update imports repository-wide; update supervisor startup order; update docker-compose.yml; update MANIFEST.md and CLAUDE.md; CI green; merge.

### 5.2 Strategy #1 lifecycle during Phase D.5

- Strategy #1 is in Gate 3 paper trading (weeks 18-26, ending just before Phase D.5 starts) or Gate 4 Day-0 (week 27).
- `services/strategies/crypto_momentum/` was born in target topology during Gate 2 (Roadmap §6.3); the migration does not move it.
- Strategy #1 paper/live operation continues unaffected by Phase D.5 PRs.

---

## 6. Compliance Verification

### 6.1 CI-enforced invariants

- **Import purity**: after PR 7, `grep -r "services.s0" services/ tests/ scripts/` returns zero hits (except in git-history-only artifacts).
- **Integration test suite green** on target paths: every integration test passes without reference to old paths.
- **Supervisor startup**: `supervisor/orchestrator.py` lists target paths in Charter §5.9 order; smoke test verifies services start in sequence.
- **Docker Compose smoke**: `docker compose -f docker/docker-compose.yml up -d --wait` brings the full stack up on target paths.

### 6.2 Manual verification checklist

- [ ] All 10 former S01-S10 services live at their target domain paths.
- [ ] All shims removed (no `services/s0N/__init__.py` files present).
- [ ] `git log --follow services/data/ingestion/service.py` shows the full history inherited from `services/s01_data_ingestion/service.py`.
- [ ] MANIFEST.md describes target topology.
- [ ] CLAUDE.md §2 reflects domain grouping.

---

## 7. References

### 7.1 Charter and Playbook

- Charter §5.4 (target topology decision); §5.9 (supervisor startup order); §12 (document relationships).
- Playbook §0.6 (binding precedence — CLAUDE.md overrides for code conventions).

### 7.2 Roadmap

- Roadmap v3.0 §5.5 (Phase D.5 migration scheduling).
- Roadmap §1.4 (migration is **can-slip** content; Charter §5.4 is **cannot-slip** binding decision).

### 7.3 Internal code references (current paths, migrating in Phase D.5)

- [`services/s01_data_ingestion/`](../../services/s01_data_ingestion/) → `services/data/ingestion/`
- [`services/s02_signal_engine/`](../../services/s02_signal_engine/) → `services/signal/engine/`
- [`services/s03_regime_detector/`](../../services/s03_regime_detector/) → `services/signal/regime_detector/`
- [`services/s04_fusion_engine/`](../../services/s04_fusion_engine/) → `services/signal/fusion/`
- [`services/s05_risk_manager/`](../../services/s05_risk_manager/) → `services/portfolio/risk_manager/`
- [`services/s06_execution/`](../../services/s06_execution/) → `services/execution/engine/`
- [`services/s07_quant_analytics/`](../../services/s07_quant_analytics/) → `services/signal/quant_analytics/`
- [`services/s08_macro_intelligence/`](../../services/s08_macro_intelligence/) → `services/data/macro_intelligence/`
- [`services/s09_feedback_loop/`](../../services/s09_feedback_loop/) → `services/research/feedback_loop/`
- [`services/s10_monitor/`](../../services/s10_monitor/) → `services/ops/monitor_dashboard/`
- [`supervisor/orchestrator.py`](../../supervisor/orchestrator.py) — startup order updated in PR 7.
- [`docker/docker-compose.yml`](../../docker/docker-compose.yml) — container build contexts updated in PR 7.
- [`MANIFEST.md`](../../MANIFEST.md) — service section rewritten in PR 7.
- [`CLAUDE.md`](../../CLAUDE.md) §2 — topology description updated in PR 7.

---

**END OF ADR-0010.**
