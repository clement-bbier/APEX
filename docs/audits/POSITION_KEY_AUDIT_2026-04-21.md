# Redis `portfolio:positions` Writer Audit — Phase A.9 Scoping Verification

**Audit date**: 2026-04-22
**Scope**: locate the production writer for the Redis key `portfolio:positions`
read by the S05 Risk Manager pre-trade context loader, in order to scope the
"PositionAggregator in S09" deliverable mandated by Roadmap §2.2.4 and
Issue #199 (Phase A.9).
**Referenced artefacts**:
- [Issue #199 — Phase A.9 PositionAggregator orphan-read](https://github.com/clement-bbier/APEX/issues/199)
- [Roadmap v3.0 §2.2.4](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
- [PHASE_5_SPEC v2 §3.2 — Event Sourcing producers](../phases/PHASE_5_SPEC_v2.md)
- [REDIS_KEYS_WRITER_AUDIT_2026-04-17.md](REDIS_KEYS_WRITER_AUDIT_2026-04-17.md) (parent orphan-read finding)
- [TRADES_KEY_WRITER_AUDIT_2026-04-20.md](TRADES_KEY_WRITER_AUDIT_2026-04-20.md) (template)
- [Charter §5.5 — Per-strategy Redis partitioning](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)
- [ADR-0007 §D8 — Per-strategy Redis namespace](../adr/ADR-0007-strategy-as-microservice.md)
- [ADR-0012 §D3 / §D5 — Sub-book Redis layout, aggregate veto](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md)

---

## 1. Method

1. Grep every occurrence of the literal keys `"portfolio:positions"`, `"positions:"`,
   and the f-string fragments `f"positions:{...}"` / `f"portfolio:..."` in
   `services/`, `core/`, and `tests/`.
2. Grep every Redis write primitive (`set`, `hset`, `lpush`, `xadd`, `sadd`)
   in `services/` to surface dynamic-key writers.
3. Cross-reference readers and writers; classify outcome per the Phase A
   audit decision tree (CASE A / B / C).

All commands executed on branch `fix/issue-199-position-aggregator` at
HEAD `~37f44c4 chore(deps): apply connector + benchmark dependency declarations`.

---

## 2. Readers found

| # | File | Line | Operation | Consumer context |
|---|------|------|-----------|------------------|
| 1 | [`services/risk_manager/context_loader.py`](../../services/risk_manager/context_loader.py#L37) | 37 | `"portfolio:positions"` in `REQUIRED_KEYS` | Pre-trade S05 batch read; `_require()` raises `RuntimeError` on `None` (ADR-0006 §D4 fail-loud) |
| 2 | [`services/risk_manager/context_loader.py`](../../services/risk_manager/context_loader.py#L79) | 79 | `self._require("portfolio:positions", results[5])` | Validates the payload is a `list`; per element does `Position.model_validate(p)`; per-element failures are logged and skipped (line 91) |

**Storage shape implied by the reader**: a JSON-encoded **list** of dict-shaped
position records, each conforming to `services.risk_manager.models.Position`
(`symbol: str`, `size: Decimal > 0`, `entry_price: Decimal > 0`,
`asset_class: str = "equity"`).

The fail-closed contract (ADR-0006 §D4) means any of: missing key, `None`
payload, non-`list` payload — rejects the candidate as
`SYSTEM_UNAVAILABLE`. In production this would block 100% of orders if no
producer ever runs.

---

## 3. Writers found

### 3.1 Aggregate key `portfolio:positions`

| Primitive | Target key | File | Line |
|-----------|------------|------|------|
| `set` | `portfolio:positions` | (none) | (none) |

**No production writer exists for `portfolio:positions`.** The exhaustive grep
across `services/` returned only the two reader hits above plus documentation
mentions in `MANIFEST.md`, `docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`,
and `docs/phases/PHASE_5_SPEC_v2.md`. The only writes to this exact key live
in test fixtures (`tests/unit/risk_manager/test_*` seeds via fakeredis
`redis.set("portfolio:positions", ...)`).

### 3.2 Sibling per-symbol key `positions:{symbol}`

| Primitive | Target key | File | Line | Owner |
|-----------|------------|------|------|-------|
| `state.set` | `f"positions:{symbol}"` | [`services/execution/service.py`](../../services/execution/service.py#L153) | 153 | S06 ExecutionService `_on_filled` |

S06 writes a per-symbol JSON object on every fill with the following shape:

```python
{
    "symbol":       str,            # e.g. "AAPL"
    "direction":    "LONG" | "SHORT",
    "entry":        str,            # Decimal-as-str — note: NOT "entry_price"
    "size":         str,            # Decimal-as-str
    "stop_loss":    str,
    "target_scalp": str,
    "target_swing": str,
    "opened_at_ms": int,
    "is_paper":     bool,
}
```

This is the **per-symbol fill record**, not a Position-model envelope: the
key is `entry`, not `entry_price`; `direction` is carried separately rather
than being signed into `size`; and the dict carries extra trade-context
fields the Position model does not declare. **No collision with
`portfolio:positions`**: distinct namespace, distinct shape, distinct
consumer.

---

## 4. Current atomicity pattern

**Not applicable**: the writer does not exist, so there is no pattern to
preserve. For reference, the analogous Phase A.7 / A.8 fixes
([PR #210 PortfolioTracker](https://github.com/clement-bbier/APEX/pull/210),
[PR #214 PnLTracker](https://github.com/clement-bbier/APEX/pull/214))
introduced **dual-key readers**, not writers. Phase A.9 is the **first
new producer in this Phase A orphan-read sweep** and so sets the writer
template for the remaining producer issues.

---

## 5. Decision-tree outcome

> Decision tree per the Phase A.9 mission brief:
> - **CASE A**: writer exists and reader works (false alarm).
> - **CASE B**: writer exists but uses a different key structure (alignment fix).
> - **CASE C**: writer doesn't exist (orphan read; need to create writer).

### Result: **CASE C — no writer exists**

S05's `ContextLoader` reads `portfolio:positions` as a `list[Position]`. No
production code anywhere in `services/` or `core/` writes this key. The S06
per-symbol writer at `services/execution/service.py:153` writes the
**source data** (`positions:{symbol}`) but no service rolls these per-symbol
records up into the consolidated list shape S05 expects.

The S05 fail-closed guard (STEP 0 in the chain, ADR-0006 §D1) is the only
reason production has not paged: it short-circuits to `REJECTED_SYSTEM_UNAVAILABLE`
on the missing-key `RuntimeError`. The orphan read is masked but not fixed.

---

## 6. Architecture decision — aggregator topology

Two architectures are in play:

### 6.1 Phase A topology (current, this PR)

The S06 per-symbol record at `positions:{symbol}` is the **source of truth**.
A new `PositionAggregator` in S09 (per Roadmap §2.2.4 row 4 +
PHASE_5_SPEC_v2 §3.2 module-structure block) scans `positions:*`, transforms
each record into the `Position` model envelope expected by S05, and writes
the aggregated list to `portfolio:positions`. No dual-write. No new ZMQ
topic. The aggregator runs as a background task on a fixed cadence
(snapshot interval `15s`, configurable via constructor).

This is path **(i)** from the Issue #199 mission brief: "PositionAggregator
becomes a true aggregator that reads … and emits aggregate views". Phase A
inherits a single-strategy world (`strategy_id="default"`), so per-symbol
aggregation collapses to a 1:1 transform per record. The aggregation
**math** (signed-size summation) is identical to the multi-strategy
formulation; only the input cardinality differs.

### 6.2 Phase B topology (forward compat, NOT implemented here)

Per [ADR-0012 §D2](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md),
in Phase B the source of truth becomes `subbook:{strategy_id}:position:{symbol}`
and the broker net is `Σ_{sid} subbook[sid].position(symbol)`. The
PositionAggregator's source-key scan can swap `positions:*` →
`subbook:*:position:*` without changing its output contract.

The **aggregation function** in this PR is implemented as a pure
`aggregate_records(records: dict[str, dict]) -> list[Position]` so the
Phase B refactor that adds sub-book scanning can reuse the same algebra.
This is the **only** forward-compat hook we add now — no parallel sub-book
namespace, no premature multi-strategy abstraction. See
CLAUDE.md §3 ("Don't add features beyond what the task requires") and
§5 ("Only validate at system boundaries").

---

## 7. ADR alignment

| ADR | Section | Alignment |
|-----|---------|-----------|
| [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) | §D4 | Reader stays fail-loud; aggregator failure surfaces via missing key + STEP 0 reject. **Preserved.** |
| [ADR-0007](../adr/ADR-0007-strategy-as-microservice.md) | §D8 | Per-strategy Redis namespace covers `kelly:*`, `trades:*`, `pnl:*`, `portfolio:allocation:*`. **`portfolio:positions` is explicitly NOT in §D8 enumeration**: it is the consolidated aggregate (broker-realized net), not a per-strategy intent. No `portfolio:{strategy_id}:positions` variant introduced. **Aligned.** |
| [ADR-0012](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md) | §D2 | Per ADR-0012 §D2, `broker_net(symbol) = Σ subbook[sid].position(symbol)`. The aggregator output contract (consolidated list) is identical; only the input-source migration is deferred to Phase B per §6.2 above. **Aligned forward.** |
| [ADR-0012](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md) | §D5 | The aggregator is a **read-only producer** of the aggregate list. STEP 7 PortfolioExposureMonitor still consumes through the same S05 `ContextLoader.load()` path. **Aligned.** |
| [Charter §5.5](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) | per-strategy keys | Charter §5.5 enumerated keys do not include `portfolio:positions`. Aggregator output remains a single global key. **Aligned.** |

---

## 8. Action taken by this PR

1. **New module** [`services/feedback_loop/position_aggregator.py`](../../services/feedback_loop/position_aggregator.py)
   implementing `PositionAggregator` with three public surfaces:
   - `aggregate_records(records: dict[str, dict]) -> list[Position]` —
     pure transform (Phase B reuse).
   - `aggregate_from_redis() -> list[Position]` — scans `positions:*`,
     applies the transform, returns the list.
   - `snapshot_to_redis() -> int` — calls `aggregate_from_redis` and
     writes the result to `portfolio:positions`; returns the count for
     observability.
   - `run_loop(interval_s: float)` — background task wrapper for
     periodic snapshotting.
2. **Unit tests** [`tests/unit/feedback_loop/test_position_aggregator.py`](../../tests/unit/feedback_loop/test_position_aggregator.py)
   covering: empty-input, single position, multi-symbol aggregation,
   zero-size skip, malformed-record skip-with-debug-log, asset-class
   inference, key-prefix isolation (`positionable:*` not captured),
   round-trip via Redis, and a Hypothesis property test confirming
   N input records → N output Positions for the Phase A 1:1 transform.
3. **Integration test** [`tests/integration/test_position_aggregator_pipeline.py`](../../tests/integration/test_position_aggregator_pipeline.py)
   walking through the S06 → aggregator → S05 ContextLoader path on
   shared fakeredis to prove the orphan read closes end-to-end.
4. **No change to ADR-0012 substantive content.** Only this audit
   document and the implementation files. ADR-0012 §D5 cross-reference
   cited in commit message and PR body.

---

## 9. Appendix — reproduced search commands

```text
grep -rn "portfolio:positions" services/ core/ tests/
grep -rn "positions:" services/ core/
grep -rn "f\"positions:" services/ core/
grep -rn "portfolio:" services/ core/ | grep -v "portfolio:capital\|portfolio:allocation"
grep -rn "\.set(" services/ | grep -i position
grep -rn "PositionAggregator" .
```

Final result of the writer search: 0 hits in `services/`, 0 hits in `core/`,
0 hits outside test fixtures and documentation.
