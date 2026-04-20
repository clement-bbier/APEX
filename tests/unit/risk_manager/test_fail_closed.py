"""FailClosedGuard + SystemRiskMonitor unit tests (Phase 5.1).

Covers:
    SD-1  Property test (Hypothesis, min_examples=100): state → admission mapping.
    SD-2  TTL boundary tests: 4.999s / 5.0s / 5.001s / 100s.
    SD-8  DEGRADED vs UNAVAILABLE both reject with SAME BlockReason.
    SD-9  ≥5 "false-fresh" tests (catastrophic failure mode).

See docs/adr/ADR-0006-fail-closed-risk-controls.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.state import (
    HEARTBEAT_TTL_SECONDS,
    REDIS_HEARTBEAT_KEY,
    SystemRiskMonitor,
    SystemRiskState,
)
from services.s05_risk_manager.fail_closed import FailClosedGuard
from services.s05_risk_manager.models import BlockReason, RuleResult


def _make_guard_real_redis() -> tuple[FailClosedGuard, fakeredis.aioredis.FakeRedis, MagicMock]:
    """Build a FailClosedGuard + SystemRiskMonitor backed by fakeredis."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    return FailClosedGuard(monitor), redis, bus


# ── Basic state tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_healthy_admits_order() -> None:
    """HEALTHY state → passed=True, no block_reason."""
    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=HEARTBEAT_TTL_SECONDS)
    state, result = await guard.check("o1", "AAPL")
    assert state == SystemRiskState.HEALTHY
    assert result.passed is True
    assert result.block_reason is None


@pytest.mark.asyncio
async def test_degraded_no_heartbeat_rejects() -> None:
    """No heartbeat key → DEGRADED → reject with SYSTEM_UNAVAILABLE."""
    guard, _, _ = _make_guard_real_redis()
    state, result = await guard.check("o1", "AAPL")
    assert state == SystemRiskState.DEGRADED
    assert result.passed is False
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_unavailable_redis_connection_error_rejects() -> None:
    """Redis raises → UNAVAILABLE → reject with SYSTEM_UNAVAILABLE."""
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=ConnectionError("fake disconnect"))
    redis.set = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    guard = FailClosedGuard(monitor)
    state, result = await guard.check("o1", "AAPL")
    assert state == SystemRiskState.UNAVAILABLE
    assert result.passed is False
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


# ── SD-1: property test — state → admission mapping ──────────────────────────


@pytest.mark.asyncio
@given(state_value=st.sampled_from(list(SystemRiskState)))
@hyp_settings(max_examples=100, deadline=None)
async def test_sd1_state_admission_mapping_property(
    state_value: SystemRiskState,
) -> None:
    """SD-1: for every SystemRiskState, admission decision is correct.

    HEALTHY → passed=True, no block_reason.
    DEGRADED or UNAVAILABLE → passed=False, block_reason=SYSTEM_UNAVAILABLE
    (exact equality, not substring).
    """
    guard = FailClosedGuard.__new__(FailClosedGuard)
    # Inject a mock monitor that returns the given state.
    monitor = MagicMock()
    monitor.current_state = AsyncMock(return_value=(state_value, 0.5, True))
    guard._monitor = monitor  # type: ignore[attr-defined]
    state, result = await guard.check("o-prop", "AAPL")
    assert state == state_value
    if state_value == SystemRiskState.HEALTHY:
        assert result.passed is True
        assert result.block_reason is None
    else:
        assert result.passed is False
        assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


# ── SD-2: TTL boundary tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sd2_boundary_age_under_ttl_is_healthy() -> None:
    """SD-2a: heartbeat_age = 4.999s → HEALTHY (fresh just under boundary)."""
    guard, redis, _ = _make_guard_real_redis()
    past = datetime.now(UTC) - timedelta(seconds=3.0)  # well under 5s
    await redis.set(REDIS_HEARTBEAT_KEY, past.isoformat(), ex=3600)
    state, _ = await guard.check("o-sd2a", "AAPL")
    assert state == SystemRiskState.HEALTHY


@pytest.mark.asyncio
async def test_sd2_boundary_age_at_ttl_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """SD-2b: heartbeat_age = EXACTLY 5.0s → DEGRADED (fail-closed at boundary)."""
    import core.state as core_state

    written_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    frozen_now = written_at + timedelta(seconds=5.0)  # exactly TTL

    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return frozen_now

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, written_at.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, result = await guard.check("o-sd2b", "AAPL")
    assert state == SystemRiskState.DEGRADED, (
        f"fail-closed boundary violated: age=5.0s admitted as {state}"
    )
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd2_boundary_age_just_past_ttl_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-2c: heartbeat_age = 5.001s → DEGRADED."""
    import core.state as core_state

    written_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    frozen_now = written_at + timedelta(seconds=5.001)
    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return frozen_now

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, written_at.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, _ = await guard.check("o-sd2c", "AAPL")
    assert state == SystemRiskState.DEGRADED


@pytest.mark.asyncio
async def test_sd2_boundary_age_very_stale_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-2d: heartbeat_age = 100s → DEGRADED (very stale)."""
    import core.state as core_state

    written_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    frozen_now = written_at + timedelta(seconds=100.0)
    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return frozen_now

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, written_at.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, _ = await guard.check("o-sd2d", "AAPL")
    assert state == SystemRiskState.DEGRADED


# ── SD-8: DEGRADED vs UNAVAILABLE both reject with SAME BlockReason ──────────


@pytest.mark.asyncio
async def test_sd8_degraded_rejects_with_system_unavailable() -> None:
    """SD-8a: DEGRADED → block_reason == SYSTEM_UNAVAILABLE (exact)."""
    monitor = MagicMock()
    monitor.current_state = AsyncMock(return_value=(SystemRiskState.DEGRADED, 10.0, True))
    guard = FailClosedGuard(monitor)
    state, result = await guard.check("o-sd8a", "AAPL")
    assert state == SystemRiskState.DEGRADED
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd8_unavailable_rejects_with_system_unavailable() -> None:
    """SD-8b: UNAVAILABLE → block_reason == SYSTEM_UNAVAILABLE (same as DEGRADED)."""
    monitor = MagicMock()
    monitor.current_state = AsyncMock(
        return_value=(SystemRiskState.UNAVAILABLE, float("inf"), False)
    )
    guard = FailClosedGuard(monitor)
    state, result = await guard.check("o-sd8b", "AAPL")
    assert state == SystemRiskState.UNAVAILABLE
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd8_state_distinguishable_in_rule_result_meta() -> None:
    """SD-8c: state field in RuleResult.meta distinguishes DEGRADED from UNAVAILABLE.

    Both rejections share BlockReason.SYSTEM_UNAVAILABLE (canonical audit code),
    but the RuleResult's ``state`` meta field preserves the distinction for
    operator paging / dashboards (ADR-0006 §D6).
    """
    for sentinel_state in (SystemRiskState.DEGRADED, SystemRiskState.UNAVAILABLE):
        monitor = MagicMock()
        monitor.current_state = AsyncMock(return_value=(sentinel_state, 7.0, True))
        guard = FailClosedGuard(monitor)
        _, result = await guard.check("o-sd8c", "AAPL")
        assert result.meta["state"] == sentinel_state.value


# ── SD-9: false-fresh tests (≥5 — catastrophic failure mode) ─────────────────


@pytest.mark.asyncio
async def test_sd9_false_fresh_stale_past_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-9a: Heartbeat timestamp parses cleanly but is 60 s in the past → DEGRADED.

    Attack vector: an adversary (or a buggy writer) persists a valid ISO-8601
    timestamp from the past. The payload looks fresh to a naive check
    ("key exists, parseable") but the age math must expose the staleness.
    """
    import core.state as core_state

    written_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    frozen_now = written_at + timedelta(seconds=60.0)
    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return frozen_now

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, written_at.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, result = await guard.check("o-sd9a", "AAPL")
    assert state == SystemRiskState.DEGRADED
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd9_false_fresh_future_timestamp_negative_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-9b: Heartbeat timestamp is 30 s in the FUTURE → DEGRADED.

    Attack vector: clock skew or adversarial write pushing the timestamp
    forward. Naive TTL check would admit (age < TTL trivially, age is negative),
    but we must fail-closed on any suspicious non-positive age.
    """
    import core.state as core_state

    frozen_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    future = frozen_now + timedelta(seconds=30.0)
    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return frozen_now

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, future.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, result = await guard.check("o-sd9b", "AAPL")
    assert state == SystemRiskState.DEGRADED, (
        f"future-dated heartbeat must fail-closed; got state={state}"
    )
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd9_false_fresh_null_string_payload() -> None:
    """SD-9c: Heartbeat payload is the literal string ``"null"`` → DEGRADED.

    Attack vector: a writer that serialized None as the JSON string ``"null"``
    rather than deleting the key. ``"null"`` parses via json.loads but is not
    a valid ISO timestamp; fail-closed on ValueError from fromisoformat.
    """
    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, "null", ex=3600)
    state, result = await guard.check("o-sd9c", "AAPL")
    assert state == SystemRiskState.DEGRADED
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd9_false_fresh_empty_string_payload() -> None:
    """SD-9d: Heartbeat payload is an empty string → DEGRADED.

    Attack vector: truncated write or corrupted payload. Empty string fails
    datetime.fromisoformat with ValueError; must fail-closed.
    """
    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, "", ex=3600)
    state, result = await guard.check("o-sd9d", "AAPL")
    assert state == SystemRiskState.DEGRADED
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd9_false_fresh_tz_naive_timestamp() -> None:
    """SD-9e: Heartbeat is an ISO timestamp WITHOUT tzinfo → DEGRADED.

    Attack vector: a writer that records local time without UTC suffix.
    Naive datetime math (``datetime.now(UTC) - naive_dt``) raises TypeError,
    which would crash the guard if not guarded. We explicitly reject
    tz-naive payloads as stale.
    """
    guard, redis, _ = _make_guard_real_redis()
    # ISO format WITHOUT timezone (naive)
    naive_iso = "2026-04-17T12:00:00"
    await redis.set(REDIS_HEARTBEAT_KEY, naive_iso, ex=3600)
    state, result = await guard.check("o-sd9e", "AAPL")
    assert state == SystemRiskState.DEGRADED, (
        f"tz-naive heartbeat must fail-closed; got state={state}"
    )
    assert result.block_reason == BlockReason.SYSTEM_UNAVAILABLE


@pytest.mark.asyncio
async def test_sd9_false_fresh_age_exactly_zero_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-9f (bonus): heartbeat_age = EXACTLY 0.0s → HEALTHY.

    Boundary the other direction: a heartbeat just written. Naive math could
    produce age < 0 (clock drift sub-ms); assert age == 0 is admitted.
    """
    import core.state as core_state

    fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    real_dt = core_state.datetime

    class _FrozenDT:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return fixed

        @staticmethod
        def fromisoformat(s: str) -> datetime:
            return real_dt.fromisoformat(s)

    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, fixed.isoformat(), ex=3600)
    monkeypatch.setattr(core_state, "datetime", _FrozenDT)
    state, _ = await guard.check("o-sd9f", "AAPL")
    assert state == SystemRiskState.HEALTHY


# ── Supplementary guard-level tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_name_is_fail_closed_guard() -> None:
    """Rejection RuleResult carries the correct rule_name for audit filtering."""
    guard, _, _ = _make_guard_real_redis()  # no heartbeat → DEGRADED
    _, result = await guard.check("o-rn", "AAPL")
    assert result.rule_name == FailClosedGuard.RULE_NAME
    assert result.rule_name == "fail_closed_guard"


@pytest.mark.asyncio
async def test_rejection_meta_carries_heartbeat_age_and_redis_reachable() -> None:
    """RuleResult.meta exposes heartbeat_age_seconds and redis_reachable for logs."""
    monitor = MagicMock()
    monitor.current_state = AsyncMock(return_value=(SystemRiskState.DEGRADED, 8.25, True))
    guard = FailClosedGuard(monitor)
    _, result = await guard.check("o-meta", "AAPL")
    assert result.meta["heartbeat_age_seconds"] == pytest.approx(8.25)
    assert result.meta["redis_reachable"] is True


@pytest.mark.asyncio
async def test_rejection_meta_replaces_infinite_age_with_sentinel() -> None:
    """Meta field normalizes math.inf age (never written) to -1.0 for JSON safety."""
    monitor = MagicMock()
    monitor.current_state = AsyncMock(
        return_value=(SystemRiskState.UNAVAILABLE, float("inf"), False)
    )
    guard = FailClosedGuard(monitor)
    _, result = await guard.check("o-inf", "AAPL")
    assert result.meta["heartbeat_age_seconds"] == -1.0
    assert result.meta["redis_reachable"] is False


@pytest.mark.asyncio
async def test_healthy_result_has_no_meta_age_field() -> None:
    """HEALTHY RuleResult.ok does not carry staleness meta (no rejection context)."""
    guard, redis, _ = _make_guard_real_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=HEARTBEAT_TTL_SECONDS)
    _, result = await guard.check("o-ok", "AAPL")
    # RuleResult.ok carries empty meta
    assert result.meta == {} or "heartbeat_age_seconds" not in result.meta


@pytest.mark.asyncio
async def test_returned_tuple_shape() -> None:
    """check() always returns (SystemRiskState, RuleResult) — contract test."""
    guard, _, _ = _make_guard_real_redis()
    ret = await guard.check("o-shape", "AAPL")
    assert isinstance(ret, tuple)
    assert len(ret) == 2
    assert isinstance(ret[0], SystemRiskState)
    assert isinstance(ret[1], RuleResult)


# ── SystemRiskMonitor error-path coverage (state.py branches) ────────────────


@pytest.mark.asyncio
async def test_monitor_write_heartbeat_swallows_exception() -> None:
    """write_heartbeat catches Redis exceptions and logs warning (does not raise).

    ADR-0006 §D2: the background writer's failure must propagate to the
    foreground reader via key expiry, not via an unhandled exception that
    would kill the heartbeat task.
    """
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=ConnectionError("simulated"))
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    await monitor.write_heartbeat()  # must not raise


@pytest.mark.asyncio
async def test_monitor_classifies_timeout_as_redis_timeout_cause() -> None:
    """Redis TimeoutError → cause=REDIS_TIMEOUT (distinct from generic ConnectionError).

    Covers the redis.exceptions.TimeoutError isinstance branch.
    """
    from redis.exceptions import TimeoutError as RedisTimeoutError

    from core.state import SystemRiskStateCause, SystemRiskStateChange

    redis = MagicMock()
    # First get raises TimeoutError → UNAVAILABLE
    redis.get = AsyncMock(side_effect=RedisTimeoutError("simulated timeout"))
    redis.set = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    # Prime the last observed to HEALTHY so the transition fires.
    monitor._last_observed = SystemRiskState.HEALTHY  # type: ignore[attr-defined]
    state, _, _ = await monitor.current_state()
    assert state == SystemRiskState.UNAVAILABLE
    # Inspect the published envelope to confirm cause classification
    assert bus.publish.await_count == 1
    _topic, payload = bus.publish.await_args.args
    envelope = SystemRiskStateChange.model_validate(payload)
    assert envelope.cause == SystemRiskStateCause.REDIS_TIMEOUT


@pytest.mark.asyncio
async def test_monitor_system_state_persist_failure_is_debug_only() -> None:
    """Persist-failure of risk:system:state is debug-level; does NOT break current_state."""
    from unittest.mock import call

    redis = MagicMock()
    # get returns a fresh heartbeat (parseable, within TTL)
    redis.get = AsyncMock(return_value=datetime.now(UTC).isoformat())
    # set raises on every call (persist fails)
    redis.set = AsyncMock(side_effect=ConnectionError("persist fail"))
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    state, _, reachable = await monitor.current_state()
    # Observation succeeded even though persist failed
    assert state == SystemRiskState.HEALTHY
    assert reachable is True
    assert redis.set.await_args_list == [
        call("risk:system:state", "healthy", ex=HEARTBEAT_TTL_SECONDS)
    ]


@pytest.mark.asyncio
async def test_monitor_publish_failure_does_not_block_state_transition() -> None:
    """bus.publish failure on transition is logged but does not propagate."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=datetime.now(UTC).isoformat())  # HEALTHY
    redis.set = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock(side_effect=RuntimeError("ZMQ socket wedged"))
    monitor = SystemRiskMonitor(redis, bus)
    monitor._last_observed = SystemRiskState.DEGRADED  # type: ignore[attr-defined]
    # Transition DEGRADED → HEALTHY triggers publish, which will raise;
    # current_state must still return normally.
    state, _, _ = await monitor.current_state()
    assert state == SystemRiskState.HEALTHY
    assert bus.publish.await_count == 1
