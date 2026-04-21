# APEX — AI Agent Permission Matrix

This file is the single source of truth for what each AI agent is allowed to read and write in this repository. All agents (Claude Code, GitHub Copilot, Copilot Coding Agent, future agents) MUST honor this matrix.

## Roles

| Role          | Where it runs                | Owns issues labelled |
|---------------|------------------------------|----------------------|
| Architect     | Claude web/desktop chat      | (creates issues only) |
| SRE Worker    | Claude Code (local)          | `sre`, `infra`, `ci` |
| Quant Worker  | Claude Code (local)          | `alpha`, `research`  |
| Config Worker | GitHub Copilot Coding Agent  | `config`, `deps`     |
| QA Worker     | GitHub Copilot Coding Agent  | `tests`, `qa`        |
| Reviewer      | Copilot PR Review            | (read-only, comments) |

## Permission Matrix (R = read, RW = read+write, — = forbidden)

| Path                                          | SRE | Quant | Config | QA  | Human-only |
|-----------------------------------------------|:---:|:-----:|:------:|:---:|:----------:|
| `core/bus.py`, `core/zmq_broker.py`           | RW  |  R    |   R    |  R  | review req |
| `core/state.py`, `core/service_runner.py`     | RW  |  R    |   R    |  R  | review req |
| `core/config.py`                              |  R  |  R    |  RW    |  R  |     —      |
| `core/models/**`                              |  R  |  R    |   R    |  R  |   **RW**   |
| `core/topics.py`, `core/logger.py`            | RW  |  R    |   R    |  R  |     —      |
| `services/data_ingestion/**`              | RW  |  R    |   R    |  R  |     —      |
| `services/signal_engine/**`               |  R  |  RW   |   R    |  R  |     —      |
| `services/regime_detector/**`             |  R  |  RW   |   R    |  R  |     —      |
| `services/fusion_engine/**`               |  R  |  RW   |   R    |  R  |     —      |
| `services/risk_manager/**`                |  R  |  R    |   R    |  R  |   **RW**   |
| `services/execution/**`                   |  R  |  R    |   R    |  R  |   **RW**   |
| `services/quant_analytics/**`             |  R  |  RW   |   R    |  R  |     —      |
| `services/macro_intelligence/**`          |  R  |  RW   |   R    |  R  |     —      |
| `services/feedback_loop/**`               |  R  |  RW   |   R    |  R  |     —      |
| `services/command_center/**`                     | RW  |  R    |   R    |  R  |     —      |
| `supervisor/**`                               | RW  |  R    |   R    |  R  |     —      |
| `backtesting/**`                              |  R  |  RW   |   R    |  R  |     —      |
| `rust/**`                                     |  R  |  R    |   R    |  R  |   **RW**   |
| `tests/unit/**`                               | RW  |  RW   |   R    | RW  |     —      |
| `tests/integration/**`                        | RW  |  R    |   R    | RW  |     —      |
| `tests/fixtures/**`                           |  R  |  RW   |   R    | RW  |     —      |
| `docker/**`                                   | RW  |  R    |  RW    |  R  |     —      |
| `.github/workflows/**`                        | RW  |  R    |  RW    |  R  |     —      |
| `.github/agents/**`, `.github/CODEOWNERS`     |  R  |  R    |   R    |  R  |   **RW**   |
| `pyproject.toml`, `requirements*.txt`         |  R  |  R    |  RW    |  R  |     —      |
| `.env.example`, `Makefile`                    |  R  |  R    |  RW    |  R  |     —      |
| `.env`                                        |  —  |  —    |   —    |  —  |   **RW**   |
| `CLAUDE.md`, `MANIFEST.md`, `README.md`       |  R  |  R    |   R    |  R  |   **RW**   |
| `docs/adr/**`                                 |  R  |  R    |   R    |  R  |   **RW**   |

## Hard rules for every agent
1. NEVER modify a path marked "Human-only RW" without an explicit human instruction quoted verbatim in the PR body.
2. ONE branch per agent per issue. Branch naming: `{role}/{issue-id}-{kebab-slug}` (e.g. `sre/42-fix-dockerfile`, `quant/57-add-vpin-feature`).
3. NEVER merge your own PR. Always wait for human or Reviewer approval.
4. If a lint, type-check or test fails, FIX FORWARD — never disable the rule, never lower a coverage threshold, never add `# type: ignore` or `# noqa` without a comment explaining why and a TODO.
5. All new functions MUST be: typed (`mypy --strict` clean), use `Decimal` for prices/sizes, use `datetime.now(UTC)` not `utcnow()`, use `structlog` not `print()`.
6. ZMQ topics are constants in `core/topics.py`. NEVER hardcode a topic string.
7. Before opening a PR, run `make preflight` locally and paste its output in the PR description.
