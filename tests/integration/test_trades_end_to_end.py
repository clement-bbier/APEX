"""End-to-end integration test: TradesWriter → Redis ``trades:all`` → 6 readers.

Phase A.12.2 (issue #238). Validates the full canonical pipeline
established by PR #253 (writer) + this PR (readers migration). Where
``tests/integration/test_trades_writer_pipeline.py`` stops at "writer
persists to Redis", this test chains through to the six production
readers enumerated in
``docs/audits/TRADES_KEY_WRITER_AUDIT_2026-04-20.md`` and
``docs/audits/TRADES_READERS_MIGRATION_2026-04-23.md``:

1. ``FeedbackLoopService._fast_analysis``            (S09 feedback_loop)
2. ``FeedbackLoopService._slow_analysis``            (S09 feedback_loop)
3. ``get_pnl``                                       (S10 command_center)
4. ``get_performance``                               (S10 command_center)
5. ``PnLTracker.get_realized_pnl``                   (S10 command_center)
6. ``PnLTracker.get_daily_pnl``                      (S10 command_center)

Hermetic: fakeredis for the Redis layer, an in-process ``_AsyncQueueBus``
for the ZMQ subscribe path — same pattern used by the writer's existing
pipeline test. No docker, no real ZMQ.

Scenarios:

1. Golden path: 5 trades → all six readers see the canonical shape.
2. Empty: no trades → every reader returns zero/empty without raising.
3. Max buffer: 10 020 trades → writer ``LTRIM`` caps at ``DEFAULT_TRIM_SIZE``
   (10 000); readers still consume the capped list.
4. Concurrent publish + reader invocation: readers never observe
   partial-serialized frames (LPUSH is atomic at the Redis level).
5. ``strategy_id`` propagation: distinct strategies land in their own
   per-strategy partitions and in the union key; legacy readers see the
   union.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.command_center.command_api import get_performance, get_pnl
from services.command_center.pnl_tracker import PnLTracker
from services.feedback_loop.service import FeedbackLoopService
from services.feedback_loop.trades_writer import (
    DEFAULT_TRIM_SIZE,
    LEGACY_AGGREGATE_KEY,
    PER_STRATEGY_KEY_TEMPLATE,
    TRADES_EXECUTED_TOPIC,
    TradesWriter,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _StateStoreShim:
    """Unified StateStore shim that satisfies both the writer Protocol
    (``lpush`` / ``ltrim``) and every reader's surface
    (``lrange`` / ``get`` / ``set`` / ``hset``) over a single fakeredis.

    JSON (de)serialization mirrors :class:`core.state.StateStore`.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    @property
    def client(self) -> fakeredis.aioredis.FakeRedis:
        return self._redis

    async def lpush(self, key: str, *values: Any) -> None:
        encoded = [json.dumps(v, default=str) for v in values]
        await self._redis.lpush(key, *encoded)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        await self._redis.ltrim(key, start, end)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        raw = await self._redis.lrange(key, start, end)
        return [json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in raw]

    async def get(self, key: str) -> Any:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value, default=str))

    async def hset(self, name: str, field: str, value: Any) -> None:
        await self._redis.hset(name, field, json.dumps(value, default=str))


class _AsyncQueueBus:
    """In-process MessageBus double. Same pattern as test_trades_writer_pipeline."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self.published_drift: list[dict[str, Any]] = []

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        # Drift alerts come out of _fast_analysis; capture them separately.
        if topic == "feedback.drift_alert":
            self.published_drift.append(data)
            return
        await self._queue.put((topic, data))

    async def subscribe(
        self,
        topics: list[str],
        handler: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        while True:
            topic, data = await self._queue.get()
            result = handler(topic, data)
            if asyncio.iscoroutine(result):
                await result


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(redis_client: fakeredis.aioredis.FakeRedis) -> _StateStoreShim:
    return _StateStoreShim(redis_client)


@pytest.fixture
def feedback_service(state: _StateStoreShim) -> FeedbackLoopService:
    """Hermetic FeedbackLoopService with fake state + bus."""
    svc = FeedbackLoopService()
    svc.state = state  # type: ignore[assignment]
    svc.bus = _AsyncQueueBus()  # type: ignore[assignment]
    return svc


def _today_exit_ms(hour: int = 12) -> int:
    today_start = int(time.time() // 86400 * 86400)
    return (today_start + hour * 3600) * 1000


def _make_trade(
    trade_id: str,
    *,
    symbol: str = "AAPL",
    strategy_id: str = "default",
    net_pnl: str = "100",
    gross_pnl: str = "110",
    exit_ms: int | None = None,
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        direction=Direction.LONG,
        entry_timestamp_ms=(exit_ms - 60_000) if exit_ms else 1_700_000_000_000,
        exit_timestamp_ms=exit_ms if exit_ms is not None else _today_exit_ms(),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        size=Decimal("10"),
        gross_pnl=Decimal(gross_pnl),
        net_pnl=Decimal(net_pnl),
        commission=Decimal("1"),
        slippage_cost=Decimal("0.5"),
        strategy_id=strategy_id,
    )


async def _drive_writer(
    bus: _AsyncQueueBus,
    writer: TradesWriter,
    trades: list[TradeRecord],
    *,
    expected_count: int | None = None,
) -> asyncio.Task[None]:
    """Publish trades through the bus and pump the writer's subscribe loop.

    Returns the writer task; caller is responsible for cancelling it.
    ``expected_count`` lets the pump yield just enough for all trades to
    land in Redis; default polls the legacy list length.
    """
    target = expected_count if expected_count is not None else len(trades)
    task = asyncio.create_task(writer.run_loop())
    for trade in trades:
        await bus.publish(TRADES_EXECUTED_TOPIC, trade.model_dump(mode="json"))

    # Drain the queue via cooperative scheduling.
    for _ in range(max(target * 20, 40)):
        await asyncio.sleep(0)
        size = await writer._state._redis.llen(LEGACY_AGGREGATE_KEY)  # type: ignore[attr-defined]
        if size >= min(target, DEFAULT_TRIM_SIZE):
            break
    return task


async def _stop_writer(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Scenario 1 — Golden path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_path_five_trades_reach_all_six_readers(
    state: _StateStoreShim,
    redis_client: fakeredis.aioredis.FakeRedis,
    feedback_service: FeedbackLoopService,
) -> None:
    """Publish 5 trades → every reader sees the full canonical set."""
    bus = _AsyncQueueBus()
    writer = TradesWriter(state, bus=bus)
    # Mix AAPL (enough for Kelly) with today-exit-ms (for get_pnl / daily).
    trades = [
        _make_trade(f"T{i}", symbol="AAPL", net_pnl="50", exit_ms=_today_exit_ms(9 + i))
        for i in range(5)
    ]
    task = await _drive_writer(bus, writer, trades)
    await _stop_writer(task)

    # Reader 1 — FeedbackLoopService._fast_analysis (5 trades = Kelly threshold).
    await feedback_service._fast_analysis()
    # Reader 2 — _slow_analysis (writes feedback:signal_quality).
    await feedback_service._slow_analysis()
    signal_quality = await state.get("feedback:signal_quality")
    assert signal_quality is not None  # proves canonical-schema deserialization

    # Kelly stats written for AAPL after _fast_analysis (proves reader 1 consumed).
    kelly = await redis_client.hgetall("kelly:AAPL")
    assert len(kelly) >= 2  # win_rate + avg_rr

    # Reader 3 — get_pnl.
    pnl_summary = await get_pnl(state)  # type: ignore[arg-type]
    assert pnl_summary.trade_count_today == 5
    assert pnl_summary.win_rate_rolling == pytest.approx(1.0)  # all net_pnl=50

    # Reader 4 — get_performance.
    perf = await get_performance(state)  # type: ignore[arg-type]
    assert perf.total_trades == 5

    # Reader 5 — PnLTracker.get_realized_pnl.
    tracker = PnLTracker()
    realized = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
    assert realized == Decimal("250")  # 5 × 50

    # Reader 6 — PnLTracker.get_daily_pnl (all 5 exits are today).
    daily = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
    assert daily == Decimal("250")


# ---------------------------------------------------------------------------
# Scenario 2 — Empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_trades_all_readers_gracefully_return_zero(
    state: _StateStoreShim,
    feedback_service: FeedbackLoopService,
) -> None:
    """No writes → every reader returns zero/empty and never raises."""
    # Readers 1 + 2 — service methods: return early, no side effects.
    await feedback_service._fast_analysis()
    await feedback_service._slow_analysis()
    assert await state.get("feedback:signal_quality") is None

    # Reader 3 — get_pnl.
    pnl_summary = await get_pnl(state)  # type: ignore[arg-type]
    assert pnl_summary.trade_count_today == 0
    assert pnl_summary.win_rate_rolling == 0.0

    # Reader 4 — get_performance.
    perf = await get_performance(state)  # type: ignore[arg-type]
    assert perf.total_trades == 0

    tracker = PnLTracker()
    # Reader 5.
    assert await tracker.get_realized_pnl(state) == Decimal("0")  # type: ignore[arg-type]
    # Reader 6.
    assert await tracker.get_daily_pnl(state) == Decimal("0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scenario 3 — Max buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_buffer_trades_preserves_writer_ltrim(
    state: _StateStoreShim,
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Writer LTRIM caps ``trades:all`` at DEFAULT_TRIM_SIZE even under overflow.

    Readers must still function correctly against the capped list. We test
    the writer's trim behaviour directly (via ``record_trade``) rather
    than through the bus to keep the test bounded under DEFAULT_TRIM_SIZE
    (10 000) iterations — driving 10 020 through the asyncio bus pump
    would blow the default test timeout.
    """
    # Cap at a small value for the test so we can observe the trim effect
    # quickly; the semantics are identical at 10 000.
    writer = TradesWriter(state, trim_size=100)
    for i in range(150):  # 50% over cap
        await writer.record_trade(_make_trade(f"T{i:04d}"))

    size = await redis_client.llen(LEGACY_AGGREGATE_KEY)
    assert size == 100  # exactly trim_size

    # Reader 4 — get_performance still works against the capped list.
    perf = await get_performance(state)  # type: ignore[arg-type]
    assert perf.total_trades == 100

    # Reader 5 — sum over capped list still makes sense.
    tracker = PnLTracker()
    realized = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
    assert realized == Decimal("10000")  # 100 × 100


# ---------------------------------------------------------------------------
# Scenario 4 — Concurrent publish + reader invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_publish_and_read_atomicity(
    state: _StateStoreShim,
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Readers invoked mid-publish see a consistent (possibly partial) view,
    never a half-serialized entry.

    ``record_trade`` LPUSHes one fully-JSON-encoded dict atomically at the
    Redis level, so every ``lrange`` snapshot, no matter when it runs,
    yields a list of complete dicts.
    """
    writer = TradesWriter(state)
    tracker = PnLTracker()

    async def _keep_writing() -> None:
        for i in range(30):
            await writer.record_trade(_make_trade(f"T{i:04d}"))
            await asyncio.sleep(0)  # yield so reader can interleave

    async def _keep_reading() -> list[Decimal]:
        observed: list[Decimal] = []
        for _ in range(30):
            observed.append(await tracker.get_realized_pnl(state))  # type: ignore[arg-type]
            await asyncio.sleep(0)
        return observed

    write_task = asyncio.create_task(_keep_writing())
    read_task = asyncio.create_task(_keep_reading())
    snapshots, _ = await asyncio.gather(read_task, write_task)

    # Every snapshot is a non-negative multiple of 100 (since each trade contributes exactly
    # net_pnl=100), proving no corrupted dict slipped into the stream.
    for obs in snapshots:
        assert obs == obs.quantize(Decimal("1"))
        assert obs >= Decimal("0")
        assert obs % Decimal("100") == Decimal("0")

    # Final state: all 30 trades persisted.
    final_size = await redis_client.llen(LEGACY_AGGREGATE_KEY)
    assert final_size == 30


# ---------------------------------------------------------------------------
# Scenario 5 — strategy_id propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_id_propagates_to_per_strategy_partition(
    state: _StateStoreShim,
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Distinct strategy_ids land in distinct ``trades:{strategy_id}:all`` keys.

    The legacy ``trades:all`` key sees the union. Legacy readers (all 6) do
    not discriminate by strategy_id — this is the whole point of the
    Charter §5.5 dual-write contract.
    """
    writer = TradesWriter(state)
    await writer.record_trade(_make_trade("T_har_1", strategy_id="har_rv", net_pnl="10"))
    await writer.record_trade(_make_trade("T_har_2", strategy_id="har_rv", net_pnl="20"))
    await writer.record_trade(_make_trade("T_crypto_1", strategy_id="crypto_momentum", net_pnl="5"))

    # Legacy key sees all three.
    legacy_raw = await redis_client.lrange(LEGACY_AGGREGATE_KEY, 0, -1)
    assert len(legacy_raw) == 3
    legacy_decoded = [
        json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in legacy_raw
    ]
    assert {t["trade_id"] for t in legacy_decoded} == {"T_har_1", "T_har_2", "T_crypto_1"}

    # Per-strategy keys partition correctly.
    har_raw = await redis_client.lrange(
        PER_STRATEGY_KEY_TEMPLATE.format(strategy_id="har_rv"), 0, -1
    )
    crypto_raw = await redis_client.lrange(
        PER_STRATEGY_KEY_TEMPLATE.format(strategy_id="crypto_momentum"), 0, -1
    )
    assert len(har_raw) == 2
    assert len(crypto_raw) == 1

    # Reader 5 sums over the UNION (legacy key) — not per-strategy.
    tracker = PnLTracker()
    realized = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
    assert realized == Decimal("35")  # 10 + 20 + 5

    # Reader 4 counts the union as well.
    perf = await get_performance(state)  # type: ignore[arg-type]
    assert perf.total_trades == 3
