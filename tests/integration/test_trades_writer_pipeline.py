"""Integration tests for the TradesWriter end-to-end pipeline.

Phase A.12.1 (issue #237). Exercises the full subscribe → validate →
dual-write → (optional) Timescale → trim chain through a simulated ZMQ
bus + fakeredis + mock Timescale inserter. Complements the unit tests
in ``tests/unit/feedback_loop/test_trades_writer.py`` by covering the
cross-cutting concerns:

- Order preservation across a multi-trade burst.
- Concurrent publish / consume without data loss.
- Timescale failure isolation under load.
- Cooperative cancellation mid-flight without leaving Redis in a torn
  state.

No real Redis, no real ZMQ — the fakeredis-backed StateStore adapter
and an in-process bus double keep the integration hermetic, matching
CLAUDE.md §7's "no real Redis in unit tests" spirit for the
integration-level scope where actual Redis would require docker.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.feedback_loop.trades_writer import (
    LEGACY_AGGREGATE_KEY,
    TRADES_EXECUTED_TOPIC,
    TradesWriter,
)


class _StateAdapter:
    """Matches :class:`core.state.StateStore` lpush/ltrim on fakeredis."""

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    async def lpush(self, key: str, *values: Any) -> None:
        encoded = [json.dumps(v, default=str) for v in values]
        await self._redis.lpush(key, *encoded)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        await self._redis.ltrim(key, start, end)


class _AsyncQueueBus:
    """In-process :class:`core.bus.MessageBus` double backed by an asyncio Queue.

    Delivers queued frames to the subscriber's handler one-by-one,
    matching the recv loop behaviour of the real bus without touching
    ZMQ. After the queue is drained the subscribe() coroutine blocks on
    a fresh queue.get() so the task stays parked and the test can drive
    cancellation explicitly.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self.subscribed: bool = False

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        await self._queue.put((topic, data))

    async def subscribe(
        self,
        topics: list[str],
        handler: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self.subscribed = True
        while True:
            topic, data = await self._queue.get()
            result = handler(topic, data)
            if asyncio.iscoroutine(result):
                await result


class _RecordingInserter:
    def __init__(self) -> None:
        self.inserted: list[TradeRecord] = []

    async def insert_trade_record(self, record: TradeRecord) -> None:
        self.inserted.append(record)


class _FlakyInserter:
    """Fails every other call to simulate a degraded Timescale."""

    def __init__(self) -> None:
        self.attempts: int = 0

    async def insert_trade_record(self, record: TradeRecord) -> None:
        self.attempts += 1
        if self.attempts % 2 == 1:
            raise RuntimeError("timescale flake")


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


def _make_trade(trade_id: str, *, strategy_id: str = "default") -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        symbol="AAPL",
        direction=Direction.LONG,
        entry_timestamp_ms=1_700_000_000_000,
        exit_timestamp_ms=1_700_000_060_000,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        size=Decimal("10"),
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("9"),
        commission=Decimal("1"),
        slippage_cost=Decimal("0"),
        strategy_id=strategy_id,
    )


async def _lrange_decoded(client: fakeredis.aioredis.FakeRedis, key: str) -> list[dict[str, Any]]:
    raw = await client.lrange(key, 0, -1)
    decoded: list[dict[str, Any]] = []
    for v in raw:
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        decoded.append(json.loads(v))
    return decoded


# ---------------------------------------------------------------------------
# End-to-end single trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_single_trade(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Publish one trade → writer consumes → Redis dual-key + Timescale insert."""
    state = _StateAdapter(redis_client)
    bus = _AsyncQueueBus()
    inserter = _RecordingInserter()
    writer = TradesWriter(state, bus=bus, timescale_inserter=inserter)

    task = asyncio.create_task(writer.run_loop())
    trade = _make_trade("T001", strategy_id="har_rv")
    await bus.publish(TRADES_EXECUTED_TOPIC, trade.model_dump(mode="json"))

    # Yield until the handler has drained the queue.
    for _ in range(10):
        await asyncio.sleep(0)
        if inserter.inserted:
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    per_strat = await _lrange_decoded(redis_client, "trades:har_rv:all")
    assert [t["trade_id"] for t in legacy] == ["T001"]
    assert [t["trade_id"] for t in per_strat] == ["T001"]
    assert inserter.inserted[0].trade_id == "T001"


# ---------------------------------------------------------------------------
# Multi-trade order preservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_trades_order_preserved(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """LPUSH semantics: later publishes land at lower indices; ordering stable."""
    state = _StateAdapter(redis_client)
    bus = _AsyncQueueBus()
    writer = TradesWriter(state, bus=bus)

    task = asyncio.create_task(writer.run_loop())
    for i in range(5):
        await bus.publish(TRADES_EXECUTED_TOPIC, _make_trade(f"T00{i}").model_dump(mode="json"))

    # Let the handler drain.
    for _ in range(30):
        await asyncio.sleep(0)
        legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
        if len(legacy) == 5:
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    # Newest first (LPUSH), so T004..T000.
    assert [t["trade_id"] for t in legacy] == ["T004", "T003", "T002", "T001", "T000"]


# ---------------------------------------------------------------------------
# Concurrent publish safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_publish_no_loss(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Many concurrent publishes must all land in the legacy key."""
    state = _StateAdapter(redis_client)
    bus = _AsyncQueueBus()
    writer = TradesWriter(state, bus=bus)

    task = asyncio.create_task(writer.run_loop())
    n = 50

    async def _publish(i: int) -> None:
        await bus.publish(TRADES_EXECUTED_TOPIC, _make_trade(f"T{i:03d}").model_dump(mode="json"))

    await asyncio.gather(*[_publish(i) for i in range(n)])

    # Drain.
    for _ in range(200):
        await asyncio.sleep(0)
        legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
        if len(legacy) == n:
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert {t["trade_id"] for t in legacy} == {f"T{i:03d}" for i in range(n)}


# ---------------------------------------------------------------------------
# Timescale failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timescale_failure_does_not_lose_redis_snapshot(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Even when Timescale fails on every other insert, all trades hit Redis."""
    state = _StateAdapter(redis_client)
    bus = _AsyncQueueBus()
    inserter = _FlakyInserter()
    writer = TradesWriter(state, bus=bus, timescale_inserter=inserter)

    task = asyncio.create_task(writer.run_loop())
    for i in range(6):
        await bus.publish(TRADES_EXECUTED_TOPIC, _make_trade(f"T00{i}").model_dump(mode="json"))

    for _ in range(30):
        await asyncio.sleep(0)
        legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
        if len(legacy) == 6:
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    # All 6 pushed to Redis despite ~3 Timescale failures.
    assert len({t["trade_id"] for t in legacy}) == 6
    assert inserter.attempts == 6


# ---------------------------------------------------------------------------
# Cancellation mid-flight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_preserves_already_written_state(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Trades written before cancellation remain in Redis after shutdown."""
    state = _StateAdapter(redis_client)
    bus = _AsyncQueueBus()
    writer = TradesWriter(state, bus=bus)

    task = asyncio.create_task(writer.run_loop())
    await bus.publish(TRADES_EXECUTED_TOPIC, _make_trade("T001").model_dump(mode="json"))
    await bus.publish(TRADES_EXECUTED_TOPIC, _make_trade("T002").model_dump(mode="json"))

    for _ in range(20):
        await asyncio.sleep(0)
        legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
        if len(legacy) == 2:
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # After cancellation, the written state is still there.
    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert {t["trade_id"] for t in legacy} == {"T001", "T002"}
