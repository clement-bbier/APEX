"""Unit tests for :mod:`services.command_center.pnl_tracker`.

Coverage mission: 14% → 85%+ (Sprint 4 Vague 2, Agent C).
Prerequisite for #203 coverage gate raise 75→85%.

The command_center PnLTracker is the **reporting** variant (loose SLA, read
from ``trades:all`` / ``positions:*`` / ``equity_curve``). Not to be confused
with :class:`services.risk_manager.pnl_tracker.PnLTracker` which is the
**pre-trade strict SLA** variant (Millennium-pod pattern, Sprint 3B PR #214).

Tests are organized by method under test. Each public method is covered by
happy-path, edge-case, and error-path scenarios. A dedicated Hypothesis
property-test block verifies the PnL sign/direction invariant and currency-
safe Decimal arithmetic invariants.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from services.command_center.pnl_tracker import PnLTracker

# ---------------------------------------------------------------------------
# Fixtures — fakeredis-backed StateStore-shaped adapter
# ---------------------------------------------------------------------------


class _FakeStateStore:
    """Minimal StateStore-shaped adapter over fakeredis.

    Implements the four async methods used by :class:`PnLTracker`:
    :meth:`get`, :meth:`lrange`, :meth:`lpush`, :meth:`ltrim`. Values are
    JSON-encoded on write and JSON-decoded on read — mirroring
    :class:`core.state.StateStore` semantics.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    async def get(self, key: str) -> Any:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any) -> None:
        await self._redis.set(key, json.dumps(value, default=str))

    async def lpush(self, key: str, *values: Any) -> None:
        serialized = [json.dumps(v, default=str) for v in values]
        await self._redis.lpush(key, *serialized)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        raw = await self._redis.lrange(key, start, end)
        return [json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in raw]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        await self._redis.ltrim(key, start, end)


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Fresh fakeredis client per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> _FakeStateStore:
    return _FakeStateStore(redis_client)


@pytest.fixture
def tracker() -> PnLTracker:
    return PnLTracker()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms_today_at(hour: int = 12) -> int:
    """Return an epoch-ms timestamp anchored at today ``hour``:00 UTC."""
    today_start = int(time.time() // 86400 * 86400)
    return (today_start + hour * 3600) * 1000


def _ms_days_ago(days: int) -> int:
    """Return an epoch-ms timestamp anchored ``days`` ago at noon UTC."""
    today_start = int(time.time() // 86400 * 86400)
    return (today_start - days * 86400 + 43200) * 1000


async def _seed_trades(
    state: _FakeStateStore,
    trades: list[Any],
) -> None:
    """Push trade records onto ``trades:all`` in insertion order."""
    for trade in trades:
        await state.lpush("trades:all", trade)


# ---------------------------------------------------------------------------
# TestInit — instantiation is trivial, but belongs here for completeness
# ---------------------------------------------------------------------------


class TestInit:
    """``PnLTracker`` takes no constructor args and is stateless."""

    def test_instantiation_takes_no_args(self) -> None:
        tracker = PnLTracker()
        assert isinstance(tracker, PnLTracker)

    def test_multiple_instances_are_independent(self) -> None:
        t1 = PnLTracker()
        t2 = PnLTracker()
        assert t1 is not t2


# ---------------------------------------------------------------------------
# TestGetRealizedPnL — sum of net_pnl from trades:all
# ---------------------------------------------------------------------------


class TestGetRealizedPnL:
    """``get_realized_pnl`` sums ``net_pnl`` across all trades."""

    async def test_empty_trades_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("0")

    async def test_single_positive_trade(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(state, [{"net_pnl": "100.50"}])
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("100.50")

    async def test_single_negative_trade(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(state, [{"net_pnl": "-75.25"}])
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("-75.25")

    async def test_sums_multiple_trades(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                {"net_pnl": "10.00"},
                {"net_pnl": "-5.50"},
                {"net_pnl": "20.75"},
                {"net_pnl": "0.25"},
            ],
        )
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("25.50")

    async def test_non_dict_entries_are_ignored(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                {"net_pnl": "10.00"},
                "garbage-string",
                42,
                None,
                {"net_pnl": "5.00"},
            ],
        )
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("15.00")

    async def test_missing_net_pnl_field_defaults_to_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [{"net_pnl": "10.00"}, {"other_field": "999"}, {"net_pnl": "5.00"}],
        )
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("15.00")

    async def test_numeric_net_pnl_also_accepted(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """net_pnl may arrive as int/float after JSON decode — Decimal(str(x)) works."""
        await _seed_trades(state, [{"net_pnl": 12}, {"net_pnl": 3.5}])
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("15.5")

    async def test_preserves_decimal_precision(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [{"net_pnl": "0.0000001"}, {"net_pnl": "0.0000002"}],
        )
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("0.0000003")

    async def test_returns_decimal_type(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(state, [{"net_pnl": "1.00"}])
        result = await tracker.get_realized_pnl(state)  # type: ignore[arg-type]
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# TestGetUnrealizedPnL — mark-to-market of open positions
# ---------------------------------------------------------------------------


class TestGetUnrealizedPnL:
    """``get_unrealized_pnl`` values each open position vs current price."""

    async def test_empty_prices_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        result = await tracker.get_unrealized_pnl(state, {})  # type: ignore[arg-type]
        assert result == Decimal("0")

    async def test_no_open_positions_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("150.00")},
        )
        assert result == Decimal("0")

    async def test_long_position_price_up_is_positive(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("120")},
        )
        assert result == Decimal("200")

    async def test_long_position_price_down_is_negative(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("90")},
        )
        assert result == Decimal("-100")

    async def test_short_position_price_up_is_negative(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "short"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("120")},
        )
        assert result == Decimal("-200")

    async def test_short_position_price_down_is_positive(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "short"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("80")},
        )
        assert result == Decimal("200")

    async def test_direction_defaults_to_long_when_missing(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10"},  # direction omitted
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110")},
        )
        assert result == Decimal("100")

    async def test_zero_entry_price_skips_position(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "0", "size": "10", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("100")},
        )
        assert result == Decimal("0")

    async def test_zero_size_skips_position(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "0", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110")},
        )
        assert result == Decimal("0")

    async def test_non_dict_position_is_skipped(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set("positions:AAPL", "corrupted-string-value")
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110")},
        )
        assert result == Decimal("0")

    async def test_missing_entry_price_field_skips(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"size": "10", "direction": "long"},  # entry_price omitted
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110")},
        )
        assert result == Decimal("0")

    async def test_multiple_positions_summed(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "long"},
        )
        await state.set(
            "positions:TSLA",
            {"entry_price": "200", "size": "5", "direction": "short"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110"), "TSLA": Decimal("180")},
        )
        # AAPL long: (110-100)*10 = +100
        # TSLA short: -(180-200)*5 = +100
        assert result == Decimal("200")

    async def test_missing_position_key_skipped(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """Only AAPL is set; TSLA price has no position → skipped without error."""
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("110"), "TSLA": Decimal("500")},
        )
        assert result == Decimal("100")

    async def test_returns_decimal_type(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.set(
            "positions:AAPL",
            {"entry_price": "100", "size": "10", "direction": "long"},
        )
        result = await tracker.get_unrealized_pnl(
            state,  # type: ignore[arg-type]
            {"AAPL": Decimal("105")},
        )
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# TestGetDailyPnL — sum of net_pnl for trades closed today
# ---------------------------------------------------------------------------


class TestGetDailyPnL:
    """``get_daily_pnl`` filters ``trades:all`` by today's midnight UTC."""

    async def test_empty_trades_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("0")

    async def test_only_today_trades_included(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                {"exit_timestamp_ms": _ms_today_at(9), "net_pnl": "10.00"},
                {"exit_timestamp_ms": _ms_today_at(14), "net_pnl": "20.00"},
            ],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("30.00")

    async def test_yesterday_trades_excluded(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                {"exit_timestamp_ms": _ms_days_ago(1), "net_pnl": "100.00"},
                {"exit_timestamp_ms": _ms_today_at(10), "net_pnl": "5.00"},
            ],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("5.00")

    async def test_missing_exit_timestamp_excluded(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """Missing ``exit_timestamp_ms`` defaults to 0 → below today_start → excluded."""
        await _seed_trades(
            state,
            [
                {"net_pnl": "99.99"},  # no timestamp
                {"exit_timestamp_ms": _ms_today_at(8), "net_pnl": "1.00"},
            ],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("1.00")

    async def test_non_dict_entries_ignored(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                "corrupt",
                {"exit_timestamp_ms": _ms_today_at(11), "net_pnl": "3.00"},
                None,
                42,
            ],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("3.00")

    async def test_mixed_past_and_today_trades(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [
                {"exit_timestamp_ms": _ms_days_ago(10), "net_pnl": "1000"},
                {"exit_timestamp_ms": _ms_days_ago(1), "net_pnl": "500"},
                {"exit_timestamp_ms": _ms_today_at(3), "net_pnl": "5"},
                {"exit_timestamp_ms": _ms_today_at(20), "net_pnl": "-2"},
            ],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("3")

    async def test_exact_midnight_boundary_included(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """A trade at exactly today 00:00:00 UTC ms is included (``>=`` boundary)."""
        today_midnight = int(time.time() // 86400 * 86400 * 1000)
        await _seed_trades(
            state,
            [{"exit_timestamp_ms": today_midnight, "net_pnl": "42"}],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("42")

    async def test_just_before_midnight_excluded(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        today_midnight = int(time.time() // 86400 * 86400 * 1000)
        await _seed_trades(
            state,
            [{"exit_timestamp_ms": today_midnight - 1, "net_pnl": "42"}],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert result == Decimal("0")

    async def test_returns_decimal_type(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await _seed_trades(
            state,
            [{"exit_timestamp_ms": _ms_today_at(12), "net_pnl": "1.00"}],
        )
        result = await tracker.get_daily_pnl(state)  # type: ignore[arg-type]
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# TestGetMaxDrawdown — DD fraction over the equity_curve list
# ---------------------------------------------------------------------------


class TestGetMaxDrawdown:
    """``get_max_drawdown`` walks the equity curve and returns the worst DD."""

    async def test_empty_curve_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == 0.0

    async def test_single_point_returns_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await state.lpush("equity_curve", {"equity": "10000"})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == 0.0

    async def test_monotonically_increasing_curve_no_drawdown(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        # LPUSH prepends, so push in reverse to get ascending lrange order.
        for equity in [13000, 12000, 11000, 10000]:
            await state.lpush("equity_curve", {"equity": str(equity)})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == 0.0

    async def test_peak_then_drop_returns_fraction(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        # Insert order matters: lpush prepends → newest first.
        # lrange returns in newest-to-oldest order, but the algorithm iterates
        # through values as provided. Seed so that the returned list has the
        # observed chronology we want.
        # Use set directly via raw push, then rely on the curve order.
        # We lpush in reverse so lrange(0,-1) gives oldest→newest.
        for equity in [12000, 11000, 10000]:  # lpushed last-to-first
            await state.lpush("equity_curve", {"equity": str(equity)})
        # lrange will now return [10000, 11000, 12000] - oldest first given LPUSH semantics
        # Actually LPUSH prepends: after lpush(12000), lpush(11000), lpush(10000)
        # LRANGE(0,-1) returns [10000, 11000, 12000] - newest-pushed first.
        # Algorithm sees peak=10000 → 11000 (new peak) → 12000 (new peak). No DD.
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == 0.0

    async def test_drawdown_computed_from_peak(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        # Seed so lrange returns [10000, 12000, 9000]: peak=12000, trough=9000
        # Max DD = (12000-9000)/12000 = 0.25
        for equity in [9000, 12000, 10000]:  # lpushed last→first
            await state.lpush("equity_curve", {"equity": str(equity)})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == pytest.approx(0.25)

    async def test_raw_float_entries_supported(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """If the curve contains raw scalars (not dicts), ``float(e)`` is used."""
        for equity in [9000.0, 12000.0, 10000.0]:
            await state.lpush("equity_curve", equity)
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == pytest.approx(0.25)

    async def test_missing_equity_field_treated_as_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """Dict entries without ``equity`` key use the ``.get("equity", 0)`` default."""
        for entry in [{"foo": "bar"}, {"equity": "100"}]:  # lpushed last→first
            await state.lpush("equity_curve", entry)
        # lrange order: [{equity:100}, {foo:bar}] → peak=100, then 0 → DD=1.0
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == pytest.approx(1.0)

    async def test_returns_float_type(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        for equity in [1000, 900]:
            await state.lpush("equity_curve", {"equity": str(equity)})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert isinstance(result, float)

    async def test_multiple_peaks_returns_largest_dd(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        # Desired lrange chronology: [10000, 15000, 12000, 20000, 14000]
        # Walk: peak=10k → 15k (peak) → 12k (dd=0.2) → 20k (peak) → 14k (dd=0.3)
        # Max DD = 0.3
        for equity in [14000, 20000, 12000, 15000, 10000]:  # lpushed last→first
            await state.lpush("equity_curve", {"equity": str(equity)})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == pytest.approx(0.3)

    async def test_peak_guard_when_equity_starts_at_zero(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """If the leading peak is 0, the ``peak > 0`` guard prevents div-by-zero."""
        # Desired lrange: [0, 100, 50] → peak starts 0 (no DD computed),
        # then becomes 100 (new peak), then 50 → dd=0.5
        for equity in [50, 100, 0]:  # lpushed last→first
            await state.lpush("equity_curve", {"equity": str(equity)})
        result = await tracker.get_max_drawdown(state)  # type: ignore[arg-type]
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# TestUpdateEquityCurve — append + trim
# ---------------------------------------------------------------------------


class TestUpdateEquityCurve:
    """``update_equity_curve`` appends and trims the rolling equity list."""

    async def test_single_append_stores_entry(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        await tracker.update_equity_curve(state, Decimal("10000.50"))  # type: ignore[arg-type]
        curve = await state.lrange("equity_curve", 0, -1)
        assert len(curve) == 1
        assert curve[0]["equity"] == "10000.50"
        assert "timestamp_ms" in curve[0]
        assert isinstance(curve[0]["timestamp_ms"], int)

    async def test_timestamp_ms_is_recent(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        before = int(time.time() * 1000)
        await tracker.update_equity_curve(state, Decimal("1"))  # type: ignore[arg-type]
        after = int(time.time() * 1000)
        curve = await state.lrange("equity_curve", 0, -1)
        assert before <= curve[0]["timestamp_ms"] <= after

    async def test_equity_serialized_as_string(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """Decimal is stored via ``str(equity)`` to preserve precision."""
        await tracker.update_equity_curve(
            state,  # type: ignore[arg-type]
            Decimal("12345.6789012345"),
        )
        curve = await state.lrange("equity_curve", 0, -1)
        assert curve[0]["equity"] == "12345.6789012345"

    async def test_multiple_appends_accumulate(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        for i in range(5):
            await tracker.update_equity_curve(state, Decimal(str(i)))  # type: ignore[arg-type]
        curve = await state.lrange("equity_curve", 0, -1)
        assert len(curve) == 5

    async def test_trim_caps_list_at_10k(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        """``update_equity_curve`` calls ``ltrim(0, 9999)``; fake-redis honors it."""
        mock_state = AsyncMock()
        await PnLTracker().update_equity_curve(mock_state, Decimal("1"))
        mock_state.lpush.assert_awaited_once()
        mock_state.ltrim.assert_awaited_once_with("equity_curve", 0, 9999)

    async def test_push_target_is_equity_curve_key(
        self,
        tracker: PnLTracker,
        state: _FakeStateStore,
    ) -> None:
        mock_state = AsyncMock()
        await PnLTracker().update_equity_curve(mock_state, Decimal("42"))
        first_call_args = mock_state.lpush.call_args
        assert first_call_args.args[0] == "equity_curve"
        assert first_call_args.args[1]["equity"] == "42"


# ---------------------------------------------------------------------------
# TestPropertyInvariants — Hypothesis
# ---------------------------------------------------------------------------


_decimal_price = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_decimal_size = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


class TestPropertyInvariants:
    """Hypothesis property tests for the PnL contract."""

    @given(entry=_decimal_price, exit_price=_decimal_price, size=_decimal_size)
    @hyp_settings(max_examples=200, deadline=None)
    def test_long_pnl_sign_matches_direction(
        self,
        entry: Decimal,
        exit_price: Decimal,
        size: Decimal,
    ) -> None:
        """Long: sign(pnl) == sign(exit - entry)."""
        pnl = (exit_price - entry) * size
        if exit_price > entry:
            assert pnl > 0
        elif exit_price < entry:
            assert pnl < 0
        else:
            assert pnl == 0

    @given(entry=_decimal_price, exit_price=_decimal_price, size=_decimal_size)
    @hyp_settings(max_examples=200, deadline=None)
    def test_short_pnl_sign_is_inverted(
        self,
        entry: Decimal,
        exit_price: Decimal,
        size: Decimal,
    ) -> None:
        """Short: sign(pnl) == -sign(exit - entry)."""
        pnl = (exit_price - entry) * size
        short_pnl = -pnl
        if exit_price > entry:
            assert short_pnl <= 0
        elif exit_price < entry:
            assert short_pnl >= 0

    @given(entry=_decimal_price, size=_decimal_size)
    @hyp_settings(max_examples=100, deadline=None)
    async def test_unrealized_pnl_at_entry_is_zero(
        self,
        entry: Decimal,
        size: Decimal,
    ) -> None:
        """Mark-to-market at the entry price yields exactly zero PnL."""
        redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            state = _FakeStateStore(redis)
            await state.set(
                "positions:SYM",
                {
                    "entry_price": str(entry),
                    "size": str(size),
                    "direction": "long",
                },
            )
            result = await PnLTracker().get_unrealized_pnl(
                state,  # type: ignore[arg-type]
                {"SYM": entry},
            )
            assert result == Decimal("0")
        finally:
            await redis.flushall()
            await redis.aclose()

    @given(
        pnls=st.lists(
            st.decimals(
                min_value=Decimal("-10000"),
                max_value=Decimal("10000"),
                places=4,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=0,
            max_size=50,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    async def test_realized_pnl_equals_sum_of_inputs(
        self,
        pnls: list[Decimal],
    ) -> None:
        """``get_realized_pnl`` returns exactly ``Σ net_pnl`` with no rounding loss."""
        redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            state = _FakeStateStore(redis)
            for pnl in pnls:
                await state.lpush("trades:all", {"net_pnl": str(pnl)})
            result = await PnLTracker().get_realized_pnl(state)  # type: ignore[arg-type]
            expected = sum((Decimal(str(p)) for p in pnls), Decimal("0"))
            assert result == expected
        finally:
            await redis.flushall()
            await redis.aclose()

    @given(
        equities=st.lists(
            st.floats(
                min_value=1.0,
                max_value=1_000_000.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=2,
            max_size=50,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    async def test_max_drawdown_is_bounded(
        self,
        equities: list[float],
    ) -> None:
        """Max drawdown is always in [0, 1] for a strictly positive curve."""
        redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            state = _FakeStateStore(redis)
            for eq in equities:
                await state.lpush("equity_curve", {"equity": str(eq)})
            result = await PnLTracker().get_max_drawdown(state)  # type: ignore[arg-type]
            assert 0.0 <= result <= 1.0
        finally:
            await redis.flushall()
            await redis.aclose()
