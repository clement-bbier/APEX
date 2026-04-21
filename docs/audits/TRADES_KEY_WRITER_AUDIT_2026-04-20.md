# Redis `trades:all` Writer Audit — Phase A.12 Scoping Verification

**Audit date**: 2026-04-20
**Scope**: locate the production writer for Redis key `trades:all` in order to
scope the per-strategy dual-write mandated by Roadmap §2.2.5 (`trades:{strategy_id}:all`).
**Referenced artefacts**:
- [Issue #202 — Phase A.12 per-strategy trades dual-write](https://github.com/clement-bbier/APEX/issues/202)
- [Roadmap v3.0 §2.2.5](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
- [ADR-0007 §D9 — Strategy as Microservice](../adr/ADR-0007-strategy-as-microservice.md)
- [Charter §5.5 — Per-strategy Redis partitioning](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)
- [MULTI_STRAT_READINESS_AUDIT_2026-04-18.md](MULTI_STRAT_READINESS_AUDIT_2026-04-18.md)
- [REDIS_KEYS_WRITER_AUDIT_2026-04-17.md](REDIS_KEYS_WRITER_AUDIT_2026-04-17.md)

---

## 1. Method

1. Grep every occurrence of the literal key `"trades:all"` and the token `trades_all`
   in the repository.
2. Grep every Redis list write primitive (`lpush`, `rpush`) and stream/hash/set writers
   (`xadd`, `sadd`, `hset`) inside `services/` and `core/`.
3. Cross-reference readers with writers to verify the key is produced somewhere.
4. Classify outcome per Phase A.12 decision tree (CASE A / B / C).

All commands executed on branch `main` at commit
`ba311a1 refactor: rename project to APEX + semantic service names (atomic) (#211)`.

---

## 2. Readers found

| # | File | Line | Operation | Context |
|---|------|------|-----------|---------|
| 1 | [`services/feedback_loop/service.py`](../../services/feedback_loop/service.py) | 57 | `lrange("trades:all", 0, KELLY_ROLLING_WINDOW - 1)` | `_fast_analysis` — drift + Kelly refresh every 5 min |
| 2 | [`services/feedback_loop/service.py`](../../services/feedback_loop/service.py) | 111 | `lrange("trades:all", 0, -1)` | `_slow_analysis` — post-market signal-quality compute |
| 3 | [`services/command_center/command_api.py`](../../services/command_center/command_api.py) | 244 | `lrange("trades:all", 0, -1)` | `/performance` endpoint aggregation |
| 4 | [`services/command_center/command_api.py`](../../services/command_center/command_api.py) | 423 | `lrange("trades:all", 0, -1)` | `/trades` endpoint export |
| 5 | [`services/command_center/pnl_tracker.py`](../../services/command_center/pnl_tracker.py) | 26 | `lrange("trades:all", 0, -1)` | Dashboard daily/intraday PnL roll-up |
| 6 | [`services/command_center/pnl_tracker.py`](../../services/command_center/pnl_tracker.py) | 72 | `lrange("trades:all", 0, -1)` | Dashboard equity-curve roll-up |

Storage structure implied by the reader: **Redis LIST** (all six readers use `lrange`).
No consumer uses `xread`, `hgetall`, `smembers`, or `get`, so the structure cannot be
a stream, hash, set, or JSON-string-encoded list.

## 3. Writers found

| Primitive | Target key | File | Line |
|-----------|------------|------|------|
| `lpush`   | `equity_curve` | `services/command_center/pnl_tracker.py` | 117 |
| `lpush`   | `REDIS_DECISION_HISTORY_KEY` (= `risk:decision_history`) | `services/risk_manager/decision_builder.py` | 101 |
| `lpush`   | `self.REDIS_KEY` (= `meta_label_history`) | `services/fusion_engine/feature_logger.py` | 133 |
| `xadd`    | orchestrator history stream | `services/data_ingestion/orchestrator/state.py` | 152 |

**No production code writes `trades:all`.**

Full repo search (`trades:all` OR `trades_all`) returned only the six readers
enumerated in §2, plus documentation strings in `MANIFEST.md`,
`docs/audits/MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`, and
`docs/phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`. The single
`lpush` surface in `core/state.py:302` is the `StateStore` primitive itself,
not a call site.

## 4. Current atomicity pattern

**Not applicable**: the writer does not exist, so there is no pattern to preserve.

For reference, the analogous Kelly dual-write merged in PR #209
(`services/fusion_engine/kelly_sizer.py`, phase-A.11) uses a `StateStore`
pipeline to commit the legacy key and per-strategy key in a single round trip.
That is the template the Phase A.12 PR would have reused once the writer existed.

## 5. Decision-tree outcome

> Decision tree per Phase A.12 mission brief:
> - **CASE A**: writer and reader both inside allowed scope (`fusion_engine`,
>   `feedback_loop`, `execution`) → proceed with dual-write.
> - **CASE B**: writer in a service outside allowed scope → STOP and report.
> - **CASE C**: no writer exists yet (ticket mis-scoped) → STOP and report.

### Result: **CASE C — no writer exists**

Issue #202 presumes an existing `trades:all` writer to extend. None exists.
Roadmap §2.2.5 row 2 reads:

> | `trades:{strategy_id}:all` | S06 + S09 | S09 fast_analysis |
> | Extend S09 `service.py` persistence to write per-strategy Redis list;
> | legacy `trades:all` continues until Phase B |

The clause "Extend S09 `service.py` persistence" is inaccurate — S09 `service.py`
has no persistence path to extend, only the two `lrange` reads at
`service.py:57` and `:111`. The key is an **orphan read** (confirmed consistent
with the broader orphan-key pattern surfaced in
`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md` §5 and
`REDIS_KEYS_WRITER_AUDIT_2026-04-17.md` §2, which found 8 of 8 pre-trade context
keys to be writer-less — `trades:all` extends the same pathology into the
post-trade feedback surface).

## 6. Recommended upstream work before Phase A.12 can execute

Phase A.12 dual-write cannot be scoped until one of the following lands first:

1. **Preferred: carve a new writer task in Phase A.**
   - Scope: `services/execution/service.py` fill handler builds a `TradeRecord`
     on each `ExecutedOrder` position close and `lpush`es it to `trades:all`
     (legacy key) AND `trades:{strategy_id}:all` (per-strategy key).
   - `strategy_id` is available on `ExecutedOrder` once Phase A.2 (core model
     field propagation, issue #192) is fully threaded into S06 fills.
     A.2 is in-flight on the parallel Terminal 2 branch; the writer task should
     depend on A.2 completion so the per-strategy partition key is populated
     from real data rather than always defaulting to `"default"`.
   - Estimated size: ~80 LOC in execution + ~40 LOC of fixture-driven tests.

2. **Alternative: close #202 without change and re-open under a clearer title.**
   The current title ("per-strategy trades dual-write for `trades:all`")
   implies an existing writer; a more accurate title would be
   "**Implement `trades:all` writer in S06 on-fill handler with per-strategy
   dual-write** (folds phase-A.12 into the same PR as the missing writer)".

3. **Not recommended: create the writer inside `feedback_loop`.**
   S09 FeedbackLoop is a read/analyse service (see module docstring at
   `services/feedback_loop/service.py:26`). Adding a trade-persistence writer
   there would violate Single Responsibility (CLAUDE.md §2 and §5) because the
   emitter of truth for a `TradeRecord` is the broker fill reported by S06,
   not the post-trade analyst.

## 7. Action taken by this PR

No code change in `services/fusion_engine/`, `services/feedback_loop/`, or
`services/execution/`. Only this audit document is added.

Mission brief: **"If CASE B or C, STOP and report immediately."** — applied.

## 8. Appendix — reproduced search commands

```text
grep -rn "trades:" services/ core/
grep -rn '"trades' services/ core/
grep -rn "trades:all\|trades_all" .
grep -rn "lpush\|rpush\|xadd\|sadd\|hset" services/
grep -rn "lpush\|rpush" core/
```
