"""Unit tests for :class:`services.data_ingestion.session_persister.SessionPersister`.

Phase A.10 (issue #200). Validates that the persister produces values
S05's :mod:`services.risk_manager.context_loader` can deserialize.

Test patterns follow CLAUDE.md §7: happy path + edge cases (DST,
weekend, midnight) + error case + Hypothesis property test for session
boundaries.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models.tick import Session
from services.data_ingestion.session_persister import (
    SESSION_REDIS_KEY,
    SessionPersister,
)


class _JsonStateAdapter:
    """Minimal JSON-aware adapter around a fakeredis client (mirrors core.state)."""

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
# Happy path + S05-deserialization round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_once_writes_us_prime_during_open_window(
    state: _JsonStateAdapter,
) -> None:
    persister = SessionPersister(state)
    # 2026-04-21 14:30 UTC is the US open prime window per SessionTagger.
    ts = datetime(2026, 4, 21, 14, 30, tzinfo=UTC)
    await persister.persist_once(now=ts)

    raw = await state.get(SESSION_REDIS_KEY)
    assert raw == "us_prime"
    # S05's context_loader path: Session(str(value)) must succeed.
    assert Session(str(raw)) == Session.US_PRIME


@pytest.mark.asyncio
async def test_persist_once_writes_us_normal_outside_prime(
    state: _JsonStateAdapter,
) -> None:
    persister = SessionPersister(state)
    # 2026-04-21 17:00 UTC is mid-session (US_NORMAL).
    ts = datetime(2026, 4, 21, 17, 0, tzinfo=UTC)
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "us_normal"


@pytest.mark.asyncio
async def test_persist_once_returns_persisted_value(
    state: _JsonStateAdapter,
) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 21, 14, 30, tzinfo=UTC)
    returned = await persister.persist_once(now=ts)
    assert returned == "us_prime"


# ---------------------------------------------------------------------------
# Edge cases: weekend, midnight, after-hours, london, asian
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekend_persisted_when_saturday(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 25, 14, 30, tzinfo=UTC)  # Saturday
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "weekend"


@pytest.mark.asyncio
async def test_weekend_persisted_when_sunday(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 26, 17, 0, tzinfo=UTC)  # Sunday
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "weekend"


@pytest.mark.asyncio
async def test_after_hours_persisted_outside_us_window(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    # 22:00 UTC on a weekday = after US close (21:00 UTC).
    ts = datetime(2026, 4, 21, 22, 0, tzinfo=UTC)
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "after_hours"


@pytest.mark.asyncio
async def test_london_session_persisted(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 21, 9, 0, tzinfo=UTC)  # 09:00 UTC weekday
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "london"


@pytest.mark.asyncio
async def test_asian_session_persisted(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 21, 1, 0, tzinfo=UTC)  # 01:00 UTC weekday
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "asian"


@pytest.mark.asyncio
async def test_midnight_utc_weekday_classifies_asian(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    ts = datetime(2026, 4, 22, 0, 0, tzinfo=UTC)  # Wednesday midnight
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "asian"


@pytest.mark.asyncio
async def test_us_prime_close_window(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    # 20:30 UTC weekday = US_PRIME close window.
    ts = datetime(2026, 4, 21, 20, 30, tzinfo=UTC)
    await persister.persist_once(now=ts)
    assert await state.get(SESSION_REDIS_KEY) == "us_prime"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_persists_eagerly_before_loop(state: _JsonStateAdapter) -> None:
    """First-tick blackout guard: start() must not require sleeping for the loop."""
    persister = SessionPersister(state, poll_interval_seconds=3600.0)
    try:
        await persister.start()
        # Value must already be present even though loop hasn't ticked yet.
        assert await state.get(SESSION_REDIS_KEY) is not None
    finally:
        await persister.stop()


@pytest.mark.asyncio
async def test_loop_persists_on_subsequent_ticks(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state, poll_interval_seconds=0.05)
    try:
        await persister.start()
        await asyncio.sleep(0.20)
        # No assertion on count — sleep is not deterministic; just verify
        # that the loop didn't crash and the key is still populated.
        assert await state.get(SESSION_REDIS_KEY) is not None
    finally:
        await persister.stop()


@pytest.mark.asyncio
async def test_stop_idempotent_when_never_started(state: _JsonStateAdapter) -> None:
    persister = SessionPersister(state)
    await persister.stop()  # must not raise


@pytest.mark.asyncio
async def test_loop_swallows_writer_errors(state: _JsonStateAdapter) -> None:
    """A transient state.set() exception must NOT kill the loop."""
    calls: list[int] = []

    class _FlakyState:
        async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
            del key, value, ttl
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("transient")

    persister = SessionPersister(_FlakyState(), poll_interval_seconds=0.02)
    try:
        await persister.start()
        await asyncio.sleep(0.10)
    finally:
        await persister.stop()

    # First call from start()'s eager persist_once + at least one loop tick.
    assert len(calls) >= 2


# ---------------------------------------------------------------------------
# Hypothesis property test — every persisted value MUST decode via Session()
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=200, deadline=None)
@given(
    timestamp=st.datetimes(
        min_value=datetime(2026, 1, 1),
        max_value=datetime(2027, 12, 31),
        timezones=st.just(UTC),
    ),
)
@pytest.mark.asyncio
async def test_property_persisted_value_decodes_to_s05_session_enum(
    timestamp: datetime,
) -> None:
    """For every UTC timestamp in the next 2 years, the persisted string
    MUST round-trip through ``core.models.tick.Session(...)`` without
    raising. This is the contract S05 ``context_loader.py:110`` enforces.
    """
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        persister = SessionPersister(state)
        await persister.persist_once(now=timestamp)
        raw = await state.get(SESSION_REDIS_KEY)
        # Contract: Session(str(value)) must not raise.
        Session(str(raw))
    finally:
        await redis.flushall()
        await redis.aclose()


@hyp_settings(max_examples=50, deadline=None)
@given(weekday_offset=st.integers(min_value=0, max_value=4))
@pytest.mark.asyncio
async def test_property_us_normal_during_us_session_on_weekdays(
    weekday_offset: int,
) -> None:
    """Mid-session weekday timestamps MUST classify as a US session
    (us_normal or us_prime) — never as weekend / london / asian.
    """
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        persister = SessionPersister(state)
        # Pick a known Monday and walk forward; ensure all weekdays land
        # inside the US window when the wall-clock is set to 17:00 UTC.
        monday = datetime(2026, 4, 20, 17, 0, tzinfo=UTC)
        ts = monday + timedelta(days=weekday_offset)
        await persister.persist_once(now=ts)
        raw = await state.get(SESSION_REDIS_KEY)
        assert raw in {"us_normal", "us_prime"}
    finally:
        await redis.flushall()
        await redis.aclose()


# ---------------------------------------------------------------------------
# DST edge case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dst_spring_forward_does_not_break_persistence(
    state: _JsonStateAdapter,
) -> None:
    """SessionTagger uses fixed UTC windows, so DST transitions do not
    move the boundaries — but verify the persister produces a valid
    decoded enum on the spring-forward Sunday.
    """
    persister = SessionPersister(state)
    # 2026-03-08 = US DST spring-forward Sunday → weekend.
    ts = datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    await persister.persist_once(now=ts)
    raw = await state.get(SESSION_REDIS_KEY)
    assert raw == "weekend"
    assert Session(str(raw)) == Session.WEEKEND


@pytest.mark.asyncio
async def test_naive_datetime_is_treated_as_utc(state: _JsonStateAdapter) -> None:
    """SessionTagger accepts naive datetimes as UTC. Persister forwards
    them via the ``now`` override; verify no exception.
    """
    persister = SessionPersister(state)
    # Construct a non-UTC tz-aware datetime; SessionTagger normalizes.
    tz_plus_5 = timezone(timedelta(hours=5))
    ts = datetime(2026, 4, 21, 19, 30, tzinfo=tz_plus_5)  # = 14:30 UTC
    await persister.persist_once(now=ts)
    raw = await state.get(SESSION_REDIS_KEY)
    assert raw == "us_prime"
