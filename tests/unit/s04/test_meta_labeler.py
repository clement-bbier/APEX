"""Unit tests for MetaLabeler and MetaFeatureLogger (OBJ-5).

Covers:
- Hard blocks (VPIN, crisis macro, wide spread)
- Soft scoring correctness
- Output contract (confidence ∈ [0,1], size_mult ∈ [0,1])
- get_features_from_redis safe defaults
- MetaFeatureLogger fire-and-forget semantics
- Hypothesis property tests

References:
    López de Prado (2018). AFML Wiley. Chapter 3 (Meta-Labeling). Cornell → AQR.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from services.s04_fusion_engine.meta_labeler import (
    MetaFeatures,
    MetaLabeler,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _good_features() -> MetaFeatures:
    """Feature vector that should produce a TRADE decision."""
    return MetaFeatures(
        signal_strength=0.80,
        n_triggers=3,
        hurst_exponent=0.20,
        vpin=0.30,
        har_rv_forecast_vol=0.18,
        spread_bps=4.0,
        session_mult=1.5,
        macro_mult=1.0,
        kyle_lambda=0.001,
    )


def _blocked_vpin() -> MetaFeatures:
    f = _good_features()
    return MetaFeatures(
        **{**f.__dict__, "vpin": 0.95}
    )


def _blocked_macro() -> MetaFeatures:
    f = _good_features()
    return MetaFeatures(
        **{**f.__dict__, "macro_mult": 0.0}
    )


def _blocked_spread() -> MetaFeatures:
    f = _good_features()
    return MetaFeatures(
        **{**f.__dict__, "spread_bps": 60.0}
    )


# ---------------------------------------------------------------------------
# Hard blocks
# ---------------------------------------------------------------------------


class TestHardBlocks:
    ml = MetaLabeler()

    def test_vpin_extreme_blocks_trade(self) -> None:
        d = self.ml.score(_blocked_vpin())
        assert not d.should_trade
        assert d.adjusted_size_mult == 0.0
        assert d.blocking_reason is not None
        assert "VPIN" in d.blocking_reason

    def test_crisis_macro_blocks_trade(self) -> None:
        d = self.ml.score(_blocked_macro())
        assert not d.should_trade
        assert d.adjusted_size_mult == 0.0
        assert "macro_mult" in (d.blocking_reason or "").lower() or "crisis" in (d.blocking_reason or "").lower()

    def test_wide_spread_blocks_trade(self) -> None:
        d = self.ml.score(_blocked_spread())
        assert not d.should_trade
        assert d.adjusted_size_mult == 0.0
        assert "50" in (d.blocking_reason or "") or "Spread" in (d.blocking_reason or "")

    def test_hard_block_returns_score_minus_one(self) -> None:
        """All hard blocks must return meta_score = -1.0."""
        for f in [_blocked_vpin(), _blocked_macro(), _blocked_spread()]:
            assert self.ml.score(f).meta_score == -1.0

    def test_vpin_just_below_threshold_not_blocked(self) -> None:
        f = MetaFeatures(**{**_good_features().__dict__, "vpin": 0.89})
        d = self.ml.score(f)
        # Should NOT be hard-blocked (VPIN < 0.90)
        assert d.meta_score != -1.0

    def test_spread_exactly_at_threshold_not_blocked(self) -> None:
        f = MetaFeatures(**{**_good_features().__dict__, "spread_bps": 50.0})
        d = self.ml.score(f)
        # spread > 50 triggers block; exactly 50.0 should NOT block
        assert d.meta_score != -1.0


# ---------------------------------------------------------------------------
# Soft scoring — output contract
# ---------------------------------------------------------------------------


class TestOutputContract:
    ml = MetaLabeler()

    def test_good_features_approve_trade(self) -> None:
        d = self.ml.score(_good_features())
        assert d.should_trade

    def test_confidence_in_unit_interval(self) -> None:
        for f in [_good_features(), _blocked_vpin(), _blocked_macro(), _blocked_spread()]:
            d = self.ml.score(f)
            assert 0.0 <= d.confidence <= 1.0, f"confidence={d.confidence}"

    def test_size_mult_in_unit_interval(self) -> None:
        for f in [_good_features(), _blocked_vpin(), _blocked_macro(), _blocked_spread()]:
            d = self.ml.score(f)
            assert 0.0 <= d.adjusted_size_mult <= 1.0, f"size_mult={d.adjusted_size_mult}"

    def test_meta_score_bounded(self) -> None:
        """Soft score (before rounding) stays within [-1, +1]."""
        d = self.ml.score(_good_features())
        assert -1.0 <= d.meta_score <= 1.0

    def test_blocking_reason_none_when_trading(self) -> None:
        d = self.ml.score(_good_features())
        if d.should_trade:
            assert d.blocking_reason is None

    def test_blocking_reason_set_when_not_trading(self) -> None:
        # Weak signal — should not trade
        weak = MetaFeatures(
            signal_strength=0.1,
            n_triggers=1,
            hurst_exponent=0.49,
            vpin=0.89,
            har_rv_forecast_vol=0.60,
            spread_bps=49.0,
            session_mult=0.5,
            macro_mult=0.2,
            kyle_lambda=0.0,
        )
        d = self.ml.score(weak)
        if not d.should_trade:
            assert d.blocking_reason is not None

    def test_high_vpin_reduces_size_mult(self) -> None:
        low_vpin = MetaFeatures(**{**_good_features().__dict__, "vpin": 0.10})
        high_vpin = MetaFeatures(**{**_good_features().__dict__, "vpin": 0.85})
        d_low = self.ml.score(low_vpin)
        d_high = self.ml.score(high_vpin)
        assert d_low.adjusted_size_mult >= d_high.adjusted_size_mult

    def test_more_triggers_improve_score(self) -> None:
        one_trigger = MetaFeatures(**{**_good_features().__dict__, "n_triggers": 1})
        four_triggers = MetaFeatures(**{**_good_features().__dict__, "n_triggers": 4})
        d1 = self.ml.score(one_trigger)
        d4 = self.ml.score(four_triggers)
        assert d4.meta_score > d1.meta_score


# ---------------------------------------------------------------------------
# get_features_from_redis
# ---------------------------------------------------------------------------


class TestGetFeaturesFromRedis:
    ml = MetaLabeler()

    def test_empty_redis_data_uses_defaults(self) -> None:
        f = self.ml.get_features_from_redis("BTCUSDT", {})
        assert 0.0 <= f.signal_strength <= 1.0
        assert f.n_triggers == 0
        assert f.hurst_exponent > 0.0
        assert f.vpin > 0.0
        assert f.macro_mult > 0.0

    def test_reads_vpin_from_correct_key(self) -> None:
        data = {"vpin:BTCUSDT": {"vpin": 0.75}}
        f = self.ml.get_features_from_redis("BTCUSDT", data)
        assert f.vpin == 0.75

    def test_reads_macro_mult_from_regime(self) -> None:
        data = {"regime:current": {"macro_mult": 0.5, "session": {}}}
        f = self.ml.get_features_from_redis("BTCUSDT", data)
        assert f.macro_mult == 0.5

    def test_n_triggers_counts_triggers_list(self) -> None:
        data = {"signal:BTCUSDT": {"strength": 0.7, "triggers": ["a", "b", "c"]}}
        f = self.ml.get_features_from_redis("BTCUSDT", data)
        assert f.n_triggers == 3

    def test_none_values_use_defaults(self) -> None:
        data = {
            "vpin:BTCUSDT": {"vpin": None},
            "analytics:fast": {"hurst_exponent": None},
        }
        f = self.ml.get_features_from_redis("BTCUSDT", data)
        assert f.vpin > 0.0        # default 0.5
        assert f.hurst_exponent > 0.0  # default 0.3


# ---------------------------------------------------------------------------
# MetaFeatureLogger — fire-and-forget
# ---------------------------------------------------------------------------


class TestMetaFeatureLogger:
    def _make_logger(self) -> tuple[Any, Any, Any]:
        """Return (logger, mock_bus, mock_state)."""
        from services.s04_fusion_engine.feature_logger import MetaFeatureLogger

        bus = MagicMock()
        bus.publish = AsyncMock(return_value=None)
        state = MagicMock()
        state.lpush = AsyncMock(return_value=None)
        state.ltrim = AsyncMock(return_value=None)
        return MetaFeatureLogger(bus, state), bus, state

    def test_log_calls_zmq_publish(self) -> None:
        logger, bus, state = self._make_logger()
        decision = MetaLabeler().score(_good_features())
        asyncio.run(
            logger.log("BTCUSDT", _good_features(), decision)
        )
        bus.publish.assert_called_once()

    def test_log_calls_redis_lpush(self) -> None:
        logger, bus, state = self._make_logger()
        decision = MetaLabeler().score(_good_features())
        asyncio.run(
            logger.log("BTCUSDT", _good_features(), decision)
        )
        state.lpush.assert_called_once()
        state.ltrim.assert_called_once()

    def test_zmq_failure_does_not_raise(self) -> None:
        from services.s04_fusion_engine.feature_logger import MetaFeatureLogger

        bus = MagicMock()
        bus.publish = AsyncMock(side_effect=RuntimeError("ZMQ down"))
        state = MagicMock()
        state.lpush = AsyncMock(return_value=None)
        state.ltrim = AsyncMock(return_value=None)
        flogger = MetaFeatureLogger(bus, state)
        decision = MetaLabeler().score(_good_features())
        # Must not raise even when ZMQ fails
        asyncio.run(
            flogger.log("BTCUSDT", _good_features(), decision)
        )

    def test_redis_failure_does_not_raise(self) -> None:
        from services.s04_fusion_engine.feature_logger import MetaFeatureLogger

        bus = MagicMock()
        bus.publish = AsyncMock(return_value=None)
        state = MagicMock()
        state.lpush = AsyncMock(side_effect=ConnectionError("Redis down"))
        state.ltrim = AsyncMock(return_value=None)
        flogger = MetaFeatureLogger(bus, state)
        decision = MetaLabeler().score(_good_features())
        asyncio.run(
            flogger.log("BTCUSDT", _good_features(), decision)
        )

    def test_payload_contains_required_fields(self) -> None:
        logger, bus, _state = self._make_logger()
        features = _good_features()
        decision = MetaLabeler().score(features)
        asyncio.run(
            logger.log("BTCUSDT", features, decision)
        )
        args, _ = bus.publish.call_args
        _topic, payload = args
        assert "ts_utc" in payload
        assert "symbol" in payload
        assert "features" in payload
        assert "meta_decision" in payload
        assert "triple_barrier_label" in payload
        assert payload["triple_barrier_label"] is None

    def test_topic_uses_constants(self) -> None:
        from core.topics import Topics

        logger, bus, _state = self._make_logger()
        decision = MetaLabeler().score(_good_features())
        asyncio.run(
            logger.log("BTCUSDT", _good_features(), decision)
        )
        args, _ = bus.publish.call_args
        topic = args[0]
        assert topic == Topics.ANALYTICS_META_FEATURES

    def test_ltrim_caps_at_max_len(self) -> None:
        from services.s04_fusion_engine.feature_logger import MetaFeatureLogger

        logger, _bus, state = self._make_logger()
        decision = MetaLabeler().score(_good_features())
        asyncio.run(
            logger.log("BTCUSDT", _good_features(), decision)
        )
        state.ltrim.assert_called_once_with(
            MetaFeatureLogger.REDIS_KEY, 0, MetaFeatureLogger.REDIS_MAX_LEN - 1
        )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestMetaLabelProperties:
    ml = MetaLabeler()

    @given(
        signal_strength=st.floats(0.0, 1.0, allow_nan=False),
        n_triggers=st.integers(0, 6),
        hurst=st.floats(0.01, 0.49, allow_nan=False),
        vpin=st.floats(0.0, 0.89, allow_nan=False),  # exclude hard block
        vol=st.floats(0.01, 0.80, allow_nan=False),
        spread=st.floats(0.0, 49.9, allow_nan=False),  # exclude hard block
        session_mult=st.floats(0.5, 2.0, allow_nan=False),
        macro_mult=st.floats(0.01, 1.0, allow_nan=False),  # exclude hard block
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_soft_score_output_contract(
        self,
        signal_strength: float,
        n_triggers: int,
        hurst: float,
        vpin: float,
        vol: float,
        spread: float,
        session_mult: float,
        macro_mult: float,
    ) -> None:
        f = MetaFeatures(
            signal_strength=signal_strength,
            n_triggers=n_triggers,
            hurst_exponent=hurst,
            vpin=vpin,
            har_rv_forecast_vol=vol,
            spread_bps=spread,
            session_mult=session_mult,
            macro_mult=macro_mult,
            kyle_lambda=0.0,
        )
        d = self.ml.score(f)
        assert 0.0 <= d.confidence <= 1.0
        assert 0.0 <= d.adjusted_size_mult <= 1.0
        assert -1.0 <= d.meta_score <= 1.0
        assert isinstance(d.should_trade, bool)

    @given(vpin=st.floats(0.90, 1.0, allow_nan=False))
    @settings(max_examples=50)
    def test_vpin_hard_block_always_triggers(self, vpin: float) -> None:
        f = MetaFeatures(
            signal_strength=1.0,
            n_triggers=5,
            hurst_exponent=0.1,
            vpin=vpin,
            har_rv_forecast_vol=0.2,
            spread_bps=1.0,
            session_mult=1.5,
            macro_mult=1.0,
            kyle_lambda=0.0,
        )
        d = self.ml.score(f)
        assert not d.should_trade
        assert d.adjusted_size_mult == 0.0

    @given(spread=st.floats(50.01, 200.0, allow_nan=False))
    @settings(max_examples=50)
    def test_spread_hard_block_always_triggers(self, spread: float) -> None:
        f = MetaFeatures(
            signal_strength=1.0,
            n_triggers=5,
            hurst_exponent=0.1,
            vpin=0.3,
            har_rv_forecast_vol=0.2,
            spread_bps=spread,
            session_mult=1.5,
            macro_mult=1.0,
            kyle_lambda=0.0,
        )
        d = self.ml.score(f)
        assert not d.should_trade
        assert d.adjusted_size_mult == 0.0
