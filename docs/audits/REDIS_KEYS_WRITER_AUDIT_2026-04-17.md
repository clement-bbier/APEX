# Redis Keys Writer Audit — S05 Pre-Trade Context

**Parent audit**: [STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md](STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md)
**Action executed**: BATCH A.1 / EXECUTABLE ACTION 2
**Anchor commit**: `1b7c3b5` (main, post PR #177)
**Date**: 2026-04-17
**Result**: **Audit claim confirmed and strengthened.** 8 of 8 pre-trade context keys have no production writer. The single verification the audit marked "likely S01 `macro_feed.py`" turned out also to be orphan.

---

## 1. Scope

[services/risk_manager/service.py:411-419](../../services/risk_manager/service.py#L411-L419) batches eight `state.get()` calls in `_load_context_parallel`:

```python
keys = (
    "portfolio:capital",
    "pnl:daily",
    "pnl:intraday_30m",
    "macro:vix_current",
    "macro:vix_1h_ago",
    "portfolio:positions",
    "correlation:matrix",
    "session:current",
)
```

Per ADR-0006 §D4 and the `_require` helper at [services/risk_manager/service.py:423-426](../../services/risk_manager/service.py#L423-L426), any of these being `None` raises `RuntimeError`, which the outer fail-closed guard converts to `REJECTED_SYSTEM_UNAVAILABLE`. If no production writer exists for these keys on first boot of the live pipeline, S05 will reject 100% of orders.

## 2. Search methodology

Exhaustive grep across `services/` using the following patterns (results in `.claude` tool-call log):

1. Literal key-string matches: `portfolio:capital`, `pnl:daily`, `pnl:intraday_30m`, `portfolio:positions`, `correlation:matrix`, `session:current`, `macro:vix_current`, `macro:vix_1h_ago`.
2. All `.set(`, `.hset(`, `.lpush(`, `.zadd(`, `.publish(` calls in `services/**/*.py` (to catch dynamic key construction).
3. f-strings that would construct any `(portfolio|pnl|correlation|session|macro):` key.
4. Variant `macro:vix` (without `_current`/`_1h_ago`) to cross-check the S03 side.
5. Manual read of `services/data_ingestion/macro_feed.py` to confirm its persistence strategy.

## 3. Results per key

| Key | S05 reader line | Production writer in `services/`? | Notes |
|---|---|---|---|
| `portfolio:capital` | [service.py:412, 428-431](../../services/risk_manager/service.py#L412) | **None** | Read by S10 command_api.py:569 (`state.get("portfolio:capital") or {}`, read-only dashboard query). No writer anywhere. |
| `pnl:daily` | [service.py:413, 433](../../services/risk_manager/service.py#L413) | **None** | S10 command_api.py:384 reads a different key `pnl:daily_pct` — not this one. No writer anywhere. |
| `pnl:intraday_30m` | [service.py:414, 434](../../services/risk_manager/service.py#L414) | **None** | No reader or writer anywhere else. |
| `macro:vix_current` | [service.py:415, 435](../../services/risk_manager/service.py#L415) | **None** | `services/data_ingestion/macro_feed.py` caches VIX in instance attribute `self._vix` only (line 53) and exposes it via `get_vix()` accessor — **never writes to Redis**. S01 `service.py` has only `tick:*` writes. |
| `macro:vix_1h_ago` | [service.py:416, 436](../../services/risk_manager/service.py#L416) | **None** | Same as `macro:vix_current`. Additionally, no service computes or persists any 1-hour rolling snapshot of macro data. |
| `portfolio:positions` | [service.py:417, 438-450](../../services/risk_manager/service.py#L417) | **None** (but see note) | [S06 service.py:153](../../services/execution/service.py#L153) writes `positions:{symbol}` — a **per-symbol** key, not the aggregated `portfolio:positions` list S05 reads. There is no aggregator that rolls up per-symbol positions into the expected list shape. |
| `correlation:matrix` | [service.py:418, 452-469](../../services/risk_manager/service.py#L418) | **None** | No correlation-computation service writes this. S07 `performance.py` computes Sharpe/Sortino but not a symbol-pair correlation matrix. |
| `session:current` | [service.py:419, 471-475](../../services/risk_manager/service.py#L419) | **None** | `services/regime_detector/session_tracker.py` defines the `Session` enum and classification logic, but does **not** publish or persist the current session. S03 service writes `regime:current` and `cb:events` only (lines 165-166). |

**All eight keys are orphan reads.** Zero production writers across `services/**`. The only writes to these exact keys exist in `tests/unit/s05/test_service_no_fallbacks.py` and `tests/unit/s05/test_risk_chain.py` via fakeredis, which seed them before each test run.

## 4. Collateral finding — S03 `macro:vix` is also orphan

[services/regime_detector/service.py:93](../../services/regime_detector/service.py#L93) reads `macro:vix` (singular, without `_current` suffix). No production writer exists for this key either. S03 also reads `macro:dxy` and `macro:yield_spread` at lines 94-95 (per the audit sub-agent report); same conclusion — orphan reads.

This means S03's regime computation silently degrades the same way S05's would: whatever key is missing, downstream behavior is undefined. In S03's case the service catches exceptions in `_tick()` and loops (next polling cycle retries), so the consequence is less immediate than S05's fail-closed rejection — but it is still a correctness gap.

**Scope note.** Action A.1 mandates the audit for S05's eight keys only. S03's three macro keys are noted here for completeness; fixing them is outside A.1 scope and should be folded into PHASE_5_SPEC v2's §3.2 (event sourcing) prerequisites list.

## 5. Collateral finding — `positions:{symbol}` vs `portfolio:positions` shape mismatch

[services/execution/service.py:153](../../services/execution/service.py#L153) writes per-symbol position records under `positions:{symbol}`. S05 reads an aggregated list under `portfolio:positions` and validates it as `list[Position]` ([service.py:438-450](../../services/risk_manager/service.py#L438-L450)).

Even if a portfolio aggregator were added, the two key namespaces should be unified into a single source of truth (either `positions:{symbol}` + scan-and-aggregate, or `portfolio:positions` authoritative list). PHASE_5_SPEC v2 event-sourcing design should reconcile this naming.

## 6. Implication for Phase 5.2 design

The audit's re-sequencing recommendation (5.2 → 5.3 → 5.5 → 5.4 → 5.8) is **reinforced** by this verification, not invalidated. Three paths forward for 5.2:

### Path A — "build the writers" (highest effort, cleanest)
Add production writers for each orphan key in the appropriate owning service:
- `portfolio:capital` — new service or extend S06 / S09 to persist capital state derived from fills.
- `pnl:daily`, `pnl:intraday_30m` — extend S09 `trade_analyzer.py` or add a new `pnl_tracker` service.
- `macro:vix_current`, `macro:vix_1h_ago` — wire S01 `macro_feed.py` to persist to Redis with a TTL and add a 1-hour rolling snapshot job.
- `portfolio:positions` — add aggregation task reading `positions:*` scan.
- `correlation:matrix` — add correlation computation loop in S07 or S09.
- `session:current` — S03 `session_tracker` persists on transitions.

Estimated scope: 400–600 LOC across 5 services. Biggest risk: distributed state drift.

### Path B — "event-sourcing as intended" (spec-aligned)
Per PHASE_5_SPEC v1 §3.2: S05 subscribes to `execution.fill.*`, `risk.m2m.*`, `portfolio.position.*` and maintains an in-memory state. But this still requires **publishers** for those topics, which do not exist today. So Path B is Path A in disguise, with the persistence target shifted from Redis to a ZMQ topic feed.

### Path C — "seed defaults at boot, evolve later" (fastest to paper trading)
For initial paper trading, seed the 8 keys at S05 startup from a config block (known capital, empty positions, NORMAL session, normal VIX). Then layer in writers phase by phase. This is a **trade-off against the Fail-Closed contract** — effectively restoring a startup fallback — and needs ADR-0006 acknowledgement.

### Recommendation (Principle 1 + Principle 7)
A senior AQR quant with a live paper-trading deadline would pick **Path B for capital/pnl/positions** (write real producers), **defer correlation_matrix** (not critical for MVP; can use identity matrix with explicit correlation=0), and **accept Path C for session** (S03 owns the single-writer contract cleanly; low risk).

This is the concrete design recommendation for PHASE_5_SPEC v2 §3.2.

## 7. Conclusion — does this change the audit or trigger a catastrophic stop?

**No catastrophic stop.** The execution-protocol guardrail reads: "Batch A.1 verification reveals the audit was **wrong** about Redis writers — STOP." The audit called 7 keys UNVERIFIED and 2 "likely S01 macro_feed.py". Verification shows both flavors are orphan. This **confirms and strengthens** the audit rather than contradicting it.

**No audit revision required.** The §1.2 orphan-read trap language still reads correctly. One clarifying sentence can be added noting that S01's `macro_feed.py` is cache-only, but this is a documentation nicety, not a substantive correction.

**Forward path.** Batch A.2 (S10 subscription) and A.3 (CI unblock) proceed normally. PHASE_5_SPEC v2 (Batch C) should explicitly address the writer strategy (Paths A/B/C above) for the 8 orphan keys.

---

**END OF ADDENDUM.**
