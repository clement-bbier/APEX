"""Regression tests: S10 command_api ``trades:all`` readers consume the canonical schema.

Phase A.12.2 (issue #238). Locks in the reader contract established by
PR #253 (TradesWriter) for the two readers in
:mod:`services.command_center.command_api`:

- :func:`get_pnl` — ``/api/v1/pnl`` — reads ``net_pnl`` and ``exit_timestamp_ms``
  from each dict to compute realized PnL, win rate, and daily trade count.
- :func:`get_performance` — ``/api/v1/performance`` — reads the full list
  and reports ``len(trades)`` as ``total_trades``.

Both are CASE M1 per ``docs/audits/TRADES_READERS_MIGRATION_2026-04-23.md``:
the deserialized dicts from :meth:`StateStore.lrange` already carry the
field names and shapes produced by :meth:`TradeRecord.model_dump(mode="json")`.
No code change was needed; these tests guard the coincidence.
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
from services.command_center.command_api import get_performance, get_pnl
from services.feedback_loop.trades_writer import TradesWriter

# ---------------------------------------------------------------------------
# Fakes matching the StateStore surface the two readers use
# ---------------------------------------------------------------------------


class _FakeStateStore:
    """Minimal StateStore-shaped adapter over fakeredis.

    :func:`get_pnl` calls ``lrange`` (for trades + equity_curve) and ``get``
    (for tick + circuit-breaker snapshot). :func:`get_performance` calls
    ``lrange`` + ``get``. We implement those plus ``lpush``/``ltrim``/``set``
    so the :class:`TradesWriter` fixture can populate the legacy key via
    the real writer path.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    @property
    def client(self) -> fakeredis.aioredis.FakeRedis:
        return self._redis

    async def get(self, key: str) -> Any:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value, default=str))

    async def lpush(self, key: str, *values: Any) -> None:
        encoded = [json.dumps(v, default=str) for v in values]
        await self._redis.lpush(key, *encoded)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        raw = await self._redis.lrange(key, start, end)
        return [json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in raw]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        await self._redis.ltrim(key, start, end)


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


def _today_exit_ms(hour: int = 12) -> int:
    """Return an exit_timestamp_ms anchored at today ``hour``:00 UTC."""
    today_start = int(time.time() // 86400 * 86400)
    return (today_start + hour * 3600) * 1000


def _yesterday_exit_ms() -> int:
    today_start = int(time.time() // 86400 * 86400)
    return (today_start - 43200) * 1000


def _make_trade(
    *,
    trade_id: str,
    net_pnl: str = "100",
    gross_pnl: str = "110",
    exit_ms: int | None = None,
    strategy_id: str = "default",
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
        strategy_id=strategy_id,
    )


async def _seed_via_writer(
    state: _FakeStateStore,
    trades: list[TradeRecord],
) -> None:
    writer = TradesWriter(state)  # type: ignore[arg-type]
    for trade in trades:
        await writer.record_trade(trade)


# ---------------------------------------------------------------------------
# Reader 3 — get_pnl (/api/v1/pnl)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pnl_consumes_canonical_schema(
    state: _FakeStateStore,
) -> None:
    """Trades written via TradesWriter produce a populated PnLSummary."""
    trades = [
        _make_trade(trade_id=f"T{i}", net_pnl="50", exit_ms=_today_exit_ms(9 + i)) for i in range(3)
    ]
    await _seed_via_writer(state, trades)

    result = await get_pnl(state)  # type: ignore[arg-type]

    assert result.trade_count_today == 3
    # realized_today is formatted as currency string "$150.00".
    assert "150" in result.realized_today
    # All three are winners (net_pnl=50) → rolling win rate should be 1.0.
    assert result.win_rate_rolling == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_get_pnl_filters_yesterday_trades(
    state: _FakeStateStore,
) -> None:
    """Trades with yesterday's exit_timestamp_ms are excluded from realized_today."""
    today_trade = _make_trade(trade_id="T_today", net_pnl="100", exit_ms=_today_exit_ms(10))
    yday_trade = _make_trade(trade_id="T_yday", net_pnl="999", exit_ms=_yesterday_exit_ms())
    await _seed_via_writer(state, [yday_trade, today_trade])

    result = await get_pnl(state)  # type: ignore[arg-type]

    assert result.trade_count_today == 1
    # Only the today trade ($100) contributes to realized.
    assert "100" in result.realized_today
    assert "999" not in result.realized_today


@pytest.mark.asyncio
async def test_get_pnl_empty_trades_returns_zeros(
    state: _FakeStateStore,
) -> None:
    """No trades → summary fields default to zero without raising."""
    result = await get_pnl(state)  # type: ignore[arg-type]

    assert result.trade_count_today == 0
    assert result.win_rate_rolling == 0.0


# ---------------------------------------------------------------------------
# Reader 4 — get_performance (/api/v1/performance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_performance_counts_canonical_trades(
    state: _FakeStateStore,
) -> None:
    """``total_trades`` equals the number of entries the writer pushed."""
    trades = [_make_trade(trade_id=f"T{i:03d}") for i in range(7)]
    await _seed_via_writer(state, trades)

    result = await get_performance(state)  # type: ignore[arg-type]

    assert result.total_trades == 7


@pytest.mark.asyncio
async def test_get_performance_empty_trades(
    state: _FakeStateStore,
) -> None:
    """No trades → ``total_trades == 0`` and no exception."""
    result = await get_performance(state)  # type: ignore[arg-type]
    assert result.total_trades == 0
