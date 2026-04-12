# APEX Onboarding Guide

Welcome. This guide gets you productive in 15 minutes.

---

## 1. What is APEX?

APEX is an autonomous quantitative trading engine targeting maximum alpha generation
on US equities (NYSE/Nasdaq via Alpaca) and crypto (BTC/ETH via Binance). It is
designed as an institutional-grade system: microservice architecture, academic-quality
signal research, and rigorous statistical validation.

The system is built by a single developer (Clement Barbier) with Claude Code as the
primary development agent. It consists of 10 microservices communicating via ZeroMQ
and Redis, with Rust extensions for CPU-bound math.

## 2. Quick orientation

| Item | Value |
|---|---|
| Repo root | `C:\Users\cleme\Documents\04_Projets_Personnels\CashMachine` |
| Language | Python 3.12 + Rust/PyO3 (apex_mc, apex_risk crates) |
| Services | 10 microservices (S01-S10) |
| Messaging | ZeroMQ XSUB/XPUB (see ADR-0001) |
| State | Redis (fakeredis in tests) |
| Time-series DB | TimescaleDB |
| Read first | `CLAUDE.md` then `docs/ARCHITECTURE.md` then `docs/GLOSSARY.md` |

## 3. Development setup

```bash
# 1. Clone and enter
git clone https://github.com/clement-bbier/CashMachine.git
cd CashMachine

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# 4. Verify setup
ruff check .                  # linter
mypy . --strict               # type checker
pytest tests/unit/ -q         # unit tests (no Docker needed)

# 5. Infrastructure (optional, for integration tests)
docker compose up -d redis timescale
pytest tests/integration/ -q
```

## 4. Workflow for new Claude Code session

This is **critical** -- follow this sequence every session:

1. Read `docs/claude_memory/CONTEXT.md` -- where the project is right now
2. Read `docs/claude_memory/PHASE_3_NOTES.md` -- Phase 3-specific state
3. Read the target issue: `gh issue view #N`
4. Follow the prompt provided by orchestrator
5. Apply `CLAUDE.md` conventions (Decimal, UTC, structlog, mypy strict)
6. Update `docs/claude_memory/SESSIONS.md` at end of session
7. Update `docs/claude_memory/CONTEXT.md` if project state changed
8. Record architectural decisions in `docs/claude_memory/DECISIONS.md`
9. **Never commit `.claude/settings.json`**

## 5. Key conventions (MUST follow)

| Convention | Rule |
|---|---|
| Financial values | `Decimal` only -- never `float()` on prices, PnL, fees, sizes |
| Timestamps | UTC only -- `datetime.now(timezone.utc)`, never naive |
| Logging | `structlog` only -- never `print()`, never `logging.basicConfig()` |
| Async | `asyncio` only -- never `threading.Thread` inside a service |
| Types | mypy `--strict` must pass with zero errors |
| Commits | Conventional Commits (see `docs/CONVENTIONS/COMMIT_MESSAGES.md`) |
| Models | Frozen Pydantic v2 for all cross-service data objects |
| Coverage | 75% gate (progressing to 85%) |
| Topics | Defined in `core/topics.py` -- never hardcode ZMQ topic strings |

## 6. Gates to pass before merging

Every commit must pass the full CI pipeline:

```bash
make lint        # ruff check + ruff format + mypy --strict + bandit
make test-unit   # pytest tests/unit/ with coverage >= 75%
make test-int    # integration tests (needs Docker)
```

Quick local check:
```bash
ruff check . && ruff format --check . && mypy . --strict && pytest tests/unit/ -q
```

## 7. Academic rigor

Every quant implementation cites its canonical reference in the docstring.
See `docs/ACADEMIC_REFERENCES.md` for the complete bibliography.
See `docs/adr/ADR-0004-feature-validation-methodology.md` for the 6-step
feature validation pipeline.

## 8. Hotfix pattern

Copilot review often catches real issues (exception types, hardcoded constants,
dead code). The standard pattern is: push PR, wait for Copilot review, fix on
the same branch, push again, then merge. This is normal workflow, not a sign
of a problem.

## 9. Where to find things

| I need to... | Go to... |
|---|---|
| Understand a term | `docs/GLOSSARY.md` |
| Find a paper reference | `docs/ACADEMIC_REFERENCES.md` |
| See architectural decisions | `docs/adr/*.md` |
| Understand Phase 3 plan | `docs/phases/PHASE_3_SPEC.md` |
| Check current project state | `docs/claude_memory/CONTEXT.md` |
| See recent session logs | `docs/claude_memory/SESSIONS.md` |
| See recent decisions | `docs/claude_memory/DECISIONS.md` |
| See the full roadmap | `docs/PROJECT_ROADMAP.md` |
| Understand commit format | `docs/CONVENTIONS/COMMIT_MESSAGES.md` |
| See the full architecture | `docs/ARCHITECTURE.md` |
| Understand service contracts | `MANIFEST.md` |

## 10. Red flags (stop immediately if you see these)

- Secrets in logs or commits (API keys, passwords)
- `float()` on a price, PnL, fee, or size value
- `datetime` without timezone
- `print()` instead of `structlog` logger
- `threading.Thread` inside a service
- pytest test skipped without a clear reason
- `# type: ignore` without a documented reason
- A commit that touches `.claude/settings.json`
- A force-push attempt on `main`
- Cross-service imports (S0X importing from S0Y)
- `core/` importing from `services/` (DIP violation)

## 11. Questions?

- Check existing docs (see table in section 9)
- Open a GitHub issue for anything not covered
- Read `CLAUDE.md` -- it is the ultimate authority on conventions
