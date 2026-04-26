"""Regression tests: S09 FeedbackLoopService consumes the canonical ``trades:all`` schema.

Phase A.12.2 (issue #238). Locks in the reader contract established by
PR #253 (TradesWriter): the two ``trades:all`` readers in
:mod:`services.feedback_loop.service` must deserialize
:meth:`TradesWriter.record_trade` output without error.

Classification: both readers are CASE M1 per
``docs/audits/TRADES_READERS_MIGRATION_2026-04-23.md`` — the existing
deserialization pattern ``[TradeRecord(**t) for t in raw_trades if isinstance(t, dict)]``
already matches the writer's ``TradeRecord.model_dump(mode="json")`` shape.
These tests guard the coincidence against future schema drift.

The fixture seeds Redis via the **real** :class:`TradesWriter` so the wire
shape under test is exactly what production produces — not a hand-rolled
dict that might diverge from the canonical payload.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.feedback_loop.service import KELLY_ROLLING_WINDOW, FeedbackLoopService
from services.feedback_loop.trades_writer import TradesWriter

# ---------------------------------------------------------------------------
# Fakes matching the StateStore surface the two readers use
# ---------------------------------------------------------------------------


class _FakeState:
    """Minimal StateStore-shaped adapter over fakeredis.

    Implements the surface consumed by :meth:`_fast_analysis` and
    :meth:`_slow_analysis`: ``lrange`` / ``lpush`` / ``ltrim`` for the
    list-backed trade log, ``get`` / ``set`` / ``hset`` for the scalar /
    hash analytics outputs. JSON (de)serialization mirrors
    :class:`core.state.StateStore`.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis
        self.hset_calls: list[tuple[str, str, Any]] = []
        self.set_calls: list[tuple[str, Any]] = []

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
        self.set_calls.append((key, value))
        await self._redis.set(key, json.dumps(value, default=str))

    async def hset(self, name: str, field: str, value: Any) -> None:
        self.hset_calls.append((name, field, value))
        await self._redis.hset(name, field, json.dumps(value, default=str))


class _FakeBus:
    """Records publish() calls so drift-alert emission is observable."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        self.published.append((topic, data))


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(redis_client: fakeredis.aioredis.FakeRedis) -> _FakeState:
    return _FakeState(redis_client)


@pytest.fixture
def service(state: _FakeState) -> FeedbackLoopService:
    """Construct FeedbackLoopService with injected fake state + bus.

    BaseService.__init__ normally instantiates a real MessageBus and
    StateStore (not connected until start()). We overwrite both to keep
    the test hermetic and focused on the reader logic.
    """
    svc = FeedbackLoopService()
    svc.state = state  # type: ignore[assignment]
    svc.bus = _FakeBus()  # type: ignore[assignment]
    return svc


def _make_trade(
    *,
    trade_id: str,
    symbol: str = "AAPL",
    net_pnl: str = "100",
    gross_pnl: str = "110",
    entry_ms: int = 1_700_000_000_000,
    exit_ms: int = 1_700_000_060_000,
    strategy_id: str = "default",
) -> TradeRecord:
    """Build a valid TradeRecord with safe defaults."""
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        direction=Direction.LONG,
        entry_timestamp_ms=entry_ms,
        exit_timestamp_ms=exit_ms,
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        size=Decimal("10"),
        gross_pnl=Decimal(gross_pnl),
        net_pnl=Decimal(net_pnl),
        commission=Decimal("1"),
        slippage_cost=Decimal("0.5"),
        strategy_id=strategy_id,
    )


async def _seed_via_writer(state: _FakeState, trades: list[TradeRecord]) -> None:
    """Populate ``trades:all`` through the real TradesWriter.

    Using the real writer guarantees the wire shape under test is exactly
    what production produces — immune to any divergence between a
    hand-rolled test dict and :meth:`TradeRecord.model_dump`.
    """
    writer = TradesWriter(state)  # type: ignore[arg-type]
    for trade in trades:
        await writer.record_trade(trade)


# ---------------------------------------------------------------------------
# Reader 1 — FeedbackLoopService._fast_analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_analysis_consumes_canonical_schema(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """Trades written via TradesWriter deserialize into TradeRecord without error,
    and Kelly stats are computed and hset for each symbol with enough trades."""
    # 6 AAPL trades (4 wins, 2 losses) → above the 5-trade minimum → Kelly stats hset.
    trades = [
        _make_trade(trade_id=f"T{i:03d}", symbol="AAPL", net_pnl="50" if i < 4 else "-30")
        for i in range(6)
    ]
    await _seed_via_writer(state, trades)

    await service._fast_analysis()

    # Kelly stats written for AAPL (only symbol with >= 5 trades).
    hset_keys = {name for name, _, _ in state.hset_calls}
    assert "kelly:AAPL" in hset_keys
    # Both win_rate and avg_rr fields written.
    aapl_fields = {field for name, field, _ in state.hset_calls if name == "kelly:AAPL"}
    assert aapl_fields == {"win_rate", "avg_rr"}


@pytest.mark.asyncio
async def test_fast_analysis_empty_trades_returns_early(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """Empty ``trades:all`` must not raise and must not emit Kelly stats."""
    await service._fast_analysis()
    assert state.hset_calls == []


@pytest.mark.asyncio
async def test_fast_analysis_window_is_bounded(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """``_fast_analysis`` reads only the most recent KELLY_ROLLING_WINDOW trades.

    LPUSH places newest at index 0, so ``lrange(0, WINDOW-1)`` returns the
    newest WINDOW trades. Trades pushed earlier than that are out-of-window.
    """
    # Write WINDOW + 5 trades; _fast_analysis should only see the last WINDOW.
    # Each trade has a unique net_pnl sign that we can use to verify which ones
    # were consumed — we mark the earliest 5 with a sentinel symbol that would
    # only appear in Kelly stats if they were read.
    early = [_make_trade(trade_id=f"EARLY{i}", symbol="OLD") for i in range(5)]
    recent = [_make_trade(trade_id=f"R{i:04d}", symbol="AAPL") for i in range(KELLY_ROLLING_WINDOW)]
    await _seed_via_writer(state, early + recent)

    await service._fast_analysis()

    hset_keys = {name for name, _, _ in state.hset_calls}
    assert "kelly:AAPL" in hset_keys
    # OLD symbol only has 5 trades and they are out of the window → no Kelly stats.
    assert "kelly:OLD" not in hset_keys


@pytest.mark.asyncio
async def test_fast_analysis_symbol_below_threshold_skipped(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """A symbol with fewer than 5 trades is skipped (not enough data for Kelly)."""
    trades = [_make_trade(trade_id=f"T{i}", symbol="AAPL") for i in range(4)]
    await _seed_via_writer(state, trades)

    await service._fast_analysis()

    hset_keys = {name for name, _, _ in state.hset_calls}
    assert "kelly:AAPL" not in hset_keys


# ---------------------------------------------------------------------------
# Reader 2 — FeedbackLoopService._slow_analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_analysis_consumes_canonical_schema(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """Trades written via TradesWriter deserialize successfully and feed both
    SignalQuality and TradeAnalyzer.

    Asserts ``feedback:signal_quality`` is written — this key is persisted
    before any downstream TradeAnalyzer call, so its presence proves the
    canonical-schema deserialization path succeeded (reader 2 survives the
    ``[TradeRecord(**t) for t in raw_trades]`` step). Also asserts
    ``feedback:attribution`` — written further down the same function via
    ``TradeAnalyzer.batch_analyze``. This second assertion was deferred in
    PR #256 because of the Decimal/float TypeError tracked as issue #258;
    that bug is now fixed (Sprint 5 Wave A) and the assertion is live.
    """
    trades = [_make_trade(trade_id=f"T{i:03d}") for i in range(10)]
    await _seed_via_writer(state, trades)

    await service._slow_analysis()

    set_keys = {key for key, _ in state.set_calls}
    assert "feedback:signal_quality" in set_keys

    # Payload must contain all four breakdown buckets — proves SignalQuality
    # received real TradeRecord objects (not empty/malformed input).
    quality_payload = next(val for key, val in state.set_calls if key == "feedback:signal_quality")
    assert set(quality_payload.keys()) == {"by_type", "by_regime", "by_session", "best_configs"}

    # #258 fix: TradeAnalyzer.batch_analyze now succeeds on real TradeRecord
    # objects, so feedback:attribution is reachable.
    assert "feedback:attribution" in set_keys
    attribution_payload = next(val for key, val in state.set_calls if key == "feedback:attribution")
    assert isinstance(attribution_payload, list)
    assert len(attribution_payload) > 0  # 5 trades seeded by fixture
    for entry in attribution_payload:
        assert isinstance(entry, dict)
        assert "r_multiple" in entry  # the field analyze() returns


@pytest.mark.asyncio
async def test_slow_analysis_empty_trades_returns_early(
    service: FeedbackLoopService,
    state: _FakeState,
) -> None:
    """Empty ``trades:all`` must not raise and must not write analytics keys."""
    await service._slow_analysis()
    assert state.set_calls == []


# ---------------------------------------------------------------------------
# Cross-reader: the deserialization round-trip itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_output_reconstructs_into_trade_record(
    state: _FakeState,
) -> None:
    """Direct round-trip: writer payload in → TradeRecord(**d) out == original trade.

    This is the foundational invariant every M1 classification rests on.
    Breaking it would break every reader simultaneously, so the test is
    intentionally independent of any specific reader's call site.
    """
    trade = _make_trade(trade_id="T001", strategy_id="har_rv")
    await _seed_via_writer(state, [trade])

    raw = await state.lrange("trades:all", 0, -1)
    assert len(raw) == 1
    reconstructed = TradeRecord(**raw[0])
    assert reconstructed == trade
