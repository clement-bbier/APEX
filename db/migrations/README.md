# `db/migrations/` — APEX TimescaleDB migration runbook

This directory holds every SQL file that defines the persistence layer of
the APEX trading system. The canonical reference for **what** is in each
file is its own header; this README covers **how** the files are named,
applied, and rolled back (or rather, why they are not).

---

## 1. Naming convention

```
NNN_short_snake_case_description.sql
```

- `NNN` — three-digit zero-padded ordinal. Lexical sort == application
  order. Gaps are allowed but avoided.
- `short_snake_case_description` — describes the scope, not the ticket.
  Keep it short enough to stay readable in `ls` output.

Current files:

| File | Scope | Notes |
|---|---|---|
| `001_universal_schema.sql` | Phase 2 ingestion data layer (assets, bars, ticks-by-asset-id, macro, fundamentals, corp events). | Pre-dates Phase B multi-strat. |
| `002_feature_store.sql` | Phase 3 feature store (feature_values, feature_versions). | — |
| `001_apex_initial_schema.sql` | **Schema v2** — multi-strat-aware (apex_ticks, apex_bars_1m, apex_signals, apex_order_candidates, apex_approved_orders, apex_executed_orders, apex_trade_records, apex_pnl_snapshots, apex_strategy_metrics, apex_regime_states, apex_risk_limits). See ADR-0014. | Additive; never drops anything. All tables carry an `apex_` prefix to coexist with the v1 schema. |

> Schema v1 (`001_universal_schema.sql`, legacy) and Schema v2
> (`001_apex_initial_schema.sql`, current) coexist on the same database.
> v2 uses an `apex_` table prefix to avoid name collision with v1 tables
> (notably `ticks` and `bars`, which v1 defines with different column
> sets). Both files are individually idempotent and can be applied
> together to the same database in lexical order; the `apex_` prefix is
> the invariant that keeps them from clobbering each other. v1 will be
> retired in a future ADR with an explicit data-migration path, at which
> point the `apex_` prefix can be dropped via a renaming migration.

---

## 2. Invariants every migration MUST satisfy

1. **Idempotent.** `CREATE ... IF NOT EXISTS`, `if_not_exists => TRUE` on
   every TimescaleDB helper, `ON CONFLICT DO NOTHING` on every seed
   `INSERT`. Re-running a migration is a no-op by construction.
2. **Forward-only.** No `DROP TABLE`, no `ALTER ... DROP COLUMN`, no
   `DELETE` on non-seed data. Destructive changes require a new file with
   a dedicated ADR that documents the blast radius and the rollback plan
   (if any).
3. **Strategy-aware.** Every order-path, PnL, or metrics table carries
   `strategy_id TEXT NOT NULL DEFAULT 'default'` per Charter §5.5.
4. **Typed correctly.** `NUMERIC(20,8)` for prices / sizes / PnL / fees;
   `TIMESTAMPTZ` for every timestamp; `JSONB` for structured metadata.
   Never `FLOAT` for money.
5. **No hidden state.** Every DDL in the file is visible. No
   `psql \include`. No outside scripts called during apply.

---

## 3. Runbook — local development

### 3.1 Fresh bring-up

```bash
scripts/db/init.sh
```

The script:

1. Runs `docker compose -f docker/docker-compose.yml up -d timescaledb`.
2. Polls `pg_isready` until the container reports healthy (up to 60s).
3. Applies every `*.sql` file in this directory in lexical order via
   `psql` invoked inside the container.
4. Prints the `schema_versions_v2` contents as a sanity check.

### 3.2 Re-apply after pulling new migrations

Same command — it is idempotent:

```bash
scripts/db/init.sh
```

### 3.3 Full teardown (DEV ONLY)

```bash
scripts/db/reset.sh
```

This destroys the volume. It prompts for confirmation and refuses to run
unless `APEX_ENV=dev` is explicitly set. Never run in staging/prod.

---

## 4. Rollback policy

**Rollback of a time-series schema is almost never safe in practice.**
Once chunks are compressed or retention has dropped older data, there is
no symmetric "undo". This codebase accepts that reality:

- **Forward-only migrations.** A mistake in migration `N` is corrected
  by migration `N+1`, not by editing `N` after it has been applied.
- **The only "rollback" is dev-env reset.** `scripts/db/reset.sh` wipes
  the volume so the next `init.sh` rebuilds from scratch. This is a
  developer escape hatch, not a production procedure.
- **Schema v2 is additive.** It never touches the rows written by the
  earlier `001_universal_schema.sql` or `002_feature_store.sql`. A future
  migration that *does* touch existing data must cite ADR-0014 §3 and
  open a dedicated ADR explaining why forward-only does not suffice.

---

## 5. Why raw SQL instead of Alembic

- TimescaleDB hypertables, compression, and retention policies are not
  first-class citizens in Alembic autogenerate — every non-trivial
  statement ends up in `op.execute(...)` anyway.
- Hedge-fund convention for time-series workloads is explicit SQL the
  DBA can read in a single file, not Python migration chains.
- The application layer uses `asyncpg` directly via `core/db.py`. No ORM
  is in use. Introducing Alembic just to track migrations adds a moving
  part without upside.
- If a non-time-series subsystem ever adopts an ORM, Alembic can be
  layered on that subsystem only without touching this directory.

See ADR-0014 for the full rationale.

---

## 6. Adding a new migration — checklist

1. [ ] Pick the next `NNN_` ordinal by lexical sort.
2. [ ] File header cites the ADR that motivated the change.
3. [ ] Every DDL is idempotent.
4. [ ] Every new table has a `strategy_id` column if it is per-strategy.
5. [ ] Prices / sizes / PnL use `NUMERIC(20,8)`.
6. [ ] Timestamps use `TIMESTAMPTZ`.
7. [ ] A row is appended to `schema_versions_v2` with the filename.
8. [ ] `scripts/db/init.sh` succeeds on a clean environment.
9. [ ] `scripts/db/init.sh` succeeds a *second* time (idempotency proof).
10. [ ] Corresponding unit or integration test exercises the new table.
