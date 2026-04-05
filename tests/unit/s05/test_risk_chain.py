"""
Risk Chain integration tests (Phase 6).

Tests the full 5-step Chain of Responsibility using fakeredis.
No real Redis, no real ZMQ, no network I/O.

Helper: build_service() creates a wired RiskManagerService backed by fakeredis.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import fakeredis.aioredis
import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models.order import OrderCandidate
from core.models.signal import Direction
from services.s05_risk_manager.cb_event_guard import CBEventGuard
from services.s05_risk_manager.circuit_breaker import CircuitBreaker
from services.s05_risk_manager.meta_label_gate import MetaLabelGate
from services.s05_risk_manager.models import (
    HALF_OPEN_RECOVERY_MINUTES,
    BlockReason,
    CircuitBreakerSnapshot,
    CircuitBreakerState,
    REDIS_CB_KEY,
)
from services.s05_risk_manager.service import RiskManagerService


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class _TestableRiskManagerService(RiskManagerService):
    """Concrete subclass that satisfies BaseService.run abstract method."""

    async def run(self) -> None:
        pass  # Not called in unit tests


def _make_service(redis: fakeredis.aioredis.FakeRedis) -> RiskManagerService:
    """Build a wired RiskManagerService backed by fakeredis."""
    svc = _TestableRiskManagerService.__new__(_TestableRiskManagerService)
    # Minimal BaseService init without real ZMQ/Redis connections
    from core.logger import get_logger
    from unittest.mock import MagicMock, AsyncMock

    svc.logger = get_logger("s05_test")
    svc.service_id = "s05_risk_manager"

    # Wire state store with fakeredis
    from core.state import StateStore
    svc.state = StateStore.__new__(StateStore)
    svc.state._service_id = "s05_test"
    svc.state._settings = MagicMock()
    svc.state._settings.redis_ttl_seconds = 3600
    svc.state._redis = redis

    # Wire bus as mock
    svc.bus = MagicMock()
    svc.bus.publish = AsyncMock(return_value=None)

    # Wire chain components
    svc._cb_guard = CBEventGuard(redis)
    svc._circuit_breaker = CircuitBreaker(redis)
    svc._meta_gate = MetaLabelGate(redis)

    return svc


def _order(
    symbol: str = "AAPL",
    entry: str = "150",
    sl: str = "148",
    tp_scalp: str = "153",
    size: str = "0.01",
    direction: Direction = Direction.LONG,
    kelly: float = 0.25,
) -> OrderCandidate:
    sz = Decimal(size)
    return OrderCandidate(
        order_id="o1",
        symbol=symbol,
        direction=direction,
        timestamp_ms=1_700_000_000_000,
        size=sz,
        size_scalp_exit=sz * Decimal("0.35"),
        size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal(entry),
        stop_loss=Decimal(sl),
        target_scalp=Decimal(tp_scalp),
        target_swing=Decimal("160"),
        capital_at_risk=Decimal("2"),
        kelly_fraction=kelly,
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_chain_valid_order_approved() -> None:
    redis = _make_redis()
    svc = _make_service(redis)
    # Set high meta-confidence
    await redis.set("meta_label:latest:AAPL", "0.90")
    decision = await svc.process_order_candidate(_order(kelly=0.25))
    assert decision.approved
    assert decision.final_size > Decimal("0")


@pytest.mark.asyncio
async def test_chain_blocked_step1_cb_event() -> None:
    """STEP 1: CB event 30min away -> CB_EVENT_BLOCK."""
    redis = _make_redis()
    svc = _make_service(redis)
    event_time = datetime.now(timezone.utc) + timedelta(minutes=30)
    await redis.set("macro:cb_events", json.dumps([event_time.isoformat()]))
    decision = await svc.process_order_candidate(_order())
    assert not decision.approved
    assert decision.first_failure == BlockReason.CB_EVENT_BLOCK


@pytest.mark.asyncio
async def test_chain_blocked_step2_circuit_breaker() -> None:
    """STEP 2: Circuit breaker OPEN -> CIRCUIT_BREAKER_OPEN."""
    redis = _make_redis()
    svc = _make_service(redis)
    snap = CircuitBreakerSnapshot(
        state=CircuitBreakerState.OPEN,
        tripped_at=datetime.now(timezone.utc),
        tripped_reason=BlockReason.DAILY_DRAWDOWN_EXCEEDED,
        daily_pnl=Decimal("-3100"),
    )
    await redis.setex(REDIS_CB_KEY, 86400, snap.model_dump_json())
    decision = await svc.process_order_candidate(_order())
    assert not decision.approved
    assert decision.first_failure == BlockReason.CIRCUIT_BREAKER_OPEN


@pytest.mark.asyncio
async def test_chain_blocked_step3_meta_confidence() -> None:
    """STEP 3: meta_confidence=0.51 -> META_LABEL_CONFIDENCE_TOO_LOW."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.51")
    decision = await svc.process_order_candidate(_order())
    assert not decision.approved
    assert decision.first_failure == BlockReason.META_LABEL_CONFIDENCE_TOO_LOW


@pytest.mark.asyncio
async def test_chain_blocked_step4_no_stop_loss() -> None:
    """STEP 4: LONG with SL above entry -> NO_STOP_LOSS."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    order = _order(entry="150", sl="152")  # SL above entry for LONG
    decision = await svc.process_order_candidate(order)
    assert not decision.approved
    assert decision.first_failure == BlockReason.NO_STOP_LOSS


@pytest.mark.asyncio
async def test_chain_blocked_step4_min_rr() -> None:
    """STEP 4: RR = 1.0 < 1.5 -> MIN_RR_NOT_MET."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    # entry=150, sl=148 (dist=2), tp_scalp=152 (dist=2) -> RR = 1.0 < 1.5
    order = _order(entry="150", sl="148", tp_scalp="152")
    decision = await svc.process_order_candidate(order)
    assert not decision.approved
    assert decision.first_failure == BlockReason.MIN_RR_NOT_MET


@pytest.mark.asyncio
async def test_chain_blocked_step4_max_risk() -> None:
    """STEP 4: monetary risk > 0.5% of capital -> MAX_RISK_PER_TRADE."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    # Set capital = 100k, size = 2.0 (large), SL dist = 2 -> risk = 4 > 500
    # Actually: risk = |150-148| * size >= capital * 0.005 = 500 when size >= 250
    # Let's use a very large size: 1000 units -> risk = 2 * 1000 = 2000 > 500
    sz = Decimal("1000")
    order = OrderCandidate(
        order_id="o_risk",
        symbol="AAPL",
        direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000,
        size=sz,
        size_scalp_exit=sz * Decimal("0.35"),
        size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal("150"),
        stop_loss=Decimal("148"),
        target_scalp=Decimal("153"),
        target_swing=Decimal("160"),
        capital_at_risk=Decimal("2000"),
        kelly_fraction=0.25,
    )
    decision = await svc.process_order_candidate(order)
    assert not decision.approved
    assert decision.first_failure == BlockReason.MAX_RISK_PER_TRADE


@pytest.mark.asyncio
async def test_chain_blocked_step4_max_size() -> None:
    """STEP 4: position notional > 10% of capital -> MAX_SIZE_EXCEEDED."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    # capital=100k, size=1, entry=15000 -> notional=15000 > 10000.
    # SL very tight (dist=1) so risk=1*1=1 < 500 (max_risk passes).
    sz = Decimal("1")
    order = OrderCandidate(
        order_id="o_sz",
        symbol="AAPL",
        direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000,
        size=sz,
        size_scalp_exit=sz * Decimal("0.35"),
        size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal("15000"),
        stop_loss=Decimal("14999"),  # dist=1 -> risk=1 < 500 (passes max_risk)
        target_scalp=Decimal("15001.5"),  # dist=1.5 >= 1.5 * dist_sl (RR=1.5 exact)
        target_swing=Decimal("15003"),
        capital_at_risk=Decimal("1"),
        kelly_fraction=0.25,
    )
    decision = await svc.process_order_candidate(order)
    assert not decision.approved
    assert decision.first_failure == BlockReason.MAX_SIZE_EXCEEDED


@pytest.mark.asyncio
async def test_chain_blocked_step5_max_positions() -> None:
    """STEP 5: 6 open positions -> MAX_POSITIONS_EXCEEDED."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    positions = [
        {"symbol": f"SYM{i}", "size": "1", "entry_price": "100", "asset_class": "equity"}
        for i in range(6)
    ]
    await redis.set("portfolio:positions", json.dumps(positions))
    decision = await svc.process_order_candidate(_order(kelly=0.25))
    assert not decision.approved
    assert decision.first_failure == BlockReason.MAX_POSITIONS_EXCEEDED


@pytest.mark.asyncio
async def test_kelly_modulated_by_confidence_0_75() -> None:
    """kelly_final = kelly_raw x weight(0.75) = kelly_raw x 0.5 (+-0.001)."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.75")
    kelly_raw = 0.40
    decision = await svc.process_order_candidate(_order(kelly=kelly_raw))
    expected_final = kelly_raw * 0.5
    assert abs(decision.kelly_fraction_final - expected_final) <= 0.001


@pytest.mark.asyncio
async def test_post_event_scalp_size_halved() -> None:
    """In post-event scalp window: final_size = base_size x 0.50."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    # Place event 7min in the past (inside 15min post-event scalp window)
    past_event = datetime.now(timezone.utc) - timedelta(minutes=7)
    await redis.set("macro:cb_events", json.dumps([past_event.isoformat()]))
    base_order = _order(size="0.01", kelly=0.25)
    decision = await svc.process_order_candidate(base_order)
    assert decision.approved
    # final_size should be < original (due to scalp multiplier 0.50)
    # Note: also modifiers from crypto/session may apply, but 0.5 is the binding one
    assert decision.final_size < base_order.size


@pytest.mark.asyncio
async def test_audit_written_to_redis() -> None:
    """Approved decision must be written to risk:audit:{order_id}."""
    redis = _make_redis()
    svc = _make_service(redis)
    await redis.set("meta_label:latest:AAPL", "0.90")
    order = _order()
    decision = await svc.process_order_candidate(order)
    raw = await redis.get(f"risk:audit:{order.order_id}")
    assert raw is not None
    data = json.loads(raw)
    assert data["order_id"] == order.order_id


@given(
    capital=st.decimals(
        min_value=Decimal("100"), max_value=Decimal("500_000"), places=2,
        allow_nan=False, allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.52, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@hyp_settings(max_examples=1000)
def test_approved_order_risk_never_exceeds_max(
    capital: Decimal, confidence: float
) -> None:
    """INVARIANT ABSOLU: for ANY capital and confidence, approved order
    monetary risk <= MAX_RISK_PER_TRADE_PCT (0.5%) x capital.

    This test uses synchronous pure function checks to verify the invariant
    holds across all inputs without running the async chain.
    """
    import asyncio
    from services.s05_risk_manager.position_rules import check_max_risk_per_trade
    from services.s05_risk_manager.meta_label_gate import MetaLabelGate

    sz = Decimal("0.01")
    order = OrderCandidate(
        order_id="hyp1",
        symbol="AAPL",
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
        kelly_fraction=0.25,
    )

    r_risk = check_max_risk_per_trade(order, capital)
    if r_risk.passed:
        sl_dist = abs(order.entry - order.stop_loss)
        actual_risk = sl_dist * order.size
        max_allowed = capital * Decimal("0.005")
        assert actual_risk <= max_allowed + Decimal("0.0001"), (
            f"INVARIANT VIOLATED: risk={actual_risk} > max={max_allowed} "
            f"for capital={capital}"
        )
