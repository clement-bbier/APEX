"""Regression tests: S10 PnLTracker ``trades:all`` readers consume the canonical schema.

Phase A.12.2 (issue #238). Locks in the reader contract established by
PR #253 (TradesWriter) for the two readers in
:mod:`services.command_center.pnl_tracker`:

- :meth:`PnLTracker.get_realized_pnl` — sums ``net_pnl`` over every trade dict.
- :meth:`PnLTracker.get_daily_pnl` — sums ``net_pnl`` over trades whose
  ``exit_timestamp_ms`` is >= today's midnight UTC.

Both are CASE M1 per ``docs/audits/TRADES_READERS_MIGRATION_2026-04-23.md``:
``Decimal(str(trade.get("net_pnl", 0)))`` correctly reconstructs a
:class:`Decimal` from either the string (``"100.50"``) or numeric
(``100.5``) shapes that :meth:`TradeRecord.model_dump` may emit.

The fixture seeds Redis via the **real** :class:`TradesWriter` so the wire
shape under test is exactly what production produces.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.command_center.pnl_tracker import PnLTracker
from services.feedback_loop.trades_writer import TradesWriter

# ---------------------------------------------------------------------------
# Fakes matching the StateStore surface PnLTracker uses
# ---------------------------------------------------------------------------


class _FakeStateStore:
    """Minimal StateStore-shaped adapter over fakeredis.

    Implements ``lpush``/``ltrim``/``lrange`` for the list-backed trade
    log, plus ``get``/``set`` which aren't needed by the readers under
    test but are required by :class:`TradesWriter` if it were to log.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    async def lpush(self, key: str, *values: Any) -> None:
        encoded = [json.dumps(v, default=str) for v in values]
        await self._redis.lpush(key, *encoded)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        raw = await self._redis.lrange(key, start, end)
        return [json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in raw]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        await self._redis.ltrim(key, start, end)

    async def get(self, key: str) -> Any:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value, default=str))


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(redis_client: fakeredis.aioredis.FakeRedis) -> _FakeStateStore:
    return _FakeStateStore(redis_client)


@pytest.fixture
def tracker() -> PnLTracker:
    return PnLTracker()


def _today_exit_ms(hour: int = 12) -> int:
    today_start = int(time.time() // 86400 * 86400)
    return (today_start + hour * 3600) * 1000


def _days_ago_exit_ms(days: int) -> int:
    today_start = int(time.time() // 86400 * 86400)
    return (today_start - days * 86400 + 43200) * 1000


def _make_trade(
    *,
    trade_id: str,
    net_pnl: str = "100",
    gross_pnl: str = "110",
    exit_ms: int | None = None,
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        symbol="AAPL",
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
    )


async def _seed_via_writer(state: _FakeStateStore, trades: list[TradeRecord]) -> None:
    writer = TradesWriter(state)  # type: ignore[arg-type]
    for trade in trades:
        await writer.record_trade(trade)


# ---------------------------------------------------------------------------
# Reader 5 — PnLTracker.get_realized_pnl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_realized_pnl_consumes_canonical_schema(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    """Sum over canonical-shape trades matches Σ net_pnl exactly (Decimal)."""
    trades = [
        _make_trade(trade_id="T001", net_pnl="100.50"),
        _make_trade(trade_id="T002", net_pnl="-25.25"),
        _make_trade(trade_id="T003", net_pnl="200.00"),
    ]
    await _seed_via_writer(state, trades)

    result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]

    assert result == Decimal("275.25")


@pytest.mark.asyncio
async def test_get_realized_pnl_preserves_decimal_precision(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    """``TradeRecord.model_dump`` stringifies Decimals → no float rounding."""
    trades = [
        _make_trade(trade_id="T001", net_pnl="0.0000001"),
        _make_trade(trade_id="T002", net_pnl="0.0000002"),
    ]
    await _seed_via_writer(state, trades)

    result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]

    assert result == Decimal("0.0000003")


@pytest.mark.asyncio
async def test_get_realized_pnl_empty_returns_zero(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
    assert result == Decimal("0")


# ---------------------------------------------------------------------------
# Reader 6 — PnLTracker.get_daily_pnl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_daily_pnl_consumes_canonical_schema(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    """Only trades with ``exit_timestamp_ms`` >= today midnight are summed."""
    trades = [
        _make_trade(trade_id="T_today_1", net_pnl="10", exit_ms=_today_exit_ms(9)),
        _make_trade(trade_id="T_today_2", net_pnl="20", exit_ms=_today_exit_ms(14)),
        _make_trade(trade_id="T_yday", net_pnl="999", exit_ms=_days_ago_exit_ms(1)),
    ]
    await _seed_via_writer(state, trades)

    result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]

    assert result == Decimal("30")


@pytest.mark.asyncio
async def test_get_daily_pnl_exact_midnight_boundary_included(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    """A trade at exactly today 00:00:00 UTC is included (``>=`` boundary)."""
    today_midnight = int(time.time() // 86400 * 86400 * 1000)
    trade = _make_trade(trade_id="T_boundary", net_pnl="42", exit_ms=today_midnight)
    await _seed_via_writer(state, [trade])

    result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]

    assert result == Decimal("42")


@pytest.mark.asyncio
async def test_get_daily_pnl_empty_returns_zero(
    tracker: PnLTracker,
    state: _FakeStateStore,
) -> None:
    result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
    assert result == Decimal("0")
