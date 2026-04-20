# CLAUDE.md — APEX Trading System Development Contract

This file is read by Claude Code at the start of every session.
It defines non-negotiable constraints for all development work on this project.

---

> **STATUS: CURRENT-STATE CONVENTIONS** (as of 2026-04-19)
>
> This document describes the **current** development conventions for the APEX codebase in its present S01-S10 topology. It remains the binding reference for all code produced today.
>
> **Target-state architecture is defined in [docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md](docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)** (Charter v1.0, ratified 2026-04-18).
>
> Specifically:
> - The target service topology is **classification by domain** (`services/data/`, `services/signal/`, `services/portfolio/`, `services/execution/`, `services/research/`, `services/ops/`, `services/strategies/`) — see Charter §5.4.
> - Strategies are **microservices** under `services/strategies/<strategy_name>/` — see Charter §5.1.
> - A new service **`services/portfolio/strategy_allocator/`** sits between signal generation and risk VETO — see Charter §5.2.
> - A new service **`services/data/panels/`** aggregates multi-asset snapshots consumed by all strategies — see Charter §5.3.
> - Every order-path Pydantic model gains a **`strategy_id`** field (default `"default"` for backward compatibility) — see Charter §5.5.
> - The VETO chain is **7 steps** (was 6 under fail-closed ADR-0006) — see Charter §8.2.
>
> **For every new file or service created by a Claude Code agent:**
> - If the target-state location is already specified in the Charter, create the file directly in the target location (e.g., `services/strategies/crypto_momentum/service.py`, NOT `services/s11_crypto_momentum/service.py`).
> - If adding functionality to an existing S01-S10 service, continue using the current path (e.g., `services/s05_risk_manager/` stays until the refactor) but ensure that new contracts (Pydantic models, ZMQ topics, Redis keys) include `strategy_id` where the Charter requires it, and reference the Charter section that motivates the change.
>
> Migration from current topology to target topology is scheduled in **Document 3 (PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md, pending authoring)**.
>
> **Binding precedence**: When CLAUDE.md and the Charter conflict, the Charter prevails for architectural decisions; CLAUDE.md prevails for code-convention rules (forbidden patterns, mandatory types, testing gates). No conflict is expected in practice because they operate on different levels.
>
> **Lifecycle Playbook (operational layer)**: [`docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md`](docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) (v1.0, ratified 2026-04-20 via PR #186).
>
> **Every Claude Code session invoked on strategy work MUST read the Playbook alongside the Charter.** The Charter defines *what* the platform is and *what* the gates require; the Playbook defines *how* a strategy is built, validated, deployed, monitored, and retired in mechanical detail. An agent that opens a Gate 1 or Gate 2 PR without following the Playbook's §3 or §4 deliverables respectively is operating outside platform discipline.
>
> Per Playbook §14.3.1, mandatory pre-session reads for any strategy work:
> 1. This document (CLAUDE.md) — code conventions
> 2. [`docs/claude_memory/CONTEXT.md`](docs/claude_memory/CONTEXT.md) — current project state
> 3. [APEX Multi-Strat Charter](docs/strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) — constitutional layer
> 4. [Lifecycle Playbook](docs/strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) — operational layer
> 5. The relevant per-strategy Charter at `docs/strategy/per_strategy/<strategy_id>.md` if working on a specific strategy.

---

## 1. What this system is

APEX is an autonomous quantitative trading engine targeting maximum alpha generation
on US equities (NYSE/Nasdaq via Alpaca) and crypto (BTC/ETH via Binance).

**Primary objective: maximize PnL through systematic, continuous alpha generation.**

The system is NOT a static bot. It is a continuously adaptive pipeline:
- S01 ingests real-time market data, macro signals, and CB announcements
- S02 recomputes signals on every tick
- S03 detects regime changes in real-time and adjusts the macro multiplier
- S04 re-evaluates and resizes positions as regime and signals evolve
- S05 enforces risk rules dynamically as market conditions shift
- S07 updates statistical models (Hurst, GARCH, Hawkes) on rolling windows
- S08 monitors CB calendars, geopolitical events, and session transitions live
- S09 tracks signal quality drift and reports degradation as it happens

**Any change that makes the system less adaptive is a regression.**
If a service becomes "static" (reads config once, never updates), flag it.

---

## 2. Architecture constraints — never violate these

- **10 microservices** (S01–S10) communicating via ZeroMQ PUB/SUB and Redis
- **Chain of Responsibility**: Tick → Signal → Regime → Fusion → Risk → Execution
- **Single Responsibility**: each service does exactly one thing
- **Immutable data pipeline**: Tick → NormalizedTick → Signal → OrderCandidate → ApprovedOrder → ExecutedOrder → TradeRecord. Never mutate an object — create a new one.
- **Frozen Pydantic v2 models** for all data objects crossing service boundaries
- **Decimal (never float)** for all prices, sizes, PnL, and fees
- **UTC datetime** for all timestamps — never datetime.now() without timezone
- **asyncio only** — never threading.Thread inside a service
- **structlog only** — never print(), never logging.basicConfig()
- **Risk Manager (S05) is a VETO** — it cannot be bypassed under any circumstance
- **ZMQ topics are defined in core/topics.py** — never hardcode topic strings

---

## 3. Continuous adaptation — design requirement

Every service that consumes external data MUST update its state continuously.
This is not optional — it is the core design principle.

When adding or modifying a service, ask:
- Does it re-read its inputs on every cycle, or only at startup?
- Does it publish updates when its state changes, or only once?
- Does it degrade gracefully if upstream data is stale?
- Does S09 FeedbackLoop have visibility into its performance?

Examples of correct adaptive behavior:
- S03 RegimeDetector recomputes macro_mult every 30s or on any macro change
- S08 MacroIntelligence fires macro.catalyst.* events as they happen, not on a fixed schedule
- S07 QuantAnalytics updates Hurst exponent and GARCH forecast on rolling windows
- S04 FusionEngine re-evaluates session_mult as the session changes throughout the day
- S09 FeedbackLoop continuously updates Kelly win_rate/RR stats in Redis

---

## 4. Before writing any code

1. Read MANIFEST.md — it is the source of truth for architecture, data models, and service contracts
2. Check if the change fits within Phase 1 scope (see MANIFEST.md Section 17 — Out of Scope)
3. Identify which services are affected and how data flows between them
4. Confirm the change does not break the immutable data hierarchy

---

## 5. Code quality — enforced on every change

### SOLID principles
- **S** — Single Responsibility: one class, one reason to change
- **O** — Open/Closed: extend via new classes, not by modifying existing ones
- **L** — Liskov Substitution: subtypes must honor parent contracts
- **I** — Interface Segregation: small focused interfaces over large ones
- **D** — Dependency Inversion: depend on abstractions (BaseService, Bus, State), not concretions

### Design patterns — use when genuinely useful
- **Chain of Responsibility** — already used in the pipeline; extend it, don't break it
- **Strategy Pattern** — for interchangeable indicators, brokers, or sizing algorithms
- **Factory Pattern** — for feed/broker instantiation
- **Circuit Breaker** — already in S05; never remove this pattern
- **Observer/Pub-Sub** — already implemented via ZeroMQ; don't add direct service coupling
- **Repository Pattern** — for any new data persistence layer

Do NOT add patterns for pattern's sake. If a simpler design is equally clear, use it.

### Performance
- Hot paths (tick processing, signal computation) must avoid object allocation in inner loops
- Use polars over pandas for any bulk data transformation
- Use numpy vectorized operations — never Python loops over arrays in signal computation
- CPU-bound math goes in Rust (apex_mc, apex_risk crates) — not in Python
- Profile before optimizing; don't optimize what isn't measured

### Type safety
- Every function must have complete type annotations
- mypy strict must pass: `mypy .` returns zero errors
- No bare generics: dict → dict[str, Any], list → list[T], etc.
- No `# type: ignore` unless absolutely unavoidable — document why if used

---

## 6. CI/CD — mandatory for every change

**Every commit must pass the full CI pipeline before merging to main.**

CI jobs (in order):
1. `quality` — ruff check + ruff format + mypy strict + bandit
2. `rust` — cargo test --workspace + maturin build + verify imports
3. `unit-tests` — pytest tests/unit/ with coverage ≥ 85%
4. `integration-tests` — full pipeline tests with Redis
5. `backtest-gate` — Sharpe ≥ 0.8, max DD ≤ 8% on 30-day fixture

**Never suggest merging if CI is red.**
**Never suggest skipping a CI step.**

To run locally before pushing:
```bash
make lint        # ruff + mypy + bandit
make test-unit   # fast unit tests, no docker
make test-int    # integration tests (needs docker)
```

---

## 7. Tests — mandatory for every new feature

For every new function, class, or service:

**Unit tests required:**
- Happy path with representative inputs
- Edge cases: empty inputs, None values, boundary conditions
- Error cases: what happens when upstream data is missing or malformed
- Property tests with hypothesis for any mathematical function

**Integration tests required when:**
- A new ZMQ topic is added
- A new Redis key pattern is introduced
- A new service is added
- The data flow between two services changes

**Test location:**
- `tests/unit/` — no real Redis, no real ZMQ, no real brokers
- Use `fakeredis.aioredis.FakeRedis()` for Redis in unit tests
- Use `tests/integration/` for end-to-end pipeline tests

**Coverage gate: 85% minimum** — enforced by CI.

---

## 8. Adding a new service — checklist

Before writing code for a new service:

- [ ] Service ID follows pattern: `s{NN}_{name}` (e.g. `s11_new_service`)
- [ ] Inherits from `core.base_service.BaseService`
- [ ] `super().__init__(service_id="s11_new_service", config=config)` called
- [ ] `get_subscribe_topics()` returns list of ZMQ topics from `core/topics.py`
- [ ] `on_message()` handles exceptions internally — never propagates
- [ ] `_heartbeat_loop()` publishes to Redis every 5s (inherited)
- [ ] Service added to `supervisor/orchestrator.py` startup order
- [ ] Dockerfile CMD updated with new SERVICE_MODULE
- [ ] docker-compose.yml updated with new service entry
- [ ] Unit tests written before the service is considered done
- [ ] MANIFEST.md updated with the new service specification

---

## 9. Adding a new signal or indicator

Every new signal must have:
- Mathematical formula documented in the docstring with academic reference
- Unit test verifying the formula against a manually computed known result
- Performance benchmark if it runs on every tick (target: < 5ms per tick)
- Registration in S02 SignalEngine's trigger list (SignalTrigger enum)
- Output validated: strength must be in [-1.0, +1.0], confidence in [0.0, 1.0]

---

## 10. Forbidden patterns

```python
# NEVER:
import random          # use secrets.SystemRandom()
float(price)           # use Decimal(str(price))
datetime.now()         # use datetime.now(timezone.utc)
time.sleep(x)          # use await asyncio.sleep(x)
print(...)             # use logger.info(...) with structlog
threading.Thread(...)  # use asyncio.create_task(...)
from alpaca_trade_api  # DISCONTINUED — use alpaca-py only

except Exception:
    pass               # always log: except Exception as exc: logger.debug(..., error=str(exc))

dict                   # bare generic — use dict[str, Any]
list                   # bare generic — use list[T]
```

---

## 11. Security

- API keys: `.env` only, never in source code, never in logs
- Execution service (S06): write-only broker API key, IP-whitelisted
- No web interface can trigger real orders — dashboard (S10) is read-only
- Risk Manager (S05) circuit breaker must remain in CLOSED state validation on every startup

---

## 12. Commit conventions

All commits must follow the convention defined in `docs/CONVENTIONS/COMMIT_MESSAGES.md`.

**Quick reference**: `<type>(<scope>): <description>`

- Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `audit`, `perf`, `style`
- Scopes: `s01`..`s10`, `core`, `infra`, `ci`, `docs`, `tests`, `rust`, etc.
- Always add `Co-Authored-By: Claude <noreply@anthropic.com>` when Claude Code authors the commit.
- Always reference issues: `Closes #N` or `Refs #N`.

---

## 13. Persistent memory across sessions

APEX development spans many Claude Code sessions. To preserve context:

### Directory: `docs/claude_memory/`

| File | Purpose |
|---|---|
| `SESSIONS.md` | Chronological log of all Claude Code sessions |
| `DECISIONS.md` | Architectural decisions (mini-ADRs) |
| `CONTEXT.md` | Current project state snapshot |
| `PHASE_3_NOTES.md` | Phase 3-specific notes and IC results |
| `templates/` | Templates for session and decision entries |

### Mandatory rules for ALL Claude Code sessions

**Step 1bis (before coding)**:
Read `docs/claude_memory/CONTEXT.md` AND the relevant phase notes file
(e.g., `docs/claude_memory/PHASE_3_NOTES.md`) BEFORE writing any code.

**Final step (after coding)**:
1. Append a session entry to `docs/claude_memory/SESSIONS.md`
2. Update `docs/claude_memory/CONTEXT.md` if project state changed
3. Record any architectural decisions in `docs/claude_memory/DECISIONS.md`

---

## 14. When in doubt

1. Check MANIFEST.md for the intended behavior
2. Check existing service implementations for established patterns
3. If adding complexity, ask: does this improve alpha generation or reduce risk?
   If not, don't add it.
4. If unsure about a type annotation, run `mypy .` and fix the error properly
5. If a test is hard to write, the design probably needs simplification

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
