"""Chaos tests for FailClosedGuard (Phase 5.1).

Covers:
    SD-6  Redis killed mid-stream: 100% rejection for post-kill iterations,
          parametrized across multiple K values (N=100 orders per run).
    SD-7  Heartbeat TTL expiry + recovery: DEGRADED → all-reject;
          fresh heartbeat → HEALTHY → no SYSTEM_UNAVAILABLE rejections.

These tests exercise the fail-closed contract end-to-end at the
``FailClosedGuard`` level (not the whole service chain). The chain-level
chaos tests in ``test_service_no_fallbacks.py`` cover the
``process_order_candidate`` error path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from core.state import REDIS_HEARTBEAT_KEY, SystemRiskMonitor, SystemRiskState
from services.risk_manager.fail_closed import FailClosedGuard
from services.risk_manager.models import BlockReason


def _make_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _make_guard(
    redis: fakeredis.aioredis.FakeRedis,
) -> tuple[FailClosedGuard, SystemRiskMonitor, MagicMock]:
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    guard = FailClosedGuard(monitor)
    return guard, monitor, bus


# ── SD-6: Redis killed at iteration K → 100 % rejection post-K ───────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("kill_iter", [17, 53, 82])
async def test_sd6_chaos_redis_killed_mid_stream(
    kill_iter: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SD-6 Chaos #1: Redis killed at iter K → 100 % SYSTEM_UNAVAILABLE post-K.

    Submits 100 OrderCandidates through FailClosedGuard. At the transition
    kill_iter → kill_iter+1, ``redis.get`` is replaced with a callable that
    raises ``ConnectionError``. Asserts:

    * Iterations ≤ kill_iter: admitted (HEALTHY, heartbeat fresh).
    * Iterations > kill_iter: 100 % rejected with ``SYSTEM_UNAVAILABLE``.
    * Sanity: 0 < n_admitted < 100 (kill fired AND setup was not empty).

    Three kill_iter values (17, 53, 82) parametrize the kill point across
    early, middle, and late iterations.
    """
    n_orders = 100
    redis = _make_redis()
    # Seed a fresh heartbeat so pre-kill iterations observe HEALTHY.
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=60)

    guard, _, _ = _make_guard(redis)

    results: list[dict[str, object]] = []
    killed = False
    for i in range(1, n_orders + 1):
        if not killed and i == kill_iter + 1:

            async def dead_get(*args: object, **kwargs: object) -> None:
                raise ConnectionError(f"SD-6 simulated Redis kill at iter {kill_iter}")

            redis.get = dead_get  # type: ignore[method-assign]
            killed = True

        state, result = await guard.check(f"o{i}", "AAPL")
        results.append(
            {
                "iter": i,
                "state": state,
                "passed": result.passed,
                "block_reason": result.block_reason,
            }
        )

    pre = [r for r in results if r["iter"] <= kill_iter]  # type: ignore[operator]
    post = [r for r in results if r["iter"] > kill_iter]  # type: ignore[operator]
    n_admitted = sum(1 for r in results if r["passed"])
    n_rejected = n_orders - n_admitted

    # Report counts so CI/human observers can sanity-check the kill fired.
    print(
        f"\nSD-6 kill_iter={kill_iter}: n_admitted={n_admitted}, "
        f"n_rejected={n_rejected}, pre_kill={len(pre)}, post_kill={len(post)}"
    )

    # Post-kill: 100 % rejection with SYSTEM_UNAVAILABLE.
    post_admitted = sum(1 for r in post if r["passed"])
    assert post_admitted == 0, (
        f"SD-6 kill_iter={kill_iter}: {post_admitted} post-kill admitted (expected 0)"
    )
    for r in post:
        assert r["block_reason"] == BlockReason.SYSTEM_UNAVAILABLE, (
            f"SD-6 kill_iter={kill_iter} iter={r['iter']}: "
            f"block_reason={r['block_reason']}, expected SYSTEM_UNAVAILABLE"
        )

    # Sanity: kill fired AND setup wasn't empty.
    assert 0 < n_admitted < n_orders, (
        f"SD-6 kill_iter={kill_iter}: expected 0 < n_admitted ({n_admitted}) "
        f"< {n_orders}. kill_fired={n_admitted < n_orders}, "
        f"setup_ok={n_admitted > 0}"
    )
    # Exactly kill_iter pre-kill iterations should have been admitted.
    assert n_admitted == kill_iter, (
        f"SD-6 kill_iter={kill_iter}: expected exactly {kill_iter} admitted, "
        f"got {n_admitted}. pre-kill iterations should observe HEALTHY."
    )


# ── SD-7: heartbeat TTL expiry + recovery ────────────────────────────────────


@pytest.mark.asyncio
async def test_sd7_chaos_heartbeat_expiry_and_recovery() -> None:
    """SD-7 Chaos #2: heartbeat expires → 50 orders rejected → recovery → 50 admitted.

    Phase 1: write heartbeat with TTL=1 s, sleep 1.5 s past expiry, verify state
    is DEGRADED, submit 50 orders → all 50 rejected with SYSTEM_UNAVAILABLE.

    Phase 2: write a fresh heartbeat, verify state is HEALTHY, submit 50 orders
    → NONE rejected with SYSTEM_UNAVAILABLE (they may be rejected by a
    downstream rule in a full chain, but at this guard-only level they should
    simply pass). This proves the DEGRADED → HEALTHY recovery path works.
    """
    redis = _make_redis()
    guard, monitor, _ = _make_guard(redis)

    # ── Phase 1: expiry ──
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=1)
    await asyncio.sleep(1.5)  # wait past TTL

    state, age, _ = await monitor.current_state()
    assert state == SystemRiskState.DEGRADED, (
        f"expected DEGRADED after TTL expiry, got {state} (age={age})"
    )

    pre_rejections = 0
    for i in range(50):
        _, result = await guard.check(f"pre_{i}", "AAPL")
        if not result.passed and result.block_reason == BlockReason.SYSTEM_UNAVAILABLE:
            pre_rejections += 1
    assert pre_rejections == 50, f"expected 50 rejections, got {pre_rejections}"

    # ── Phase 2: recovery ──
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=5)

    state, _, _ = await monitor.current_state()
    assert state == SystemRiskState.HEALTHY, f"expected HEALTHY after fresh heartbeat, got {state}"

    post_sys_unavail = 0
    post_admitted = 0
    for i in range(50):
        _, result = await guard.check(f"post_{i}", "AAPL")
        if result.block_reason == BlockReason.SYSTEM_UNAVAILABLE:
            post_sys_unavail += 1
        if result.passed:
            post_admitted += 1
    assert post_sys_unavail == 0, (
        f"SD-7: expected 0 SYSTEM_UNAVAILABLE rejections post-recovery, "
        f"got {post_sys_unavail}. DEGRADED → HEALTHY recovery path is broken."
    )
    assert post_admitted == 50, (
        f"SD-7: expected all 50 post-recovery orders admitted, got {post_admitted}"
    )


# ── Additional chaos edge cases ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chaos_flapping_redis_connection() -> None:
    """Redis flapping (UP/DOWN alternating) → state tracks the actual connectivity.

    No spurious stuck-in-one-state bug: each check reflects the current Redis
    reachability, not the previous observation.
    """
    redis = _make_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=60)
    _, monitor, _ = _make_guard(redis)

    original_get = redis.get
    toggle = {"n": 0}

    async def flaky_get(*args: object, **kwargs: object) -> object:
        toggle["n"] += 1
        if toggle["n"] % 2 == 0:
            raise ConnectionError("flap")
        return await original_get(*args, **kwargs)

    redis.get = flaky_get  # type: ignore[method-assign]

    # Alternate HEALTHY / UNAVAILABLE
    observed: list[SystemRiskState] = []
    for _ in range(6):
        state, _, _ = await monitor.current_state()
        observed.append(state)

    # Odd indices (1st, 3rd, 5th) → HEALTHY; even → UNAVAILABLE
    for i, state in enumerate(observed):
        if i % 2 == 0:  # 1st, 3rd, 5th call in 1-indexed counting
            assert state == SystemRiskState.HEALTHY, f"index {i}: {state}"
        else:
            assert state == SystemRiskState.UNAVAILABLE, f"index {i}: {state}"


@pytest.mark.asyncio
async def test_chaos_rapid_fire_many_orders_all_consistent() -> None:
    """1000 orders fired back-to-back while state is stable → all consistent.

    Stress/soak test to ensure no intermediate race produces an inconsistent
    admission decision. With heartbeat fresh and no Redis failures, every
    order must be admitted.
    """
    redis = _make_redis()
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=60)
    guard, _, _ = _make_guard(redis)

    admitted = 0
    for i in range(1000):
        _, result = await guard.check(f"rapid_{i}", "AAPL")
        if result.passed:
            admitted += 1
    assert admitted == 1000, f"expected 1000 admitted, got {admitted}"


@pytest.mark.asyncio
async def test_chaos_many_orders_while_dead_all_rejected() -> None:
    """500 orders fired with Redis dead → all 500 rejected with SYSTEM_UNAVAILABLE."""
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=ConnectionError("dead from start"))
    redis.set = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    monitor = SystemRiskMonitor(redis, bus)
    guard = FailClosedGuard(monitor)

    rejections = 0
    for i in range(500):
        _, result = await guard.check(f"dead_{i}", "AAPL")
        if not result.passed and result.block_reason == BlockReason.SYSTEM_UNAVAILABLE:
            rejections += 1
    assert rejections == 500, f"expected 500 rejections, got {rejections}"
