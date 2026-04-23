# Session/Macro Persistence Shims — Phase A.10 Writer Audit

**Audit date**: 2026-04-21
**Anchor commit**: `37f44c4` (main, post PR #232)
**Scope**: Resolve the remaining P2-4 orphan reads identified in
[`MULTI_STRAT_READINESS_AUDIT_2026-04-18.md`](MULTI_STRAT_READINESS_AUDIT_2026-04-18.md)
§ Top-Risks and the Phase-5 baseline audit
[`REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`](REDIS_KEYS_WRITER_AUDIT_2026-04-17.md).
The keys in scope:

| # | Key | Reader | Writer status (pre-fix) |
|---|---|---|---|
| 1 | `session:current` | `services/risk_manager/context_loader.py:39,108` | **Orphan** |
| 2 | `macro:vix_current` | `services/risk_manager/context_loader.py:35,76` | **Orphan** |
| 3 | `macro:vix_1h_ago` | `services/risk_manager/context_loader.py:36,77` | **Orphan** |

Roadmap reference: [`PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) §2.2.4.
Phase A success criterion (line 411) requires production writers for these
three keys before Phase A can close.

---

## 1. Method

1. Grep every literal occurrence of `session:current`, `macro:vix_current`,
   `macro:vix_1h_ago` across `services/`, `core/`, and `tests/`.
2. Grep every `state.set(`, `r.set(`, `state.publish(` site for the
   prefixes `session:` and `macro:`.
3. Cross-reference readers ↔ writers per Phase A.7 / A.8 audit pattern
   (PR #210, PR #214).
4. Classify per CASE A / B / C:
   - **CASE A**: writer exists in scope → wire reader & ship.
   - **CASE B**: writer is in a service outside the audit scope → STOP.
   - **CASE C**: no writer exists → introduce the writer.

Search executed on branch `fix/issue-200-session-macro-shims` at HEAD `37f44c4`.

---

## 2. Reader inventory

| Key | File | Line | Operation | Decode |
|-----|------|------|-----------|--------|
| `session:current` | [`services/risk_manager/context_loader.py`](../../services/risk_manager/context_loader.py#L108) | 108 | `state.get` | `Session(str(value))` (enum from `core.models.tick`) |
| `macro:vix_current` | [`services/risk_manager/context_loader.py`](../../services/risk_manager/context_loader.py#L76) | 76 | `state.get` | `float(value)` |
| `macro:vix_1h_ago` | [`services/risk_manager/context_loader.py`](../../services/risk_manager/context_loader.py#L77) | 77 | `state.get` | `float(value)` |

All three reads pass through `_require(name, value)` which raises
`RuntimeError` on `None`, satisfying ADR-0006 §D4 fail-loud. The S05
fail-closed guard (STEP 0) currently shields production by rejecting
every order until a writer materializes.

## 3. Writer search results

### 3.1 Literal grep

```text
grep -rn '"session:current"\|"macro:vix_current"\|"macro:vix_1h_ago"' services/ core/
```

| Hit | File | Line | Verdict |
|-----|------|------|---------|
| Reader | `services/risk_manager/context_loader.py` | 39 | tuple key |
| Reader | `services/risk_manager/context_loader.py` | 76, 77, 108, 112 | usage |
| Test seed | `tests/unit/risk_manager/test_service_no_fallbacks.py` | 84-88, 327-331, 381 | fakeredis seed |
| Test seed | `tests/unit/risk_manager/test_risk_chain.py` | 97-101 | fakeredis seed |

**Zero production writers** in `services/` or `core/`.

### 3.2 Set-primitive grep

```text
grep -rn '\.set("session:\|\.set("macro:vix' services/ core/
```

Returns no production writer for any of the three keys. The only macro
keys with writers in `services/` are:

- `macro:sectors`, `macro:risk_regime` — `services/macro_intelligence/service.py:47-50`
- `macro:energy` — `services/macro_intelligence/service.py:67`
- `macro:cb:next_event`, `macro:cb:block_active`, `macro:cb:monitor_active`
  — `services/macro_intelligence/cb_watcher.py:215-220`

None of these are in scope for #200.

### 3.3 Cache-only producers

[`services/data_ingestion/macro_feed.py`](../../services/data_ingestion/macro_feed.py)
polls VIX (and DXY, yield spread) from FRED / Yahoo every 60 s and stores
the latest values in **instance attributes** (`self._vix`, `self._dxy`,
`self._yield_spread`). No `state.set()` call exists in the module —
exactly the pattern the original audit
(`REDIS_KEYS_WRITER_AUDIT_2026-04-17.md` §3 row 4) flagged.

[`services/regime_detector/session_tracker.py`](../../services/regime_detector/session_tracker.py)
exposes `SessionTracker.get_session(utc_now)` returning a **different**
`Session` enum (`us_open`, `us_morning`, `us_lunch`, `us_afternoon`,
`us_close`, `after_hours`, `asian`, `london`, `weekend`) defined in the
S03 module itself. **It does not match the `core.models.tick.Session`
enum that S05 expects** (`us_prime`, `us_normal`, `after_hours`,
`london`, `asian`, `weekend`, `unknown`).

The canonical S05-compatible classifier is
[`services/data_ingestion/normalizers/session_tagger.py`](../../services/data_ingestion/normalizers/session_tagger.py)
`SessionTagger.tag(ts)`, which already returns the correct enum. It is
the only existing component that produces the values S05 deserializes.

### 3.4 Enum-mismatch finding (collateral)

The roadmap §2.2.4 row 6 prescribes "Persistence shim in S03
`session_tracker.py`" for `session:current`. **Following that location
literally would produce values that S05 cannot decode** (`Session("us_open")`
raises `ValueError`, which `context_loader.py:112` re-raises as
`RuntimeError`). The roadmap row is taken as a *service-of-origin
intent* (S01 vs S03 as session owner) rather than a strict file path:
the audit recommends **co-locating the writer in S01 alongside the
existing `SessionTagger`** to keep the producer/consumer enum contract
intact and to avoid threading the S05-shape `Session` enum into S03's
sizing-multiplier code path.

## 4. Decision-tree outcome

> Decision tree per Phase A.10 mission brief:
> - **CASE A**: writer in scope → wire reader & ship.
> - **CASE B**: writer outside scope → STOP and report.
> - **CASE C**: no writer exists → introduce the writer.

### Result: **CASE C — no writer exists**

For all three keys: zero production writers; introduce them.

## 5. Architectural decision: persist to Redis (not in-memory or ZMQ-only)

Three options were considered:

| Option | Pros | Cons |
|---|---|---|
| **A. In-memory per-consumer** | Zero Redis round-trip. | S05 would need to embed a `MacroFeed` and a `SessionTagger` directly, violating Single Responsibility (CLAUDE.md §2). |
| **B. ZMQ broadcast** | Push-based, no polling. | S05 would have to subscribe and maintain its own cache; same SRP violation; loses the snapshot-on-restart property the existing context-loader reads rely on. |
| **C. Redis with TTL + writer task in S01** | Reuses the established context-load pattern (the eight pre-trade keys are all `state.get` reads); zero changes to S05 and to ADR-0006; matches Roadmap §2.2.4 prescription. | Adds a small writer task to S01 (≈80 LOC). |

**Choice: Option C.** It is the option Roadmap §2.2.4 already mandates,
matches the Phase A.7 and Phase A.8 trackers (which also kept the
pre-trade context on Redis), and incurs the smallest blast radius.

## 6. Fix specification

### 6.1 New module: `services/data_ingestion/session_persister.py`

A `SessionPersister` class that:

1. Holds a `SessionTagger` and a `_StateWriter` reference.
2. Runs a background loop on a configurable cadence (default 30 s,
   chosen to match the S03 regime tick — sub-minute granularity is
   plenty given session boundaries are minutes apart).
3. On every tick: `await state.set("session:current", tagger.tag(utc_now).value)`.
4. Exposes `start()` / `stop()` lifecycle hooks consistent with
   `MacroFeed`.

Persistence is idempotent — re-writing the same value is a Redis no-op
beyond the round trip; no risk of double-writes corrupting state.

### 6.2 New module: `services/data_ingestion/macro_persister.py`

A `MacroPersister` class that:

1. Holds a `MacroFeed` and a `_StateWriter` reference.
2. Runs a background loop on a configurable cadence (default 60 s,
   matching `MacroFeed._POLL_INTERVAL_SECONDS`).
3. On every tick:
   - Reads the cached `_vix`, `_dxy`, `_yield_spread` accessors
     (offered as a small `snapshot()` method on `MacroFeed`).
   - Persists `macro:vix_current` (and `macro:vix`, `macro:dxy`,
     `macro:yield_spread` for S03 regime-detector consumption — these
     are the *same* orphan-read pattern documented in
     `REDIS_KEYS_WRITER_AUDIT_2026-04-17.md` §4 collateral, fixed here
     as a no-extra-cost bonus since the persister is right there).
   - Appends `(now_utc, vix)` to a bounded deque (max age 90 min).
   - Trims expired snapshots.
   - Resolves `macro:vix_1h_ago` as the **VIX value of the oldest
     snapshot ≥ 60 min old**. Until 60 min of history accumulates, the
     persister writes the oldest available value (graceful degradation
     per CLAUDE.md §3 — "degrades gracefully if upstream data is stale").
4. Exposes `start()` / `stop()` lifecycle hooks.

### 6.3 Wiring: `services/data_ingestion/service.py`

Both persisters are constructed in `__init__` and started inside `run()`
alongside the existing `MacroFeed`. `stop()` is called in the `finally`
block guarding the gather, identical to the existing `MacroFeed`
pattern at lines 99-120.

### 6.4 Out of scope (explicitly deferred)

- **Per-strategy partitioning** (`session:{strategy_id}:current`,
  `macro:{strategy_id}:vix_current`). Charter §5.5 keeps macro/session
  context **global** (it is not strategy-scoped — VIX is the same value
  for every strategy at any given instant). The dual-key reader pattern
  used by Phase A.7 / A.8 (capital, PnL, positions) does not apply here.
- **Writer for `macro:cb_events`** read by
  `services/risk_manager/cb_event_guard.py:42`. The reader's own
  docstring says "Written by S08 Macro Intelligence" — the actual S08
  writer at `services/macro_intelligence/cb_watcher.py:215-220` writes
  `macro:cb:block_active` / `:monitor_active` / `:next_event` instead.
  The naming gap is real but tangential; tracked as a follow-up under
  Phase A.11+ unless a separate issue surfaces.

## 7. Updated writer table (post-fix)

| Key | Reader | Writer (post-fix) | Cadence |
|-----|--------|-------------------|---------|
| `session:current` | `services/risk_manager/context_loader.py` | `services/data_ingestion/session_persister.py` | 30 s |
| `macro:vix_current` | `services/risk_manager/context_loader.py` | `services/data_ingestion/macro_persister.py` | 60 s |
| `macro:vix_1h_ago` | `services/risk_manager/context_loader.py` | `services/data_ingestion/macro_persister.py` (rolling deque) | 60 s |

Phase A success criterion (Roadmap line 411) is satisfied for the three
keys covered by this audit.

## 8. Coordination notes

- **Terminal 4 (#199 PositionAggregator)** also operates on the orphan-key
  initiative but on a disjoint set of services
  (`services/risk_manager/` for the reader, `services/feedback_loop/`
  for the writer). This audit's fix lives in `services/data_ingestion/`
  + `services/regime_detector/` is **read-only**. **No file overlap.**
- **Terminal 1, 2, 3** operate on `.github/`, `backtesting/`, and
  `services/quant_analytics/` respectively. **No overlap.**

---

**END OF AUDIT.**
