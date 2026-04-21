# APEX Orchestrator Playbook

This document is the operating manual for the human orchestrator (clement-bbier) who pilots the APEX repo via AI agents.

## Daily routine

1. **Morning (5 min)** — Open https://github.com/clement-bbier/CashMachine/issues
2. Pick the highest-priority unassigned issue with a single agent label (`sre`, `alpha`, `qa`, `config`, `infra`)
3. In Claude Code (VS Code panel), open a NEW conversation and paste:

   ```
   Pick up issue #N from the APEX repo. Read AI_RULES.md and the relevant
   .github/agents/apex-{role}.agent.md before starting. Create a branch
   named {role}/{N}-{kebab-slug}, work the issue, run `make preflight`
   before committing, and open a PR when done. Do not merge.
   ```

4. Wait for Claude Code's PR. The CI runs automatically.
5. Review the PR diff (5-10 min depending on size)
6. Merge with **"Create a merge commit"** (preserves history)
7. Repeat

## Issue → agent mapping

| Label | Agent | Where it runs |
|---|---|---|
| `sre`, `infra`, `ci` | SRE Worker (apex-sre.agent.md) | Claude Code local |
| `alpha`, `research` | Quant Worker (apex-quant.agent.md) | Claude Code local |
| `qa`, `tests` | QA Worker (apex-qa.agent.md) | Claude Code local OR GitHub Copilot Coding Agent |
| `config`, `deps` | Config Worker (apex-config.agent.md) | Claude Code local OR GitHub Copilot Coding Agent |

## Mission templates (paste in Claude Code "New chat")

### Quant mission

```
You are picking up a Quant issue from APEX. Read AI_RULES.md, then read
.github/agents/apex-quant.agent.md as your system prompt. Then read the
target issue body via `gh issue view {N}`. Confirm the scope is within
your allowed zones. Create branch quant/{N}-{slug}. Work the issue.
Run `make preflight` until green. Commit by phases. Open a PR with
`gh pr create` referencing #N and pasting the preflight output. Do not merge.
```

### QA mission

```
You are picking up a QA issue from APEX. Read AI_RULES.md, then read
.github/agents/apex-qa.agent.md as your system prompt. Then `gh issue view {N}`.
Create branch qa/{N}-{slug}. NEVER modify production code under services/
or core/ — if a test reveals a bug, open a sub-issue with the right label.
Run `make preflight`. Open PR.
```

### Config mission

```
You are picking up a Config issue from APEX. Read AI_RULES.md and
.github/agents/apex-config.agent.md. `gh issue view {N}`. Create branch
config/{N}-{slug}. Stay in pyproject/requirements/Dockerfile/workflows
zones only. Run `make preflight`. Open PR.
```

### SRE mission

```
You are picking up an SRE issue from APEX. Read AI_RULES.md and
.github/agents/apex-sre.agent.md. `gh issue view {N}`. Create branch
sre/{N}-{slug}. You can touch core/, supervisor/, docker/, .github/.
Never touch alpha logic. Run `make preflight`. Open PR.
```

## Conflict avoidance

The single most important rule: **one agent = one branch = one issue at a time per zone**.

If two issues touch overlapping zones (e.g. two `alpha` issues both touching `services/fusion_engine/`), pick them up SEQUENTIALLY, not in parallel.

## Emergency stop

If a CI run mass-fails (3+ jobs red simultaneously), do NOT pile on more agent missions. Open a `[sre] CI investigation` issue, pause all agent work, and triage manually first.

## See also

- [AI_RULES.md](../AI_RULES.md) — agent permission matrix
- [docs/adr/0001-zmq-broker-topology.md](adr/0001-zmq-broker-topology.md) — first ADR
- [.github/agents/](../.github/agents/) — agent system prompts
