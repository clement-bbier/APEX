# APEX Meta-Project Audit — Documentation, Methodology, Agents & Knowledge Base

**Date**: 2026-04-11
**Auditor**: Claude Opus 4.6 (orchestrated by Clement Barbier)
**Scope**: All non-code artifacts (docs, ADRs, conventions, workflows, knowledge base)
**Trigger**: Gate obligatoire avant Phase 3 (companion to whole-codebase audit #55)
**Reference**: Knaster & Leffingwell (2020) SAFe 5.0, Hunt & Thomas (2019) Pragmatic Programmer

---

## Executive Summary

| Metric | Value |
|---|---|
| Markdown files inventoried | 30 (excluding .venv) |
| ADRs reviewed | 3 (ADR-0001, ADR-0002, ADR-0003) |
| Convention/governance files | 5 (CLAUDE.md, AI_RULES.md, CODEOWNERS, copilot-instructions.md, MANAGED_AGENTS_PLAYBOOK.md) |
| Workflow files | 3 (ci.yml, backtest.yml, _disabled_cd.yml) |
| Agent prompts | 5 (sre, quant, qa, config, data) |
| Templates | 3 (PR default, PR quant, issue agent-task) |
| Config files (YAML/TOML) | 10 |
| Total findings | P0: 3, P1: 8, P2: 7, P3: 5 |
| New artifacts proposed | 18 |
| New agents proposed | 6 |
| **Decision** | **CLEARED for Phase 3 governance-wise** |

The APEX project has **strong governance foundations**: CLAUDE.md is comprehensive and binding, ADR-0002 (Quant Methodology Charter) is institutional-grade, the AI agent permission matrix (AI_RULES.md) is well-designed, and the multi-agent workflow (ORCHESTRATOR_PLAYBOOK.md) is practical. However, the project suffers from **three P0 governance gaps**: (1) no glossary — APEX uses 40+ acronyms and quant terms with no central definition; (2) PROJECT_ROADMAP sub-phase descriptions are stale (2.7-2.12 still show PENDING/IN PROGRESS despite being DONE); (3) no formal conventions docs beyond CLAUDE.md (commit messages, naming, docstrings are implicit). These gaps will slow onboarding for new Claude Code sessions and increase the risk of inconsistency as Phase 3+ introduces more complex signal validation work. All P0 items can be addressed in 1-2 sessions.

---

## Section A — Inventaire des artefacts non-code

### A.1 Root-level documentation

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `CLAUDE.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `MANIFEST.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `README.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `AI_RULES.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `CHANGELOG.md` | Yes | Stale | Partial | High | Minor inconsistency — [Unreleased] used for both SRE-001 and Phase 3 sections | **UPDATE** |
| `EXTENSIONS.md` | Partial | Stale | Skeleton | Medium | Uses emoji-heavy style inconsistent with rest of project | **UPDATE** |
| `MANAGED_AGENTS_PLAYBOOK.md` | Yes | Up-to-date | Complete | High | Minor — references `platform.claude.com` URLs that are speculative | **KEEP** |
| `Makefile` | Yes | Up-to-date | Partial | High | Missing `make audit`, `make build-rust`, `make serve` targets | **UPDATE** |

### A.2 docs/ directory

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `docs/PROJECT_ROADMAP.md` | Yes | **Stale** | Partial — Phase 2 sub-phase descriptions 2.7-2.12 say PENDING/IN PROGRESS but all are DONE | High | **Contradicts** Section 4 which was updated but Section 5 sub-phase details were not | **UPDATE (P0)** |
| `docs/ORCHESTRATOR_PLAYBOOK.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `docs/observability.md` | Yes | Up-to-date | Complete | Medium | Consistent | **KEEP** |
| `docs/adr/0001-zmq-broker-topology.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `docs/adr/0002-quant-methodology-charter.md` | Yes | Up-to-date | Complete | High | Consistent — this is the crown jewel of project governance | **KEEP** |
| `docs/adr/ADR-0003-universal-data-schema.md` | Yes | Up-to-date | Complete | High | Minor — filename uses different pattern than 000X | **KEEP** (rename optional) |
| `docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `docs/audits/2026-04-08-quant-scaffolding-inventory.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |

### A.3 .github/ artifacts

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `.github/workflows/ci.yml` | Yes | Up-to-date | Complete | High | **Drifted** from CLAUDE.md (coverage 40% vs 85%, backtest non-blocking) — already tracked by audit #55 issues #64-#65 | **UPDATE** (tracked) |
| `.github/workflows/backtest.yml` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `.github/workflows/_disabled_cd.yml` | Partial | Stale (v4 actions) | Complete | High | Disabled by design — appropriate | **KEEP** |
| `.github/PULL_REQUEST_TEMPLATE.md` | Yes | Up-to-date | Complete | High | Consistent with CLAUDE.md | **KEEP** |
| `.github/PULL_REQUEST_TEMPLATE/quant.md` | Yes | Up-to-date | Complete | High | Excellent — directly implements ADR-0002 | **KEEP** |
| `.github/ISSUE_TEMPLATE/agent-task.yml` | Yes | Up-to-date | Complete | High | Consistent with AI_RULES.md | **KEEP** |
| `.github/CODEOWNERS` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `.github/copilot-instructions.md` | Partial | **Stale** | Partial — still references S01 `bind=True` which is now handled by ZMQ broker (ADR-0001) | Medium | **Contradicts** ADR-0001 | **UPDATE** |

### A.4 Agent prompts (.github/agents/)

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `apex-sre.agent.md` | Yes | **Stale** | Partial — still references `S01 bind=True` topology pre-ADR-0001 | High | **Contradicts** ADR-0001 (broker topology) | **UPDATE** |
| `apex-quant.agent.md` | Yes | Up-to-date | Complete | High | Correctly references ADR-0002 | **KEEP** |
| `apex-qa.agent.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `apex-config.agent.md` | Yes | Up-to-date | Complete | High | Minor: says "pinée (==X.Y.Z)" but requirements.txt uses `>=` — inconsistent | **UPDATE** |
| `apex-data.agent.md` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |

### A.5 Service-level documentation

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `services/s01_data_ingestion/observability/README.md` | Yes | Up-to-date | Complete | Medium | Consistent | **KEEP** |
| `services/s01_data_ingestion/orchestrator/README.md` | Yes | Up-to-date | Complete | Medium | Consistent | **KEEP** |

### A.6 Config files

| File | Pertinence | Fraicheur | Completude | Accessibilite | Coherence | Verdict |
|---|---|---|---|---|---|---|
| `pyproject.toml` | Yes | Up-to-date | Complete | High | Well-configured | **KEEP** |
| `docker/docker-compose.yml` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `docker/docker-compose.test.yml` | Yes | Up-to-date | Complete | High | Consistent | **KEEP** |
| `docker/prometheus.yml` | Yes | Up-to-date | Complete | Medium | Consistent | **KEEP** |
| `services/s01_data_ingestion/orchestrator/jobs.yaml` | Yes | Up-to-date | Complete | Medium | Consistent | **KEEP** |
| `.claude/settings.json` | Yes | Up-to-date | N/A | Low | N/A | **KEEP** |
| `.claude/settings.local.json` | Yes | Up-to-date | N/A | Low | N/A | **KEEP** |

---

## Section B — Evaluation critere par critere

### B.1 Documentation quality

**Strengths:**
- CLAUDE.md is one of the best AI-agent development contracts seen in an open project. It covers architecture, code quality, forbidden patterns, security, CI/CD, testing, and new service checklists.
- ADR-0002 is institutional-grade. The 15-reference mandatory bibliography and 10-point evaluation checklist would pass review at any systematic quant shop.
- PROJECT_ROADMAP is impressively detailed for each phase with canonical references and open questions.
- The multi-agent governance (AI_RULES.md + ORCHESTRATOR_PLAYBOOK.md + agent prompts) is a genuinely novel approach to solo-developer AI-assisted development.

**Weaknesses:**
- No glossary for 40+ specialized terms (HAR-RV, OFI, CVD, PSR, DSR, PBO, CPCV, IC, IC_IR, VIF, VPIN, GEX, Kelly, etc.).
- No architecture overview document separate from MANIFEST.md (which is too long for quick reference).
- No conventions documentation beyond what's embedded in CLAUDE.md.
- PROJECT_ROADMAP has stale sub-phase descriptions (Section 5, Phase 2 details).
- CHANGELOG.md uses [Unreleased] for two different sections, violating keepachangelog.com conventions.

### B.2 Convention enforcement

**Strengths:**
- CLAUDE.md Section 10 (Forbidden patterns) is clear and enforceable.
- PR templates enforce CLAUDE.md compliance via checkboxes.
- Quant PR template enforces ADR-0002 compliance.
- Agent prompts encode zone restrictions from AI_RULES.md.
- `make preflight` runs the full quality chain.

**Weaknesses:**
- No pre-commit hooks (`.pre-commit-config.yaml` does not exist). Conventions rely entirely on CI and human discipline.
- No commit message convention (Conventional Commits, etc.). CHANGELOG.md entries don't map to a systematic commit format.
- Naming conventions (variables, classes, modules) are implicit — derived from examples, not documented.
- ADR template is implicit (derived from ADR-0001 pattern) — no formal template file.

### B.3 Workflow completeness

**Strengths:**
- CI pipeline (ci.yml) covers quality → rust → unit-tests → integration-tests → backtest-gate.
- Nightly backtest (backtest.yml) runs Mon-Fri with walk-forward validation.
- CD pipeline exists (disabled by design until Phase 7).

**Weaknesses:**
- No dependency update automation (Dependabot/Renovate) — 19 CVEs found in audit #55.
- No scheduled security scan (beyond bandit which runs in CI).
- No auto-doc generation from docstrings.
- No pre-commit hook configuration.

### B.4 Knowledge base

**Strengths:**
- ADR-0002 contains 15 canonical references spanning backtesting methodology, market microstructure, and portfolio theory.
- Each phase in PROJECT_ROADMAP has its own canonical reference section.
- Academic citations in code docstrings are consistently present.

**Weaknesses:**
- No centralized reference list — references are scattered across ADR-0002, PROJECT_ROADMAP phases, EXTENSIONS.md, and individual code docstrings.
- No curated reading list prioritized by phase.
- Missing several important modern references (see Section E).
- No research digest or literature review output.

---

## Section C — Manques structurels

### C.1 Documentation manquante

| Doc | Impact | Priority |
|---|---|---|
| `docs/GLOSSARY.md` | Every new Claude Code session must rediscover 40+ acronyms. Slows onboarding significantly. | **P0** |
| `docs/ARCHITECTURE.md` | MANIFEST.md is 16K+ tokens. Need a 1-page architecture overview for quick context. | P1 |
| `docs/ACADEMIC_REFERENCES.md` | References scattered across 6+ files. Need one canonical list. | P1 |
| `docs/TROUBLESHOOTING.md` | No guide for common issues (ZMQ connection, Redis timeout, mypy errors). | P2 |
| `docs/ONBOARDING.md` | No "start here" guide for a new Claude Code session beyond reading CLAUDE.md + MANIFEST.md. | P1 |
| `CONTRIBUTING.md` | Not needed now (solo developer), but useful when scaling. | P3 |

### C.2 Conventions manquantes

| Convention | Impact | Priority |
|---|---|---|
| `docs/CONVENTIONS/COMMIT_MESSAGES.md` | No standard commit format. CHANGELOG.md maintenance is ad hoc. | **P0** |
| `docs/CONVENTIONS/NAMING.md` | Service IDs (`s{NN}_name`), branch names (`{role}/{N}-{slug}`), Redis keys, ZMQ topics — all implicit. | P1 |
| `docs/CONVENTIONS/DOCSTRINGS.md` | Academic citations in docstrings are inconsistently formatted. No standard. | P2 |
| `docs/CONVENTIONS/ADR_TEMPLATE.md` | ADR format varies (ADR-0001 vs ADR-0003 filename, Status/Date/Decider header). | P1 |
| New service checklist doc | CLAUDE.md Section 8 has a checklist but it's buried. Needs standalone doc. | P2 |
| New connector checklist doc | No explicit checklist for adding a data connector to S01. | P2 |

### C.3 Workflows/Runbooks manquants

| Runbook | Impact | Priority |
|---|---|---|
| API key rotation runbook | No documented process for rotating Alpaca/Binance/FRED keys. | P2 |
| Dependency update process | No Dependabot/Renovate config. 19 CVEs open (audit #55 issue #68). | P1 |
| Release/versioning process | CHANGELOG.md exists but no SemVer tagging, no release workflow. | P2 |
| Disaster recovery (Phase 8+) | Critical for live trading. Not needed now but ADR should be planned. | P3 |
| Incident response (Phase 8+) | Critical for live trading. | P3 |

### C.4 Knowledge base academique

| Item | Impact | Priority |
|---|---|---|
| `docs/ACADEMIC_REFERENCES.md` | Centralized bibliography with all refs from ADR-0002, PROJECT_ROADMAP, and code docstrings. | P1 |
| Missing modern references | See Section E for 8+ important papers not yet cited. | P1 |
| `docs/PAPERS_TO_READ.md` | Prioritized reading list by phase. Helps focus research time. | P2 |

### C.5 Tooling/Automation

| Tool | Impact | Priority |
|---|---|---|
| `.pre-commit-config.yaml` | No pre-commit hooks. Relies on CI to catch violations. | P1 |
| `make audit` target | No Makefile target for running the audit pipeline (bandit + pip-audit). | P2 |
| `make build-rust` target | Referenced in README but not in Makefile. | P1 |
| `make serve` target | No quick way to start the serving layer for development. | P2 |
| Scaffold scripts | No `scaffold_connector.py` or `scaffold_service.py` helpers. | P3 |

---

## Section D — Propositions strategiques

### D.1 Managed Agents — 6 propositions

#### Agent 1: `apex-veille-quant` (P0 — deploy now)

- **Description**: Weekly automated scan of arXiv q-fin.ST, q-fin.TR, SSRN, and quant industry blogs (AQR, Two Sigma, Man AHL). Produces a markdown brief filtered for APEX-relevant topics (HAR-RV, OFI, rough vol, regime detection, meta-labeling, Kelly, market microstructure).
- **Trigger**: Cron — every Monday 8:00 UTC
- **Inputs**: Web search (arXiv, SSRN, blogs). No repo access needed.
- **Outputs**: `docs/veille/YYYY-MM-DD-quant-brief.md`
- **Cost estimate**: ~$2-4/month (Sonnet 4.6, 30min/week, web search)
- **Priority**: **P0** — deploy immediately
- **ROI**: Saves 1-2h/week of manual literature scanning. At $0/cost for the user's time, this is pure alpha acceleration. The brief surfaces papers that could become new features or ADR amendments. **Fits within $0-20/month budget.**

#### Agent 2: `apex-convention-checker` (P1 — Phase 3)

- **Description**: Runs on every PR via Claude Code `/schedule` or manually. Checks commit messages match Conventional Commits format, docstrings cite academic references where required, naming conventions are followed, and no forbidden patterns are introduced (float for prices, print(), threading, etc.).
- **Trigger**: Manual or PR event (via Claude Code triggers)
- **Inputs**: Git diff of the PR
- **Outputs**: Comment on the PR with violations found
- **Cost estimate**: ~$1-2/month (Sonnet 4.6, 5min per PR, ~10 PRs/month)
- **Priority**: P1
- **ROI**: Catches convention drift that CI doesn't cover (commit messages, naming, docstring format). Low cost, high consistency.

#### Agent 3: `apex-nightly-backtest` (P1 — Phase 5)

- **Description**: Already detailed in MANAGED_AGENTS_PLAYBOOK.md. Nightly backtest regression with Sharpe/PSR/DSR comparison to baseline. Alerts on degradation > 5%.
- **Trigger**: Cron — daily 2:00 UTC
- **Inputs**: Latest data in TimescaleDB, strategy configs
- **Outputs**: Report in `data/nightly_reports/`, alert if degraded
- **Cost estimate**: ~$5/month
- **Priority**: P1 (deploy after Phase 5 backtesting engine is complete)
- **ROI**: Catches strategy degradation before it reaches live trading. Essential for Phase 8+.

#### Agent 4: `apex-dep-auditor` (P1 — now)

- **Description**: Weekly `pip-audit` + check for new CVEs affecting APEX dependencies. Creates GitHub issues for critical CVEs automatically.
- **Trigger**: Cron — weekly
- **Inputs**: `requirements.txt`, pip-audit output
- **Outputs**: GitHub issues for new CVEs, summary in `docs/security/`
- **Cost estimate**: ~$1/month (Haiku 4.5, very simple task)
- **Priority**: P1
- **ROI**: 19 CVEs currently untracked. Automated scanning prevents accumulation. **Fits within budget.**

#### Agent 5: `apex-watchdog-circuit-breaker` (P2 — Phase 8)

- **Description**: 24/7 monitoring of circuit breaker state. Already detailed in MANAGED_AGENTS_PLAYBOOK.md.
- **Trigger**: Persistent (30s polling)
- **Inputs**: MCP server `apex-risk` or Redis direct
- **Outputs**: SMS/email/Slack alerts on CB state changes
- **Cost estimate**: ~$15-25/month (always-on)
- **Priority**: P2 (Phase 8 only — when real money is at risk)
- **ROI**: Non-negotiable for live trading. Cost is a rounding error vs. capital at risk. **Exceeds $20/month budget — revisit when live trading begins.**

#### Agent 6: `apex-paper-summarizer` (P3 — on demand)

- **Description**: Takes a PDF of an academic paper, extracts pseudocode, mathematical formulations, datasets used, and generates a mini ADR template "Implementation candidate for APEX".
- **Trigger**: Manual (push PDF)
- **Inputs**: PDF file
- **Outputs**: Structured summary markdown
- **Cost estimate**: ~$0.50-1 per paper
- **Priority**: P3 (nice to have)
- **ROI**: Saves 30-60min per paper review. Only worth it if reading 4+ papers/month.

#### Budget summary

| Agent | Phase | Monthly Cost | Within $20 budget? |
|---|---|---|---|
| apex-veille-quant | Now | $2-4 | **Yes** |
| apex-dep-auditor | Now | $1 | **Yes** |
| apex-convention-checker | Phase 3 | $1-2 | **Yes** |
| apex-nightly-backtest | Phase 5 | $5 | **Yes** (cumulative ~$10) |
| apex-watchdog-circuit-breaker | Phase 8 | $15-25 | **No** — revisit when live |
| apex-paper-summarizer | On demand | $0.50/paper | **Yes** (ad hoc) |

**Recommended immediate deployment**: `apex-veille-quant` + `apex-dep-auditor` = **~$3-5/month**. Well within budget and both provide immediate value.

### D.2 Nouveaux fichiers documentation — 18 candidats

| # | File | Justification | Effort | Priority | Dependencies |
|---|---|---|---|---|---|
| 1 | `docs/GLOSSARY.md` | 40+ undefined acronyms/terms. Every session wastes time rediscovering definitions. | S | **P0** | None |
| 2 | `docs/CONVENTIONS/COMMIT_MESSAGES.md` | No commit format standard. CHANGELOG unmaintainable without it. | S | **P0** | None |
| 3 | `docs/CONVENTIONS/ADR_TEMPLATE.md` | ADR format varies (0001 vs 0003). Need a canonical template. | S | **P0** | None |
| 4 | `docs/ARCHITECTURE.md` | 1-page high-level overview. MANIFEST.md is too long for quick reference. | M | P1 | None |
| 5 | `docs/ACADEMIC_REFERENCES.md` | Centralized bibliography. Currently scattered across 6+ files. | M | P1 | None |
| 6 | `docs/ONBOARDING.md` | "Start here" guide for new Claude Code sessions. | S | P1 | #1, #4 |
| 7 | `docs/CONVENTIONS/NAMING.md` | Document all naming patterns (services, branches, Redis keys, ZMQ topics). | S | P1 | None |
| 8 | `.pre-commit-config.yaml` | Pre-commit hooks for ruff, mypy, bandit. | S | P1 | None |
| 9 | `docs/CONVENTIONS/DOCSTRINGS.md` | Standard format for academic citations in docstrings. | S | P2 | None |
| 10 | `docs/CONVENTIONS/TESTING.md` | Extract testing conventions from CLAUDE.md Section 7 into standalone doc. | S | P2 | None |
| 11 | `docs/CONVENTIONS/NEW_SERVICE_CHECKLIST.md` | Extract from CLAUDE.md Section 8 into standalone checklist. | S | P2 | None |
| 12 | `docs/CONVENTIONS/NEW_CONNECTOR_CHECKLIST.md` | Codify the S01 connector addition process from Phase 2 experience. | S | P2 | None |
| 13 | `docs/PAPERS_TO_READ.md` | Prioritized reading list by phase. | S | P2 | #5 |
| 14 | `docs/TROUBLESHOOTING.md` | Common issues and solutions (ZMQ, Redis, mypy, Docker). | M | P2 | None |
| 15 | `docs/RUNBOOKS/API_KEY_ROTATION.md` | Process for rotating broker API keys safely. | S | P2 | None |
| 16 | `docs/RUNBOOKS/DEPENDENCY_UPDATE.md` | Process for updating deps and handling CVEs. | S | P2 | None |
| 17 | `CONTRIBUTING.md` | Not critical for solo dev, useful for future scaling. | S | P3 | None |
| 18 | `docs/RUNBOOKS/INCIDENT_RESPONSE.md` | Critical for Phase 8+ live trading. | M | P3 | None |

### D.3 Nouveaux ADRs strategiques — 8 candidats

| # | ADR | Phase | Justification | Priority |
|---|---|---|---|---|
| 1 | ADR-0004: Feature validation methodology and IC thresholds | Phase 3 | PROJECT_ROADMAP Phase 3 lists this as "ADR-XXXX (to create)". Defines IC threshold, stability criteria, multicollinearity cutoffs. | **P0** |
| 2 | ADR-0005: HMM library for Regime Detector | Phase 4 | hmmlearn vs pomegranate vs custom — listed as open question in Phase 4. | P1 |
| 3 | ADR-0006: Capital allocation methodology (Risk Parity vs B-L vs Kelly) | Phase 4 | Listed as open question in Phase 4. Critical architectural choice. | P1 |
| 4 | ADR-0007: Backtesting engine architecture (build vs vectorbt vs Lean) | Phase 5 | Listed as open question in Phase 5. High-impact decision. | P1 |
| 5 | ADR-0008: Feature versioning and feature store architecture | Phase 3+ | No strategy for feature versioning. When IC changes, how to track feature evolution? | P1 |
| 6 | ADR-0009: Monitoring and alerting strategy | Phase 8 | No documented monitoring architecture beyond S01 observability. | P2 |
| 7 | ADR-0010: Paper-to-live cutover process | Phase 7-8 | Critical safety process. Go-live criteria exist in PROJECT_ROADMAP but not formalized as ADR. | P2 |
| 8 | ADR-0011: Disaster recovery and failover | Phase 8+ | Essential for live trading. No current DR plan. | P3 |

### D.4 Workflows/hooks proposes

| # | Workflow/Hook | Justification | Priority |
|---|---|---|---|
| 1 | `.pre-commit-config.yaml` with ruff + mypy + bandit hooks | Catch violations before commit, not in CI. Faster feedback loop. | P1 |
| 2 | Dependabot or Renovate config (`.github/dependabot.yml`) | Automated dependency updates. Addresses 19 CVEs (audit #55 #68). | P1 |
| 3 | Weekly security scan workflow (`security.yml`) | Scheduled pip-audit + bandit beyond what CI runs. | P2 |
| 4 | Auto-label PRs based on changed files | Map file paths to labels (alpha, sre, config, etc.) automatically. | P3 |
| 5 | CHANGELOG auto-update from Conventional Commits | Only if commit message convention is adopted first (D.2 #2). | P3 |

### D.5 Tooling complementaire

| # | Tool | Justification | Priority |
|---|---|---|---|
| 1 | `make build-rust` target in Makefile | Referenced in README but not in Makefile. | P1 |
| 2 | `make audit` target (`bandit + pip-audit`) | No single command to run full security audit. | P1 |
| 3 | `make serve` target | Start serving layer for development. | P2 |
| 4 | `make docs` target | Generate docs from docstrings (sphinx/mkdocs). | P3 |
| 5 | `scripts/dev/scaffold_service.py` | Auto-generate service boilerplate following CLAUDE.md Section 8 checklist. | P3 |

---

## Section E — Alignment strategique max alpha

### E.1 Academic references review

ADR-0002 contains 15 references. The PROJECT_ROADMAP adds ~25 more across phases. This is a solid foundation. However, several important modern references are missing:

#### Missing references — recommended additions

| # | Reference | Relevance to APEX | Recommended location | Priority |
|---|---|---|---|---|
| 1 | Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge University Press. | Feature importance (MDA, MDI, SFI), clustering, portfolio construction with ML. Directly relevant to Phase 3 feature validation. | ADR-0002 + Phase 3 | **P1** |
| 2 | Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning". *Review of Financial Studies*, 33(5), 2223-2273. | The definitive empirical comparison of ML methods for cross-sectional return prediction. Sets the benchmark for any ML-based alpha signal. | Phase 3, Phase 9 | P1 |
| 3 | Israel, R., Kelly, B. & Moskowitz, T. (2020). "Can Machines Learn Finance?" *SSRN*. | Critical examination of ML in finance — when it works, when it doesn't. Essential reading before Phase 9 ML strategies. | Phase 9 | P2 |
| 4 | Cont, R. (2011). "Statistical modeling of high-frequency financial data". *IEEE Signal Processing Magazine*, 28(5), 16-25. | Foundation for high-frequency data modeling. Relevant to S01 tick processing and S02 signal computation. | ADR-0002 ref table | P2 |
| 5 | Stoikov, S. (2018). "The micro-price: a high-frequency estimator of future prices". *Quantitative Finance*, 18(12), 1959-1966. | Micro-price as a feature. Directly implementable in S02 microstructure module. | Phase 3 features | P2 |
| 6 | Cartea, A., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency Trading*. Cambridge University Press. | Already cited in Phase 7 but not in ADR-0002. Comprehensive execution framework. | ADR-0002 ref table | P2 |
| 7 | Avellaneda, M. & Lee, J.-H. (2010). "Statistical arbitrage in the US equities market". *Quantitative Finance*, 10(7), 761-782. | Foundation for stat arb strategies in Phase 9. | Phase 9 | P3 |
| 8 | Hasbrouck, J. (2019). "Price Discovery in High Resolution". *Journal of Financial Econometrics*. | Updated price discovery framework. Relevant to S02 microstructure. | Phase 3 | P3 |

### E.2 Phase 3 strategic importance

Phase 3 (Feature Validation Harness) is the **most critical phase for alpha generation**. Everything before it is infrastructure; everything after it depends on validated features. The PROJECT_ROADMAP gives Phase 3 a weight of ~10% which is appropriate, but:

1. **ADR-0004 (Feature validation methodology) must be written BEFORE Phase 3 starts.** The IC thresholds, stability criteria, and multicollinearity cutoffs need to be decided upfront, not discovered during implementation.
2. **Lopez de Prado (2020) "ML for Asset Managers" is essential reading for Phase 3** — particularly Chapter 6 (Feature Importance) and Chapter 8 (Portfolio Construction). This book wasn't published when ADR-0002 was drafted but directly addresses the Phase 3 challenge.
3. **Feature versioning** is not addressed anywhere. When a feature's IC changes after a model update, there's no way to track which version of the feature was used in which backtest. This needs an ADR (proposed ADR-0008).

### E.3 ADR-0002 completeness

ADR-0002 is excellent. The 10-point evaluation checklist is comprehensive and the anti-patterns are well-chosen. Two minor gaps:

1. **No mention of feature importance testing** (MDA, MDI, SFI from Lopez de Prado 2020). This is critical for Phase 3 — knowing which features matter and which are noise.
2. **No mention of regime-conditional feature importance**. A feature may be important overall but useless in certain regimes. The methodology should require regime-stratified importance testing.

**Recommendation**: Extend ADR-0002 with items #11 (Feature importance testing) and #12 (Regime-conditional importance) when creating ADR-0004. Or create ADR-0004 as the feature-level extension of ADR-0002.

---

## Section F — Action Items prioritaires

### P0 (bloque Phase 3 governance-wise)

| # | Action | File(s) | Effort | Issue |
|---|---|---|---|---|
| G-P0-1 | Create `docs/GLOSSARY.md` with all APEX-specific terms and acronyms | New file | S | #78 |
| G-P0-2 | Fix PROJECT_ROADMAP.md Phase 2 sub-phase descriptions (2.7-2.12 still say PENDING/IN PROGRESS) | `docs/PROJECT_ROADMAP.md` | S | #79 |
| G-P0-3 | Create `docs/CONVENTIONS/COMMIT_MESSAGES.md` — adopt Conventional Commits | New file | S | #80 |

### P1 (before Phase 5)

| # | Action | File(s) | Effort | Issue |
|---|---|---|---|---|
| G-P1-1 | Create ADR-0004: Feature validation methodology (IC thresholds, stability, multicollinearity) | `docs/adr/0004-feature-validation-methodology.md` | M | #81 |
| G-P1-2 | Create `docs/ARCHITECTURE.md` — 1-page high-level overview | New file | S | #82 |
| G-P1-3 | Create `docs/ACADEMIC_REFERENCES.md` — centralized bibliography | New file | M | #83 |
| G-P1-4 | Create `docs/ONBOARDING.md` | New file | S | #84 |
| G-P1-5 | Create `docs/CONVENTIONS/NAMING.md` | New file | S | — |
| G-P1-6 | Add `.pre-commit-config.yaml` (ruff + mypy + bandit) | New file | S | #85 |
| G-P1-7 | Fix `apex-sre.agent.md` — remove stale S01 bind=True references | `.github/agents/apex-sre.agent.md` | S | #86 |
| G-P1-8 | Fix `.github/copilot-instructions.md` — update ZMQ topology to match ADR-0001 | `.github/copilot-instructions.md` | S | #86 |

### P2 (Phase 6-8)

| # | Action | File(s) | Effort | Issue |
|---|---|---|---|---|
| G-P2-1 | Create `docs/CONVENTIONS/ADR_TEMPLATE.md` | New file | S | — |
| G-P2-2 | Create `docs/CONVENTIONS/DOCSTRINGS.md` | New file | S | — |
| G-P2-3 | Create `docs/CONVENTIONS/NEW_SERVICE_CHECKLIST.md` | New file | S | — |
| G-P2-4 | Create `docs/CONVENTIONS/NEW_CONNECTOR_CHECKLIST.md` | New file | S | — |
| G-P2-5 | Add `make build-rust`, `make audit`, `make serve` targets | `Makefile` | S | — |
| G-P2-6 | Add Dependabot config (`.github/dependabot.yml`) | New file | S | — |
| G-P2-7 | Fix CHANGELOG.md — deduplicate [Unreleased] sections, adopt keepachangelog.com format | `CHANGELOG.md` | S | — |

### P3 (Phase 9+)

| # | Action | File(s) | Effort | Issue |
|---|---|---|---|---|
| G-P3-1 | Create `docs/RUNBOOKS/INCIDENT_RESPONSE.md` | New file | M | — |
| G-P3-2 | Create ADR-0011: Disaster recovery | New file | M | — |
| G-P3-3 | Create `docs/PAPERS_TO_READ.md` | New file | S | — |
| G-P3-4 | Create scaffold scripts (`scaffold_service.py`, `scaffold_connector.py`) | New files | M | — |
| G-P3-5 | Update EXTENSIONS.md — remove emojis, align style with rest of project | `EXTENSIONS.md` | S | — |

---

## Section G — Roadmap d'implementation

### Immediate (this session or next)

1. **G-P0-1**: Create `docs/GLOSSARY.md` — 30min
2. **G-P0-2**: Fix PROJECT_ROADMAP.md stale sub-phases — 15min
3. **G-P0-3**: Create commit message convention — 15min

### Phase 3 sprint 1 (week 1-2)

4. **G-P1-1**: Write ADR-0004 (Feature validation methodology) — blocks Phase 3 work
5. **G-P1-6**: Add `.pre-commit-config.yaml`
6. **G-P1-7**: Fix stale agent prompts (apex-sre, copilot-instructions)
7. Deploy `apex-veille-quant` agent ($2-4/month)

### Phase 3 sprint 2 (week 3-4)

8. **G-P1-2**: Create `docs/ARCHITECTURE.md`
9. **G-P1-3**: Create `docs/ACADEMIC_REFERENCES.md`
10. **G-P1-4**: Create `docs/ONBOARDING.md`
11. **G-P1-5**: Create `docs/CONVENTIONS/NAMING.md`

### Phase 4-5 (parallel with development)

12. ADR-0005 (HMM library) — before Phase 4 starts
13. ADR-0007 (Backtesting engine architecture) — before Phase 5 starts
14. P2 convention docs and Makefile improvements
15. Deploy `apex-nightly-backtest` agent (after Phase 5)

### Phase 8 (pre-live)

16. ADR-0010 (Paper-to-live cutover)
17. ADR-0011 (Disaster recovery)
18. Incident response runbook
19. Deploy `apex-watchdog-circuit-breaker`

---

## Section H — Decision: Cleared for Phase 3 governance-wise

**Decision**: **YES — CLEARED**

**Justification**:

The 3 P0 findings (glossary, stale roadmap sub-phases, commit convention) are all documentation artifacts that can be created in a single session without blocking Phase 3 code work. They are important for long-term project health but do not prevent Phase 3 feature validation from starting.

The governance foundations are **strong**:
- CLAUDE.md provides a comprehensive development contract
- ADR-0002 provides institutional-grade quant methodology
- AI_RULES.md + agent prompts provide clear multi-agent governance
- CI pipeline covers quality, types, tests, and backtesting
- PR templates enforce compliance

The P1 items (ADR-0004, pre-commit hooks, architecture doc, academic references) should be addressed **during** Phase 3, not before. ADR-0004 (feature validation methodology) is the most important and should ideally be drafted before the first Phase 3.1 PR.

**Comparison with audit #55 (whole-codebase)**:
- Audit #55 found P0: 0, P1: 15, P2: 13, P3: 6 — decision: CLEARED
- This audit found P0: 3, P1: 8, P2: 7, P3: 5 — decision: CLEARED
- No overlap between the two audits — they are genuinely complementary
- Combined: the project has 0 code-blocking + 3 governance-blocking P0s, all addressable in <2h

---

## Appendix — Overlap check with audit #55

The following items from audit #55 are **NOT duplicated** in this governance audit:

| Audit #55 Issue | Status | Covered here? |
|---|---|---|
| #64 CI coverage gate drift | Tracked | No — code/CI issue, not governance |
| #65 Backtest gate non-blocking | Tracked | No — code/CI issue |
| #66 float→Decimal | Tracked | No — code issue |
| #67 PROJECT_ROADMAP outdated | Tracked | **Partially overlaps** with G-P0-2 but #67 covers Section 4 (metrics) while G-P0-2 covers Section 5 (sub-phase descriptions) |
| #68 CVEs | Tracked | Related to G-P1-6 (Dependabot) but different action |
| #69-#77 Code quality issues | Tracked | No — all code issues |

No duplicate issues will be created.
