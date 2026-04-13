# Claude Code — APEX Project Conventions

## Model routing recommendations

Start each session with:
```
/model opusplan
```

This routes Opus to planning (strategic decisions, architecture) and Sonnet to execution
(writing tests matching an established pattern, applying D024-D034, routine PR body).

**Use `/model opus` ONLY for:**
- Phase transitions (where pattern is still being established)
- Cross-calculator analysis (3.9 multicollinearity, 3.10 CPCV, 3.11 DSR/PBO)
- Copilot review investigation when a bug seems mathematically subtle
- ADR drafting

**Use `/model sonnet`** for straight execution when pattern is crystal clear
(rare — `/model opusplan` handles routing automatically).

## Context diagnostics

- Run `/context` and `/cost` at start of session to baseline
- Run `/compact` if session exceeds 45 minutes or 30+ messages

## Active skills

- **apex-calculator** — for new FeatureCalculator implementations (Phase 3.4-3.8 pattern)

## Active hooks (see `.claude/settings.json`)

| Hook | Trigger | Purpose |
|------|---------|---------|
| PreToolUse (protection) | Write\|Edit\|MultiEdit | Blocks modification of S01-S10, ADRs, PHASE_SPEC, .env, pyproject.toml, CI workflows |
| PostToolUse (ruff) | Write\|Edit\|MultiEdit | Runs `ruff check` + `ruff format --check` on every Python file edit |
| PostToolUse (pytest) | Write\|Edit\|MultiEdit | Runs targeted `pytest` on matching test file |
| UserPromptSubmit | every prompt | Injects git state (branch, last commit, uncommitted count, recent files) |
