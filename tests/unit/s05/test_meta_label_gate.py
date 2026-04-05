"""Tests for MetaLabelGate (Phase 6).

Covers hard gate, Kelly modulation, fallback, and 2 Hypothesis property tests.
"""
from __future__ import annotations
import pytest
import fakeredis.aioredis
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st
from services.s05_risk_manager.meta_label_gate import MetaLabelGate
from services.s05_risk_manager.models import BlockReason

_SYMBOL = "BTCUSDT"


def _gate() -> tuple[MetaLabelGate, fakeredis.aioredis.FakeRedis]:
    redis = fakeredis.aioredis.FakeRedis()
    return MetaLabelGate(redis), redis


@pytest.mark.asyncio
async def test_confidence_below_threshold_blocks() -> None:
    gate, redis = _gate()
    await redis.set(f"meta_label:latest:{_SYMBOL}", "0.51")
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.1)
    assert not result.passed
    assert result.block_reason == BlockReason.META_LABEL_CONFIDENCE_TOO_LOW


@pytest.mark.asyncio
async def test_confidence_at_threshold_passes() -> None:
    gate, redis = _gate()
    await redis.set(f"meta_label:latest:{_SYMBOL}", "0.52")
    # kelly_raw must be high enough: kelly_final = raw * weight(0.52) = raw * 0.04 >= 0.01
    # So raw >= 0.25. Use 0.30 to test that gate 1 passes (confidence check only).
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.30)
    assert result.passed


@pytest.mark.asyncio
async def test_kelly_weight_at_0_50() -> None:
    weight = MetaLabelGate._confidence_weight(0.50)
    assert abs(weight - 0.0) < 1e-9


@pytest.mark.asyncio
async def test_kelly_weight_at_0_75() -> None:
    weight = MetaLabelGate._confidence_weight(0.75)
    assert abs(weight - 0.5) < 1e-9


@pytest.mark.asyncio
async def test_kelly_weight_at_1_00() -> None:
    weight = MetaLabelGate._confidence_weight(1.00)
    assert abs(weight - 1.0) < 1e-9


@pytest.mark.asyncio
async def test_modulated_kelly_below_minimum_blocks() -> None:
    # confidence=0.52 -> weight = (0.52-0.5)/0.5 = 0.04
    # kelly_raw=0.1 -> kelly_final = 0.1 * 0.04 = 0.004 < 0.01 -> block
    gate, redis = _gate()
    await redis.set(f"meta_label:latest:{_SYMBOL}", "0.52")
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.1)
    assert not result.passed
    assert result.block_reason == BlockReason.KELLY_FRACTION_TOO_SMALL


@pytest.mark.asyncio
async def test_no_redis_data_uses_fallback_confidence() -> None:
    gate, _ = _gate()
    # No key set -> fallback = 0.52
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.5)
    assert abs(conf - 0.52) < 1e-6


@pytest.mark.asyncio
async def test_corrupted_redis_data_uses_fallback() -> None:
    gate, redis = _gate()
    await redis.set(f"meta_label:latest:{_SYMBOL}", "not_a_number")
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.5)
    assert abs(conf - 0.52) < 1e-6


@pytest.mark.asyncio
async def test_confidence_clamped_to_0_1() -> None:
    gate, redis = _gate()
    await redis.set(f"meta_label:latest:{_SYMBOL}", "1.5")
    result, conf, kf = await gate.check(_SYMBOL, kelly_raw=0.2)
    assert conf <= 1.0


@given(confidence=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False))
@hyp_settings(max_examples=1000)
def test_weight_monotone_increasing(confidence: float) -> None:
    """Weight must be monotone non-decreasing with confidence."""
    delta = 0.001
    w1 = MetaLabelGate._confidence_weight(confidence)
    w2 = MetaLabelGate._confidence_weight(min(1.0, confidence + delta))
    assert w2 >= w1 - 1e-10


@given(
    confidence=st.floats(min_value=0.52, max_value=1.0, allow_nan=False, allow_infinity=False),
    kelly_raw=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
)
@hyp_settings(max_examples=1000)
def test_kelly_final_never_exceeds_raw(confidence: float, kelly_raw: float) -> None:
    """Kelly modulated <= Kelly raw (shrinkage only towards zero)."""
    weight = MetaLabelGate._confidence_weight(confidence)
    kelly_final = kelly_raw * weight
    assert kelly_final <= kelly_raw + 1e-10
