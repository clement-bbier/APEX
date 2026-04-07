"""Tests TripleBarrierLabeler avec Hypothesis property tests."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.math.labeling import BarrierResult, TripleBarrierConfig, TripleBarrierLabeler


def _ts(m: int = 0) -> datetime:
    return datetime(2024, 1, 1, 9, 30, tzinfo=UTC) + timedelta(minutes=m)


def _future(start: float, moves: list[float]) -> list[tuple[datetime, Decimal]]:
    px = start
    result: list[tuple[datetime, Decimal]] = []
    for i, m in enumerate(moves):
        px = px * (1 + m)
        result.append((_ts(i + 1), Decimal(str(round(px, 8)))))
    return result


class TestUpperBarrier:
    lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=1.5, sl_multiplier=1.0))

    def test_long_tp_hit(self) -> None:
        label = self.lb.label_event(
            Decimal("100"), _ts(), +1, _future(100, [0.03, 0.03, 0.03]), daily_vol=0.01
        )
        assert label.barrier_hit == BarrierResult.UPPER
        assert label.label == 1

    def test_short_tp_hit(self) -> None:
        label = self.lb.label_event(
            Decimal("100"), _ts(), -1, _future(100, [-0.03, -0.03, -0.03]), daily_vol=0.01
        )
        assert label.barrier_hit == BarrierResult.UPPER
        assert label.label == 1


class TestLowerBarrier:
    lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=2.0, sl_multiplier=1.0))

    def test_long_sl_hit(self) -> None:
        label = self.lb.label_event(
            Decimal("100"), _ts(), +1, _future(100, [-0.02, -0.02, -0.02]), daily_vol=0.01
        )
        assert label.barrier_hit == BarrierResult.LOWER
        assert label.label == -1

    def test_short_sl_hit(self) -> None:
        label = self.lb.label_event(
            Decimal("100"), _ts(), -1, _future(100, [0.02, 0.02, 0.02]), daily_vol=0.01
        )
        assert label.barrier_hit == BarrierResult.LOWER
        assert label.label == -1


class TestVerticalBarrier:
    def _lb_no_hit(self) -> TripleBarrierLabeler:
        return TripleBarrierLabeler(TripleBarrierConfig(10.0, 10.0, 3))

    def test_timeout_gives_zero(self) -> None:
        label = self._lb_no_hit().label_event(
            Decimal("100"), _ts(), +1, _future(100, [0.001, -0.001, 0.001]), 0.001
        )
        assert label.label == 0

    def test_empty_future_vertical(self) -> None:
        lb = TripleBarrierLabeler()
        label = lb.label_event(Decimal("100"), _ts(), +1, [], daily_vol=0.01)
        assert label.barrier_hit == BarrierResult.VERTICAL

    def test_vertical_barrier_time_matches_last_period(self) -> None:
        lb = TripleBarrierLabeler(TripleBarrierConfig(10.0, 10.0, 3))
        futures = _future(100, [0.001, -0.001, 0.001])
        label = lb.label_event(Decimal("100"), _ts(), +1, futures, 0.001)
        assert label.vertical_barrier == futures[2][0]

    def test_holding_periods_correct_on_timeout(self) -> None:
        lb = TripleBarrierLabeler(TripleBarrierConfig(10.0, 10.0, 5))
        futures = _future(100, [0.001] * 5)
        label = lb.label_event(Decimal("100"), _ts(), +1, futures, 0.001)
        assert label.holding_periods == 5


class TestSideAwareness:
    """Verify that long/short labels are correctly inverted."""

    def test_long_and_short_opposite_on_same_move(self) -> None:
        """A strong upward move is TP for long and SL for short."""
        lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=1.0, sl_multiplier=1.0))
        moves = [0.03] * 5  # strong upward
        long_label = lb.label_event(Decimal("100"), _ts(), +1, _future(100, moves), 0.01)
        short_label = lb.label_event(Decimal("100"), _ts(), -1, _future(100, moves), 0.01)
        assert long_label.label == 1
        assert short_label.label == -1

    def test_down_move_opposite(self) -> None:
        """A strong downward move is SL for long and TP for short."""
        lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=1.0, sl_multiplier=1.0))
        moves = [-0.03] * 5  # strong downward
        long_label = lb.label_event(Decimal("100"), _ts(), +1, _future(100, moves), 0.01)
        short_label = lb.label_event(Decimal("100"), _ts(), -1, _future(100, moves), 0.01)
        assert long_label.label == -1
        assert short_label.label == 1


class TestBarrierLevels:
    """Test that barrier absolute levels are computed correctly."""

    def test_upper_barrier_level(self) -> None:
        lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=2.0, sl_multiplier=1.0))
        result = lb.label_event(Decimal("100"), _ts(), +1, _future(100, [0.001]), 0.01)
        expected_upper = Decimal("100") + Decimal("2.0") * Decimal(str(0.01 * 100))
        assert result.upper_barrier == expected_upper

    def test_lower_barrier_level(self) -> None:
        lb = TripleBarrierLabeler(TripleBarrierConfig(pt_multiplier=2.0, sl_multiplier=1.5))
        result = lb.label_event(Decimal("100"), _ts(), +1, _future(100, [0.001]), 0.01)
        expected_lower = Decimal("100") - Decimal("1.5") * Decimal(str(0.01 * 100))
        assert result.lower_barrier == expected_lower


class TestComputeDailyVol:
    def test_single_price_returns_default(self) -> None:
        lb = TripleBarrierLabeler()
        assert lb.compute_daily_vol([Decimal("100")]) == pytest.approx(0.01)

    def test_empty_returns_default(self) -> None:
        lb = TripleBarrierLabeler()
        assert lb.compute_daily_vol([]) == pytest.approx(0.01)

    def test_vol_estimate_positive(self) -> None:
        lb = TripleBarrierLabeler()
        prices = [Decimal(str(100 + i * 0.5)) for i in range(30)]
        assert lb.compute_daily_vol(prices) > 0

    def test_constant_prices_zero_vol(self) -> None:
        lb = TripleBarrierLabeler()
        prices = [Decimal("100")] * 10
        assert lb.compute_daily_vol(prices) == pytest.approx(0.0)


class TestProperties:
    @given(
        side=st.sampled_from([-1, 1]),
        vol=st.floats(0.001, 0.10, allow_nan=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_label_always_valid(self, side: int, vol: float) -> None:
        rng = random.Random(42)
        future = _future(100, [rng.uniform(-0.05, 0.05) for _ in range(20)])
        lb = TripleBarrierLabeler()
        result = lb.label_event(Decimal("100"), _ts(), side, future, vol)
        assert result.label in (-1, 0, 1)
        assert result.holding_periods >= 0

    @given(
        side=st.sampled_from([-1, 1]),
        vol=st.floats(0.001, 0.10, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_exit_time_gte_entry_time(self, side: int, vol: float) -> None:
        rng = random.Random(7)
        future = _future(100, [rng.uniform(-0.05, 0.05) for _ in range(20)])
        lb = TripleBarrierLabeler()
        result = lb.label_event(Decimal("100"), _ts(), side, future, vol)
        assert result.exit_time >= result.entry_time

    @given(vol=st.floats(1e-6, 0.5, allow_nan=False))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_upper_barrier_above_lower(self, vol: float) -> None:
        lb = TripleBarrierLabeler()
        result = lb.label_event(Decimal("100"), _ts(), +1, _future(100, [0.001]), vol)
        assert result.upper_barrier > result.lower_barrier
