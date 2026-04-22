"""End-to-end pipeline test: S06 fill → PositionAggregator → S05 ContextLoader.

Phase A.9 (issue #199). Verifies the orphan-read fix closes the producer →
consumer loop:

1. S06 ExecutionService writes a per-symbol record under
   ``positions:{symbol}`` (we simulate the production
   ``services/execution/service.py:_on_filled`` shape directly).
2. :class:`services.feedback_loop.position_aggregator.PositionAggregator`
   scans the ``positions:*`` namespace and writes the aggregated list to
   ``portfolio:positions``.
3. :class:`services.risk_manager.context_loader.ContextLoader` (the S05
   pre-trade reader) consumes ``portfolio:positions`` via the same code
   path used in production and surfaces a ``list[Position]``.

The test uses a ``fakeredis`` backend wrapped in the
:class:`core.state.StateStore`-shaped adapter that production callers see;
mirrors the in-process integration approach used by
``tests/integration/test_circuit_breaker_integration.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio

from services.feedback_loop.position_aggregator import (
    AGGREGATE_KEY,
    PER_SYMBOL_KEY_PREFIX,
    PositionAggregator,
)
from services.risk_manager.context_loader import ContextLoader
from services.risk_manager.models import Position


class _StateAdapter:
    """Production-shaped ``StateStore`` substitute over ``fakeredis``.

    Implements the subset of :class:`core.state.StateStore` required by
    both producers (``set``) and the context loader (``get``) plus the
    ``client`` property used by the aggregator's ``scan_iter``. All
    payloads are JSON-encoded on the wire to mirror
    ``core/state.py:121``/``core/state.py:153``.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    @property
    def client(self) -> fakeredis.aioredis.FakeRedis:
        return self._redis

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value, default=str), ex=ttl)


@pytest_asyncio.fixture
async def state() -> AsyncIterator[_StateAdapter]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield _StateAdapter(client)
    finally:
        await client.flushall()
        await client.aclose()


def _s06_filled_record(
    symbol: str,
    *,
    direction: str = "LONG",
    entry: str = "100",
    size: str = "1",
) -> dict[str, Any]:
    """Reproduce the dict shape S06 writes in ``_on_filled``
    (``services/execution/service.py:153``)."""
    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "size": size,
        "stop_loss": "98",
        "target_scalp": "102",
        "target_swing": "105",
        "opened_at_ms": 1_700_000_000_000,
        "is_paper": True,
    }


async def _seed_pre_trade_context(state: _StateAdapter) -> None:
    """Populate the seven *other* pre-trade context keys so that
    :meth:`ContextLoader.load` does not raise on a sibling miss when we
    invoke it on the merged state. Aggregator-related assertions remain
    isolated to the ``portfolio:positions`` slot."""
    await state.set("portfolio:capital", {"available": "100000"})
    await state.set("pnl:daily", "0")
    await state.set("pnl:intraday_30m", "0")
    await state.set("macro:vix_current", "20.0")
    await state.set("macro:vix_1h_ago", "20.0")
    await state.set("correlation:matrix", {})
    await state.set("session:current", "unknown")


@pytest.mark.asyncio
async def test_orphan_read_closes_end_to_end(state: _StateAdapter) -> None:
    """Without the aggregator, S05 sees a missing key and rejects.

    With the aggregator running once, the same S05 read returns a
    populated ``list[Position]`` and the chain proceeds.
    """
    # 1. Producer side: simulate two S06 fills.
    await state.set(
        f"{PER_SYMBOL_KEY_PREFIX}AAPL", _s06_filled_record("AAPL", entry="150", size="2")
    )
    await state.set(
        f"{PER_SYMBOL_KEY_PREFIX}BTCUSDT",
        _s06_filled_record("BTCUSDT", entry="50000", size="0.5"),
    )

    # 2. Confirm the orphan read still fails before snapshot:
    raw_before = await state.get(AGGREGATE_KEY)
    assert raw_before is None  # nobody has written the aggregate yet

    # 3. Aggregator runs once.
    aggregator = PositionAggregator(state)
    count = await aggregator.snapshot_to_redis()
    assert count == 2

    # 4. Confirm the aggregate is now present and Position-model shaped.
    raw_after = await state.get(AGGREGATE_KEY)
    assert isinstance(raw_after, list)
    assert len(raw_after) == 2

    # 5. Now seed the seven sibling keys and run the *real* ContextLoader.
    await _seed_pre_trade_context(state)
    loader = ContextLoader(state)
    ctx = await loader.load(symbol="AAPL")
    positions = ctx["positions"]
    assert isinstance(positions, list)
    assert all(isinstance(p, Position) for p in positions)
    by_sym = {p.symbol: p for p in positions}
    assert set(by_sym.keys()) == {"AAPL", "BTCUSDT"}
    assert by_sym["AAPL"].size == Decimal("2")
    assert by_sym["AAPL"].entry_price == Decimal("150")
    assert by_sym["BTCUSDT"].size == Decimal("0.5")
    assert by_sym["BTCUSDT"].entry_price == Decimal("50000")
    assert by_sym["BTCUSDT"].asset_class == "crypto"
    assert by_sym["AAPL"].asset_class == "equity"


@pytest.mark.asyncio
async def test_empty_book_pipeline(state: _StateAdapter) -> None:
    """A flat book emits an empty list — S05 ContextLoader must accept this
    rather than rejecting on missing-key. This is the load-bearing
    fail-closed contract that makes the snapshot-to-empty-list call in
    :meth:`PositionAggregator.snapshot_to_redis` non-trivial."""
    aggregator = PositionAggregator(state)
    await aggregator.snapshot_to_redis()
    await _seed_pre_trade_context(state)

    loader = ContextLoader(state)
    ctx = await loader.load(symbol="AAPL")
    assert ctx["positions"] == []


@pytest.mark.asyncio
async def test_position_close_propagates_through_aggregator(state: _StateAdapter) -> None:
    """When S06 deletes a per-symbol record (position closed), the next
    aggregator snapshot drops it from the aggregate."""
    # Open AAPL.
    await state.set(f"{PER_SYMBOL_KEY_PREFIX}AAPL", _s06_filled_record("AAPL", size="2"))
    aggregator = PositionAggregator(state)
    await aggregator.snapshot_to_redis()
    raw = await state.get(AGGREGATE_KEY)
    assert isinstance(raw, list)
    assert len(raw) == 1

    # Close AAPL: S06 would delete the per-symbol key on a flat exit.
    await state.client.delete(f"{PER_SYMBOL_KEY_PREFIX}AAPL")
    await aggregator.snapshot_to_redis()
    raw_after = await state.get(AGGREGATE_KEY)
    assert raw_after == []
