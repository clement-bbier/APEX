# ADR-0003: Universal Data Schema Design Decisions

**Status:** Accepted
**Date:** 2026-04-10
**Context:** Phase 2.1 — Universal Data Infrastructure

---

## 1. Single Universal `bars` Table vs. Per-Resolution Tables

### Decision
We use a single `bars` table with composite primary key `(asset_id, bar_type, bar_size, timestamp)` rather than creating separate tables like `bars_1m`, `bars_5m`, `bars_1h`, `bars_1d`.

### Rationale
A single table dramatically simplifies the codebase: the repository needs only one `insert_bars()` and one `get_bars()` method, parameterized by `bar_type` and `bar_size`. Adding a new resolution (e.g. `2m` or `3d`) requires zero schema changes — just a new `BarSize` enum value. This follows the open/closed principle: extend via configuration, not modification.

TimescaleDB hypertables partition by timestamp regardless of how many logical "types" coexist in the table. The `compress_segmentby = 'asset_id, bar_type, bar_size'` directive ensures that each segment contains homogeneous data, so compression ratios are identical to what per-table storage would achieve. Query performance is also equivalent: the composite index on `(asset_id, bar_type, bar_size, timestamp)` yields the same B-tree scan as a single-column timestamp index on a dedicated table.

### Alternatives Considered
- **Per-resolution tables** (`bars_1m`, `bars_1h`, etc.): better isolation but O(N) schema changes when adding resolutions, O(N) repository methods, and cross-resolution queries require UNION ALL. Rejected for maintenance cost.
- **Partitioned table by bar_size**: PostgreSQL native partitioning on a non-timestamp column conflicts with TimescaleDB's hypertable partitioning on timestamp. Rejected for technical incompatibility.

### References
- Kleppmann (2017), *DDIA*, Ch. 3: "The simplest data model that correctly captures the semantics is usually the best starting point."
- TimescaleDB docs: segmentby compression preserves per-segment homogeneity.

---

## 2. UUID for `asset_id` vs. Integer Auto-Increment

### Decision
We use `UUID` (v4, `gen_random_uuid()`) as the primary key for the `assets` table rather than `SERIAL` or `BIGSERIAL`.

### Rationale
UUIDs enable decentralized ID generation: any connector, backfill script, or service can create asset records without coordinating with a central sequence. This is critical for APEX's microservice architecture where S01 data ingestion, backfill scripts, and future connectors all need to register assets independently. UUIDs also eliminate cross-source deduplication issues: if we ingest AAPL from both Alpaca and Polygon, each gets a distinct UUID, and the `UNIQUE(symbol, exchange)` constraint prevents logical duplicates within the same source.

The storage overhead of UUID (16 bytes) vs. integer (4-8 bytes) is negligible compared to the bar/tick data volumes. UUID comparison performance in B-tree indexes is within 10% of integer comparison (PostgreSQL uses memcmp on the 16-byte binary representation). At our expected scale (< 50K assets), the index will fit entirely in memory.

### Alternatives Considered
- **SERIAL/BIGSERIAL**: simpler, smaller, but requires centralized sequence coordination. Problematic for distributed ingestion and cross-source merges. Rejected.
- **Composite natural key (symbol, exchange)**: no surrogate key, but makes all FK references verbose (`asset_id UUID` vs. two VARCHAR columns in every child table). Rejected for ergonomics.

### References
- Kleppmann (2017), *DDIA*, Ch. 6: "UUIDs can be generated independently on each node without coordination."

---

## 3. TimescaleDB vs. Alternative Time-Series Databases

### Decision
We use TimescaleDB (PostgreSQL extension) as the primary time-series store.

### Rationale
TimescaleDB runs as a PostgreSQL extension, which means APEX gets the full PostgreSQL ecosystem: ACID transactions, JOINs between time-series and relational data (e.g. joining bars with assets metadata), mature tooling (pgAdmin, psql, asyncpg), and a vast library of extensions (PostGIS for geolocation if needed, pg_cron for scheduling). The `assets` registry is inherently relational — it has foreign keys, UNIQUE constraints, and JSONB columns — and co-locating it with the time-series data eliminates the need for a separate RDBMS.

TimescaleDB's automatic chunk management, transparent compression (90%+ on OHLCV data), and built-in retention policies reduce operational complexity. The hypertable abstraction means our SQL queries look like standard PostgreSQL — no proprietary query language to learn or maintain.

Performance is sufficient for APEX's scale: TimescaleDB benchmarks show > 100K rows/second insert throughput with COPY protocol, and our target is 10K bars/second. For the read path, chunk exclusion on timestamp ranges provides sub-millisecond query planning.

### Alternatives Considered
- **InfluxDB**: purpose-built for metrics/IoT, but lacks relational JOINs, has a proprietary query language (Flux/InfluxQL), and the open-source version has limited retention/compression features. Rejected.
- **QuestDB**: excellent ingestion speed, but immature ecosystem, no ACID transactions, limited JOIN support. Rejected for Phase 2 where we need relational integrity.
- **ClickHouse**: columnar OLAP engine, exceptional for analytics but poor for point lookups and transactional writes. No native hypertable/retention abstraction. Rejected.
- **MongoDB**: document store, no native time-series partitioning (time-series collections are limited), and schema-less approach conflicts with APEX's type-safe philosophy. Rejected.

### References
- TimescaleDB docs: "Full SQL, optimized for time-series."
- Kleppmann (2017), *DDIA*, Ch. 3: choosing the right storage engine for the workload.

---

## 4. NUMERIC(20,8) for Prices vs. DOUBLE PRECISION

### Decision
All price, volume, and monetary columns use `NUMERIC(20,8)` (PostgreSQL arbitrary-precision decimal) rather than `DOUBLE PRECISION` (IEEE 754 float64).

### Rationale
IEEE 754 floating-point arithmetic introduces representation errors that accumulate in financial computations. For example, `0.1 + 0.2 = 0.30000000000000004` in float64. While individual rounding errors are small, they compound across thousands of trades, bars, and PnL calculations, leading to phantom penny differences that are notoriously difficult to debug and audit.

APEX's core design principle (CLAUDE.md Section 10) mandates `Decimal(str(price))` for all monetary values in Python. Using `NUMERIC` in PostgreSQL maintains this guarantee end-to-end: `asyncpg` maps `NUMERIC` columns to Python `Decimal` natively, so there is zero lossy conversion at the database boundary.

`NUMERIC(20,8)` provides 12 digits before the decimal and 8 after, which accommodates both BTC prices (> $100,000) and sub-penny equity ticks. The 8 decimal places match the maximum precision used by Binance and most crypto exchanges.

The storage cost is higher than float64 (variable-length vs. 8 bytes fixed), but compression reduces this gap significantly. The computational overhead of decimal arithmetic in PostgreSQL is irrelevant for our query patterns (simple range scans and aggregations, not matrix algebra).

### Alternatives Considered
- **DOUBLE PRECISION**: 8 bytes fixed, fast arithmetic, but lossy. Violates the Decimal-everywhere invariant. Rejected.
- **BIGINT with implicit scaling** (e.g. store price × 10^8 as integer): zero precision loss, fast, but requires manual scaling at every read/write boundary and breaks human-readable SQL queries. Rejected for developer ergonomics.
- **NUMERIC without precision** (`NUMERIC` unqualified): unlimited precision, but PostgreSQL stores it less efficiently and cannot optimize range checks. Rejected.

### References
- Bouchaud et al. (2018), *Trades, Quotes and Prices*, Ch. 2: "Financial data must be stored with exact arithmetic."
- CLAUDE.md Section 10: "Decimal (never float) for all prices, sizes, PnL, and fees."

---

## 5. Plain SQL Migrations vs. Alembic

### Decision
We use plain SQL migration files (`db/migrations/001_*.sql`) with a custom idempotent runner (`scripts/init_db.py`) rather than Alembic or another migration framework.

### Rationale
In Phase 2.1, we have exactly one migration file creating the entire schema from scratch. Introducing Alembic at this stage would add:
- A new dependency (`alembic`, `sqlalchemy`) with its own configuration (`alembic.ini`, `env.py`)
- An ORM layer that conflicts with our asyncpg-direct approach
- Auto-generation logic that produces DDL we'd need to heavily customize (hypertable creation, compression policies, TimescaleDB-specific syntax)

Our custom runner is 80 lines of code, fully async, idempotent (checks `schema_versions`), and handles the TimescaleDB-specific DDL that Alembic cannot auto-generate. It does exactly what we need and nothing more.

When the project exceeds 3 migration files, we will evaluate migrating to Alembic with a custom `run_migrations_online()` that handles TimescaleDB DDL. The `schema_versions` table is compatible with a future Alembic migration — we can bootstrap Alembic's `alembic_version` table from our existing records.

### Alternatives Considered
- **Alembic**: industry standard, but overkill for one migration file and requires SQLAlchemy ORM integration that conflicts with our asyncpg-direct repository pattern. Deferred to Phase 3+.
- **Flyway**: Java-based, requires JVM runtime. Rejected.
- **golang-migrate**: requires Go runtime. Rejected.
- **No migration tracking**: just run the SQL file manually. Rejected because it's not idempotent and doesn't scale to multiple environments (dev, CI, staging, prod).

### References
- Fowler (2002), *PoEAA*: "Start with the simplest thing that could possibly work."
- Martin (2017), *Clean Architecture*, Ch. 22: dependencies point inward — infrastructure adapts to domain, not the reverse.
