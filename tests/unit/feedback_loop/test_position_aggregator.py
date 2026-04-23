"""Unit tests for :class:`services.feedback_loop.position_aggregator.PositionAggregator`.

Phase A.9 (issue #199). Validates the source-scan + transform + snapshot
contract that closes the ``portfolio:positions`` orphan read identified in
``docs/audits/POSITION_KEY_AUDIT_2026-04-21.md``.

Test patterns follow CLAUDE.md §2 (fakeredis only, no real Redis) and §7
(happy path + edge cases + error cases + property test). Mirrors the
fakeredis adapter pattern used by ``test_portfolio_tracker.py`` (PR #210)
and ``test_pnl_tracker.py`` (PR #214).
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

from services.feedback_loop.position_aggregator import (
    AGGREGATE_KEY,
    DEFAULT_SNAPSHOT_INTERVAL_S,
    PER_SYMBOL_KEY_PREFIX,
    PositionAggregator,
    aggregate_records,
)
from services.risk_manager.models import Position

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _JsonStateAdapter:
    """Mirrors :class:`core.state.StateStore` ``get``/``set``/``client`` semantics.

    Encodes via ``json.dumps`` on ``set`` and decodes via ``json.loads`` on
    ``get`` to match the production wire format
    (``core/state.py:121``/``core/state.py:136``). Exposes the underlying
    fakeredis client so :meth:`PositionAggregator.aggregate_from_redis` can
    use ``scan_iter``.
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
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Fresh fakeredis per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def state(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> _JsonStateAdapter:
    return _JsonStateAdapter(redis_client)


@pytest_asyncio.fixture
async def aggregator(state: _JsonStateAdapter) -> PositionAggregator:
    return PositionAggregator(state)


def _s06_record(
    symbol: str,
    *,
    direction: str = "LONG",
    entry: str = "100",
    size: str = "1",
    is_paper: bool = True,
) -> dict[str, Any]:
    """Build a per-symbol record in the exact shape S06 writes today
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
        "is_paper": is_paper,
    }


async def _seed_position(
    state: _JsonStateAdapter,
    symbol: str,
    **overrides: Any,
) -> None:
    record = _s06_record(symbol, **overrides)
    await state.set(f"{PER_SYMBOL_KEY_PREFIX}{symbol}", record)


# ---------------------------------------------------------------------------
# (a) aggregate_records — pure transform contract
# ---------------------------------------------------------------------------


def test_aggregate_records_empty_returns_empty() -> None:
    assert aggregate_records({}) == []


def test_aggregate_records_single_position() -> None:
    out = aggregate_records({"AAPL": _s06_record("AAPL", entry="150", size="2")})
    assert len(out) == 1
    assert out[0].symbol == "AAPL"
    assert out[0].size == Decimal("2")
    assert out[0].entry_price == Decimal("150")
    assert out[0].asset_class == "equity"


def test_aggregate_records_multi_symbol_sorted() -> None:
    out = aggregate_records(
        {
            "MSFT": _s06_record("MSFT", entry="320"),
            "AAPL": _s06_record("AAPL", entry="150"),
            "BTCUSDT": _s06_record("BTCUSDT", entry="50000"),
        }
    )
    # Sorted by symbol for deterministic test assertions.
    assert [p.symbol for p in out] == ["AAPL", "BTCUSDT", "MSFT"]
    assert out[1].asset_class == "crypto"  # BTCUSDT inferred as crypto
    assert out[0].asset_class == "equity"  # AAPL inferred as equity
    assert out[2].asset_class == "equity"


def test_aggregate_records_negative_size_treated_as_magnitude() -> None:
    """Phase A: per-symbol record carries direction separately; sign filtered."""
    out = aggregate_records({"AAPL": _s06_record("AAPL", direction="SHORT", size="-3")})
    assert len(out) == 1
    assert out[0].size == Decimal("3")  # magnitude only


def test_aggregate_records_zero_size_skipped() -> None:
    """Closed positions (size 0) are not surfaced to S05."""
    out = aggregate_records({"AAPL": _s06_record("AAPL", size="0")})
    assert out == []


def test_aggregate_records_non_positive_entry_skipped() -> None:
    """Position model rejects entry_price <= 0; pre-filter keeps snapshot alive."""
    assert aggregate_records({"AAPL": _s06_record("AAPL", entry="0")}) == []
    assert aggregate_records({"AAPL": _s06_record("AAPL", entry="-1")}) == []


def test_aggregate_records_missing_size_skipped() -> None:
    bad = {"symbol": "AAPL", "entry": "100"}  # no 'size'
    assert aggregate_records({"AAPL": bad}) == []


def test_aggregate_records_missing_entry_skipped() -> None:
    bad = {"symbol": "AAPL", "size": "1"}  # no 'entry' or 'entry_price'
    assert aggregate_records({"AAPL": bad}) == []


def test_aggregate_records_accepts_explicit_entry_price_field() -> None:
    """Forward-compat: sub-book records may use the canonical 'entry_price' field."""
    out = aggregate_records({"AAPL": {"size": "1", "entry_price": "150"}})
    assert len(out) == 1
    assert out[0].entry_price == Decimal("150")


def test_aggregate_records_explicit_entry_price_wins_over_legacy_entry() -> None:
    out = aggregate_records({"AAPL": {"size": "1", "entry": "200", "entry_price": "150"}})
    assert out[0].entry_price == Decimal("150")


def test_aggregate_records_explicit_asset_class_wins_over_inference() -> None:
    """Forward-compat: sub-book records may carry an explicit asset_class."""
    out = aggregate_records({"AAPL": {"size": "1", "entry_price": "150", "asset_class": "futures"}})
    assert out[0].asset_class == "futures"


def test_aggregate_records_non_dict_record_skipped() -> None:
    assert aggregate_records({"AAPL": "not_a_dict"}) == []  # type: ignore[dict-item]
    assert aggregate_records({"AAPL": 42}) == []  # type: ignore[dict-item]
    assert aggregate_records({"AAPL": None}) == []  # type: ignore[dict-item]


def test_aggregate_records_undecodable_decimal_skipped() -> None:
    out = aggregate_records({"AAPL": {"size": "not_a_number", "entry": "100"}})
    assert out == []


def test_aggregate_records_partial_failure_does_not_block_other_symbols() -> None:
    """A corrupted row on AAPL must not silently block MSFT's snapshot."""
    out = aggregate_records(
        {
            "AAPL": {"size": "garbage", "entry": "100"},  # bad
            "MSFT": _s06_record("MSFT", entry="320"),
        }
    )
    assert [p.symbol for p in out] == ["MSFT"]


# ---------------------------------------------------------------------------
# (b) aggregate_from_redis — Redis SCAN integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_from_redis_no_keys_returns_empty(
    aggregator: PositionAggregator,
) -> None:
    assert await aggregator.aggregate_from_redis() == []


@pytest.mark.asyncio
async def test_aggregate_from_redis_single_key(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
) -> None:
    await _seed_position(state, "AAPL", entry="150", size="2")
    out = await aggregator.aggregate_from_redis()
    assert len(out) == 1
    assert out[0].symbol == "AAPL"
    assert out[0].size == Decimal("2")
    assert out[0].entry_price == Decimal("150")


@pytest.mark.asyncio
async def test_aggregate_from_redis_multi_key_sorted(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
) -> None:
    await _seed_position(state, "MSFT", entry="320")
    await _seed_position(state, "AAPL", entry="150")
    await _seed_position(state, "BTCUSDT", entry="50000")
    out = await aggregator.aggregate_from_redis()
    assert [p.symbol for p in out] == ["AAPL", "BTCUSDT", "MSFT"]


@pytest.mark.asyncio
async def test_aggregate_from_redis_ignores_other_namespaces(
    state: _JsonStateAdapter,
    redis_client: fakeredis.aioredis.FakeRedis,
    aggregator: PositionAggregator,
) -> None:
    """Non-`positions:*` keys must not be picked up."""
    await _seed_position(state, "AAPL", entry="150")
    await redis_client.set("portfolio:capital", json.dumps({"available": "100000"}))
    await redis_client.set("kelly:default:AAPL", json.dumps({"win_rate": 0.6}))
    await redis_client.set("trades:all", json.dumps([]))
    out = await aggregator.aggregate_from_redis()
    assert [p.symbol for p in out] == ["AAPL"]


@pytest.mark.asyncio
async def test_aggregate_from_redis_corrupted_record_skipped(
    state: _JsonStateAdapter,
    redis_client: fakeredis.aioredis.FakeRedis,
    aggregator: PositionAggregator,
) -> None:
    """A non-dict payload at a positions:* key is skipped, not raised."""
    await _seed_position(state, "MSFT", entry="320")
    # AAPL is a JSON list at the positions: key — wrong shape.
    await redis_client.set(f"{PER_SYMBOL_KEY_PREFIX}AAPL", json.dumps(["not", "a", "dict"]))
    out = await aggregator.aggregate_from_redis()
    assert [p.symbol for p in out] == ["MSFT"]


@pytest.mark.asyncio
async def test_aggregate_from_redis_empty_symbol_segment_skipped(
    redis_client: fakeredis.aioredis.FakeRedis,
    aggregator: PositionAggregator,
) -> None:
    """Defensive: a key shaped exactly `positions:` (no symbol) is skipped."""
    await redis_client.set(PER_SYMBOL_KEY_PREFIX, json.dumps({"size": "1", "entry": "100"}))
    out = await aggregator.aggregate_from_redis()
    assert out == []


# ---------------------------------------------------------------------------
# (c) snapshot_to_redis — write-side contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_to_redis_writes_aggregate_key(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
) -> None:
    await _seed_position(state, "AAPL", entry="150", size="2")
    count = await aggregator.snapshot_to_redis()
    assert count == 1
    payload = await state.get(AGGREGATE_KEY)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["symbol"] == "AAPL"
    assert payload[0]["size"] == "2"
    assert payload[0]["entry_price"] == "150"


@pytest.mark.asyncio
async def test_snapshot_writes_empty_list_when_no_positions(
    aggregator: PositionAggregator,
    state: _JsonStateAdapter,
) -> None:
    """A flat book MUST surface as an empty list, not a missing key — the
    fail-closed reader treats missing-key as ``REJECTED_SYSTEM_UNAVAILABLE``."""
    count = await aggregator.snapshot_to_redis()
    assert count == 0
    assert await state.get(AGGREGATE_KEY) == []


@pytest.mark.asyncio
async def test_snapshot_round_trip_is_position_model_compatible(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
) -> None:
    """Round-trip: snapshot → ContextLoader-style validation → :class:`Position`.

    Reproduces the exact decode path used by
    :meth:`services.risk_manager.context_loader.ContextLoader.load`
    so a regression in the wire shape would surface here, not in
    a downstream S05 production rejection.
    """
    await _seed_position(state, "AAPL", entry="150", size="2")
    await _seed_position(state, "BTCUSDT", entry="50000", size="0.5")
    await aggregator.snapshot_to_redis()
    raw = await state.get(AGGREGATE_KEY)
    assert isinstance(raw, list)
    rebuilt = [Position.model_validate(p) for p in raw]
    by_sym = {p.symbol: p for p in rebuilt}
    assert by_sym["AAPL"].size == Decimal("2")
    assert by_sym["AAPL"].entry_price == Decimal("150")
    assert by_sym["BTCUSDT"].asset_class == "crypto"


@pytest.mark.asyncio
async def test_snapshot_overwrites_previous_value(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """A new snapshot replaces the previous aggregate atomically (StateStore.set)."""
    await _seed_position(state, "AAPL", entry="150", size="2")
    await aggregator.snapshot_to_redis()
    # Now AAPL closes (size 0) and MSFT opens.
    await redis_client.delete(f"{PER_SYMBOL_KEY_PREFIX}AAPL")
    await _seed_position(state, "MSFT", entry="320", size="1")
    await aggregator.snapshot_to_redis()
    payload = await state.get(AGGREGATE_KEY)
    assert isinstance(payload, list)
    assert [p["symbol"] for p in payload] == ["MSFT"]


# ---------------------------------------------------------------------------
# (d) Multi-strategy offsetting (Phase A 1:1; ADR-0012 §D2 forward-compat)
# ---------------------------------------------------------------------------


def test_aggregate_multi_strategy_offsetting_via_pure_transform() -> None:
    """When two strategies offset on the same symbol, the per-symbol record
    fed to ``aggregate_records`` is already the algebraic sum (Phase A: only
    one source per symbol; Phase B: the sub-book pre-aggregator pre-sums).
    A net-flat symbol therefore arrives with ``size=0`` and is filtered.

    This test pins the contract: the aggregator does NOT itself receive
    raw per-strategy intents — it receives the symbol-level net. The
    pre-aggregation responsibility is the SubBookAttributor's per
    ADR-0012 §D8.
    """
    # Net-flat AAPL (e.g. +2 from Strategy A, -2 from Strategy B):
    out = aggregate_records({"AAPL": {"size": "0", "entry_price": "150"}})
    assert out == []  # filtered: size == 0


def test_aggregate_multi_strategy_same_direction_via_pure_transform() -> None:
    """Two same-direction strategies on AAPL → net-long arrives pre-summed."""
    out = aggregate_records({"AAPL": {"size": "5", "entry_price": "150"}})
    assert len(out) == 1
    assert out[0].size == Decimal("5")


# ---------------------------------------------------------------------------
# (e) Hypothesis property: N input records → N filtered output Positions
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=50, deadline=None)
@given(
    st.dictionaries(
        # Symbol: alpha-only, 3-6 chars, uppercased.
        keys=st.text(
            alphabet=st.characters(min_codepoint=65, max_codepoint=90),
            min_size=3,
            max_size=6,
        ),
        values=st.fixed_dictionaries(
            {
                "size": st.decimals(
                    min_value=Decimal("0.0001"),
                    max_value=Decimal("1e6"),
                    places=8,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                "entry_price": st.decimals(
                    min_value=Decimal("0.01"),
                    max_value=Decimal("1e6"),
                    places=4,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            }
        ),
        min_size=0,
        max_size=10,
    )
)
def test_property_valid_records_round_trip_one_to_one(
    records_in: dict[str, dict[str, Decimal]],
) -> None:
    """For any non-empty, well-formed input, output cardinality equals input
    cardinality and per-symbol values round-trip exactly."""
    serialized: dict[str, dict[str, Any]] = {
        sym: {"size": str(rec["size"]), "entry_price": str(rec["entry_price"])}
        for sym, rec in records_in.items()
    }
    out = aggregate_records(serialized)
    assert len(out) == len(serialized)
    by_sym = {p.symbol: p for p in out}
    for sym, rec in records_in.items():
        assert by_sym[sym].size == rec["size"]
        assert by_sym[sym].entry_price == rec["entry_price"]


# ---------------------------------------------------------------------------
# (f) run_loop — periodic snapshot lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_loop_one_shot_with_running_flag(
    state: _JsonStateAdapter,
    aggregator: PositionAggregator,
) -> None:
    """A ``running`` flag set to False after one snapshot exits the loop cleanly."""

    class _OneShotFlag:
        def __init__(self) -> None:
            self.calls = 0

        def __bool__(self) -> bool:
            self.calls += 1
            # First check (entry): True; second check (after sleep): False → exit.
            return self.calls == 1

    flag = _OneShotFlag()
    await _seed_position(state, "AAPL", entry="150", size="2")
    await aggregator.run_loop(interval_s=0.0, running=flag)
    payload = await state.get(AGGREGATE_KEY)
    assert isinstance(payload, list)
    assert len(payload) == 1


@pytest.mark.asyncio
async def test_run_loop_swallows_snapshot_exception(
    aggregator: PositionAggregator,
    state: _JsonStateAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient snapshot failure must not crash the loop."""
    calls: list[int] = []

    class _OneShotFlag:
        def __init__(self) -> None:
            self.calls = 0

        def __bool__(self) -> bool:
            self.calls += 1
            return self.calls == 1

    async def _boom() -> int:
        calls.append(1)
        raise RuntimeError("simulated transient redis failure")

    monkeypatch.setattr(aggregator, "snapshot_to_redis", _boom)
    # Should not raise — the loop logs and exits when the flag flips False.
    await aggregator.run_loop(interval_s=0.0, running=_OneShotFlag())
    assert calls == [1]


# ---------------------------------------------------------------------------
# (g) Static module contract checks
# ---------------------------------------------------------------------------


def test_module_constants_are_stable_contracts() -> None:
    """Constants exposed by the module are part of the public contract."""
    assert PER_SYMBOL_KEY_PREFIX == "positions:"
    assert AGGREGATE_KEY == "portfolio:positions"
    assert DEFAULT_SNAPSHOT_INTERVAL_S == 15.0
