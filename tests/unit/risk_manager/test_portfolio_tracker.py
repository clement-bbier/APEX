"""Unit tests for :class:`services.risk_manager.portfolio_tracker.PortfolioTracker`.

Phase A.7 (issue #197). Validates the dual-key Redis read pattern:
primary ``portfolio:{strategy_id}:capital`` with fallback to legacy
``portfolio:capital`` and a structlog audit-trail WARNING on fallback.

Test patterns follow CLAUDE.md Section 2 (fakeredis only, no real Redis)
and Section 7 (happy path + edge cases + error cases + property test).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from services.risk_manager.portfolio_tracker import (
    DEFAULT_STRATEGY_ID,
    LEGACY_CAPITAL_KEY,
    PortfolioTracker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _JsonStateAdapter:
    """Minimal JSON-aware adapter around a fakeredis client.

    Mirrors :class:`core.state.StateStore.get` semantics: raw bytes/str
    values are JSON-decoded before being returned to the caller.
    """

    def __init__(self, redis: fakeredis.aioredis.FakeRedis) -> None:
        self._redis = redis

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)


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
async def tracker(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> PortfolioTracker:
    return PortfolioTracker(_JsonStateAdapter(redis_client))


async def _seed(
    redis: fakeredis.aioredis.FakeRedis,
    key: str,
    payload: Any,
) -> None:
    await redis.set(key, json.dumps(payload))


# ---------------------------------------------------------------------------
# (a) Primary-key hit: no fallback, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_primary_key_hit_returns_value_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Primary hit returns Decimal immediately, no fallback warning."""
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("default"),
        {"available": "123456.78"},
    )

    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital()

    assert capital == Decimal("123456.78")
    assert "portfolio_tracker.legacy_key_fallback" not in caplog.text


@pytest.mark.asyncio
async def test_primary_key_hit_read_raw_returns_payload(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
) -> None:
    """``read_raw`` returns the deserialized dict, not a Decimal."""
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("default"),
        {"available": 100_000, "currency": "USD"},
    )
    payload = await tracker.read_raw()
    assert payload == {"available": 100_000, "currency": "USD"}


# ---------------------------------------------------------------------------
# (b) Legacy fallback (default strategy_id): value returned + WARNING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_fallback_default_strategy_id(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only legacy populated + default strategy_id -> fallback + WARNING."""
    await _seed(redis_client, LEGACY_CAPITAL_KEY, {"available": "50000"})

    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital()

    assert capital == Decimal("50000")
    assert "portfolio_tracker.legacy_key_fallback" in caplog.text
    assert LEGACY_CAPITAL_KEY in caplog.text
    assert "portfolio:default:capital" in caplog.text
    assert DEFAULT_STRATEGY_ID in caplog.text


# ---------------------------------------------------------------------------
# (c) Double-write: new key wins, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_write_primary_wins_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both keys populated -> primary takes precedence, no warning."""
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("default"),
        {"available": "99999"},
    )
    await _seed(redis_client, LEGACY_CAPITAL_KEY, {"available": "1"})

    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital()

    assert capital == Decimal("99999")
    assert "portfolio_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# (d) Both keys empty: tracker returns None (caller's fail-loud decides)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_keys_empty_returns_none(
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither key populated -> both methods return None, no WARNING."""
    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital()
        payload = await tracker.read_raw()

    assert capital is None
    assert payload is None
    assert "portfolio_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# (e) Non-default strategy_id fallback still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_default_strategy_id_falls_back_to_legacy(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase-B caller with real strategy_id + only legacy populated ->
    fallback + WARNING records the strategy_id (cross-strategy audit)."""
    await _seed(redis_client, LEGACY_CAPITAL_KEY, {"available": "42"})

    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital(strategy_id="crypto_momentum")

    assert capital == Decimal("42")
    assert "portfolio_tracker.legacy_key_fallback" in caplog.text
    assert "crypto_momentum" in caplog.text
    assert "portfolio:crypto_momentum:capital" in caplog.text


@pytest.mark.asyncio
async def test_non_default_strategy_id_primary_hit_isolates_from_legacy(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-strategy primary populated for X -> reads X, ignores default
    and legacy. Proves per-strategy isolation post-Phase-B."""
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("crypto_momentum"),
        {"available": "7777"},
    )
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("default"),
        {"available": "1"},
    )
    await _seed(redis_client, LEGACY_CAPITAL_KEY, {"available": "2"})

    with caplog.at_level("WARNING"):
        capital = await tracker.get_capital(strategy_id="crypto_momentum")

    assert capital == Decimal("7777")
    assert "portfolio_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# Malformed-payload / fail-loud contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_payload_not_dict_raises(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
) -> None:
    """Non-dict payload -> RuntimeError with resolved key + strategy_id context."""
    await _seed(redis_client, PortfolioTracker.primary_key("default"), ["not", "a", "dict"])
    with pytest.raises(RuntimeError, match="malformed") as excinfo:
        await tracker.get_capital()
    msg = str(excinfo.value)
    assert "portfolio:default:capital" in msg
    assert "default" in msg


@pytest.mark.asyncio
async def test_malformed_payload_missing_available_raises(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
) -> None:
    """Dict missing ``available`` -> RuntimeError with resolved key + strategy_id."""
    await _seed(redis_client, PortfolioTracker.primary_key("default"), {"currency": "USD"})
    with pytest.raises(RuntimeError, match="malformed") as excinfo:
        await tracker.get_capital()
    msg = str(excinfo.value)
    assert "portfolio:default:capital" in msg
    assert "default" in msg


@pytest.mark.asyncio
async def test_malformed_payload_non_numeric_available_raises(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
) -> None:
    """Non-numeric ``available`` -> RuntimeError with resolved key + strategy_id."""
    await _seed(
        redis_client,
        PortfolioTracker.primary_key("default"),
        {"available": "not_a_number"},
    )
    with pytest.raises(RuntimeError, match="not numeric") as excinfo:
        await tracker.get_capital()
    msg = str(excinfo.value)
    assert "portfolio:default:capital" in msg
    assert "default" in msg


@pytest.mark.asyncio
async def test_malformed_legacy_payload_reports_legacy_key(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PortfolioTracker,
) -> None:
    """Malformed payload under legacy key -> error cites the LEGACY key, not primary.

    Ensures post-Phase-B audits can distinguish a corrupted legacy producer
    from a corrupted per-strategy producer (addresses #210 Copilot thread 1).
    """
    await _seed(redis_client, LEGACY_CAPITAL_KEY, {"currency": "USD"})
    with pytest.raises(RuntimeError, match="malformed") as excinfo:
        await tracker.get_capital(strategy_id="crypto_momentum")
    msg = str(excinfo.value)
    assert LEGACY_CAPITAL_KEY in msg
    assert "crypto_momentum" in msg
    assert "portfolio:crypto_momentum:capital" not in msg


# ---------------------------------------------------------------------------
# Property test: any numeric-like payload round-trips through Decimal
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=50, deadline=None)
@given(
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e12"),
        places=8,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_property_numeric_available_round_trips(value: Decimal) -> None:
    """Non-negative, finite 8-decimal value round-trips through Decimal."""
    import asyncio

    async def _run() -> Decimal | None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            await client.set(
                PortfolioTracker.primary_key("default"),
                json.dumps({"available": str(value)}),
            )
            tr = PortfolioTracker(_JsonStateAdapter(client))
            return await tr.get_capital()
        finally:
            await client.flushall()
            await client.aclose()

    result = asyncio.run(_run())
    assert result == value


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


def test_primary_key_format() -> None:
    """Sanity-check the key-builder helper (contract with future writers)."""
    assert PortfolioTracker.primary_key("default") == "portfolio:default:capital"
    assert PortfolioTracker.primary_key("crypto_momentum") == "portfolio:crypto_momentum:capital"


def test_module_constants_are_stable_contracts() -> None:
    """Constants exposed by the module are stable contracts."""
    assert LEGACY_CAPITAL_KEY == "portfolio:capital"
    assert DEFAULT_STRATEGY_ID == "default"
