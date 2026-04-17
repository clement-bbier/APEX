# Phase 7.5 — Infrastructure Hardening — Backlog

**Status**: BACKLOG — revisit only if Phase 8 live-trading benchmarks prove bottlenecks.
**Created**: 2026-04-17
**Origin**: [`docs/audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) §4.2.
**Supersedes scope of**: PHASE_5_SPEC.md v1 §3.6, §3.7, §3.9 (now canonical here).
**Canonical active spec**: [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md).

---

## 1. Rationale (Principles 1, 3, 7)

These three sub-phases were part of PHASE_5_SPEC v1 but were deferred by the
[STRATEGIC_AUDIT_2026-04-17](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) for
the following reasons:

1. **Principle 1 (long-term cash generation).** The operator has no live trading pipeline
   yet. These three sub-phases collectively represent ~4–10 weeks of work that solves
   latency / SPOF / serialization problems that are not yet measurable — and some that
   are structurally irrelevant at the operator's scale. Every week spent here is a week
   that delays live PnL.
2. **Principle 3 (acknowledged constraints).** The operator runs ten Docker containers
   on a single host with personal capital and no colocation / microsecond feeds. There
   is no meaningful SPOF-isolation win from a P2P bus (when the host is down every
   service is down regardless). JSON serialization overhead (~1 µs per tick at
   10 ticks/sec/symbol × 10 symbols) is a rounding error against broker round-trip
   latency (~50–200 ms). Rust FFI has no current bottleneck to prove.
3. **Principle 7 (senior-quant tie-breaker).** A senior quant at AQR / Man AHL with a
   one-person crew would ship alpha first, measure latency empirically from live
   benchmarks, and only then decide which (if any) of these three to invest in.

## 2. Re-entry criteria

Each sub-phase below is **only** considered for implementation if **both** of the
following are true:

1. Phase 5 v2 has fully closed (5.1–5.10 all merged + paper trading live).
2. Live benchmarks from Phase 8 demonstrate a specific bottleneck that the proposed
   sub-phase would relieve, with quantified evidence (not speculation). Examples of
   qualifying evidence:
   - For 5.6 (P2P bus): measured broker-process failure frequency or message-loss rate
     with containerized-isolation benefit.
   - For 5.7 (SBE/FlatBuffers): profiler data showing JSON `model_dump_json()` in the
     top 10 hot-path CPU consumers.
   - For 5.9 (Rust FFI): P99 order-validation latency exceeding the in-memory-state
     target of 100 µs with profiler data pinning Python overhead as the cause.

Absent that evidence, these specifications are **kept frozen as historical reference
only** and do not get scheduled.

## 3. Relationship to existing work

- **ADR-0001 (ZMQ Broker Topology)** remains ACCEPTED indefinitely; the planned
  supersession in v1 §3.6 is cancelled. If Phase 7.5.1 is ever revived, a fresh ADR
  records the decision as of that date.
- The **Rust crates** (`apex_mc`, `apex_risk`) remain in use for Monte Carlo and
  exposure computation per their existing production role. Phase 7.5.3 would extend
  them with tick-processing + risk-validation hot paths; it does not replace them.
- The **pydantic JSON serialization** in `core/bus.py` remains in use. Phase 7.5.2
  would introduce dual-mode transport (binary + legacy JSON) rather than replacing
  JSON outright.

---

## 4. Deferred sub-phase specifications

The three sub-specs below are preserved **verbatim** from PHASE_5_SPEC v1 for audit-trail
purposes. Numbering is retained at `5.6 / 5.7 / 5.9` inside the specs themselves even
though these now live under Phase 7.5, to avoid breaking cross-references in historical
documents (ADRs, session logs, PR bodies). When any of these is revived, the implementer
should re-number as `7.5.1 / 7.5.2 / 7.5.3` at that time.

---

### (Former) 5.6 — ZMQ Peer-to-Peer Bus

## 3.6 Sub-phase 5.6 — ZMQ Peer-to-Peer Bus

### Objective
Replace the centralized XSUB/XPUB broker (`zmq_broker.py`) with a
distributed peer-to-peer topology using Redis-based service discovery.
Eliminate the single point of failure.

### Scope
- **IN**: Each publisher BINDs its own ephemeral port; service
  registry in Redis with TTL + heartbeat; subscribers CONNECT
  directly to publishers; abstract `TransportLayer` interface for
  future Aeron swap; chaos test proving resilience.
- **OUT**: Aeron IPC implementation (evaluated, not shipped — Phase 6
  if benchmarks justify); UDP multicast (network-dependent, deferred).

### Module structure
```
core/
├── bus.py                     # MODIFY — implement P2P topology
├── transport.py               # NEW — TransportLayer ABC
├── service_registry.py        # NEW — Redis-based registry
├── zmq_broker.py              # DEPRECATE (keep for backward compat, flag)

tests/unit/core/
├── test_transport_layer.py    (~12 tests)
├── test_service_registry.py   (~14 tests)

tests/integration/
├── test_zmq_p2p_resilience.py (~10 tests)
```

### Algorithm notes
- Service registry: each publisher writes
  `service:{service_id}:endpoint = "tcp://{ip}:{port}"` to Redis
  with TTL = 10s. Heartbeat loop refreshes every 5s.
- Subscriber startup: reads all `service:*:endpoint` keys matching
  its subscription topics. CONNECTs directly to each publisher.
- Dynamic discovery: subscriber polls registry every 10s for new
  publishers (handles service restarts / scaling).
- `TransportLayer` ABC with methods: `bind()`, `connect()`,
  `publish()`, `subscribe()`. ZMQ implementation is the default.
  Aeron implementation is a stub for Phase 6 evaluation.
- Backward compatibility: services that haven't migrated can still
  use the broker via a `LegacyBrokerTransport` adapter (transitional,
  removed in Phase 6).

### Criteria — Definition of Done
1. Chaos test: kill any single service container → remaining
   services continue communicating within 2s recovery.
2. Latency reduction: measured P50/P99 transport latency lower than
   broker topology (one fewer network hop).
3. Service registry in Redis with TTL and heartbeat, tested.
4. `TransportLayer` ABC with ZMQ + stub Aeron implementations.
5. All tests passing, coverage ≥ 88%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.2 merged (event-sourcing defines the ZMQ topic
  contract that P2P must honor).

### Estimated scope
- LOC: ~600–850.
- Tests: ~36.
- Complexity: **high** (infrastructure, distributed systems).
- Copilot review cycles: **3**.

### References
- CME Group infrastructure whitepapers.
- Real Logic Aeron (https://github.com/real-logic/aeron).
- CLAUDE.md §2: "ZMQ topics are defined in core/topics.py."
- ADR-0001 (superseded by this sub-phase).
- GitHub issue #150.

---

### (Former) 5.7 — SBE / FlatBuffers Serialization

## 3.7 Sub-phase 5.7 — SBE / FlatBuffers Serialization

### Objective
Migrate the hot-path message serialization from JSON
(`.model_dump_json()`) to zero-copy binary encoding
(FlatBuffers or SBE) to eliminate GC pressure from continuous
string allocation.

### Scope
- **IN**: Binary schemas for `Tick`, `Signal`, `OrderCandidate`,
  `RiskDecision`; compiled Python wrappers; `MessageBus` modified
  to send/receive raw `bytes`; backward-compatible JSON adapter
  for non-migrated services.
- **OUT**: Full SBE compliance certification (not required for
  internal use); Cap'n Proto evaluation (deferred).

### Module structure
```
core/
├── schemas/                   # NEW directory
│   ├── tick.fbs               # FlatBuffers schema
│   ├── signal.fbs
│   ├── order_candidate.fbs
│   └── risk_decision.fbs
├── serialization.py           # NEW — encode/decode wrappers
├── bus.py                     # MODIFY — bytes transport mode

tests/unit/core/
├── test_serialization.py      (~20 tests)
├── test_bus_binary_mode.py    (~10 tests)

tests/integration/
├── test_binary_pipeline.py    (~6 tests)
```

### Algorithm notes
- FlatBuffers chosen over SBE for Phase 5: richer tooling, Python
  code generation, zero-copy access. SBE remains an option for
  Phase 6 Rust hot path if FlatBuffers overhead is measured.
- `MessageBus.publish()` accepts both `BaseModel` (legacy JSON path)
  and `bytes` (new binary path). The bus detects the type and routes
  accordingly. No service needs to change its consumer code until
  explicitly migrated.
- JSON adapter: non-migrated services receive a thin
  `FlatBufferToJsonAdapter` that deserializes binary → Pydantic
  model transparently. Performance penalty accepted for backward
  compatibility during Phase 5.
- Schema versioning: each `.fbs` file includes a `schema_version`
  field. Consumers validate version on decode. Unknown versions
  raise `ValueError` (fail-loud).

### Criteria — Definition of Done
1. CPU profiling report: > 80% reduction in serialization CPU time
   for `Tick` messages.
2. GC stability: stress test (10,000 ticks/s for 60s) shows
   no GC pause > 10ms.
3. Schemas versioned and documented.
4. Backward-compatible: non-migrated services still consume JSON.
5. All tests passing, coverage ≥ 90%.
6. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.6 merged (P2P bus defines the transport; binary
  encoding is layered on top).

### Estimated scope
- LOC: ~500–700.
- Tests: ~36.
- Complexity: **medium** (schema design + dual-mode bus).
- Copilot review cycles: **2**.

### References
- FIX Trading Community — SBE specification.
- Google FlatBuffers (https://google.github.io/flatbuffers/).
- CLAUDE.md §5: "Hot paths must avoid object allocation in inner
  loops."
- GitHub issue #151.

---

### (Former) 5.9 — Rust FFI Hot Path Migration

## 3.9 Sub-phase 5.9 — Rust FFI Hot Path Migration

### Objective
Rewrite S01 (Market Data ingestion) and S05 (Risk validation) hot
paths in Rust, connected to the Python ecosystem via FFI (PyO3 or
shared-memory ring buffer). Achieve > 1M ticks/second/core for
L2 order book processing.

### Scope
- **IN**: Rust crates `apex_mc` (market data) and `apex_risk`
  (risk validation) extended with production-grade tick processing;
  PyO3 FFI bindings for S02/S08 Python consumers; zero-copy shared
  memory ring buffer for tick transmission; ADR documenting FFI
  architecture; benchmark suite.
- **OUT**: Full Rust monolith consolidation (Phase 6); Aeron
  transport in Rust (Phase 6); GPU acceleration (Phase 6).

### Module structure
```
rust/
├── apex_mc/
│   ├── src/
│   │   ├── ingestion.rs       # EXTEND — production tick parser
│   │   ├── ring_buffer.rs     # NEW — lock-free ring buffer
│   │   └── ffi.rs             # NEW — PyO3 bindings
│   └── Cargo.toml
├── apex_risk/
│   ├── src/
│   │   ├── validator.rs       # EXTEND — order validation logic
│   │   └── ffi.rs             # NEW — PyO3 bindings
│   └── Cargo.toml

services/s01_data_ingestion/
├── rust_bridge.py             # NEW — Python FFI consumer

services/s05_risk_manager/
├── rust_bridge.py             # NEW — Python FFI consumer

docs/adr/
├── ADR-0007-rust-ffi-architecture.md  (NEW)

tests/
├── rust/                      # Rust-side unit tests (cargo test)
├── unit/services/s01/
│   └── test_rust_bridge.py    (~10 tests)
├── unit/services/s05/
│   └── test_rust_bridge.py    (~10 tests)
├── integration/
│   └── test_ffi_pipeline.py   (~8 tests)
```

### Algorithm notes
- PyO3 chosen over raw shared memory for Phase 5 MVP: simpler
  error handling, automatic reference counting, existing CI
  infrastructure (`maturin build`). Shared-memory ring buffer
  is a Phase 6 optimization if PyO3 overhead is measured.
- The Rust tick parser handles L2 order book updates with
  nanosecond-precision timestamps. Decimal arithmetic via the
  `rust_decimal` crate (128-bit, matching Python `Decimal`
  semantics).
- FFI contract: Python calls `apex_mc.process_tick(raw_bytes) ->
  NormalizedTick` and `apex_risk.validate_order(candidate, state)
  -> RiskDecision`. Both functions are GIL-releasing.
- Benchmark target: > 1M ticks/second/core for `process_tick`.
  Measured via `criterion` benchmarks in Rust + Python wall-clock
  in integration tests.

### Criteria — Definition of Done
1. ADR-0007 committed (FFI architecture: PyO3 vs SHM decision).
2. Benchmark: > 1M ticks/s/core for `process_tick` (Rust).
3. Benchmark: Python→Rust→Python round-trip < 5μs per tick.
4. `cargo test --workspace` all passing.
5. `maturin build` + `import apex_mc, apex_risk` in Python.
6. Comparative benchmark: Python vs Rust on hot path (P50/P99/P999).
7. Integration tests: FFI transparent for S02/S08.
8. All Python tests passing, coverage ≥ 85%.
9. `mypy --strict` clean, `ruff` clean.

### Dependencies
- Sub-phase 5.2 merged (event-sourced state is the Rust validation
  target).
- Track B (5.6, 5.7) preferred but not blocking (Rust operates at
  the transport layer boundary).

### Estimated scope
- LOC: ~1500–2500 (Rust + Python bindings).
- Tests: ~28 Python + ~40 Rust.
- Complexity: **very high** (polyglot, FFI, performance).
- Copilot review cycles: **4+**.

### References
- López de Prado (2018), AFML — research vs production separation.
- PyO3 (https://pyo3.rs/).
- CLAUDE.md §5: "CPU-bound math goes in Rust (apex_mc, apex_risk
  crates) — not in Python."
- GitHub issue #152.


---

## 5. Cross-reference map

| Topic | Document |
|---|---|
| Strategic deferral rationale | [`STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md §4.2`](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) |
| v1 original (superseded) | [`PHASE_5_SPEC.md`](PHASE_5_SPEC.md) |
| v2 canonical active spec | [`PHASE_5_SPEC_v2.md`](PHASE_5_SPEC_v2.md) |
| Backlog MD issues (DEFERRED banners) | [`docs/issues_backlog/issue_zmq_p2p.md`](../issues_backlog/issue_zmq_p2p.md) · [`issue_sbe_serialization.md`](../issues_backlog/issue_sbe_serialization.md) · [`issue_rust_hotpath.md`](../issues_backlog/issue_rust_hotpath.md) |
| GitHub issues (to be closed as DEFERRED in Batch E) | #150 (ZMQ P2P), #151 (SBE), #152 (Rust FFI) |

---

**END OF PHASE_7_5_INFRASTRUCTURE_HARDENING_BACKLOG.**
