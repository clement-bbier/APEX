# ADR-0006 — Fail-Closed Pre-Trade Risk Controls

> *Note (2026-04-18): This ADR continues to govern its respective subsystem. See [APEX Multi-Strat Charter](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) §12.4 for the inventory of existing and anticipated ADRs in the multi-strat context.*

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-04-17 |
| Decider | Clement Barbier (system architect) |
| Supersedes | None |
| Superseded by | None |
| Related | ADR-0001 (ZMQ Broker), ADR-0002 (Quant Methodology Charter), PHASE_5_SPEC §3.1 |

---

## 1. Context

S05 Risk Manager is the **VETO layer** of the APEX trading pipeline
(CLAUDE.md §2). Every `OrderCandidate` from S04 must pass S05 before
it can become an `ApprovedOrder` consumed by S06 Execution.

The S05 service as inherited from Phase 4 (`services/risk_manager/service.py:341-385`)
loads its critical pre-trade context via a single `_load_context_parallel()` call that
fans out 8 parallel Redis reads (capital, daily PnL, intraday PnL, VIX current, VIX 1h
ago, positions, correlation matrix, session). When any read fails or returns `None`, a
local `_safe(value, default)` helper substitutes a heuristic fallback:

| Field | Heuristic fallback when Redis read fails |
|---|---|
| `portfolio:capital` | `Decimal("100000")` (assumed 100k) |
| `pnl:daily` | `Decimal("0")` (assumes flat day) |
| `pnl:intraday_30m` | `Decimal("0")` (assumes no intraday loss) |
| `macro:vix_current` / `vix_1h_ago` | `20.0` (assumed normal regime) |
| `portfolio:positions` | `[]` (assumes flat book) |
| `correlation:matrix` | `{}` (assumes no correlations) |
| `session:current` | `"us_normal"` (assumed mid-session) |

This is the canonical **Fail-Open** anti-pattern: when state is unavailable, the system
silently assumes the most permissive interpretation and continues trading. The historical
precedent is Knight Capital (2012-08-01), where a similar "assume-safe-on-error" path in
their SMARS routing logic produced $440M of unintended principal losses in 45 minutes.
SEC Rule 15c3-5 ("Market Access Rule") was tightened in the aftermath to require pre-trade
controls that reject — never silently bypass — when their inputs are not verifiable.

Phase 5.1 transitions S05 from Fail-Open to **Fail-Closed**: when the risk subsystem
cannot verify its inputs are fresh and authoritative, 100% of incoming `OrderCandidate`
messages are rejected with a single explicit reason code. The system never substitutes
heuristics for missing state. This is the non-negotiable safety foundation of all
subsequent Phase 5 work (5.2 event sourcing, 5.3 streaming inference, 5.4 short-side,
5.5 drift monitoring).

---

## 2. Decision

### D1 — Three-state system risk machine in `core/state.py`

A new `SystemRiskState(StrEnum)` is added to `core/state.py` with exactly three values:

| Value | Semantics | Order admission |
|---|---|---|
| `HEALTHY` | All critical state inputs verifiable and fresh | Allowed (chain proceeds) |
| `DEGRADED` | Heartbeat key absent or older than TTL; Redis itself is reachable | **All orders rejected** |
| `UNAVAILABLE` | Redis itself is unreachable (connection error, timeout) | **All orders rejected** |

`DEGRADED` and `UNAVAILABLE` differ only in the **observability signal** they emit (so
operators can distinguish "stale state" from "infrastructure down"). They are
**identical in trading effect**: both reject 100% of orders. There is no "partial
trading" mode — see D7.

A companion class `SystemRiskMonitor` (in the same `core/state.py` module per spec §3.1)
owns the state transitions and persists the current state to Redis key `risk:system:state`
with the same 5s TTL as the heartbeat itself, so a recovering observer sees the
authoritative state immediately.

### D2 — Single Redis heartbeat key, TTL 5s

A single Redis key `risk:heartbeat` (TTL = 5s) is the sole liveness signal driving
`SystemRiskState`. Per spec §3.1:

> S05 reads a `risk:heartbeat` key with TTL 5s. If the key is absent or stale, state
> transitions to `DEGRADED`. If Redis is unreachable (connection error), state
> transitions to `UNAVAILABLE`.

The key is refreshed by a dedicated `risk_heartbeat_loop()` task inside the S05 service
(period 2s, TTL 5s — gives 2 missed refreshes of slack). The refresh path runs
independently of the order-processing path so a backlog of order processing cannot mask
infrastructure failure.

The synchronous `FailClosedGuard.check()` (D3) reads the key directly on every
`OrderCandidate`. This dual-path design (background writer, foreground reader) means:

- Redis killed mid-flow → next foreground EXISTS raises → `UNAVAILABLE` → reject in O(1).
- Background refresh hung but Redis up → key TTL expires → next foreground read returns
  `None` → `DEGRADED` → reject in O(1).

If the background `risk_heartbeat_loop` task crashes or is cancelled, the next
foreground read will see TTL expire within 5s and the system transitions to `DEGRADED`,
rejecting all subsequent orders until the loop is restored. This is the intended
fail-closed behavior — a dead heartbeat writer must not allow trading to continue.

### D3 — `FailClosedGuard` as the chain's outermost shell

`services/risk_manager/fail_closed.py` ships `FailClosedGuard.check()` returning
`(SystemRiskState, RuleResult)`. `RiskManagerService.process_order_candidate()` calls
it as **STEP 0**, before STEP 1 CB Event Guard. When the returned state is not
`HEALTHY`, the service returns a `RiskDecision` with `approved=False` and
`first_failure=BlockReason.SYSTEM_UNAVAILABLE` (see D6) without invoking any subsequent
step. Latency budget for the guard: < 1ms (single Redis EXISTS).

### D4 — Removal of `_safe()` heuristic fallback

The `_safe()` helper at `services/risk_manager/service.py:341` and all 8 call sites
are removed. The `try/except: results = [None] * 8` wrapper around the parallel read is
also removed. After 5.1, `_load_context_parallel()` either returns a fully-populated
context (every field non-None, every Redis read succeeded) or raises. Order processing
wraps the call: if it raises, the order is rejected with
`BlockReason.SYSTEM_UNAVAILABLE` and the FailClosedGuard's heartbeat refresher is
signalled to re-evaluate state.

This means that after 5.1, there are **zero** code paths in S05 that substitute a
heuristic value for a missing or unreadable Redis key. This invariant is enforced by a
CI grep audit:

```
grep -rn "_safe(" services/risk_manager/   # must return zero hits
```

### D5 — New ZMQ topic `risk.system.state_change`

A new topic constant `Topics.RISK_SYSTEM_STATE_CHANGE = "risk.system.state_change"` is
added to `core/topics.py`. `SystemRiskMonitor` publishes a transition event on this
topic each time the state changes (e.g. `HEALTHY → DEGRADED`). The payload is a frozen
Pydantic model `SystemRiskStateChange` with fields
`{previous_state, new_state, heartbeat_age_seconds, cause, timestamp_utc, redis_reachable}`. S10 dashboard consumes
this topic for operator visibility per spec §3.1.

The naming follows the existing dot-separated functional convention (`risk.approved`,
`risk.blocked`, `risk.audit`, `risk.cb.tripped`): the topic is service-effect-named
(`risk.system.*`), not service-source-named (`s05.*`).

### D6 — Single new `BlockReason` value

`BlockReason.SYSTEM_UNAVAILABLE = "system_unavailable"` is added to
`services/risk_manager/models.py`. The spec name `REJECTED_SYSTEM_UNAVAILABLE`
(PHASE_5_SPEC §3.1) maps to this canonical reason code; the lowercase
`"system_unavailable"` matches the existing `BlockReason` value convention
(`"circuit_breaker_open"`, `"service_down"`, etc.). The same value is emitted whether
the underlying cause is `DEGRADED` or `UNAVAILABLE`; the distinction is preserved in
the structured log and in the `risk.system.state_change` event, not in the per-order
reason code (so downstream auditing has a single, stable rejection enum).

### D7 — Invariant: no graceful degradation

There is **no partial-risk mode**. Either every input the S05 chain needs is verifiable
and fresh, or 100% of incoming `OrderCandidate` messages are rejected. There is no
"trade smaller," "reduce-only," or "long-only" middle ground triggered by stale state.

Justification: the only safe response to "I cannot verify my inputs" is "I do not act."
Any partial-trade rule introduces a code path where the system trades on **partially
unknown state** — exactly the Knight Capital failure mode. Operator-driven reduce-only
modes (panic button, halts) remain valid future work but live in a separate path that
is **explicitly invoked by an operator**, not silently entered by an exception handler.

This invariant is binding. Any future ADR proposing a partial-trade fallback in S05
must explicitly supersede D7 and cite the new mitigation against the Knight Capital
failure mode.

### D8 — Structured-critical log on every rejection and transition

Every `BlockReason.SYSTEM_UNAVAILABLE` rejection emits a `structlog.critical()` event
with the following fields:

| Field | Type | Purpose |
|---|---|---|
| `rejection_reason` | str | Always `"system_unavailable"` (canonical reason code from D6) |
| `state` | str | Current `SystemRiskState` value (`DEGRADED` or `UNAVAILABLE`) |
| `order_id` | str | UUID of the rejected `OrderCandidate` for audit trail |
| `symbol` | str | Symbol of the rejected order |
| `timestamp_utc` | str | ISO-8601 UTC timestamp of the rejection event |

Every state transition emits an analogous critical-level event with the following
fields (consumed by Phase 5.5 drift monitoring and S10 dashboard):

| Field | Type | Purpose |
|---|---|---|
| `previous_state` | str | `SystemRiskState` before the transition |
| `new_state` | str | `SystemRiskState` after the transition |
| `redis_reachable` | bool | Whether Redis itself responded; distinguishes `DEGRADED` from `UNAVAILABLE` |
| `heartbeat_age_seconds` | float | Time since last successful heartbeat write (or `inf` if never written) |
| `cause` | str | Short machine-readable cause code (`heartbeat_stale`, `redis_connection_error`, `redis_timeout`, `recovery`) |
| `timestamp_utc` | str | ISO-8601 UTC timestamp of the transition |

`critical` (not `warning`) is deliberate — these events represent the system declining
to trade, which is a routable on-call signal in production.

---

## 3. Consequences

### Positive

- Zero heuristic fallback values remain in S05 for Capital, Exposure, PnL, VIX,
  positions, correlation, or session. The Knight-Capital-style "silent assume-safe"
  failure mode is structurally eliminated.
- `SystemRiskState` semantics are simple enough to reason about and audit in three
  lines: `HEALTHY` ⇔ all-fresh; `DEGRADED` ⇔ heartbeat-stale; `UNAVAILABLE` ⇔
  Redis-dead. Both non-healthy states reject 100% of orders; the distinction is for
  observability only.
- The `FailClosedGuard` is a pure-function pre-chain shell. It does not couple to any
  individual rule; subsequent sub-phases (5.2 in-memory state, 5.3 streaming
  inference) can replace Redis as the heartbeat backing store without touching the
  guard's contract.
- The CI grep audit (`grep -rn "_safe(" services/risk_manager/`) prevents
  regression: any future PR that re-introduces the pattern fails CI.

### Negative

- Marginal latency overhead: every `OrderCandidate` now incurs one extra Redis EXISTS
  before the chain begins. Measured target < 200µs locally; budget < 1ms even on
  degraded networks. Acceptable given the safety gain.
- Operator must distinguish `DEGRADED` (stale heartbeat) from `UNAVAILABLE` (Redis
  dead) when paging — runbook must be updated.
- During the first chaotic startup (before the heartbeat is ever written), the system
  is `DEGRADED` and rejects all orders. This is the intended fail-closed semantics but
  means a clean S05 start requires the heartbeat refresher to land its first write
  before any `OrderCandidate` arrives. Mitigation: `SystemRiskMonitor` writes the first
  heartbeat eagerly inside `on_start()` before S05 subscribes to `ORDER_CANDIDATE`.

---

## 4. Alternatives Considered

### A. Multi-source per-input staleness checks

Maintain a separate freshness threshold for each input class (regime, signal_quality,
tick, meta_label, liquidity, exposure) and degrade per-source. Rejected for Phase 5.1
scope: the spec §3.1 explicitly calls for a single Redis heartbeat ("S05 reads a
`risk:heartbeat` key with TTL 5s"), and per-source thresholds introduce a per-source
policy surface that is properly the concern of Phase 5.2 (in-memory event-sourced
state, where each input's last-update timestamp is naturally available) and Phase 5.5
(drift monitoring, where per-source SLAs are calibrated empirically). The
single-heartbeat design strictly satisfies the SEC 15c3-5 "reject when not verifiable"
requirement without prematurely designing the per-source policy.

### B. Per-source `register_cause(name, severity)` API

Expose a public API on `SystemRiskMonitor` so external monitors (drift detector, NLP
risk scorer) can register named causes contributing to `DEGRADED` / `UNAVAILABLE`.
Rejected for Phase 5.1: no caller exists yet; YAGNI. Phase 5.5 will design the
appropriate integration when the drift monitor lands and concrete requirements are
known. Adding the API speculatively now would expand the VETO layer's surface area
without a validated requirement.

### C. Reduce-only mode in `DEGRADED`

Allow orders whose intent is to flatten existing exposure when state is `DEGRADED`.
Rejected — see D7. The reduce/entry classification itself depends on the very same
`portfolio:positions` Redis state whose unavailability triggered `DEGRADED` in the
first place. Trying to permit "reduce-only" while positions are unknown is a logical
contradiction and a Knight-Capital-class failure mode.

### D. Use a Redis pub/sub channel instead of a ZMQ topic for state changes

Rejected — `core/topics.py` is the canonical bus convention (CLAUDE.md §2: "ZMQ topics
are defined in `core/topics.py` — never hardcode topic strings"). Adding a Redis
pub/sub channel for one event class would fork the messaging model.

### E. Implement the heartbeat externally (supervisor or separate watchdog service)

Rejected for Phase 5.1: the spec asks for the simplest fail-closed implementation. An
external watchdog adds a deployment dependency (another service to start, supervise,
alert on) for marginal benefit over an in-process refresh task. Future phases may
externalize this as part of the supervisor (#150 ZMQ P2P) work.

### F. Implement the heartbeat check as a Redis Lua script for atomicity

Rejected — the read-then-decide pattern fits Python perfectly; the atomicity gain is
moot for a single `EXISTS` (no read-modify-write race exists), and Lua scripting adds
operational complexity (script SHA management, debugging difficulty, harder to unit
test in isolation). The simple synchronous EXISTS in the foreground reader path is the
right choice for Phase 5.1's scope.

---

## 5. References

- **SEC Rule 15c3-5** (Market Access Rule). 17 CFR § 240.15c3-5. Adopted 2010-11-03;
  tightened post-Knight Capital. Pre-trade controls "reasonably designed to prevent
  the entry of orders that exceed appropriate pre-set credit or capital thresholds, or
  that appear to be erroneous."
- **Knight Capital Group post-mortem** (2012-08-01). SEC Release No. 70694
  (2013-10-16). $440M loss in 45 minutes caused by deployment that activated dead
  code reverting orders to a fail-open path.
- **Nygard, M. T.** (2007). *Release It! Design and Deploy Production-Ready Software*.
  Pragmatic Bookshelf, Ch. 5 (Stability Patterns — Circuit Breaker, Fail Fast).
- **CLAUDE.md §2** — "Risk Manager (S05) is a VETO — it cannot be bypassed under any
  circumstance."
- **CLAUDE.md §3** — Continuous adaptation requirement: services must degrade
  gracefully if upstream data is stale. ADR-0006 defines what "degrade gracefully"
  means in S05's case: refuse to trade.
- **CLAUDE.md §10** — Forbidden patterns: `except Exception: pass` and silent
  fallbacks.
- **PHASE_5_SPEC.md §3.1** — Sub-phase 5.1 specification.
- **GitHub issue #148** — Fail-Open → Fail-Closed.
- **ADR-0001** — ZMQ Broker topology (the bus on which `risk.system.state_change` is
  published).