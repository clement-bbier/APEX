# `trades:all` Readers Migration Audit — Phase A.12.2

**Date**: 2026-04-23
**Author**: Claude Opus 4.7 (Sprint 4 Vague 2 Wave B, Agent B)
**Origin**: PR #212 (Sprint 3B orphan audit) → PR #253 (writer, Sprint 4 V2 WA) → this PR (readers, Sprint 4 V2 WB)
**Closes**: issue #238

---

## 1. Context

The Phase A.12 pipeline targets a canonical, per-strategy-partitioned trade-record surface under the legacy `trades:all` Redis list. It was decomposed into three sequential deliverables after the Sprint 3B audit ([PR #212](https://github.com/clement-bbier/APEX/pull/212), commit `3e2fa76`) revealed that the key had six readers and zero writers — the classic orphan-read pathology documented in [`TRADES_KEY_WRITER_AUDIT_2026-04-20.md`](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md).

| Deliverable | Issue | PR | Scope |
|-------------|-------|-----|-------|
| 1. Audit | #237 decomposition | [#212](https://github.com/clement-bbier/APEX/pull/212) | Enumerate the six readers; document the orphan |
| 2. Writer | [#237](https://github.com/clement-bbier/APEX/issues/237) | [#253](https://github.com/clement-bbier/APEX/pull/253) | Canonical `TradesWriter` in S09 feedback_loop |
| 3. Readers | [#238](https://github.com/clement-bbier/APEX/issues/238) | this PR | Classify, migrate where needed, add regression tests, add E2E |

This document is the record for step 3.

## 2. Canonical schema (PR #253)

The canonical wire format produced by [`TradesWriter.record_trade`](../../services/feedback_loop/trades_writer.py) (`services/feedback_loop/trades_writer.py:243`) is:

- **Redis key**: `trades:all` (legacy aggregate, preserved for backward compat per Charter §5.5 / Roadmap §2.2.5) **and** `trades:{strategy_id}:all` (per-strategy, Charter §5.5, ADR-0007 §D6).
- **Storage type**: Redis list. Values are JSON-encoded scalars, one entry per `LPUSH`.
- **Per-entry shape**: `TradeRecord.model_dump(mode="json")` — a `dict` with every field of [`TradeRecord`](../../core/models/order.py) (`core/models/order.py:339`), with `Decimal` fields serialized as strings, `Direction` as its `StrEnum` value, and `int`/`float`/`str` fields as themselves.
- **Ordering**: `LPUSH` places newest at index 0. Readers reading `lrange(..., 0, N-1)` receive the most recent `N` trades; readers reading `lrange(..., 0, -1)` receive the full list, newest first.
- **TTL**: none at writer level. Size-bounded via `ltrim(..., 0, DEFAULT_TRIM_SIZE-1)` (10 000 entries per key).
- **Invariant**: each `lrange` entry, when fed into `TradeRecord(**entry)`, reconstructs an identical `TradeRecord` (proven by `test_record_trade_payload_shape_roundtrips_through_trade_record` and the Hypothesis property test in `test_trades_writer.py`).

Compliance: CLAUDE.md §2 (Decimal as string over the wire; UTC ms timestamps; structlog), §3 (single responsibility), §5 (list-based Redis storage, JSON via `StateStore`).

## 3. Reader inventory

Six readers were enumerated in Sprint 3B (see [`TRADES_KEY_WRITER_AUDIT_2026-04-20.md`](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md) §2). Re-running the grep on the current branch (2026-04-23) confirms the count is unchanged — no reader has been added or consolidated since.

| # | File:line | Service | Function | Classification | Migration effort |
|---|-----------|---------|----------|----------------|------------------|
| 1 | [`services/feedback_loop/service.py:101`](../../services/feedback_loop/service.py) | S09 feedback_loop | `FeedbackLoopService._fast_analysis` | **M1** | regression test only |
| 2 | [`services/feedback_loop/service.py:155`](../../services/feedback_loop/service.py) | S09 feedback_loop | `FeedbackLoopService._slow_analysis` | **M1** | regression test only |
| 3 | [`services/command_center/command_api.py:244`](../../services/command_center/command_api.py) | S10 command_center | `get_pnl` (`/api/v1/pnl`) | **M1** | regression test only |
| 4 | [`services/command_center/command_api.py:423`](../../services/command_center/command_api.py) | S10 command_center | `get_performance` (`/api/v1/performance`) | **M1** | regression test only |
| 5 | [`services/command_center/pnl_tracker.py:26`](../../services/command_center/pnl_tracker.py) | S10 command_center | `PnLTracker.get_realized_pnl` | **M1** | regression test only |
| 6 | [`services/command_center/pnl_tracker.py:72`](../../services/command_center/pnl_tracker.py) | S10 command_center | `PnLTracker.get_daily_pnl` | **M1** | regression test only |

**Total**: 6 readers. 6 × M1. Zero code changes to reader logic. 0 × M2. 0 × M3.

Classification legend (mission spec):

- **M1** — reader already expects the canonical schema; only a regression test is added.
- **M2** — reader needs a simple deserialization update.
- **M3** — reader needs logic adaptation (e.g., eliminate a redundant local aggregation).

## 4. Per-reader migration detail

### 4.1 Reader 1 — `FeedbackLoopService._fast_analysis` (`services/feedback_loop/service.py:101`)

```python
raw_trades = await self.state.lrange("trades:all", 0, KELLY_ROLLING_WINDOW - 1)
if not raw_trades:
    return
trades = [TradeRecord(**t) for t in raw_trades if isinstance(t, dict)]
```

- **Current behaviour**: calls `state.lrange`, which returns `list[dict]` (each `dict` already JSON-decoded by `StateStore.lrange` per `core/state.py:328`). Filters non-dict entries defensively, then reconstructs `TradeRecord` via `TradeRecord(**t)`.
- **Gap vs. canonical**: none. `TradeRecord(**t)` accepts exactly what `TradeRecord.model_dump(mode="json")` produces — Pydantic v2 coerces Decimal-string values back to `Decimal` via its field validators. The writer's own unit test (`test_record_trade_payload_shape_roundtrips_through_trade_record`) proves this round-trip.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/feedback_loop/test_service_canonical_trades.py::test_fast_analysis_consumes_canonical_schema` — seeds the legacy key with real `TradesWriter.record_trade` output, invokes `_fast_analysis`, asserts Kelly stats are computed and published without error.

### 4.2 Reader 2 — `FeedbackLoopService._slow_analysis` (`services/feedback_loop/service.py:155`)

```python
raw_trades = await self.state.lrange("trades:all", 0, -1)
if not raw_trades:
    return
trades = [TradeRecord(**t) for t in raw_trades if isinstance(t, dict)]
```

- **Current behaviour**: identical deserialization pattern to reader 1; reads the full list instead of a bounded window.
- **Gap vs. canonical**: none. Same round-trip guarantee as reader 1.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/feedback_loop/test_service_canonical_trades.py::test_slow_analysis_consumes_canonical_schema` — seeds via writer, invokes `_slow_analysis`, asserts `feedback:signal_quality` and `feedback:attribution` keys are populated.

### 4.3 Reader 3 — `get_pnl` (`services/command_center/command_api.py:244`)

```python
trades = await state.lrange("trades:all", 0, -1)
today_start = int(time.time() // 86400 * 86400 * 1000)
today_trades = [
    t for t in trades
    if isinstance(t, dict) and t.get("exit_timestamp_ms", 0) >= today_start
]
realized = sum(float(t.get("net_pnl", 0) or 0) for t in today_trades)
wins = sum(1 for t in trades[-50:] if isinstance(t, dict) and float(t.get("net_pnl", 0) or 0) > 0)
```

- **Current behaviour**: reads by field name (`exit_timestamp_ms`, `net_pnl`) from each dict — does **not** reconstruct a `TradeRecord`. The `exit_timestamp_ms` field is an `int` (ms since epoch) in the writer's output, and `net_pnl` is a decimal-string. Both the `>= today_start` comparison and the `float(t.get("net_pnl", 0) or 0)` arithmetic work correctly for these wire shapes.
- **Gap vs. canonical**: none. The field names match; the string→float coercion handles the Decimal-string case explicitly.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/command_center/test_command_api_canonical_trades.py::test_get_pnl_consumes_canonical_schema` — seeds via writer output, asserts `realized_today`, `win_rate_rolling`, `trade_count_today` are correctly populated.

### 4.4 Reader 4 — `get_performance` (`services/command_center/command_api.py:423`)

```python
trades = await state.lrange("trades:all", 0, -1)
...
total_trades=len(trades),
```

- **Current behaviour**: reads the full list; the only use of `trades` is `len(trades)`.
- **Gap vs. canonical**: none. `len(list[dict])` is trivially correct.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/command_center/test_command_api_canonical_trades.py::test_get_performance_counts_canonical_trades` — seeds via writer, asserts `total_trades` equals the number of trades written.

### 4.5 Reader 5 — `PnLTracker.get_realized_pnl` (`services/command_center/pnl_tracker.py:26`)

```python
trades = await state.lrange("trades:all", 0, -1)
total = Decimal("0")
for trade in trades:
    if isinstance(trade, dict):
        total += Decimal(str(trade.get("net_pnl", 0)))
return total
```

- **Current behaviour**: reads each dict and extracts `net_pnl` as a `Decimal` via `Decimal(str(...))`. This is defensive against both Decimal-string and raw-numeric shapes.
- **Gap vs. canonical**: none. `TradeRecord.model_dump(mode="json")` emits `net_pnl` as a string (e.g. `"123.45"`); `Decimal(str("123.45"))` → `Decimal("123.45")` exactly.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/command_center/test_pnl_tracker_canonical_trades.py::test_get_realized_pnl_consumes_canonical_schema`.

### 4.6 Reader 6 — `PnLTracker.get_daily_pnl` (`services/command_center/pnl_tracker.py:72`)

```python
today_start_ms = int(time.time() // 86400 * 86400 * 1000)
trades = await state.lrange("trades:all", 0, -1)
total = Decimal("0")
for trade in trades:
    if isinstance(trade, dict):
        exit_ms = trade.get("exit_timestamp_ms", 0)
        if exit_ms >= today_start_ms:
            total += Decimal(str(trade.get("net_pnl", 0)))
return total
```

- **Current behaviour**: reads by field names `exit_timestamp_ms` (int ms) and `net_pnl` (Decimal-string). Filters by today's midnight UTC.
- **Gap vs. canonical**: none. Both field names and shapes match the writer's output.
- **Classification**: **M1**. No code change.
- **Regression test added**: `tests/unit/command_center/test_pnl_tracker_canonical_trades.py::test_get_daily_pnl_consumes_canonical_schema`.

## 5. End-to-end integration test

New file: `tests/integration/test_trades_end_to_end.py`. Unlike the existing [`test_trades_writer_pipeline.py`](../../tests/integration/test_trades_writer_pipeline.py) (which stops at "writer writes to Redis"), this test chains the full pipeline: **publish on ZMQ → `TradesWriter` → Redis `trades:all` → each of the 6 readers**.

Scenarios:

1. `test_golden_path_five_trades_reach_all_six_readers` — publish five trades, confirm each reader sees the full set.
2. `test_empty_trades_all_readers_gracefully_return_zero` — no trades published; all readers return zero/empty without exception.
3. `test_max_buffer_trades_preserves_writer_ltrim` — publish 10 020 trades, confirm `trades:all` is capped at `DEFAULT_TRIM_SIZE` (10 000) and readers still work.
4. `test_concurrent_publish_and_read_atomicity` — readers invoked concurrently with writer; no partial-read exceptions (writer `LPUSH` is atomic at the Redis level; readers never see half-serialized frames).
5. `test_strategy_id_propagates_to_per_strategy_partition` — trades with distinct `strategy_id` land in both `trades:all` and `trades:{strategy_id}:all`; legacy readers (which don't discriminate) see the union.

The test fixture reuses the `_AsyncQueueBus` / `_StateAdapter` pattern from `test_trades_writer_pipeline.py` and builds a lightweight `_FakeStateStore` that satisfies the reader surface (`lrange`, `get`, `set`, `lpush`, `ltrim`). This keeps the test hermetic per CLAUDE.md §7 (no real Redis or ZMQ in this integration level).

## 6. Summary

- **Readers inspected**: 6.
- **Readers migrated** (code changed): 0.
- **Readers with regression test added**: 6.
- **Integration test**: 1 new file, 5 scenarios.
- **Pipeline status**: Phase A.12 (`trades:all` orphan) is now fully closed. Combined with PR #245 (`portfolio:positions` via `PositionAggregator`) and PR #249 (session/macro persisters), every Redis orphan-read identified in the Sprint 3B audit has a live writer and a regression-tested consumer.

The absence of any M2/M3 reader is itself a meaningful finding: the Sprint 3B audit identified the orphan but did not document the readers' actual deserialization contracts. Writing this audit confirms that every reader was already coded defensively to the exact shape the canonical writer produces — so the Phase A.12 split into writer-first (#237) / readers-second (#238) was strictly about **adding the missing producer**, not about resolving a schema mismatch. The regression tests in this PR are the artefact that locks the coincidence in place so no future refactor silently breaks the contract.

## 7. Cross-references

- [ADR-0007 §D6 — Strategy as microservice / `strategy_id` first-class](../adr/ADR-0007-strategy-as-microservice.md)
- [ADR-0007 §D8 — Per-strategy Redis partitioning](../adr/ADR-0007-strategy-as-microservice.md)
- [ADR-0012 §D4 — Attribution + contributor list](../adr/ADR-0012-automation-agency-and-attribution.md)
- [Charter §5.5 — Per-strategy state partitioning](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)
- [Roadmap §2.2.5 — Phase A.12 migration plan](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
- [PR #212 — Sprint 3B orphan-write audit](https://github.com/clement-bbier/APEX/pull/212)
- [PR #253 — `TradesWriter` canonical writer](https://github.com/clement-bbier/APEX/pull/253)
- [`TRADES_KEY_WRITER_AUDIT_2026-04-20.md`](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md) — original audit
- [`TRADES_WRITER_IMPL_2026-04-23.md`](./TRADES_WRITER_IMPL_2026-04-23.md) — writer implementation record
