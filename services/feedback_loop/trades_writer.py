"""Canonical writer for ``trades:all`` (legacy) and ``trades:{strategy_id}:all``.

Phase A.12.1 (issue #237, Roadmap v3.0 §2.2.5, Charter §5.5, ADR-0007 §D6).

Audit finding (2026-04-20, see ``docs/audits/TRADES_KEY_WRITER_AUDIT_2026-04-20.md``)
-----------------------------------------------------------------------------------
The Redis key ``trades:all`` is consumed by six production readers
(S09 ``_fast_analysis`` / ``_slow_analysis``; S10 ``command_api.py``
``/performance`` and ``/trades``; S10 ``pnl_tracker`` daily and equity
roll-ups) but has **zero** producers anywhere in ``services/`` or
``core/``. Issue #202 presumed an existing writer to extend; the audit
showed the premise was wrong and the ticket was decomposed into #237
(this module — writer creation) and #238 (reader migration, separate PR).

Fix
---
:class:`TradesWriter` subscribes to the ``trades.executed`` ZMQ topic and,
for each validated :class:`TradeRecord` payload, dual-writes it to the
legacy aggregate key ``trades:all`` and the per-strategy key
``trades:{strategy_id}:all`` (Roadmap §2.2.5 row 2, Charter §5.5). The
dual-write preserves the legacy consumer surface untouched while
populating the per-strategy partition that Phase B readers will migrate
to (tracked in #238).

Sister-writer pattern
---------------------
This writer mirrors the :class:`services.feedback_loop.position_aggregator.PositionAggregator`
pattern introduced in PR #245 for ``portfolio:positions``:

- Bounded in-memory structure for idempotency tracking (there, a list of
  positions; here, a FIFO deque of seen ``trade_id`` values).
- Periodic Redis bound-enforcement (there, a fail-fast TTL; here, a
  periodic ``LTRIM`` that caps the list size).
- Lifecycle managed by :class:`services.feedback_loop.service.FeedbackLoopService`
  via :meth:`run_loop` as a background task cancelled cooperatively in
  ``finally``.

Key difference: :class:`PositionAggregator` uses the READ-then-AGGREGATE
pattern (scan ``positions:*``, write ``portfolio:positions``);
:class:`TradesWriter` uses the SUBSCRIBE-then-WRITE pattern (pull
records off ZMQ, push to ``trades:all``). The two patterns coexist in
S09 because their sources differ — positions are written piecemeal by
S06 as fills arrive, while trade records are lifecycle-complete
post-close objects that only S09 is authoritatively positioned to
persist (CLAUDE.md §1: single responsibility per service; TradeRecord
docstring at ``core/models/order.py:340``: "Written by S09 Feedback
Loop after a position closes.").

Topic contract
--------------
On main as of 2026-04-23, ``core/topics.py`` does not yet declare a
canonical ``TRADES_EXECUTED`` constant — the only order-lifecycle topic
is ``order.filled`` which carries :class:`ExecutedOrder` (a fill), not
:class:`TradeRecord` (a closed trade). :data:`TRADES_EXECUTED_TOPIC`
below is the forward-looking topic name this writer subscribes to; any
future producer of ``TradeRecord`` events (position-close emitter in
S06 or S09, Phase B sub-book flusher, etc.) MUST publish on exactly
``"trades.executed"``. When a canonical constant lands in
``core/topics.py``, this literal will be replaced by the import.

Compliance notes
----------------
- CLAUDE.md §2 — :class:`Decimal` (never float): ``TradeRecord`` fields
  are already Decimal; this module does no numeric coercion.
  :mod:`structlog` via :func:`core.logger.get_logger`; ``asyncio`` only
  (no threads); UTC is carried on the model's millisecond timestamps.
- CLAUDE.md §3 — Single responsibility: subscribe + dual-write +
  bound-enforcement. No analytics, no transforms, no multi-strategy
  fan-out beyond the per-strategy partition Charter §5.5 mandates.
- CLAUDE.md §5 — Redis conventions: list-based storage (six readers use
  ``lrange``); JSON serialization via :class:`core.state.StateStore`
  primitives; no hardcoded TTL on the aggregate (reader-driven liveness
  is the contract, not writer-driven expiry).
- CLAUDE.md §10 — Payload validation failures log at ``error`` and skip
  (a single corrupted ZMQ frame must not halt the consumer); unknown
  exceptions in the Timescale path log at ``error`` and are swallowed
  so Redis persistence is never blocked on durable-DB availability.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from core.logger import get_logger
from core.models.order import TradeRecord

logger = get_logger("feedback_loop.trades_writer")

TRADES_EXECUTED_TOPIC = "trades.executed"
"""Canonical ZMQ topic for TradeRecord events.

Forward-looking: not yet declared in :mod:`core.topics` as of the 2026-04-23
PR. Any producer of :class:`TradeRecord` events MUST publish on exactly
``"trades.executed"``. This module-local constant will be replaced by an
import of ``core.topics.Topics.TRADES_EXECUTED`` when the canonical
constant lands in core/ (out of scope for this PR — see
``docs/audits/TRADES_WRITER_IMPL_2026-04-23.md`` §3)."""

LEGACY_AGGREGATE_KEY = "trades:all"
"""Legacy aggregate key read by the six pre-migration readers listed in
``docs/audits/TRADES_KEY_WRITER_AUDIT_2026-04-20.md`` §2. Kept populated
until #238 migrates readers to the per-strategy partition."""

PER_STRATEGY_KEY_TEMPLATE = "trades:{strategy_id}:all"
"""Per-strategy partition mandated by Roadmap §2.2.5 row 2 and Charter §5.5."""

DEFAULT_TRIM_SIZE = 10_000
"""Maximum list length preserved per key after each write.

Rationale: the two heaviest readers (S09 ``_slow_analysis`` and S10
``/trades`` endpoint) call ``lrange(..., 0, -1)`` so an unbounded list
would drag response times linearly with history. 10 000 records at
roughly 10 closes/min gives about 16 h of raw trade history, which
exceeds the readers' rolling windows (``KELLY_ROLLING_WINDOW = 100`` for
drift/Kelly; dashboard endpoints are already day-windowed upstream)."""

DEFAULT_SEEN_CAPACITY = 50_000
"""Bounded idempotency cache for ``trade_id`` deduplication within a
single process lifetime. FIFO eviction. 5× ``DEFAULT_TRIM_SIZE`` so a
replay window that spans the trimmed list still rejects duplicates."""


class _StateProtocol(Protocol):
    """Subset of :class:`core.state.StateStore` consumed by the writer.

    Mirrors the Protocol style used by
    :class:`services.feedback_loop.position_aggregator._StateProtocol` so
    a ``fakeredis``-backed adapter can satisfy it in unit tests without
    pulling in the full :class:`StateStore` contract.
    """

    async def lpush(self, key: str, *values: Any) -> None: ...  # noqa: ANN401

    async def ltrim(self, key: str, start: int, end: int) -> None: ...


class _BusProtocol(Protocol):
    """Subset of :class:`core.bus.MessageBus` consumed by the writer.

    The ``subscribe`` coroutine runs an infinite recv-and-dispatch loop;
    :meth:`TradesWriter.run_loop` delegates to it directly so the
    underlying ZMQ socket lifecycle stays owned by :mod:`core.bus`.
    """

    async def subscribe(
        self,
        topics: list[str],
        handler: Callable[[str, dict[str, Any]], Any],
    ) -> None: ...


class _TimescaleInserter(Protocol):
    """Optional durable-persistence sink for :class:`TradeRecord`.

    Kept as a narrow Protocol so the in-flight ``apex_trade_records``
    hypertable wiring (ADR-0014 table 7) can be layered on without a
    re-design. :class:`TradesWriter` treats the inserter as best-effort:
    failures here are logged and swallowed so Redis persistence never
    blocks on durable-DB availability (see module docstring).
    """

    async def insert_trade_record(self, record: TradeRecord) -> None: ...


class TradesWriter:
    """Consolidated writer for ``trades:all`` + ``trades:{strategy_id}:all``.

    Lifecycle::

        writer = TradesWriter(state, bus=service.bus)
        task = asyncio.create_task(writer.run_loop())
        ...
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    Invariants:

    - Each :class:`TradeRecord` lpush'd to ``trades:all`` is also lpush'd
      to ``trades:{strategy_id}:all`` in the same :meth:`record_trade`
      call. If either write raises, both keys may be left inconsistent
      for at most one record — the module docstring acknowledges that
      atomic dual-write would require a Redis ``MULTI`` surface that
      :class:`StateStore` does not currently expose; eventual
      consistency within one record is deemed acceptable because the
      partition migration (#238) flips the primary surface to the
      per-strategy key and the legacy key becomes a read-through
      convenience only.
    - Idempotency: a :class:`TradeRecord` whose ``trade_id`` has already
      been observed within the process lifetime (bounded FIFO cache) is
      silently dropped. This defends against replayed ZMQ frames and
      transient producer retries; it does not defend against restart
      replays (tracked as a Phase B enhancement in the audit doc).
    - Bound enforcement: after each successful dual-write, both keys are
      ``LTRIM``'d to :data:`DEFAULT_TRIM_SIZE`. LPUSH places the newest
      at index 0, so ``ltrim(key, 0, size-1)`` retains the most recent.

    Args:
        state: Any object satisfying :class:`_StateProtocol`. In
            production this is :class:`core.state.StateStore`; in unit
            tests a ``fakeredis``-backed wrapper.
        bus: Optional :class:`_BusProtocol` used by :meth:`run_loop` to
            subscribe to :data:`TRADES_EXECUTED_TOPIC`. When ``None``,
            the writer operates in direct-injection mode — callers
            invoke :meth:`record_trade` directly (used by tests and by
            any future in-process producer).
        topic: Override for :data:`TRADES_EXECUTED_TOPIC` (tests).
        trim_size: Override for :data:`DEFAULT_TRIM_SIZE`.
        seen_capacity: Override for :data:`DEFAULT_SEEN_CAPACITY`.
        timescale_inserter: Optional durable-DB sink; see
            :class:`_TimescaleInserter`.
    """

    def __init__(
        self,
        state: _StateProtocol,
        *,
        bus: _BusProtocol | None = None,
        topic: str = TRADES_EXECUTED_TOPIC,
        trim_size: int = DEFAULT_TRIM_SIZE,
        seen_capacity: int = DEFAULT_SEEN_CAPACITY,
        timescale_inserter: _TimescaleInserter | None = None,
    ) -> None:
        if trim_size <= 0:
            raise ValueError(f"trim_size must be positive; got {trim_size}")
        if seen_capacity <= 0:
            raise ValueError(f"seen_capacity must be positive; got {seen_capacity}")
        self._state = state
        self._bus = bus
        self._topic = topic
        self._trim_size = trim_size
        self._timescale_inserter = timescale_inserter
        # FIFO-bounded trade_id cache for idempotency. deque(maxlen=...)
        # evicts the oldest id automatically; the set mirror gives O(1)
        # membership checks without paying deque's O(n) ``in`` cost.
        self._seen_order: deque[str] = deque(maxlen=seen_capacity)
        self._seen_set: set[str] = set()

    async def record_trade(self, trade: TradeRecord) -> None:
        """Dual-write a validated :class:`TradeRecord` to both aggregate keys.

        Order of operations:

        1. Idempotency check: drop if ``trade.trade_id`` already seen.
        2. LPUSH legacy key ``trades:all``.
        3. LPUSH per-strategy key ``trades:{strategy_id}:all``.
        4. LTRIM both keys to :data:`DEFAULT_TRIM_SIZE` (most recent
           kept; LPUSH places newest at index 0).
        5. Best-effort Timescale insert if an inserter was supplied;
           failures logged and swallowed.
        6. Mark ``trade_id`` as seen.

        The legacy key is written before the per-strategy key so that,
        on a partial failure, the legacy readers (pre-migration) still
        observe the new trade — preserving the pre-existing single-
        strategy contract while the per-strategy partition is still
        being rolled out (#238).

        Args:
            trade: Validated :class:`TradeRecord` to persist.
        """
        if trade.trade_id in self._seen_set:
            logger.debug(
                "trades_writer_duplicate_skipped",
                trade_id=trade.trade_id,
                strategy_id=trade.strategy_id,
            )
            return

        payload = trade.model_dump(mode="json")
        per_strategy_key = PER_STRATEGY_KEY_TEMPLATE.format(strategy_id=trade.strategy_id)

        await self._state.lpush(LEGACY_AGGREGATE_KEY, payload)
        await self._state.lpush(per_strategy_key, payload)
        await self._state.ltrim(LEGACY_AGGREGATE_KEY, 0, self._trim_size - 1)
        await self._state.ltrim(per_strategy_key, 0, self._trim_size - 1)

        if self._timescale_inserter is not None:
            try:
                await self._timescale_inserter.insert_trade_record(trade)
            except Exception as exc:
                # Durable-DB outages must not block the Redis surface —
                # the six legacy readers remain whole even when Timescale
                # is unavailable. The orphan-write will be reconciled by
                # the Phase B replay tool (tracked in ADR-0014 §future).
                logger.error(
                    "trades_writer_timescale_insert_failed",
                    trade_id=trade.trade_id,
                    strategy_id=trade.strategy_id,
                    error=str(exc),
                )

        # Mark seen AFTER the writes so a failing write can be retried
        # by a higher-level replay. The bounded deque automatically
        # evicts the oldest id; mirror the eviction in the set.
        self._mark_seen(trade.trade_id)

        logger.info(
            "trades_writer_recorded",
            trade_id=trade.trade_id,
            strategy_id=trade.strategy_id,
            symbol=trade.symbol,
            net_pnl=str(trade.net_pnl),
        )

    def _mark_seen(self, trade_id: str) -> None:
        """Record a trade_id in the FIFO idempotency cache.

        If the deque is at capacity, its oldest entry is silently
        evicted by :class:`collections.deque` semantics; we mirror that
        eviction in the accompanying set so membership remains O(1) and
        the two structures stay in sync.
        """
        if len(self._seen_order) == self._seen_order.maxlen:
            evicted = self._seen_order[0]
            self._seen_set.discard(evicted)
        self._seen_order.append(trade_id)
        self._seen_set.add(trade_id)

    async def on_trade_message(self, topic: str, data: dict[str, Any]) -> None:
        """ZMQ subscription handler: validate, then :meth:`record_trade`.

        Designed to match the :class:`core.bus.MessageBus.subscribe`
        handler signature so the writer can be plugged directly in
        without a translation shim. Validation failures are logged and
        swallowed so a single malformed frame cannot halt the consumer.

        Args:
            topic: ZMQ topic string; logged for observability but not
                otherwise used — the writer is single-purpose and all
                incoming frames on its subscription are expected to
                carry :class:`TradeRecord` payloads.
            data: JSON-decoded payload.
        """
        try:
            trade = TradeRecord.model_validate(data)
        except ValidationError as exc:
            logger.error(
                "trades_writer_payload_invalid",
                topic=topic,
                error=str(exc),
                payload_keys=sorted(data.keys()) if isinstance(data, dict) else None,
            )
            return
        await self.record_trade(trade)

    async def run_loop(self) -> None:
        """Subscribe to :data:`TRADES_EXECUTED_TOPIC` and dispatch forever.

        Delegates the recv-and-dispatch loop to
        :meth:`core.bus.MessageBus.subscribe`, which owns the ZMQ socket
        lifecycle and handles per-message exceptions internally. Cancel
        this task cooperatively to stop.

        Raises:
            RuntimeError: if the writer was constructed without a bus.
        """
        if self._bus is None:
            raise RuntimeError(
                "TradesWriter.run_loop requires a MessageBus; "
                "construct with bus=service.bus or call record_trade() directly."
            )
        try:
            await self._bus.subscribe([self._topic], self.on_trade_message)
        except asyncio.CancelledError:
            logger.info("trades_writer_loop_cancelled", topic=self._topic)
            raise


__all__ = [
    "DEFAULT_SEEN_CAPACITY",
    "DEFAULT_TRIM_SIZE",
    "LEGACY_AGGREGATE_KEY",
    "PER_STRATEGY_KEY_TEMPLATE",
    "TRADES_EXECUTED_TOPIC",
    "TradesWriter",
]
