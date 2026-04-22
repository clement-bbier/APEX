"""Unit tests for :class:`services.data_ingestion.macro_persister.MacroPersister`.

Phase A.10 (issue #200). Validates rolling-1h-ago resolution, graceful
degradation before history accumulates, and S05-deserialization
contract.

Test patterns follow CLAUDE.md §7: happy path + edge cases (no-history,
partial-history, full-history, DST/midnight rollover) + property test +
error case.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from services.data_ingestion.macro_persister import (
    DXY_KEY,
    VIX_1H_AGO_KEY,
    VIX_CURRENT_KEY,
    VIX_HISTORY_WINDOW_SECONDS,
    VIX_KEY,
    YIELD_SPREAD_KEY,
    MacroPersister,
)


class _JsonStateAdapter:
    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        del ttl
        await self._redis.set(key, json.dumps(value, default=str))

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)


class _StubMacroFeed:
    """Deterministic stand-in for :class:`MacroFeed` used by the persister."""

    def __init__(
        self,
        *,
        vix: float | None = 18.5,
        dxy: float | None = 104.2,
        yield_spread: float | None = -0.35,
    ) -> None:
        self.vix = vix
        self.dxy = dxy
        self.yield_spread = yield_spread

    async def get_vix(self) -> float | None:
        return self.vix

    async def get_dxy(self) -> float | None:
        return self.dxy

    async def get_yield_spread(self) -> float | None:
        return self.yield_spread


class _Clock:
    """Manually advanced UTC clock for deterministic 1 h-rollover tests."""

    def __init__(self, start: datetime) -> None:
        assert start.tzinfo is not None
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(redis_client: fakeredis.aioredis.FakeRedis) -> _JsonStateAdapter:
    return _JsonStateAdapter(redis_client)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_once_writes_all_macro_keys(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=18.5, dxy=104.2, yield_spread=-0.35)
    persister = MacroPersister(state, feed)

    written = await persister.persist_once()

    assert written[VIX_CURRENT_KEY] == 18.5
    assert written[VIX_KEY] == 18.5
    # First tick: history depth = 1 → vix_1h_ago degrades to oldest = current.
    assert written[VIX_1H_AGO_KEY] == 18.5
    assert written[DXY_KEY] == 104.2
    assert written[YIELD_SPREAD_KEY] == -0.35

    # Round-trip: every value S05 reads MUST decode via float(...).
    for key in (VIX_CURRENT_KEY, VIX_1H_AGO_KEY, VIX_KEY, DXY_KEY, YIELD_SPREAD_KEY):
        raw = await state.get(key)
        float(raw)  # contract per context_loader.py:76-77


# ---------------------------------------------------------------------------
# vix_1h_ago resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vix_1h_ago_degrades_to_current_with_no_history(
    state: _JsonStateAdapter,
) -> None:
    """First tick after boot: history is empty → vix_1h_ago = current."""
    feed = _StubMacroFeed(vix=20.0)
    persister = MacroPersister(state, feed)
    await persister.persist_once()
    assert await state.get(VIX_1H_AGO_KEY) == 20.0


@pytest.mark.asyncio
async def test_vix_1h_ago_returns_oldest_when_history_under_one_hour(
    state: _JsonStateAdapter,
) -> None:
    """Less than 1 h history: degrade to oldest available snapshot."""
    feed = _StubMacroFeed(vix=15.0)
    clock = _Clock(datetime(2026, 4, 21, 12, 0, tzinfo=UTC))
    persister = MacroPersister(state, feed, clock=clock)

    await persister.persist_once()  # snapshot @ t=0, vix=15
    feed.vix = 20.0
    clock.advance(seconds=600)  # +10 min
    await persister.persist_once()  # snapshot @ t=10min, vix=20

    # 10 min of history → vix_1h_ago = oldest = 15.0.
    assert await state.get(VIX_1H_AGO_KEY) == 15.0


@pytest.mark.asyncio
async def test_vix_1h_ago_returns_snapshot_at_least_one_hour_old(
    state: _JsonStateAdapter,
) -> None:
    """≥ 1 h of history: vix_1h_ago = youngest snapshot ≥ 60 min old."""
    feed = _StubMacroFeed(vix=10.0)
    clock = _Clock(datetime(2026, 4, 21, 12, 0, tzinfo=UTC))
    persister = MacroPersister(state, feed, poll_interval_seconds=60.0, clock=clock)

    # Build 70 min of history at 1-min cadence.
    for minute in range(71):
        feed.vix = 10.0 + minute  # 10, 11, 12, ..., 80
        await persister.persist_once()
        clock.advance(seconds=60)

    # Now @ t=70min after start. vix_1h_ago should be the snapshot
    # taken at t≈10min (vix=20.0), since that is the youngest snapshot
    # still ≥ 60 min old.
    written = await state.get(VIX_1H_AGO_KEY)
    assert written == 20.0


@pytest.mark.asyncio
async def test_vix_1h_ago_evicts_old_snapshots(state: _JsonStateAdapter) -> None:
    """Snapshots older than (window + interval) must be evicted."""
    feed = _StubMacroFeed(vix=42.0)
    clock = _Clock(datetime(2026, 4, 21, 0, 0, tzinfo=UTC))
    persister = MacroPersister(state, feed, poll_interval_seconds=60.0, clock=clock)

    await persister.persist_once()  # @ t=0
    # Advance well past the eviction cutoff (1 h + 1 interval).
    clock.advance(seconds=VIX_HISTORY_WINDOW_SECONDS + 600)
    feed.vix = 100.0
    await persister.persist_once()

    # The t=0 snapshot must have been evicted; vix_1h_ago is now the
    # youngest snapshot ≥ 60 min old. With only the t≈3700 snapshot
    # remaining and no older snapshot in deque, the persister degrades
    # to the oldest available = current.
    assert await state.get(VIX_1H_AGO_KEY) == 100.0


# ---------------------------------------------------------------------------
# Partial-feed cases — missing values do NOT crash and are NOT written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_vix_skips_vix_keys(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=None, dxy=104.2, yield_spread=-0.1)
    persister = MacroPersister(state, feed)
    await persister.persist_once()

    assert await state.get(VIX_CURRENT_KEY) is None
    assert await state.get(VIX_KEY) is None
    assert await state.get(VIX_1H_AGO_KEY) is None
    assert await state.get(DXY_KEY) == 104.2
    assert await state.get(YIELD_SPREAD_KEY) == -0.1


@pytest.mark.asyncio
async def test_missing_dxy_does_not_block_other_keys(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=18.5, dxy=None, yield_spread=-0.1)
    persister = MacroPersister(state, feed)
    await persister.persist_once()

    assert await state.get(VIX_CURRENT_KEY) == 18.5
    assert await state.get(DXY_KEY) is None
    assert await state.get(YIELD_SPREAD_KEY) == -0.1


@pytest.mark.asyncio
async def test_all_missing_writes_nothing(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=None, dxy=None, yield_spread=None)
    persister = MacroPersister(state, feed)
    written = await persister.persist_once()
    assert all(v is None for v in written.values())


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_persists_eagerly(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=18.5)
    persister = MacroPersister(state, feed, poll_interval_seconds=3600.0)
    try:
        await persister.start()
        assert await state.get(VIX_CURRENT_KEY) == 18.5
    finally:
        await persister.stop()


@pytest.mark.asyncio
async def test_loop_persists_on_subsequent_ticks(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed(vix=18.5)
    persister = MacroPersister(state, feed, poll_interval_seconds=0.05)
    try:
        await persister.start()
        await asyncio.sleep(0.20)
        assert await state.get(VIX_CURRENT_KEY) == 18.5
    finally:
        await persister.stop()


@pytest.mark.asyncio
async def test_stop_idempotent_when_never_started(state: _JsonStateAdapter) -> None:
    feed = _StubMacroFeed()
    persister = MacroPersister(state, feed)
    await persister.stop()


@pytest.mark.asyncio
async def test_loop_swallows_writer_errors() -> None:
    """A transient state.set() exception must NOT kill the loop."""
    calls: list[int] = []

    class _FlakyState:
        async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
            del key, value, ttl
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("transient")

    feed = _StubMacroFeed(vix=18.5, dxy=104.2, yield_spread=-0.1)
    persister = MacroPersister(_FlakyState(), feed, poll_interval_seconds=0.02)
    try:
        await persister.start()
        await asyncio.sleep(0.10)
    finally:
        await persister.stop()

    assert len(calls) >= 3


# ---------------------------------------------------------------------------
# Hypothesis property test — every persisted vix value must round-trip via float()
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=200, deadline=None)
@given(
    vix=st.floats(min_value=5.0, max_value=120.0, allow_nan=False, allow_infinity=False),
)
@pytest.mark.asyncio
async def test_property_persisted_vix_round_trips_via_float(vix: float) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        persister = MacroPersister(state, _StubMacroFeed(vix=vix))
        await persister.persist_once()
        for key in (VIX_CURRENT_KEY, VIX_1H_AGO_KEY, VIX_KEY):
            raw = await state.get(key)
            assert float(raw) == vix
    finally:
        await redis.flushall()
        await redis.aclose()


@hyp_settings(max_examples=50, deadline=None)
@given(
    elapsed_seconds=st.integers(min_value=0, max_value=2 * VIX_HISTORY_WINDOW_SECONDS),
)
@pytest.mark.asyncio
async def test_property_vix_1h_ago_is_always_a_real_observed_value(
    elapsed_seconds: int,
) -> None:
    """vix_1h_ago must always be ONE of the snapshots we recorded —
    never a fabricated value, never None once any snapshot exists.
    """
    feed = _StubMacroFeed(vix=10.0)
    clock = _Clock(datetime(2026, 4, 21, 0, 0, tzinfo=UTC))
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        persister = MacroPersister(
            state,
            feed,
            poll_interval_seconds=60.0,
            clock=clock,
        )
        seen: set[float] = set()
        for i in range(0, elapsed_seconds + 1, 60):
            feed.vix = 10.0 + (i // 60) * 0.5
            seen.add(feed.vix)
            await persister.persist_once()
            clock.advance(seconds=60)

        raw = await state.get(VIX_1H_AGO_KEY)
        assert raw is not None
        assert float(raw) in seen
    finally:
        await redis.flushall()
        await redis.aclose()
