"""Service-level tests for the _safe() removal and FailClosedGuard wiring (Phase 5.1).

Covers:
    SD-3  _safe() grep audit (performed in CI; also asserted here via AST scan).
    SD-4  Execution order: FailClosedGuard.check BEFORE _load_context_parallel.
    SD-5  Startup order: eager heartbeat write BEFORE bus.subscribe(ORDER_CANDIDATE).

Plus targeted tests that each required Redis key triggers
``BlockReason.SYSTEM_UNAVAILABLE`` when missing — proving the heuristic
fallbacks are gone (ADR-0006 §D4).
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from core.models.order import OrderCandidate
from core.models.signal import Direction
from core.state import (
    REDIS_HEARTBEAT_KEY,
    SystemRiskMonitor,
    SystemRiskState,
)
from services.risk_manager.cb_event_guard import CBEventGuard
from services.risk_manager.circuit_breaker import CircuitBreaker
from services.risk_manager.fail_closed import FailClosedGuard
from services.risk_manager.meta_label_gate import MetaLabelGate
from services.risk_manager.models import BlockReason, RuleResult
from services.risk_manager.service import RiskManagerService


def _make_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class _TestableRiskManagerService(RiskManagerService):
    """Subclass that satisfies BaseService.run abstract method (same as test_risk_chain)."""

    async def run(self) -> None:
        pass  # not called in unit tests unless explicitly invoked


def _make_service(redis: fakeredis.aioredis.FakeRedis) -> RiskManagerService:
    """Build a wired RiskManagerService backed by fakeredis, without on_start."""
    from core.logger import get_logger
    from core.state import StateStore

    svc = _TestableRiskManagerService.__new__(_TestableRiskManagerService)
    svc.logger = get_logger("s05_test")
    svc.service_id = "risk_manager"

    svc.state = StateStore.__new__(StateStore)
    svc.state._service_id = "s05_test"
    svc.state._settings = MagicMock()
    svc.state._settings.redis_ttl_seconds = 3600
    svc.state._redis = redis

    svc.bus = MagicMock()
    svc.bus.publish = AsyncMock(return_value=None)
    svc.bus.subscribe = AsyncMock(return_value=None)

    svc._cb_guard = CBEventGuard(redis)
    svc._circuit_breaker = CircuitBreaker(redis)
    svc._meta_gate = MetaLabelGate(redis)
    svc._monitor = SystemRiskMonitor(redis, svc.bus)
    svc._fail_closed = FailClosedGuard(svc._monitor)
    svc._risk_heartbeat_task = None
    return svc


async def _seed_context(redis: fakeredis.aioredis.FakeRedis) -> None:
    await redis.set("portfolio:capital", json.dumps({"available": 100000}))
    await redis.set("pnl:daily", "0")
    await redis.set("pnl:intraday_30m", "0")
    await redis.set("macro:vix_current", "20.0")
    await redis.set("macro:vix_1h_ago", "20.0")
    await redis.set("portfolio:positions", "[]")
    await redis.set("correlation:matrix", "{}")
    await redis.set("session:current", json.dumps("us_normal"))
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=5)


def _order(symbol: str = "AAPL", kelly: float = 0.25) -> OrderCandidate:
    sz = Decimal("0.01")
    return OrderCandidate(
        order_id="o-nf",
        symbol=symbol,
        direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000,
        size=sz,
        size_scalp_exit=sz * Decimal("0.35"),
        size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal("150"),
        stop_loss=Decimal("148"),
        target_scalp=Decimal("153"),
        target_swing=Decimal("160"),
        capital_at_risk=Decimal("2"),
        kelly_fraction=kelly,
    )


# ── SD-3: _safe helper is gone from service.py (AST-level assertion) ─────────


def test_sd3_no_safe_helper_defined_in_service() -> None:
    """SD-3: ``_safe`` function/nested function is absent from service.py.

    A belt-and-braces complement to the CI grep audit; catches any renamed
    reintroduction like ``_safe_default`` or ``_safe_v2`` at the AST level.
    """
    import services.risk_manager.service as svc_mod

    source = inspect.getsource(svc_mod)
    tree = ast.parse(source)
    all_funcs: list[str] = []
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_funcs.append(node.name)
            if node.name.startswith("_safe"):
                offenders.append(node.name)
    # Sanity: confirm the AST walk actually ran. Without this check, a silent
    # TypeError inside the loop (e.g. the earlier PEP-604 bug) would make the
    # SD-3 guarantee cosmetic — the test would pass with zero inspections.
    assert len(all_funcs) > 0, (
        "AST walk found zero function definitions; the test is not actually scanning."
    )
    assert offenders == [], (
        f"ADR-0006 §D4 violation: found helper(s) matching ``_safe*`` in "
        f"services/risk_manager/service.py: {offenders}"
    )


def test_sd3_no_safe_call_expression_in_service() -> None:
    """SD-3: No ``_safe(...)`` call expression remains in service.py source."""
    import services.risk_manager.service as svc_mod

    source = inspect.getsource(svc_mod)
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id.startswith("_safe"):
                offenders.append(ast.unparse(node))
    assert offenders == [], (
        f"ADR-0006 §D4 violation: ``_safe(*)`` call expression present: {offenders}"
    )


# ── SD-4: execution order — FailClosedGuard BEFORE _load_context_parallel ────


@pytest.mark.asyncio
async def test_sd4_guard_check_runs_before_load_context_even_when_guard_passes() -> None:
    """SD-4: guard.check is called BEFORE _load_context_parallel.

    Setup: guard returns HEALTHY (forcing proceeding past STEP 0),
    _load_context_parallel mocked to raise. Expected: order REJECTED (because
    load raised), and call_order is [guard, load].
    """
    redis = _make_redis()
    svc = _make_service(redis)

    call_order: list[str] = []

    async def mock_check(order_id: str, symbol: str) -> tuple[SystemRiskState, RuleResult]:
        call_order.append("guard_check")
        return (
            SystemRiskState.HEALTHY,
            RuleResult.ok(rule_name="fail_closed_guard", reason="mocked healthy"),
        )

    async def mock_load(symbol: str) -> dict[str, Any]:
        call_order.append("load_context")
        raise RuntimeError("SD-4 forced context-load failure")

    svc._fail_closed.check = mock_check  # type: ignore[method-assign]
    svc._load_context_parallel = mock_load  # type: ignore[method-assign]

    decision = await svc.process_order_candidate(_order())

    assert decision.approved is False, "order must be rejected when load raises"
    assert decision.first_failure == BlockReason.SYSTEM_UNAVAILABLE
    assert call_order == ["guard_check", "load_context"], (
        f"SD-4: expected [guard_check, load_context], got {call_order}"
    )


@pytest.mark.asyncio
async def test_sd4_load_context_not_called_when_guard_rejects() -> None:
    """SD-4 negative: when guard rejects, _load_context_parallel is NEVER called.

    Verifies the O(1) short-circuit semantics promised by ADR-0006 §D3.
    """
    redis = _make_redis()
    svc = _make_service(redis)
    # No heartbeat → guard DEGRADED

    call_order: list[str] = []
    orig_load = svc._load_context_parallel

    async def tracked_load(symbol: str) -> dict[str, Any]:
        call_order.append("load_context")
        return await orig_load(symbol)

    svc._load_context_parallel = tracked_load  # type: ignore[method-assign]

    decision = await svc.process_order_candidate(_order())
    assert decision.approved is False
    assert decision.first_failure == BlockReason.SYSTEM_UNAVAILABLE
    assert "load_context" not in call_order, (
        "SD-4: _load_context_parallel must not run when guard rejects"
    )


# ── SD-5: startup order — eager heartbeat BEFORE subscribe ───────────────────


@pytest.mark.asyncio
async def test_sd5_eager_heartbeat_write_before_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SD-5: heartbeat is written BEFORE bus.subscribe(ORDER_CANDIDATE).

    This ordering is the fail-closed startup invariant (ADR-0006 Consequences):
    if subscribe landed before the first heartbeat write, the very first
    OrderCandidate could arrive while FailClosedGuard observes an absent
    heartbeat and rejects — a spurious startup-time rejection.
    """
    redis = _make_redis()

    # Build a minimally-wired RiskManagerService (NOT the testable subclass,
    # because we need the real run() method which calls on_start + subscribe).
    from core.logger import get_logger
    from core.state import StateStore

    svc = RiskManagerService.__new__(RiskManagerService)
    svc.logger = get_logger("s05_sd5")
    svc.service_id = "risk_manager"
    svc.state = StateStore.__new__(StateStore)
    svc.state._service_id = "s05_sd5"
    svc.state._settings = MagicMock()
    svc.state._settings.redis_ttl_seconds = 3600
    svc.state._redis = redis
    svc.bus = MagicMock()
    svc.bus.publish = AsyncMock(return_value=None)
    # Fields populated later by on_start
    svc._cb_guard = None
    svc._circuit_breaker = None
    svc._meta_gate = None
    svc._monitor = None
    svc._fail_closed = None
    svc._risk_heartbeat_task = None

    call_order: list[str] = []

    original_wh = SystemRiskMonitor.write_heartbeat

    async def tracked_wh(self: SystemRiskMonitor) -> None:
        call_order.append("heartbeat_write")
        await original_wh(self)

    async def tracked_loop(self: SystemRiskMonitor, interval: float = 2.0) -> None:
        # Prevent the background heartbeat loop from spinning forever in-test.
        return None

    monkeypatch.setattr(SystemRiskMonitor, "write_heartbeat", tracked_wh)
    monkeypatch.setattr(SystemRiskMonitor, "run_heartbeat_loop", tracked_loop)

    async def tracked_subscribe(topics: list[str], handler: object) -> None:
        call_order.append(f"subscribe:{topics}")

    svc.bus.subscribe = tracked_subscribe  # type: ignore[method-assign]

    await svc.run()

    assert "heartbeat_write" in call_order, f"no heartbeat_write observed: {call_order}"
    sub_events = [c for c in call_order if c.startswith("subscribe:")]
    assert sub_events, f"no subscribe observed: {call_order}"
    hb_idx = call_order.index("heartbeat_write")
    sub_idx = call_order.index(sub_events[0])
    assert hb_idx < sub_idx, (
        f"SD-5: heartbeat_write at {hb_idx} must precede subscribe at {sub_idx}. "
        f"call_order = {call_order}"
    )
    assert "order.candidate" in sub_events[0], (
        f"SD-5: subscribe topic must be ORDER_CANDIDATE; got {sub_events[0]}"
    )


@pytest.mark.asyncio
async def test_sd5_heartbeat_key_exists_after_on_start() -> None:
    """SD-5 evidence: risk:heartbeat Redis key is populated after on_start completes.

    Observable postcondition: a fresh OrderCandidate immediately after on_start
    should find HEALTHY state (not DEGRADED from a missing heartbeat).
    """
    redis = _make_redis()
    svc = _make_service(redis)
    await svc.on_start()
    # Heartbeat should now exist
    raw = await redis.get(REDIS_HEARTBEAT_KEY)
    assert raw is not None, "eager heartbeat write did not populate the key"
    # And parseable
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is not None


# ── _load_context_parallel raises on each missing required key ───────────────


@pytest.mark.parametrize(
    "missing_key",
    [
        "portfolio:capital",
        "pnl:daily",
        "pnl:intraday_30m",
        "macro:vix_current",
        "macro:vix_1h_ago",
        "portfolio:positions",
        "correlation:matrix",
        "session:current",
    ],
)
@pytest.mark.asyncio
async def test_load_context_raises_when_any_required_key_missing(
    missing_key: str,
) -> None:
    """_load_context_parallel raises RuntimeError when any one of the 8 keys is None.

    This is ADR-0006 §D4 invariant: no heuristic fallbacks. Missing key =
    raise = process_order_candidate converts to SYSTEM_UNAVAILABLE rejection.
    """
    redis = _make_redis()
    svc = _make_service(redis)
    await _seed_context(redis)
    await redis.delete(missing_key)

    with pytest.raises(RuntimeError, match=missing_key):
        await svc._load_context_parallel("AAPL")


@pytest.mark.asyncio
async def test_load_context_raises_on_malformed_capital_dict() -> None:
    """capital value without an ``available`` field → RuntimeError (no defaults)."""
    redis = _make_redis()
    svc = _make_service(redis)
    await _seed_context(redis)
    # Overwrite capital with a dict missing "available"
    await redis.set("portfolio:capital", json.dumps({"other": 123}))
    with pytest.raises(RuntimeError, match="portfolio:capital malformed"):
        await svc._load_context_parallel("AAPL")


@pytest.mark.asyncio
async def test_load_context_raises_on_malformed_positions() -> None:
    """positions value must be a list → RuntimeError on dict/string/etc."""
    redis = _make_redis()
    svc = _make_service(redis)
    await _seed_context(redis)
    await redis.set("portfolio:positions", json.dumps({"not": "a list"}))
    with pytest.raises(RuntimeError, match="portfolio:positions malformed"):
        await svc._load_context_parallel("AAPL")


@pytest.mark.asyncio
async def test_load_context_raises_on_invalid_session() -> None:
    """Unknown session string → RuntimeError (no silent fallback to US_NORMAL)."""
    redis = _make_redis()
    svc = _make_service(redis)
    await _seed_context(redis)
    await redis.set("session:current", json.dumps("not_a_real_session"))
    with pytest.raises(RuntimeError, match="session:current invalid"):
        await svc._load_context_parallel("AAPL")


@pytest.mark.asyncio
async def test_load_context_happy_path_produces_complete_dict() -> None:
    """Seeded context returns a fully-populated ctx dict (no None values)."""
    redis = _make_redis()
    svc = _make_service(redis)
    await _seed_context(redis)
    ctx = await svc._load_context_parallel("AAPL")
    for k in (
        "capital",
        "daily_pnl",
        "intraday_loss_30m",
        "vix_current",
        "vix_1h_ago",
        "positions",
        "correlation_matrix",
        "session",
    ):
        assert k in ctx, f"missing {k} in loaded context"
        assert ctx[k] is not None, f"None value for {k} in loaded context"


# ── process_order_candidate converts load failures to SYSTEM_UNAVAILABLE ─────


@pytest.mark.asyncio
async def test_process_order_rejects_on_load_failure_with_system_unavailable() -> None:
    """Any raise from _load_context_parallel → RiskDecision with SYSTEM_UNAVAILABLE."""
    redis = _make_redis()
    svc = _make_service(redis)
    # Seed only heartbeat so guard passes, leave context keys empty so load fails.
    await redis.set(REDIS_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=5)

    decision = await svc.process_order_candidate(_order())
    assert decision.approved is False
    assert decision.first_failure == BlockReason.SYSTEM_UNAVAILABLE
    # The rationale should record the load failure alongside the guard's ok.
    assert any("context load failed" in r for r in decision.rationale), decision.rationale
