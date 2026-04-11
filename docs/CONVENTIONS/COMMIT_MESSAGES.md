# APEX Commit Message Convention

Adapted from [Conventional Commits 1.0.0](https://www.conventionalcommits.org/) for the
APEX trading system.

---

## Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Header (required)

- **Max 72 characters** for the header line.
- `<type>` and `<description>` are mandatory. `<scope>` is recommended.
- Description starts with lowercase, no trailing period.
- Use imperative mood: "add feature" not "added feature" or "adds feature".

### Body (optional)

- Separated from header by a blank line.
- Wrap at 72 characters per line.
- Describe the **why**, not the what. The diff shows what changed.
- Reference issues with `Refs #N` or `Closes #N`.

### Footer (optional)

- `Closes #N` -- for issues fully resolved by this commit.
- `Refs #N` -- for related issues not fully resolved.
- `Co-Authored-By: Claude <noreply@anthropic.com>` -- when Claude Code contributed.
- `BREAKING CHANGE: <description>` -- for breaking changes (rare in APEX).

---

## Types

| Type | Usage | Example |
|---|---|---|
| `feat` | New feature or capability | `feat(s02): add OFI signal component` |
| `fix` | Bug fix | `fix(s05): circuit breaker not persisting to Redis` |
| `refactor` | Code restructuring without behavior change | `refactor(s02): extract BarBuilder from TechnicalAnalyzer` |
| `docs` | Documentation only | `docs: add GLOSSARY.md with 46 APEX terms` |
| `test` | Adding or modifying tests | `test(s07): add hypothesis tests for Hurst estimator` |
| `chore` | Maintenance (gitignore, deps, scripts) | `chore: gitignore .claude/ local settings` |
| `ci` | GitHub Actions workflows | `ci: raise coverage gate to 60%` |
| `audit` | Audit reports and findings | `audit: whole-codebase architecture review` |
| `perf` | Performance optimization | `perf(s05): migrate risk chain to Rust apex_risk` |
| `style` | Formatting (no logic change) | `style(core): ruff format pass` |

---

## Scopes

Scopes identify the area of change. Use the most specific applicable scope.

### Service scopes

| Scope | Service |
|---|---|
| `s01` | S01 Data Ingestion |
| `s02` | S02 Signal Engine |
| `s03` | S03 Regime Detector |
| `s04` | S04 Fusion Engine |
| `s05` | S05 Risk Manager |
| `s06` | S06 Execution Engine |
| `s07` | S07 Quant Analytics |
| `s08` | S08 Macro Intelligence |
| `s09` | S09 Feedback Loop |
| `s10` | S10 Monitor Dashboard |

### Cross-cutting scopes

| Scope | Area |
|---|---|
| `core` | core/ package (models, bus, config, topics, base_service) |
| `infra` | Docker, docker-compose, Makefile, deployment |
| `ci` | GitHub Actions workflows |
| `docs` | Documentation files (when type is not already `docs`) |
| `tests` | Test infrastructure (conftest, fixtures, helpers) |
| `observability` | Metrics, tracing, healthchecks |
| `orchestrator` | Backfill orchestrator, job scheduler |
| `serving` | Internal REST API (S01 serving layer) |
| `quality` | Data quality pipeline |
| `rust` | Rust crates (apex_mc, apex_risk) |

---

## Real Examples from APEX History

Good examples extracted from the actual git log:

```
feat(observability): metrics + tracing + healthchecks (Phase 2.12 -- FINAL Phase 2)
```

```
fix(orchestrator): use WATCH/MULTI/EXEC instead of EVAL for fakeredis compat
```

```
feat(orchestrator): centralized backfill scheduler with retry/state/gaps (Phase 2.11)
```

```
ci: disable CD workflow until Phase 7 paper trading
```

```
audit: whole-codebase architecture & quality review (gate before Phase 3)
```

```
chore: gitignore .claude/ local settings directory
```

```
fix(ci): add types-PyYAML and types-croniter for mypy strict
```

---

## Multi-line Example

```
feat(s02): add OFI signal component with Cont et al. (2014) formula

Implements Order Flow Imbalance as a new SignalComponent in S02.
Uses tick-by-tick trade classification (Lee-Ready) to compute
buy/sell imbalance at the best bid/ask.

IC validation pending Phase 3.3.

Closes #42
Refs #81

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Rules for Claude Code Sessions

1. **Always** use this convention for commits.
2. **Always** add `Co-Authored-By: Claude <noreply@anthropic.com>` in the footer
   when Claude Code authored or co-authored the commit.
3. **Never** use generic messages like "update files" or "fix stuff".
4. **Always** reference relevant issues with `Closes #N` or `Refs #N`.
5. Scope is optional but strongly recommended for service-specific changes.
6. For multi-service changes, omit scope and describe in body.
7. Phase references (e.g., `(Phase 2.11)`) in the header are encouraged for
   milestone commits.

---

## Revision History

| Date | Change |
|---|---|
| 2026-04-11 | Initial creation (Sprint 1, closes #80). |
