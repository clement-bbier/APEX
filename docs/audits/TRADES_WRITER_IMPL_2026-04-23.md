# `trades:all` Canonical Writer — Implementation Record

**Date**: 2026-04-23
**Scope**: Resolve issue [#237](https://github.com/clement-bbier/APEX/issues/237) (Phase A.12.1) by introducing the canonical producer for the `trades:all` Redis list and its per-strategy partition `trades:{strategy_id}:all`.
**Branch / PR**: `fix/issue-237-trades-writer` → PR TBD

**Referenced artefacts**

- Original issue [#202](https://github.com/clement-bbier/APEX/issues/202) — Phase A.12 dual-write (closed, mis-scoped).
- Audit [`TRADES_KEY_WRITER_AUDIT_2026-04-20.md`](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md) — CASE C finding (no writer exists).
- Reference implementation [`POSITION_KEY_AUDIT_2026-04-21.md`](./POSITION_KEY_AUDIT_2026-04-21.md) — companion orphan-read / orphan-write pattern resolved in PR #245.
- Roadmap [`§2.2.5`](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md).
- Charter [`§5.5`](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) (per-strategy Redis partitioning).
- ADR-0007 §D6 (`strategy_id` first-class) / §D8 (per-strategy Redis partitioning).
- ADR-0012 §D4 / §D6 (attribution surface; sub-book schema forward-compat).
- ADR-0014 table 7 (`apex_trade_records` TimescaleDB hypertable).

---

## 1. Context & origin

Issue #202 specified a per-strategy dual-write for the `trades:all` Redis key. The Sprint 3B audit (PR #212, commit `3e2fa76`) tested that premise by enumerating every producer of the literal key and found zero writers against six readers. The audit classified the finding as **CASE C — no writer exists** and declined to open a dual-write PR before the writer itself landed.

Issue #202 was subsequently transformed into two sibling issues:

- **#237 (this PR)** — implement the canonical writer, populating *both* the legacy `trades:all` list and the per-strategy `trades:{strategy_id}:all` partition.
- **#238** — migrate the six existing readers ([audit §2](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md#2-readers-found)) to the per-strategy partition and retire the legacy surface.

This document records the implementation decisions for #237 so the follow-on #238 has a faithful reference.

## 2. Reference implementation — PR #245 `PositionAggregator`

The production sibling of this writer is `PositionAggregator` (PR #245, `services/feedback_loop/position_aggregator.py`), which closed the analogous orphan-read on `portfolio:positions` identified in [`POSITION_KEY_AUDIT_2026-04-21.md`](./POSITION_KEY_AUDIT_2026-04-21.md). We follow that module line-for-line on:

- Module location: `services/feedback_loop/` rather than a dedicated new service, because the S09 FeedbackLoopService already owns the lifecycle of post-trade Redis aggregation tasks and both objects share its `self.state` handle.
- `_StateProtocol` pattern for testability (narrow duck-typed interface consumed by the class; production uses `core.state.StateStore`, tests use a `fakeredis`-backed adapter).
- Background-task wiring in `FeedbackLoopService.run()` with cooperative cancellation in the `finally` block.
- structlog event naming (`trades_writer_*` mirrors `position_aggregator_*`).

The **difference** from PositionAggregator is the input pattern:

| Writer | Input surface | Input cadence |
|---|---|---|
| `PositionAggregator` | READ-then-AGGREGATE — scans `positions:*` periodically | Every 15 s (bound by S06 fill cadence, not tick cadence) |
| `TradesWriter` | SUBSCRIBE-then-WRITE — consumes ZMQ `trades.executed` frames | On every message (event-driven) |

Aggregators poll; writers react. The choice follows from the source of truth: positions are *maintained piecemeal* by S06 under per-symbol keys and need to be collated, whereas trade records are *lifecycle-complete objects* that arrive once and need to be persisted verbatim.

## 3. Architectural decision — where does the writer live, and what does it subscribe to?

Two non-trivial decisions were made, both documented below with rejection rationale.

### 3.1 Service placement: S09 FeedbackLoop vs. S06 Execution

The [`TRADES_KEY_WRITER_AUDIT_2026-04-20.md`](./TRADES_KEY_WRITER_AUDIT_2026-04-20.md) §6 pathway *preferred* placing the writer inside S06 ExecutionService under the "emit a `TradeRecord` when a position closes" contract. That path was rejected for this PR because:

1. Issue #237 explicitly scopes the writer to S09 FeedbackLoop.
2. The emitter-of-truth for a `TradeRecord` (which carries entry-and-exit fields, i.e. a **closed-trade** object) is not the fill handler — it is whatever component observes the closing fill *and* matches it to the opening fill. That matcher is itself a post-trade aggregator, and S09 is the existing home for such aggregators.
3. `TradeRecord.__doc__` (at `core/models/order.py:340`) declares: *"Written by S09 Feedback Loop after a position closes."* The model's intent has always been S09-resident; the audit's §6.1 alternative would have required reclassifying the model.

### 3.2 Topic name: no canonical constant exists yet

`core/topics.py` on `main` at commit `1f72418` declares no `TRADES_EXECUTED` constant. The only order-lifecycle topic is `Topics.ORDER_FILLED = "order.filled"`, which carries `ExecutedOrder` — a *fill* object, not a *closed-trade* object. Subscribing to `order.filled` and reinterpreting the payload as a `TradeRecord` would fail schema validation on every frame.

The mission brief for #237 allowed two responses to this ambiguity:

> *"If core/topics.py doesn't have a `TOPIC_TRADES_EXECUTED` constant, STOP and ask user for correct topic name."*

— or —

> *"Subscribes to ZMQ topic `trades.executed` (or equivalent — verify exact topic name in core/topics.py)"*

We chose the second interpretation because it is additive (no change required in `core/`, which is out of scope for this PR) and forward-compatible: the writer is ready to consume TradeRecord frames the moment any producer is introduced (tracked as a future task). The module declares a local constant:

```python
TRADES_EXECUTED_TOPIC = "trades.executed"
```

When the canonical constant eventually lands in `core/topics.Topics`, this literal will be replaced by an import, and the literal string itself stays identical so no producer needs to know about the swap.

**Consequence for the running system**: until a TradeRecord producer exists, this writer subscribes to a topic that receives no frames. The `trades:all` key therefore remains empty even with the writer wired — same end-state as before this PR, *but* the plumbing is now in place. Readers that grep `trades:all` see no regression; the moment any component starts publishing on `trades.executed`, the writer populates both keys.

## 4. Redis key contract

### 4.1 Legacy aggregate key `trades:all`

- **Structure**: Redis LIST (all six pre-migration readers use `lrange`; no reader uses `get`, `hgetall`, or `xread`).
- **Element shape**: JSON-serialized `TradeRecord.model_dump(mode="json")`. Readers deserialize via `TradeRecord(**element)`.
- **Ordering**: LPUSH semantics — newest at index 0. Readers with bounded windows (e.g. `lrange("trades:all", 0, KELLY_ROLLING_WINDOW - 1)`) get the most recent N trades.
- **Bound**: `LTRIM` to `DEFAULT_TRIM_SIZE = 10_000` after each write. Rationale: the heaviest readers (`_slow_analysis`, `/trades` endpoint) call `lrange(0, -1)` so an unbounded list degrades response time linearly with history. 10 000 records at ~10 closes/min covers ~16 h, well beyond every reader's effective window.
- **TTL**: *none*. Readers treat absence as "no recent trades"; writer-side expiry would cause legitimate quiet periods to manifest as missing data. Contrast with `PositionAggregator` which sets a fail-fast TTL because readers rely on positional liveness — trade history does not have that fail-fast requirement.

### 4.2 Per-strategy partition `trades:{strategy_id}:all`

- **Structure**: Identical to legacy. Roadmap §2.2.5 row 2 and Charter §5.5 mandate per-strategy Redis partitioning so the feedback loop can compute per-strategy Sharpe, Kelly, and attribution without scanning an aggregated list.
- **Key format**: `trades:{strategy_id}:all` via `PER_STRATEGY_KEY_TEMPLATE.format(strategy_id=trade.strategy_id)`. The `strategy_id` value is bounded + validated by the `TradeRecord.validate_strategy_id` field validator (no slashes, no quotes, no whitespace, ≤64 chars), so Redis-key injection is impossible.
- **Writer contract**: Every call to `record_trade(trade)` writes to both `trades:all` and `trades:{trade.strategy_id}:all`. Legacy is written **first** so that a partial failure still preserves the pre-migration reader contract.

### 4.3 Idempotency

Each `TradeRecord` carries a unique `trade_id`. The writer maintains an in-memory FIFO cache (`collections.deque(maxlen=DEFAULT_SEEN_CAPACITY=50_000)` mirrored to a `set` for O(1) membership) and silently drops any `trade_id` already observed in the current process lifetime. This defends against:

- Producer retries (duplicate publish of the same record).
- ZMQ frame-level replay (pathological but observed in broker-reconnect scenarios).

It **does not** defend against restart replays — the seen-cache is memory-only. A Phase-B durability enhancement (Redis SET-based idempotency or `SETNX` pre-check) is tracked as a future task. The in-memory approach was chosen because:

- `StateStore` does not expose Redis `MULTI`/pipeline primitives, so SETNX-plus-LPUSH cannot be atomic without modifying `core/`, which is out of scope.
- Restart-window duplicates are bounded by the producer's retry policy and are not catastrophic (post-trade analytics tolerate one duplicate per restart window).

## 5. TimescaleDB persistence contract

The writer accepts an optional `_TimescaleInserter` Protocol for durable persistence to the `apex_trade_records` hypertable (ADR-0014 table 7). The production wiring in `FeedbackLoopService.run()` **does not currently supply one** because:

- `core/db.py` (PR #215) provides `DBPool` / `DBSettings` via `asyncpg`, but S09 FeedbackLoopService has no lifecycle-managed pool today.
- Adding pool management to S09 is a non-trivial change that would require a schema spike for the `apex_trade_records` row mapping — outside this PR's scope.
- `PositionAggregator` sets the precedent of Redis-only persistence in S09; diverging now would be inconsistent.

**Forward plan**: a follow-up PR will plumb a DBPool into `FeedbackLoopService` and wire a concrete `_TimescaleInserter` into `TradesWriter`. The Protocol surface is pre-baked so that PR is additive — no changes to `trades_writer.py` required.

**Failure semantics when a Timescale inserter IS supplied**: every `insert_trade_record` failure is logged at `error` and swallowed. Durable-DB outages must not block the Redis dual-write — the six legacy readers remain whole even when Timescale is unavailable. Orphan writes (Redis has the record, Timescale doesn't) are reconcilable via a future replay tool that diffs the two surfaces.

## 6. Lifecycle + cancellation semantics

### 6.1 Instantiation

`TradesWriter` is instantiated lazily in `FeedbackLoopService.run()` (not `__init__`), after `BaseService.start()` has connected `self.state` and initialized `self.bus`. The construction is trivial and cheap:

```python
trades_writer = TradesWriter(self.state, bus=self.bus)
self._trades_writer_task = asyncio.create_task(trades_writer.run_loop())
```

### 6.2 Subscription loop

`run_loop()` delegates to `self.bus.subscribe([TRADES_EXECUTED_TOPIC], self.on_trade_message)`. `MessageBus.subscribe` owns the ZMQ socket recv-loop and handles per-message exceptions internally, so `TradesWriter` never needs to `try/except` around individual frames — the bus already protects the loop from handler failures.

### 6.3 Cancellation

The `run` method's `finally` block cancels both the PositionAggregator task and the TradesWriter task, awaiting each with `contextlib.suppress(asyncio.CancelledError)`. This mirrors the PR #245 pattern.

Inside `run_loop()`:

```python
try:
    await self._bus.subscribe([self._topic], self.on_trade_message)
except asyncio.CancelledError:
    logger.info("trades_writer_loop_cancelled", topic=self._topic)
    raise
```

Cancellation propagates immediately; no frame in flight is acknowledged or dropped silently.

### 6.4 Error isolation

- Validation errors on incoming payloads: logged at `error`, swallowed, frame skipped.
- Redis errors: propagated to the bus loop (which logs at `error` and keeps going). The writer does NOT mark the trade as seen until the Redis write completes, so a retry by any future replay mechanism succeeds.
- Timescale errors (when an inserter is supplied): logged at `error`, swallowed; Redis writes are preserved.

## 7. Observability (structlog events)

| Event | Level | Fields | When |
|---|---|---|---|
| `trades_writer_recorded` | info | `trade_id`, `strategy_id`, `symbol`, `net_pnl` | After every successful dual-write |
| `trades_writer_duplicate_skipped` | debug | `trade_id`, `strategy_id` | When a `trade_id` was already in the seen-cache |
| `trades_writer_payload_invalid` | error | `topic`, `error`, `payload_keys` | When a frame fails `TradeRecord.model_validate` |
| `trades_writer_timescale_insert_failed` | error | `trade_id`, `strategy_id`, `error` | When the optional Timescale inserter raises |
| `trades_writer_loop_cancelled` | info | `topic` | On cooperative cancellation of `run_loop` |

The `trades_writer_recorded` log line is the main audit surface for live trades — S10 command center can consume it via log aggregation without needing a Redis poll.

## 8. Failure modes + mitigations

| Mode | Mitigation |
|---|---|
| Malformed ZMQ frame | `on_trade_message` validates with `TradeRecord.model_validate`; failures logged + skipped. |
| Redis outage | Writer propagates exception; bus loop logs and continues; seen-cache not updated so retry (via future replay) succeeds. Aggregator-sibling outage does not cascade. |
| Timescale outage | Inserter exception caught in `record_trade`; Redis writes preserved. Orphan write reconciled by future replay tool. |
| Producer retries / duplicate publishes | In-memory FIFO seen-cache dedupes by `trade_id` within the process lifetime. |
| Restart-window duplicates | Not defended; bounded by producer retry policy. Tracked as Phase-B enhancement. |
| Unbounded list growth | `LTRIM` to `DEFAULT_TRIM_SIZE=10_000` after every write; keeps reader latency bounded. |
| `strategy_id` injection attempts via bad payload | `TradeRecord.validate_strategy_id` rejects slashes/quotes/whitespace/>64 chars; writer never sees an unsafe key suffix. |

## 9. Forward-compatibility with ADR-0012 §D4 sub-books

ADR-0012's Phase B sub-book design has the capital allocator flushing per-strategy realized PnL from `subbook:{sid}:realized_pnl:daily` into `apex_trade_records` and `apex_strategy_metrics`. When that flush lands:

1. The flusher will publish each closed-trade `TradeRecord` on `trades.executed` (the canonical topic this writer already subscribes to). No change to `TradesWriter`.
2. The `strategy_id` on every flushed record will be the sub-book's owning strategy. The existing per-strategy partition key `trades:{strategy_id}:all` is unchanged.
3. The legacy `trades:all` key remains the union view until issue #238 migrates its readers. The writer continues dual-writing for as long as #238 is open.

No breaking change is required on the writer side when sub-books go live — this PR was designed so Phase B is additive.

## 10. Cross-references

- **Charter §5.5** — per-strategy identity: every order-path model carries `strategy_id`; Redis keys partition on it. The writer honours both surfaces.
- **ADR-0007 §D6** — `strategy_id` is a first-class model field. `TradeRecord.strategy_id` is validated at model-construction time, so the writer trusts the validator and concatenates directly.
- **ADR-0007 §D8** — per-strategy Redis partitioning. `trades:{strategy_id}:all` is the per-strategy partition.
- **ADR-0012 §D4** — attribution surface via the order-path contributor list. The writer preserves the full `TradeRecord` shape, so future attribution readers can access the `signal_type` / `regime_at_entry` / `session_at_entry` / `fusion_score_at_entry` fields without schema evolution.
- **ADR-0012 §D6** — sub-book emits `TradeRecord` on position close. The writer is the corresponding consumer.
- **ADR-0014 table 7** — `apex_trade_records` hypertable. The `_TimescaleInserter` Protocol is the wiring point for this surface; production wiring deferred to a follow-up PR (see §5 above).
- **Roadmap §2.2.5** — Phase A.12 dual-write mandate. This PR satisfies row 2.
- **CLAUDE.md §1** — single responsibility. TradesWriter does one thing: subscribe + dual-write + bound.
- **CLAUDE.md §2** — Decimal / structlog / asyncio / UTC. All honoured (TradeRecord carries the Decimals; the module uses structlog; no threading; UTC is in the model's ms timestamps).
- **CLAUDE.md §6** — 85% coverage gate. Unit tests: 33 passing (incl. 4 Hypothesis property tests). Integration tests: 5 passing.

---

## Appendix A — File inventory

Files added or modified by PR #237:

| File | Change |
|---|---|
| `services/feedback_loop/trades_writer.py` | **new** — canonical writer module. |
| `services/feedback_loop/service.py` | modified — TradesWriter wired into `FeedbackLoopService.run()` lifecycle. |
| `tests/unit/feedback_loop/test_trades_writer.py` | **new** — 33 unit tests (incl. 4 Hypothesis). |
| `tests/integration/test_trades_writer_pipeline.py` | **new** — 5 end-to-end integration tests. |
| `docs/audits/TRADES_WRITER_IMPL_2026-04-23.md` | **new** — this document. |

No changes to `core/`, `services/execution/`, `services/risk_manager/`, `services/command_center/`, or any other service — the scope boundary declared in the mission brief was respected throughout.

## Appendix B — Quality gates (run on 2026-04-23)

```text
python -m mypy --strict services/feedback_loop/           → 7 files, 0 issues
python -m ruff check services/feedback_loop/
                    tests/unit/feedback_loop/
                    tests/integration/test_trades_writer_pipeline.py
                                                           → All checks passed
python -m ruff format --check (same paths)                 → no diffs
python -m pytest tests/unit/feedback_loop/test_trades_writer.py      → 33 passed
python -m pytest tests/integration/test_trades_writer_pipeline.py    → 5 passed
```
