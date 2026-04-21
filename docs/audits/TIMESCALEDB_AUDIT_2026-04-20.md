# TimescaleDB Infrastructure Audit — 2026-04-20

**Scope**: foundation for `infra/timescale-schema-v2`. What exists, what is missing, chosen migration strategy.

---

## 1. Existing state

### 1.1 Docker Compose

`docker/docker-compose.yml` already declares a `timescaledb` service:

- Image: `timescale/timescaledb:latest-pg16` (not the `-ha` variant)
- Env: `POSTGRES_DB=apex`, `POSTGRES_USER=apex`, `POSTGRES_PASSWORD=${DB_PASSWORD:-apex_secret}`
- Volume: `timescale_data:/var/lib/postgresql/data`
- Healthcheck: `pg_isready -U apex` (10s interval, 5 retries)
- Network: `apex`
- `s01-serving` and `s01-orchestrator` depend on `timescaledb: service_healthy`

### 1.2 Existing SQL migrations

```
db/migrations/001_universal_schema.sql     (8765 bytes) — assets, bars, ticks (asset_id FK based), macro, fundamentals, events, dq, ingestion, schema_versions
db/migrations/002_feature_store.sql        (2822 bytes) — feature_values, feature_versions
```

Both files were authored for the **Phase 2 / Phase 3 data-ingestion era**. They are:

- **Asset-centric** (FK to `assets.asset_id`), designed for data-ingestion use cases
- **Single-strategy** — no `strategy_id` anywhere
- **Not wired** into any live service as the order-path persistence layer. The existing `core/data/timescale_repository.py` uses them for S01 data ingestion only.

### 1.3 Migration tooling

- No Alembic / yoyo / goose / dbmate detected
- `scripts/init_db.py` exists (Python driver; used only for S01 ingest bootstrap)
- `pyproject.toml` has no `testcontainers` dependency

### 1.4 Python deps

- `asyncpg>=0.30.0,<1.0.0` ✅ already present
- `core/data/timescale_repository.py` already uses asyncpg pool with JSONB codec registration
- `core.config.Settings` already has `timescale_host/port/db/user/password/pool_min/pool_max` + `timescale_dsn` property

---

## 2. Gap analysis vs Phase B / Charter §5.5

Charter §5.5 mandates `strategy_id` on every order-path model (`Signal`, `OrderCandidate`, `ApprovedOrder`, `ExecutedOrder`, `TradeRecord`) with default `"default"`. The current schemas have **no persistence tables at all** for those five models — only asset data and features.

The order-path, PnL, risk, and regime tables **do not exist**. There is therefore nothing to migrate in the per-strategy sense — the schema is a **greenfield addition**.

Phase B roadmap §3 (line 429) anticipates a "TimescaleDB schema migration [that] adds nullable column; existing rows are populated with `'default'` on read" — but that comment assumes order-path tables already exist, which they do not.

---

## 3. Chosen migration strategy

**Scenario B** (user-confirmed): base exists but is not load-bearing. Dev-env only; no production data at risk.

**Chosen approach: additive migration, forward-only, fully idempotent.**

- Keep `001_universal_schema.sql` and `002_feature_store.sql` untouched. They describe the ingestion layer and will continue to be applied.
- Add a new migration `db/migrations/001_apex_initial_schema.sql` that creates the **11 schema-v2 tables** described in ADR-0014 (ticks, bars_1m, signals, order_candidates, approved_orders, executed_orders, trade_records, pnl_snapshots, strategy_metrics, regime_states, risk_limits).
- ⚠️ File-number collision note: there is already a `001_universal_schema.sql`. The new file is named `001_apex_initial_schema.sql` because ADR-0014 treats it as the *initial* multi-strat schema (schema v2 takes identity 001 in the new migration lineage). The `init.sh` runner applies every `*.sql` file in sorted order — the two `001_*` files are disambiguated by the suffix, and both are idempotent (`CREATE TABLE IF NOT EXISTS`, `if_not_exists => TRUE` on hypertable/policy calls), so running both is safe. A follow-up cleanup can renumber later under its own ADR.
- Every DDL is guarded with `CREATE ... IF NOT EXISTS`, `if_not_exists => TRUE`, or `ON CONFLICT DO NOTHING`. Re-running the migration must be a no-op.
- **No DROP.** If a future change needs a destructive step, it gets a separate migration file under its own ADR.

### Rationale

- Forward-only is the hedge-fund convention: destructive rollback on time-series data is essentially never safe.
- Idempotency is cheap, and lets any environment (dev laptop, CI, future prod) converge via `bash scripts/db/init.sh` without state tracking beyond what TimescaleDB itself records.
- Per-strategy-tagged tables are **new** in v2; there are no pre-existing rows to backfill. The `"default"` sentinel is applied by the application layer on every INSERT path (not by the DB).
- We deliberately do NOT adopt Alembic here. Charter + user preference: hedge-fund standard for time-series workloads is raw SQL with explicit control. Alembic's autogenerate is designed for ORM-tracked relational models, not hypertables with compression/retention policies. If an ORM is ever adopted for a non-time-series subsystem, Alembic can be layered on that subsystem only.

---

## 4. Tooling additions required

- `testcontainers-python` → add to `[dependency-groups.dev]` in `pyproject.toml` (currently absent)
- `core/db.py` — new, minimal asyncpg pool wrapper (distinct from `core/data/timescale_repository.py` which is domain-specific to S01 ingest)
- `scripts/db/init.sh`, `scripts/db/reset.sh` — new lifecycle entry points
- `docker/docker-compose.yml` — bump image to `timescale/timescaledb-ha:pg16` and mount `db/migrations/` as `/docker-entrypoint-initdb.d/` (init-on-first-boot path)

---

## 5. Verdict

Ship the 11 new v2 tables as a single additive migration. No destructive operation on existing tables. No Alembic. Fresh asyncpg primitive under `core/db.py`. All idempotent. Retention/compression policies per ADR-0014.
