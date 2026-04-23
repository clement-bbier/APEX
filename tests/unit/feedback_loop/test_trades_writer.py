"""Unit tests for :class:`services.feedback_loop.trades_writer.TradesWriter`.

Phase A.12.1 (issue #237). Validates the dual-write contract that closes
the ``trades:all`` orphan-write identified in
``docs/audits/TRADES_KEY_WRITER_AUDIT_2026-04-20.md``.

Test patterns follow CLAUDE.md §7: happy path + edge cases + error cases
+ Hypothesis property tests. Fakeredis adapter mirrors the style used by
``tests/unit/feedback_loop/test_position_aggregator.py`` (PR #245), so the
two sibling writers in S09 share one testing convention.
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
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.feedback_loop.trades_writer import (
    DEFAULT_SEEN_CAPACITY,
    DEFAULT_TRIM_SIZE,
    LEGACY_AGGREGATE_KEY,
    PER_STRATEGY_KEY_TEMPLATE,
    TRADES_EXECUTED_TOPIC,
    TradesWriter,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StateAdapter:
    """Mirrors :class:`core.state.StateStore` ``lpush``/``ltrim`` semantics.

    JSON-encodes on ``lpush`` and exposes the underlying fakeredis client so
    tests can ``lrange`` raw values and decode them like production readers.
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


class _RecordingState:
    """Captures the exact sequence of lpush/ltrim calls for ordering assertions.

    Does no Redis I/O; just records the arguments so tests can verify the
    legacy-before-per-strategy and push-before-trim invariants documented on
    :meth:`TradesWriter.record_trade`.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    async def lpush(self, key: str, *values: Any) -> None:
        self.calls.append(("lpush", key, values))

    async def ltrim(self, key: str, start: int, end: int) -> None:
        self.calls.append(("ltrim", key, (start, end)))


class _FailingState:
    """Raises on every operation; used to verify error-swallowing semantics."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or RuntimeError("simulated redis outage")

    async def lpush(self, key: str, *values: Any) -> None:
        raise self._error

    async def ltrim(self, key: str, start: int, end: int) -> None:
        raise self._error


class _FakeBus:
    """Captures subscribe() arguments and runs the handler against a queue."""

    def __init__(self, frames: list[tuple[str, dict[str, Any]]] | None = None) -> None:
        self.subscribed_topics: list[str] | None = None
        self._frames: list[tuple[str, dict[str, Any]]] = frames or []
        self.handler_results: list[Any] = []

    async def subscribe(
        self,
        topics: list[str],
        handler: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self.subscribed_topics = topics
        for topic, data in self._frames:
            result = handler(topic, data)
            if asyncio.iscoroutine(result):
                self.handler_results.append(await result)
            else:
                self.handler_results.append(result)
        # Park forever so tests that want to exercise cancellation can do
        # so by cancelling the enclosing task; tests that only validate
        # one-shot dispatch cancel the run_loop task externally.
        await asyncio.Event().wait()


class _RecordingInserter:
    """Records every ``insert_trade_record`` call."""

    def __init__(self) -> None:
        self.inserted: list[TradeRecord] = []

    async def insert_trade_record(self, record: TradeRecord) -> None:
        self.inserted.append(record)


class _FailingInserter:
    async def insert_trade_record(self, record: TradeRecord) -> None:
        raise RuntimeError("timescale down")


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Fresh fakeredis per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(redis_client: fakeredis.aioredis.FakeRedis) -> _StateAdapter:
    return _StateAdapter(redis_client)


def _make_trade(
    *,
    trade_id: str = "T001",
    symbol: str = "AAPL",
    direction: Direction = Direction.LONG,
    strategy_id: str = "default",
    net_pnl: str = "100",
    gross_pnl: str = "110",
) -> TradeRecord:
    """Build a valid TradeRecord with safe defaults."""
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        direction=direction,
        entry_timestamp_ms=1_700_000_000_000,
        exit_timestamp_ms=1_700_000_060_000,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        size=Decimal("10"),
        gross_pnl=Decimal(gross_pnl),
        net_pnl=Decimal(net_pnl),
        commission=Decimal("1"),
        slippage_cost=Decimal("0.5"),
        strategy_id=strategy_id,
    )


async def _lrange_decoded(client: fakeredis.aioredis.FakeRedis, key: str) -> list[dict[str, Any]]:
    """Read + JSON-decode a Redis list; mirrors production readers."""
    raw = await client.lrange(key, 0, -1)
    decoded: list[dict[str, Any]] = []
    for v in raw:
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        decoded.append(json.loads(v))
    return decoded


# ---------------------------------------------------------------------------
# Constructor / validation
# ---------------------------------------------------------------------------


def test_init_defaults(state: _StateAdapter) -> None:
    w = TradesWriter(state)
    # Private attributes are part of the documented lifecycle surface; tests
    # that touch them keep invariants honest.
    assert w._trim_size == DEFAULT_TRIM_SIZE
    assert w._seen_order.maxlen == DEFAULT_SEEN_CAPACITY
    assert w._bus is None
    assert w._timescale_inserter is None


def test_init_rejects_non_positive_trim_size(state: _StateAdapter) -> None:
    with pytest.raises(ValueError, match="trim_size must be positive"):
        TradesWriter(state, trim_size=0)
    with pytest.raises(ValueError, match="trim_size must be positive"):
        TradesWriter(state, trim_size=-5)


def test_init_rejects_non_positive_seen_capacity(state: _StateAdapter) -> None:
    with pytest.raises(ValueError, match="seen_capacity must be positive"):
        TradesWriter(state, seen_capacity=0)
    with pytest.raises(ValueError, match="seen_capacity must be positive"):
        TradesWriter(state, seen_capacity=-1)


def test_init_custom_topic(state: _StateAdapter) -> None:
    w = TradesWriter(state, topic="custom.topic")
    assert w._topic == "custom.topic"


def test_constants_are_exposed_at_module_level() -> None:
    assert TRADES_EXECUTED_TOPIC == "trades.executed"
    assert LEGACY_AGGREGATE_KEY == "trades:all"
    assert PER_STRATEGY_KEY_TEMPLATE.format(strategy_id="xyz") == "trades:xyz:all"


# ---------------------------------------------------------------------------
# record_trade — dual-write happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_trade_dual_writes(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    writer = TradesWriter(state)
    trade = _make_trade(trade_id="T001", strategy_id="default")
    await writer.record_trade(trade)

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    per_strat = await _lrange_decoded(redis_client, "trades:default:all")
    assert len(legacy) == 1
    assert len(per_strat) == 1
    assert legacy[0]["trade_id"] == "T001"
    assert per_strat[0]["trade_id"] == "T001"


@pytest.mark.asyncio
async def test_record_trade_per_strategy_partition(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """Different strategy_ids must land in different per-strategy keys."""
    writer = TradesWriter(state)
    await writer.record_trade(_make_trade(trade_id="T001", strategy_id="har_rv"))
    await writer.record_trade(_make_trade(trade_id="T002", strategy_id="crypto_momentum"))

    har = await _lrange_decoded(redis_client, "trades:har_rv:all")
    crypto = await _lrange_decoded(redis_client, "trades:crypto_momentum:all")
    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)

    assert [t["trade_id"] for t in har] == ["T001"]
    assert [t["trade_id"] for t in crypto] == ["T002"]
    assert {t["trade_id"] for t in legacy} == {"T001", "T002"}


@pytest.mark.asyncio
async def test_record_trade_payload_shape_roundtrips_through_trade_record(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """Readers deserialize via TradeRecord(**t); payload must round-trip."""
    writer = TradesWriter(state)
    trade = _make_trade(trade_id="T001", symbol="BTCUSDT", strategy_id="har_rv")
    await writer.record_trade(trade)

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    reconstructed = TradeRecord(**legacy[0])
    assert reconstructed == trade


@pytest.mark.asyncio
async def test_record_trade_lpush_places_newest_at_index_zero(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """Confirms LPUSH semantics (newest first) so readers' lrange(0, N) works."""
    writer = TradesWriter(state)
    for i in range(3):
        await writer.record_trade(_make_trade(trade_id=f"T00{i}"))

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    # Newest (T002) at index 0, oldest (T000) at the tail.
    assert [t["trade_id"] for t in legacy] == ["T002", "T001", "T000"]


# ---------------------------------------------------------------------------
# record_trade — call ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_trade_legacy_key_written_before_per_strategy() -> None:
    """Module docstring invariant: legacy first, per-strategy second."""
    state = _RecordingState()
    writer = TradesWriter(state)
    await writer.record_trade(_make_trade(strategy_id="har_rv"))

    # Filter lpushes only; the trims come after.
    pushes = [c for c in state.calls if c[0] == "lpush"]
    assert len(pushes) == 2
    assert pushes[0][1] == LEGACY_AGGREGATE_KEY
    assert pushes[1][1] == "trades:har_rv:all"


@pytest.mark.asyncio
async def test_record_trade_pushes_before_trims() -> None:
    state = _RecordingState()
    writer = TradesWriter(state)
    await writer.record_trade(_make_trade())

    ops = [c[0] for c in state.calls]
    assert ops == ["lpush", "lpush", "ltrim", "ltrim"]


@pytest.mark.asyncio
async def test_record_trade_trim_applies_configured_trim_size() -> None:
    state = _RecordingState()
    writer = TradesWriter(state, trim_size=500)
    await writer.record_trade(_make_trade())

    trims = [c for c in state.calls if c[0] == "ltrim"]
    # ltrim(key, 0, trim_size - 1) retains the newest N.
    assert all(args == (0, 499) for _, _, args in trims)


# ---------------------------------------------------------------------------
# record_trade — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_trade_duplicate_trade_id_is_skipped(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    writer = TradesWriter(state)
    trade = _make_trade(trade_id="T001")
    await writer.record_trade(trade)
    await writer.record_trade(trade)  # exact same id

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert len(legacy) == 1


@pytest.mark.asyncio
async def test_record_trade_distinct_trade_ids_both_written(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    writer = TradesWriter(state)
    await writer.record_trade(_make_trade(trade_id="T001"))
    await writer.record_trade(_make_trade(trade_id="T002"))

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert {t["trade_id"] for t in legacy} == {"T001", "T002"}


@pytest.mark.asyncio
async def test_record_trade_seen_cache_fifo_eviction(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """When seen-cache fills, oldest id is evicted and can be re-recorded."""
    writer = TradesWriter(state, seen_capacity=3)
    for i in range(3):
        await writer.record_trade(_make_trade(trade_id=f"T00{i}"))
    # Cache is now full: {T000, T001, T002}.
    # Push three more → evicts T000, T001, T002.
    for i in range(3, 6):
        await writer.record_trade(_make_trade(trade_id=f"T00{i}"))
    # T000 was evicted; re-recording it must succeed (no dedup).
    await writer.record_trade(_make_trade(trade_id="T000"))

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    # T000 appears twice (original + re-record after eviction); others once each.
    trade_ids = [t["trade_id"] for t in legacy]
    assert trade_ids.count("T000") == 2


@pytest.mark.asyncio
async def test_record_trade_seen_set_and_deque_stay_in_sync(
    state: _StateAdapter,
) -> None:
    writer = TradesWriter(state, seen_capacity=4)
    for i in range(4):
        await writer.record_trade(_make_trade(trade_id=f"T00{i}"))
    # Private state sanity — both structures should be exactly same size.
    assert len(writer._seen_order) == len(writer._seen_set) == 4

    for i in range(4, 10):
        await writer.record_trade(_make_trade(trade_id=f"T00{i}"))
    # Capacity never exceeded.
    assert len(writer._seen_order) == len(writer._seen_set) == 4


# ---------------------------------------------------------------------------
# Timescale inserter path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_trade_invokes_timescale_inserter(
    state: _StateAdapter,
) -> None:
    inserter = _RecordingInserter()
    writer = TradesWriter(state, timescale_inserter=inserter)
    trade = _make_trade(trade_id="T001")
    await writer.record_trade(trade)

    assert inserter.inserted == [trade]


@pytest.mark.asyncio
async def test_record_trade_timescale_failure_does_not_block_redis(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """Durable-DB outage must not interrupt the Redis dual-write."""
    writer = TradesWriter(state, timescale_inserter=_FailingInserter())
    await writer.record_trade(_make_trade(trade_id="T001"))

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    per_strat = await _lrange_decoded(redis_client, "trades:default:all")
    assert len(legacy) == 1
    assert len(per_strat) == 1


@pytest.mark.asyncio
async def test_record_trade_no_inserter_skips_timescale_path(
    state: _StateAdapter,
) -> None:
    # Purely coverage: exercise the None branch explicitly.
    writer = TradesWriter(state, timescale_inserter=None)
    await writer.record_trade(_make_trade())
    # No assertion needed beyond "does not raise"; state stores the trade.


# ---------------------------------------------------------------------------
# on_trade_message — ZMQ handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_trade_message_valid_payload_records(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    writer = TradesWriter(state)
    trade = _make_trade(trade_id="T001")
    await writer.on_trade_message(TRADES_EXECUTED_TOPIC, trade.model_dump(mode="json"))

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert len(legacy) == 1
    assert legacy[0]["trade_id"] == "T001"


@pytest.mark.asyncio
async def test_on_trade_message_invalid_payload_swallowed(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """A malformed frame must not raise or halt the consumer."""
    writer = TradesWriter(state)
    await writer.on_trade_message(TRADES_EXECUTED_TOPIC, {"not": "a trade"})

    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert legacy == []


@pytest.mark.asyncio
async def test_on_trade_message_non_dict_payload_swallowed(
    state: _StateAdapter,
) -> None:
    """Pydantic rejects non-mapping payloads; handler must not raise."""
    writer = TradesWriter(state)
    # Pass a list rather than a dict; still must not raise.
    await writer.on_trade_message(TRADES_EXECUTED_TOPIC, [])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_on_trade_message_wrong_strategy_id_shape_swallowed(
    state: _StateAdapter,
) -> None:
    """Invalid strategy_id (e.g. with slash) fails validator; handler swallows."""
    writer = TradesWriter(state)
    bad = _make_trade().model_dump(mode="json")
    bad["strategy_id"] = "bad/strategy"  # forbidden char
    await writer.on_trade_message(TRADES_EXECUTED_TOPIC, bad)
    # Does not raise; trades are not recorded.
    assert len(writer._seen_order) == 0


# ---------------------------------------------------------------------------
# run_loop — bus integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_loop_raises_without_bus(state: _StateAdapter) -> None:
    writer = TradesWriter(state)
    with pytest.raises(RuntimeError, match="requires a MessageBus"):
        await writer.run_loop()


@pytest.mark.asyncio
async def test_run_loop_subscribes_to_configured_topic(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    trade = _make_trade(trade_id="T001")
    bus = _FakeBus(frames=[(TRADES_EXECUTED_TOPIC, trade.model_dump(mode="json"))])
    writer = TradesWriter(state, bus=bus)

    task = asyncio.create_task(writer.run_loop())
    # Give the loop a chance to process the one queued frame before we cancel.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert bus.subscribed_topics == [TRADES_EXECUTED_TOPIC]
    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert len(legacy) == 1
    assert legacy[0]["trade_id"] == "T001"


@pytest.mark.asyncio
async def test_run_loop_cancellation_propagates(state: _StateAdapter) -> None:
    bus = _FakeBus()
    writer = TradesWriter(state, bus=bus)
    task = asyncio.create_task(writer.run_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_loop_custom_topic(state: _StateAdapter) -> None:
    bus = _FakeBus()
    writer = TradesWriter(state, bus=bus, topic="custom.trades")
    task = asyncio.create_task(writer.run_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bus.subscribed_topics == ["custom.trades"]


# ---------------------------------------------------------------------------
# Error propagation — Redis failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_trade_propagates_redis_failure() -> None:
    """A Redis outage surfaces to the caller so the bus loop logs it.

    The bus-level try/except in :meth:`core.bus.MessageBus.subscribe`
    already protects the recv loop from handler failures, so the writer
    does not need to swallow state errors here. Propagation preserves
    observability.
    """
    writer = TradesWriter(_FailingState())
    with pytest.raises(RuntimeError, match="simulated redis outage"):
        await writer.record_trade(_make_trade())


@pytest.mark.asyncio
async def test_record_trade_redis_failure_does_not_poison_seen_cache(
    state: _StateAdapter, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    """If the lpush raises, the trade_id must not be marked seen, so a
    retry can succeed."""
    # Use a state that fails the first call then succeeds.
    calls = {"n": 0}

    class _FlakyState:
        async def lpush(self, key: str, *values: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            encoded = [json.dumps(v, default=str) for v in values]
            await redis_client.lpush(key, *encoded)

        async def ltrim(self, key: str, start: int, end: int) -> None:
            await redis_client.ltrim(key, start, end)

    writer = TradesWriter(_FlakyState())
    trade = _make_trade(trade_id="T001")

    with pytest.raises(RuntimeError, match="transient"):
        await writer.record_trade(trade)

    # Retry — the in-memory seen-cache must still allow this id through.
    await writer.record_trade(trade)
    legacy = await _lrange_decoded(redis_client, LEGACY_AGGREGATE_KEY)
    assert len(legacy) == 1


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


_strategy_ids = st.sampled_from(["default", "har_rv", "crypto_momentum", "ofi"])
_prices = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


@st.composite
def _trade_records(draw: st.DrawFn) -> TradeRecord:
    strategy_id = draw(_strategy_ids)
    tid = draw(
        st.text(
            min_size=1, max_size=16, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))
        )
    )
    symbol = draw(st.sampled_from(["AAPL", "MSFT", "BTCUSDT", "ETHUSDT"]))
    direction = draw(st.sampled_from([Direction.LONG, Direction.SHORT]))
    entry = draw(_prices)
    exit_price = draw(_prices)
    size = draw(_prices)
    gross = draw(_prices)
    return TradeRecord(
        trade_id=tid,
        symbol=symbol,
        direction=direction,
        entry_timestamp_ms=1_700_000_000_000,
        exit_timestamp_ms=1_700_000_060_000,
        entry_price=entry,
        exit_price=exit_price,
        size=size,
        gross_pnl=gross,
        net_pnl=gross - Decimal("1"),
        commission=Decimal("1"),
        slippage_cost=Decimal("0"),
        strategy_id=strategy_id,
    )


@given(trade=_trade_records())
@hyp_settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@pytest.mark.asyncio
async def test_property_payload_roundtrips_through_trade_record(
    trade: TradeRecord,
) -> None:
    """Any valid TradeRecord survives model_dump → JSON → model_validate."""
    dumped = trade.model_dump(mode="json")
    encoded = json.dumps(dumped, default=str)
    decoded = json.loads(encoded)
    restored = TradeRecord(**decoded)
    assert restored == trade


@given(n=st.integers(min_value=1, max_value=40))
@hyp_settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@pytest.mark.asyncio
async def test_property_seen_cache_never_exceeds_capacity(n: int) -> None:
    state = _RecordingState()
    # Small capacity so overflow is reached within the bounded n range.
    writer = TradesWriter(state, seen_capacity=8)
    for i in range(n):
        await writer.record_trade(_make_trade(trade_id=f"TID_{i:04d}"))
    assert len(writer._seen_order) <= 8
    assert len(writer._seen_set) <= 8
    assert len(writer._seen_order) == len(writer._seen_set)


@given(
    trade_ids=st.lists(
        st.text(min_size=1, max_size=12, alphabet=st.characters(whitelist_categories=("Lu", "Nd"))),
        min_size=1,
        max_size=20,
        unique=True,
    )
)
@hyp_settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@pytest.mark.asyncio
async def test_property_distinct_ids_are_all_persisted(
    trade_ids: list[str],
) -> None:
    """All unique trade_ids pushed in a single session must appear in legacy key."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _StateAdapter(redis)
        writer = TradesWriter(state, trim_size=100)
        for tid in trade_ids:
            await writer.record_trade(_make_trade(trade_id=tid))
        legacy = await _lrange_decoded(redis, LEGACY_AGGREGATE_KEY)
        persisted = {t["trade_id"] for t in legacy}
        assert persisted == set(trade_ids)
    finally:
        await redis.flushall()
        await redis.aclose()


@given(trade=_trade_records())
@hyp_settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@pytest.mark.asyncio
async def test_property_duplicate_record_is_always_skipped(
    trade: TradeRecord,
) -> None:
    """Recording any TradeRecord twice must leave only one entry in Redis."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _StateAdapter(redis)
        writer = TradesWriter(state)
        await writer.record_trade(trade)
        await writer.record_trade(trade)
        legacy = await _lrange_decoded(redis, LEGACY_AGGREGATE_KEY)
        assert len(legacy) == 1
    finally:
        await redis.flushall()
        await redis.aclose()
