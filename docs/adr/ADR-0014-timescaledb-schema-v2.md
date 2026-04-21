# ADR-0014 - TimescaleDB Schema v2 (Multi-Strategy Persistence Foundation)

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None (additive - pre-existing 001_universal_schema.sql and 002_feature_store.sql remain in place for the ingestion layer) |
| Superseded by | None |
| Related | Charter sec 5.5 (per-strategy identity), ADR-0007 (strategy-as-microservice), ADR-0010 (target topology), Roadmap sec 3 (Phase B) |

---

## 1. Context

Phase A of the Multi-Strat Aligned Roadmap added strategy_id to the order-path Pydantic models but did not yet introduce a persistence layer for those models. Phase B requires a durable store for:

- Per-strategy order flow: OrderCandidate -> ApprovedOrder -> ExecutedOrder -> TradeRecord (Charter sec 5.5).
- Per-strategy PnL reporting: intraday snapshots plus daily metrics consumed by the allocator (ADR-0008) and the feedback loop (S09).
- Time-series market data: ticks and 1-minute bars as reproducibility inputs for backtests and offline analysis.
- Regime classification history: recoverable regime states for post-hoc attribution and strategy health checks.
- Risk envelopes: per-strategy limits consulted by the VETO chain (STEP 3 StrategyHealthCheck per Roadmap sec 3.2.3 / sec 4.2.3).

The existing 001_universal_schema.sql (assets, bars, ticks-by-asset-id, macro, fundamentals, feature store) pre-dates the multi-strategy Charter. It is asset-centric, single-strategy, and wired into S01 data ingestion only. It cannot carry the order-path or PnL requirements of Phase B without significant additive tables.

At the same time, the user has confirmed a Scenario B posture: the existing tables are not load-bearing in any deployed environment (Phase 2/3 fixtures only; CD disabled; no production rows at risk). This gives us room to introduce a clean v2 schema without a complex migration dance, provided v2 is additive and idempotent.

Two orthogonal questions had to be decided:

1. Migration tool. Alembic (Python migration DAG) vs raw SQL files applied by a shell runner.
2. Schema layout. One giant generic events table vs eleven focused tables matching the Pydantic model hierarchy.

---

## 2. Decision

We ship a schema v2 consisting of eleven additive tables, authored as a single idempotent SQL migration applied directly via psql, with no ORM and no Alembic.

### 2.1 The eleven tables

| # | Table | Kind | Hypertable | Retention | Compression | Per-strategy |
|---|---|---|---|---|---|---|
| 1 | ticks | raw tick / top-of-book | yes, ts, 1 day | 90 days | after 7 days | no (asset-level) |
| 2 | bars_1m | 1-min OHLCV | yes, ts, 1 day | 730 days | after 30 days | yes |
| 3 | signals | strategy signals | yes, ts, 1 day | 730 days | - | yes |
| 4 | order_candidates | pre-VETO proposals | yes, ts_proposed, 1 day | - | - | yes |
| 5 | approved_orders | post-VETO approvals | yes, ts_approved, 1 day | - | - | yes |
| 6 | executed_orders | broker fills | yes, ts_submitted, 1 day | - | - | yes |
| 7 | trade_records | closed-trade PnL | yes, ts_close, 1 day | - | - | yes |
| 8 | pnl_snapshots | portfolio state | yes, snapshot_ts, 1 hour | - | - | yes |
| 9 | strategy_metrics | daily perf metrics | regular | - | - | yes |
| 10 | regime_states | regime labels | yes, ts, 1 day | - | - | no (global) |
| 11 | risk_limits | per-strategy envelopes | regular | - | - | yes |

Every order-path / PnL / metrics table includes `strategy_id TEXT NOT NULL DEFAULT 'default'` per Charter sec 5.5. Prices, sizes, PnL and fees are NUMERIC(20,8). Timestamps are TIMESTAMPTZ. Structured metadata (features, targets, positions, risk_chain_result) is JSONB.

A one-row seed populates risk_limits('default', ...) with placeholder limits so the legacy path does not trip STEP 3 during Phase B bring-up. Real limits are written by each Gate 2 PR per Playbook sec 4.

### 2.2 Migration toolchain

- Raw SQL in db/migrations/*.sql, applied in lexical order by scripts/db/init.sh.
- Every DDL is idempotent: CREATE ... IF NOT EXISTS, if_not_exists => TRUE on TimescaleDB helpers, ON CONFLICT DO NOTHING on seed inserts.
- Forward-only. No DROP, no destructive ALTER, no deletes on non-seed rows. Corrections are new migrations (002_..., 003_...).
- Dev-env reset is the only "rollback": scripts/db/reset.sh wipes the Docker volume, gated behind APEX_ENV=dev plus a typed WIPE confirmation.

### 2.3 Application-layer primitive

core/db.py provides DBPool (async context manager wrapping asyncpg.create_pool) and DBSettings (env-driven dataclass). The existing core/data/timescale_repository.py - a richer repository for the ingestion layer - remains in place. New Phase B services that need persistence depend on core/db.py directly rather than the ingestion-specific repository.

---

## 3. Rationale

### 3.1 Why eleven focused tables rather than a generic event table

A generic events(event_type, payload_jsonb, ts) table is tempting because it requires no future migrations. It is also the wrong answer for a trading system:

- Query plans for strategy-scoped range scans on strategy_id + ts are dominated by the column layout. Narrow tables with indexed (strategy_id, ts DESC) serve the feedback loop, allocator, and backtest replay in constant-ish time. A generic table forces every read to deserialise JSONB, defeating the reason we picked TimescaleDB.
- Schema enforcement at the DB layer catches entire classes of bugs (direction check constraints, confidence in [0,1], NUMERIC(20,8) preventing float drift) before they hit the trading path.
- Compression segmentation (segmentby = 'strategy_id, symbol' on bars_1m) gives 10x+ compression ratios for homogeneous time-series. It requires columnar per-table layout - it is not available on a generic JSONB store.

The eleven-table split mirrors the immutable Pydantic hierarchy (Tick -> Signal -> OrderCandidate -> ApprovedOrder -> ExecutedOrder -> TradeRecord) one-to-one, plus five cross-cutting tables (bars_1m, pnl_snapshots, strategy_metrics, regime_states, risk_limits). This is the minimum that makes the model hierarchy round-trippable.

### 3.2 Why raw SQL and asyncpg, not Alembic plus an ORM

- TimescaleDB primitives are not Alembic-native. create_hypertable, add_retention_policy, add_compression_policy, timescaledb.compress_segmentby are all raw SQL calls - Alembic autogenerate does not emit them, so every non-trivial migration ends up inside op.execute("...") anyway. We skip the wrapper.
- Explicit control is hedge-fund convention. Time-series workloads with compression, retention, and continuous-aggregate policies need a DBA-readable migration file. A Python DAG adds indirection, not clarity.
- No ORM means no lazy loading, no hidden queries, no identity map surprises. Inner-loop hot paths write with COPY and read with explicit queries - every byte on the wire is visible in a grep.
- asyncpg is the fastest PostgreSQL driver in Python by a wide margin, and it is already a dependency via core/data/timescale_repository.py. Adding an ORM on top of asyncpg is a net performance regression for the pipeline's hot paths.
- If a non-time-series subsystem ever needs an ORM, SQLAlchemy plus Alembic can be layered on that subsystem only. The hypertables in this ADR stay in raw SQL.

### 3.3 Why forward-only and idempotent

- Rollback on a compressed hypertable is not the symmetric inverse of the forward DDL. Once chunks are compressed or retention has dropped rows, the old state is irrecoverable. Any migration discipline that promises "down" in that environment is misleading.
- Idempotent DDL means convergence can be re-run from any state without tracking what has or has not been applied. That matches how the pipeline handles other idempotent operations (dual-writes, replay of Redis keys, etc.).
- A forward-only history is a clean audit trail: the sequence of files in db/migrations/ is the total history of the persistence layer.

### 3.4 Why 'default' rather than NULL for unfilled strategy_id

Charter sec 5.5 mandates the sentinel 'default' string so the legacy single-strategy path - which will be wrapped as LegacyConfluenceStrategy in Phase B sec 3.2.1 - emits rows that are indistinguishable from a modern strategy at the persistence layer. NULL would force every downstream aggregate (GROUP BY strategy_id) to coalesce defensively. A sentinel avoids that at the cost of a reserved name in the strategy namespace.

---

## 4. Consequences

### 4.1 Positive

- Per-strategy observability is now mechanically enabled from the DB layer up. Any dashboard, feedback-loop query, or allocator input can filter on strategy_id without joins.
- Backtest reproducibility is preserved because every signal, candidate, approval, fill, and close is persisted with its strategy tag.
- Phase B unblocked. The StrategyHealthCheck state machine (Roadmap sec 3.2.3) can write to risk_limits; the allocator (Roadmap sec 4.2.4) can read strategy_metrics; the feedback loop (S09) can read trade_records directly instead of reconstructing from Redis lists.
- Development velocity. A fresh scripts/db/init.sh on a dev laptop produces a fully initialised schema in under 60s.

### 4.2 Negative

- Two schema lineages coexist (001_universal_schema.sql legacy ingest layer plus 001_apex_initial_schema.sql v2). Any future consolidation is its own ADR.
- No backfill of legacy rows into v2 tables. Phase B services see empty tables on first boot and populate them going forward. Historical replay for pre-Phase-B data requires a separate migration with its own ADR.
- Forward-only means mistakes persist. A bad migration (e.g. wrong chunk_time_interval) cannot be silently corrected; it must be fixed by a subsequent additive migration, which becomes part of the permanent history.

### 4.3 Mitigations

- Lineage confusion: db/migrations/README.md documents which file covers which layer. The per-file header points to this ADR.
- Missing backfill: the application layer tolerates empty tables (no joins on the new tables are hard-coded as existence checks). A follow-up ADR can define a backfill path once Phase B is stable.
- Forward-only mistakes: the idempotent DDL contract plus a per-file reviewer checklist in the README limit the blast radius of any single migration.

---

## 5. Alternatives Considered

### 5.1 Alembic plus SQLAlchemy ORM

Pros: auto-generated migrations from model changes; familiar to Python engineers; built-in downgrade().

Cons: TimescaleDB-specific DDL (hypertables, compression policies, retention) bypasses autogenerate; ORM identity map plus lazy loading add inner-loop overhead on hot paths; downgrade() is misleading on compressed hypertables (see sec 3.3).

Rejected: the autogenerate benefit evaporates for time-series workloads, and the ORM cost lands directly on the trading path.

### 5.2 Single generic events table (JSONB payloads)

Pros: no migrations as the Pydantic models evolve; maximum flexibility.

Cons: per-strategy scans require JSONB unnest; no column-level constraints (no CHECK on direction, no NUMERIC precision); compression segmentation is table-level, not payload-level, so compression ratios collapse.

Rejected: wrong tradeoff for a system whose inner loops are dominated by time-ranged scans.

### 5.3 Keep extending 001_universal_schema.sql in place

Pros: single lineage, simpler mental model.

Cons: that file is asset-centric (FK to assets.asset_id) and single-strategy by design. Adding strategy_id would require destructive ALTER on the existing tables, violating the forward-only posture; and the file is also already applied on some dev machines, so editing it in place is non-idempotent for those environments.

Rejected: the additive v2 schema respects both forward-only and idempotency.

---

## 6. Rollout

1. Land this ADR, the migration, core/db.py, tests, and the docker-compose update on a feature branch.
2. CI applies the migration against the testcontainer TimescaleDB; tests/unit/db/test_core_db.py proves the pool primitive works end-to-end.
3. Merge to main; Phase B services (StrategyHealthCheck, allocator, persistence-aware feedback loop) start depending on core/db.py via their own PRs.
4. The first Gate 2 strategy seeds risk_limits for its strategy_id as part of its Playbook sec 4 deliverables.

---

## 7. References

- Charter sec 5.5 - per-strategy identity and config
- ADR-0007 - Strategy as Microservice (D9 failure isolation)
- ADR-0010 - Target Topology Reorganization
- Roadmap sec 3 - Phase B infrastructure lift
- TimescaleDB docs - hypertables, compression, retention policies
