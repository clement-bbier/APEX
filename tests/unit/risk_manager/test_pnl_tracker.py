"""Unit tests for :class:`services.risk_manager.pnl_tracker.PnLTracker`.

Phase A.8 (issue #198). Validates the dual-key Redis read pattern:
primary ``pnl:{strategy_id}:daily`` (and ``:24h``) with fallback to
legacy ``pnl:daily`` (and ``pnl:24h``) and a structlog audit-trail
WARNING on fallback.

Test patterns follow CLAUDE.md Section 2 (fakeredis only, no real
Redis) and Section 7 (happy path + edge cases + error cases + property
test). The adapter mirrors the Phase-A writer API
(:meth:`core.state.StateStore.set`) which stores JSON-encoded scalars
under Redis ``STRING`` keys.
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

from services.risk_manager.pnl_tracker import (
    DEFAULT_STRATEGY_ID,
    LEGACY_24H_KEY,
    LEGACY_DAILY_KEY,
    PnLTracker,
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
) -> PnLTracker:
    return PnLTracker(_JsonStateAdapter(redis_client))


async def _seed(
    redis: fakeredis.aioredis.FakeRedis,
    key: str,
    payload: Any,
) -> None:
    """Mirror :meth:`core.state.StateStore.set` — JSON-encode under STRING."""
    await redis.set(key, json.dumps(payload))


# ---------------------------------------------------------------------------
# (a) Primary-key hit: no fallback, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_primary_daily_hit_returns_decimal_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Primary daily hit returns Decimal immediately, no fallback warning."""
    await _seed(redis_client, PnLTracker.primary_daily_key("default"), "1234.56")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl()

    assert pnl == Decimal("1234.56")
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


@pytest.mark.asyncio
async def test_primary_24h_hit_returns_decimal_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Primary 24h hit returns Decimal immediately, no fallback warning."""
    await _seed(redis_client, PnLTracker.primary_24h_key("default"), "5678.90")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_24h_pnl()

    assert pnl == Decimal("5678.90")
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# (b) Legacy fallback (default strategy_id): value returned + WARNING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_daily_fallback_with_default_strategy_warns(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only legacy populated + default strategy_id -> fallback + WARNING."""
    await _seed(redis_client, LEGACY_DAILY_KEY, "42.00")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl()

    assert pnl == Decimal("42.00")
    assert "pnl_tracker.legacy_key_fallback" in caplog.text
    assert LEGACY_DAILY_KEY in caplog.text
    assert "pnl:default:daily" in caplog.text
    assert DEFAULT_STRATEGY_ID in caplog.text


@pytest.mark.asyncio
async def test_legacy_24h_fallback_with_default_strategy_warns(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only legacy 24h populated + default strategy_id -> fallback + WARNING."""
    await _seed(redis_client, LEGACY_24H_KEY, "-100.25")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_24h_pnl()

    assert pnl == Decimal("-100.25")
    assert "pnl_tracker.legacy_key_fallback" in caplog.text
    assert LEGACY_24H_KEY in caplog.text
    assert "pnl:default:24h" in caplog.text
    assert DEFAULT_STRATEGY_ID in caplog.text


# ---------------------------------------------------------------------------
# (c) Double-write: new key wins, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_write_primary_daily_wins_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both daily keys populated -> primary takes precedence, no warning."""
    await _seed(redis_client, PnLTracker.primary_daily_key("default"), "999")
    await _seed(redis_client, LEGACY_DAILY_KEY, "1")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl()

    assert pnl == Decimal("999")
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


@pytest.mark.asyncio
async def test_double_write_primary_24h_wins_no_warning(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both 24h keys populated -> primary takes precedence, no warning."""
    await _seed(redis_client, PnLTracker.primary_24h_key("default"), "7777")
    await _seed(redis_client, LEGACY_24H_KEY, "2")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_24h_pnl()

    assert pnl == Decimal("7777")
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# (d) Both keys empty: tracker returns None (caller's fail-loud decides)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_keys_empty_daily_returns_none(
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither daily key populated -> None, no WARNING."""
    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl()

    assert pnl is None
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


@pytest.mark.asyncio
async def test_both_keys_empty_24h_returns_none(
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither 24h key populated -> None, no WARNING."""
    with caplog.at_level("WARNING"):
        pnl = await tracker.get_24h_pnl()

    assert pnl is None
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


# ---------------------------------------------------------------------------
# (e) Non-default strategy_id isolation + fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_default_strategy_primary_isolated_from_legacy_daily(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-strategy primary for X -> reads X, ignores default and legacy."""
    await _seed(redis_client, PnLTracker.primary_daily_key("crypto_momentum"), "333")
    await _seed(redis_client, PnLTracker.primary_daily_key("default"), "1")
    await _seed(redis_client, LEGACY_DAILY_KEY, "2")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl(strategy_id="crypto_momentum")

    assert pnl == Decimal("333")
    assert "pnl_tracker.legacy_key_fallback" not in caplog.text


@pytest.mark.asyncio
async def test_non_default_strategy_fallback_to_legacy_daily_warns(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase-B caller with real strategy_id + only legacy populated ->
    fallback + WARNING records the strategy_id (cross-strategy audit)."""
    await _seed(redis_client, LEGACY_DAILY_KEY, "55.5")

    with caplog.at_level("WARNING"):
        pnl = await tracker.get_daily_pnl(strategy_id="crypto_momentum")

    assert pnl == Decimal("55.5")
    assert "pnl_tracker.legacy_key_fallback" in caplog.text
    assert "crypto_momentum" in caplog.text
    assert "pnl:crypto_momentum:daily" in caplog.text


# ---------------------------------------------------------------------------
# Malformed-payload / fail-loud contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_primary_payload_daily_raises_with_context(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
) -> None:
    """Non-numeric primary payload -> RuntimeError with resolved key + strategy_id."""
    await _seed(
        redis_client,
        PnLTracker.primary_daily_key("default"),
        "not_a_number",
    )
    with pytest.raises(RuntimeError, match="non-numeric") as excinfo:
        await tracker.get_daily_pnl()
    msg = str(excinfo.value)
    assert "pnl:default:daily" in msg
    assert "default" in msg


@pytest.mark.asyncio
async def test_malformed_legacy_payload_reports_legacy_key_daily(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
) -> None:
    """Malformed payload under legacy key -> error cites LEGACY key, not primary.

    Ensures post-Phase-B audits can distinguish a corrupted legacy
    producer from a corrupted per-strategy producer (same contract as
    PortfolioTracker -- addresses PR #210 Copilot thread 1).
    """
    await _seed(redis_client, LEGACY_DAILY_KEY, ["not", "a", "scalar"])
    with pytest.raises(RuntimeError, match="non-numeric") as excinfo:
        await tracker.get_daily_pnl(strategy_id="crypto_momentum")
    msg = str(excinfo.value)
    assert LEGACY_DAILY_KEY in msg
    assert "crypto_momentum" in msg
    assert "pnl:crypto_momentum:daily" not in msg


@pytest.mark.asyncio
async def test_malformed_payload_rejects_bool(
    redis_client: fakeredis.aioredis.FakeRedis,
    tracker: PnLTracker,
) -> None:
    """Boolean payload -> RuntimeError (never silently Decimal(True)=1)."""
    await _seed(redis_client, PnLTracker.primary_daily_key("default"), True)
    with pytest.raises(RuntimeError, match="non-numeric"):
        await tracker.get_daily_pnl()


# ---------------------------------------------------------------------------
# Property test: any non-negative numeric payload round-trips through Decimal
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
def test_property_numeric_daily_pnl_round_trips(value: Decimal) -> None:
    """Non-negative, finite 8-decimal value round-trips through Decimal."""
    import asyncio

    async def _run() -> Decimal | None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            await client.set(
                PnLTracker.primary_daily_key("default"),
                json.dumps(str(value)),
            )
            tr = PnLTracker(_JsonStateAdapter(client))
            return await tr.get_daily_pnl()
        finally:
            await client.flushall()
            await client.aclose()

    result = asyncio.run(_run())
    assert result == value


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


def test_primary_key_format() -> None:
    """Sanity-check the key-builder helpers (contract with future writers)."""
    assert PnLTracker.primary_daily_key("default") == "pnl:default:daily"
    assert PnLTracker.primary_daily_key("crypto_momentum") == "pnl:crypto_momentum:daily"
    assert PnLTracker.primary_24h_key("default") == "pnl:default:24h"
    assert PnLTracker.primary_24h_key("crypto_momentum") == "pnl:crypto_momentum:24h"


def test_module_constants_are_stable_contracts() -> None:
    """Constants exposed by the module are stable contracts."""
    assert LEGACY_DAILY_KEY == "pnl:daily"
    assert LEGACY_24H_KEY == "pnl:24h"
    assert DEFAULT_STRATEGY_ID == "default"
