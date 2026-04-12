# Copilot Instructions for APEX

This repository is APEX -- an institutional-grade quantitative trading system.
10 microservices (S01-S10) communicating via ZeroMQ and Redis.

## Before suggesting code

1. Read `CLAUDE.md` for conventions (Decimal, UTC, structlog, mypy strict)
2. Read `docs/ONBOARDING.md` for quick orientation
3. Read `docs/ARCHITECTURE.md` for high-level structure
4. Read `docs/GLOSSARY.md` for APEX-specific terminology

## Code quality

- **Typing**: All code must be strictly typed. Validate with `mypy . --strict`.
- **Linting**: Respect `ruff` rules (config in `pyproject.toml`). All code must pass `ruff check`.
- **Pre-commit**: Run `make lint` and `make test-unit` before any commit or PR.
- **Coverage**: Unit test coverage gate is 75% (progressing to 85%).

## Architecture constraints

- **ZMQ topology** (ADR-0001): S01 binds on port 5555 (`bind=True`). All other services connect (`bind=False`).
- **Redis**: Use `ttl` argument (not `expire_seconds`) in `StateStore.set()` calls.
- **No cross-service imports**: Services communicate only via ZMQ pub/sub and Redis. S0X must never import from S0Y.
- **DIP**: `core/` never imports from `services/`. Services depend on `core/` abstractions.
- **Broker ABC**: S06 execution uses `Broker` ABC. New brokers implement the interface, register in `BrokerFactory`.
- **S05 is a VETO**: Risk Manager circuit breaker cannot be bypassed.

## Red flags to avoid

- `float()` on prices, sizes, PnL, fees -- use `Decimal`
- `datetime` without timezone -- use `datetime.now(timezone.utc)`
- `print()` for logging -- use `structlog`
- `threading.Thread` inside a service -- use `asyncio`
- Bare `except Exception: pass` -- always log the exception
- `# type: ignore` without a documented reason

## Academic rigor

- Quant implementations must cite canonical references in docstrings
- See `docs/ACADEMIC_REFERENCES.md` for approved sources
- See `docs/adr/0002-quant-methodology-charter.md` for methodology charter
- See `docs/adr/ADR-0004-feature-validation-methodology.md` for feature validation pipeline

## CI/CD

- Code must be environment-agnostic (Windows + Linux)
- `PYTHONPATH` must be set in workflows to resolve `core/`
- Windows: use `asyncio.WindowsSelectorEventLoopPolicy()` when `sys.platform == 'win32'`
