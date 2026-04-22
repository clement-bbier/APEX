"""Integration test: SessionPersister + MacroPersister → ContextLoader contract.

Phase A.10 (issue #200). Verifies the producer/consumer end-to-end flow:

1. :class:`SessionPersister` writes ``session:current``.
2. :class:`MacroPersister` writes ``macro:vix_current`` + ``macro:vix_1h_ago``.
3. :class:`services.risk_manager.context_loader.ContextLoader` consumes
   both keys without raising the fail-loud :class:`RuntimeError` that
   ADR-0006 §D4 requires when a key is orphan.

All seven other context keys are pre-seeded with valid fixtures so the
test isolates the three keys under audit. fakeredis is used end-to-end —
no Docker dependency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import fakeredis.aioredis
import pytest

from core.models.tick import Session
from services.data_ingestion.macro_persister import (
    VIX_1H_AGO_KEY,
    VIX_CURRENT_KEY,
    MacroPersister,
)
from services.data_ingestion.session_persister import (
    SESSION_REDIS_KEY,
    SessionPersister,
)
from services.risk_manager.context_loader import ContextLoader


class _JsonStateAdapter:
    """Mirrors :class:`core.state.StateStore` JSON encode/decode semantics."""

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
    def __init__(self, *, vix: float, dxy: float, yield_spread: float) -> None:
        self._vix = vix
        self._dxy = dxy
        self._yield_spread = yield_spread

    async def get_vix(self) -> float:
        return self._vix

    async def get_dxy(self) -> float:
        return self._dxy

    async def get_yield_spread(self) -> float:
        return self._yield_spread


async def _seed_other_context_keys(state: _JsonStateAdapter) -> None:
    """Seed the five non-A.10 pre-trade keys so ContextLoader.load() succeeds."""
    await state.set("portfolio:capital", {"available": "100000.00"})
    await state.set("pnl:daily", "0.0")
    await state.set("pnl:intraday_30m", "0.0")
    await state.set("portfolio:positions", [])
    await state.set("correlation:matrix", {})


# ---------------------------------------------------------------------------
# Producer/consumer round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_persister_writes_a_value_context_loader_can_decode() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        await _seed_other_context_keys(state)
        # Macro keys also required by the loader; seed them so this test
        # isolates session decoding.
        await state.set("macro:vix_current", 18.0)
        await state.set("macro:vix_1h_ago", 18.0)

        persister = SessionPersister(state)
        await persister.persist_once(now=datetime(2026, 4, 21, 14, 30, tzinfo=UTC))

        loader = ContextLoader(state)
        ctx = await loader.load("AAPL")

        assert ctx["session"] == Session.US_PRIME
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest.mark.asyncio
async def test_macro_persister_writes_vix_keys_context_loader_can_decode() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        await _seed_other_context_keys(state)
        await state.set(SESSION_REDIS_KEY, "us_normal")

        feed = _StubMacroFeed(vix=18.5, dxy=104.2, yield_spread=-0.35)
        persister = MacroPersister(state, feed)
        await persister.persist_once()

        loader = ContextLoader(state)
        ctx = await loader.load("AAPL")

        assert ctx["vix_current"] == pytest.approx(18.5)
        assert ctx["vix_1h_ago"] == pytest.approx(18.5)  # first tick: degraded
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest.mark.asyncio
async def test_full_pipeline_session_plus_macro_decodable_by_context_loader() -> None:
    """End-to-end: both persisters + ContextLoader, no fail-loud raise."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        await _seed_other_context_keys(state)

        session_p = SessionPersister(state)
        await session_p.persist_once(now=datetime(2026, 4, 21, 14, 30, tzinfo=UTC))

        macro_p = MacroPersister(
            state,
            _StubMacroFeed(vix=22.1, dxy=105.0, yield_spread=-0.2),
        )
        await macro_p.persist_once()

        loader = ContextLoader(state)
        ctx = await loader.load("AAPL")

        # All three orphan keys now resolve through the loader without raising.
        assert ctx["session"] == Session.US_PRIME
        assert ctx["vix_current"] == pytest.approx(22.1)
        assert ctx["vix_1h_ago"] == pytest.approx(22.1)
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest.mark.asyncio
async def test_context_loader_still_fails_loud_when_macro_persister_has_no_data() -> None:
    """Regression guard: removing the persisters' output reverts to fail-loud.

    This protects the audit invariant that the keys are MEANT to be
    fail-loud when missing — the writer is the only thing standing
    between us and a 100% rejection rate. A future regression that
    silently coerces `None` would surface here.
    """
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        await _seed_other_context_keys(state)
        await state.set(SESSION_REDIS_KEY, "us_normal")
        # Macro keys deliberately NOT persisted.

        loader = ContextLoader(state)
        with pytest.raises(RuntimeError, match="macro:vix_current"):
            await loader.load("AAPL")
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest.mark.asyncio
async def test_context_loader_still_fails_loud_when_session_persister_has_no_data() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        await _seed_other_context_keys(state)
        feed = _StubMacroFeed(vix=18.5, dxy=104.0, yield_spread=-0.1)
        await MacroPersister(state, feed).persist_once()
        # Session deliberately NOT persisted.

        loader = ContextLoader(state)
        with pytest.raises(RuntimeError, match="session:current"):
            await loader.load("AAPL")
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest.mark.asyncio
async def test_macro_persister_writes_keys_with_value_floats_decodable() -> None:
    """Verify exact values written, not just the keys (defensive)."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        state = _JsonStateAdapter(redis)
        feed = _StubMacroFeed(vix=22.1, dxy=105.5, yield_spread=-0.42)
        persister = MacroPersister(state, feed)
        await persister.persist_once()

        assert float(await state.get(VIX_CURRENT_KEY)) == pytest.approx(22.1)
        assert float(await state.get(VIX_1H_AGO_KEY)) == pytest.approx(22.1)
    finally:
        await redis.flushall()
        await redis.aclose()
