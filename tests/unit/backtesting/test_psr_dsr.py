"""Institutional metrics: PSR, DSR, PBO, MinTRL — property-tested."""

from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backtesting.metrics import (
    backtest_overfitting_probability,
    deflated_sharpe_ratio,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
)


class TestPSR:
    def test_strong_positive_high_psr(self) -> None:
        assert probabilistic_sharpe_ratio([0.005] * 252) > 0.99

    def test_zero_returns_near_half(self) -> None:
        assert abs(probabilistic_sharpe_ratio([0.0] * 100) - 0.5) < 0.1

    def test_negative_low_psr(self) -> None:
        assert probabilistic_sharpe_ratio([-0.003] * 100) < 0.1

    def test_higher_benchmark_lowers_psr(self) -> None:
        # mean=0.001/period, std=0.01 → annualised SR≈1.6 < benchmark=2.0.
        # PSR(bench=0) ≈ 0.92, PSR(bench=2.0) < 0.5 — both distinct, no boundary 1.0.
        rng = np.random.default_rng(0)
        r = (rng.standard_normal(200) * 0.01 + 0.001).tolist()
        assert probabilistic_sharpe_ratio(r, 0.0) > probabilistic_sharpe_ratio(r, 2.0)

    def test_more_obs_higher_psr(self) -> None:
        assert probabilistic_sharpe_ratio([0.003] * 500) >= probabilistic_sharpe_ratio([0.003] * 50)

    def test_fewer_than_4_returns_zero(self) -> None:
        assert probabilistic_sharpe_ratio([0.01, 0.02, 0.01]) == 0.0

    def test_constant_positive_returns_one(self) -> None:
        # std=0, mean>0 → PSR should be 1.0
        assert probabilistic_sharpe_ratio([0.01] * 50) == 1.0

    def test_constant_negative_returns_zero(self) -> None:
        # std=0, mean<0 → PSR should be 0.0
        assert probabilistic_sharpe_ratio([-0.01] * 50) == 0.0

    @given(
        mean_ret=st.floats(-0.01, 0.01, allow_nan=False),
        n_obs=st.integers(10, 500),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_always_in_zero_one(self, mean_ret: float, n_obs: int) -> None:
        rng = np.random.default_rng(abs(int(mean_ret * 1e8)) % 2**31)
        r = (rng.standard_normal(n_obs) * 0.01 + mean_ret).tolist()
        result = probabilistic_sharpe_ratio(r)
        assert 0.0 <= result <= 1.0

    @given(
        benchmark=st.floats(0.0, 3.0, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_monotone_in_benchmark(self, benchmark: float) -> None:
        """Higher benchmark always yields lower or equal PSR."""
        r = [0.004] * 200
        psr_low = probabilistic_sharpe_ratio(r, benchmark_sharpe=0.0)
        psr_high = probabilistic_sharpe_ratio(r, benchmark_sharpe=benchmark)
        assert psr_low >= psr_high - 1e-10


class TestDSR:
    def test_one_trial_close_to_psr(self) -> None:
        r = [0.004] * 200
        assert abs(deflated_sharpe_ratio(r, 1) - probabilistic_sharpe_ratio(r)) < 0.05

    def test_more_trials_lower_dsr(self) -> None:
        # Use returns with realistic variance so DSR deflation is measurable.
        rng = np.random.default_rng(1)
        r = (rng.standard_normal(200) * 0.005 + 0.004).tolist()
        assert deflated_sharpe_ratio(r, 5) > deflated_sharpe_ratio(r, 1000)

    def test_high_sharpe_resists_deflation(self) -> None:
        assert deflated_sharpe_ratio([0.020] * 300, n_trials=1000) > 0.80

    def test_dsr_leq_psr(self) -> None:
        """DSR must always be ≤ PSR (selection bias can only reduce confidence)."""
        r = [0.003] * 150
        assert deflated_sharpe_ratio(r, 50) <= probabilistic_sharpe_ratio(r) + 1e-10

    def test_fewer_than_4_returns_psr(self) -> None:
        r = [0.01, 0.02]
        assert deflated_sharpe_ratio(r, 10) == probabilistic_sharpe_ratio(r)

    @given(n_trials=st.integers(1, 10_000))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_always_valid(self, n_trials: int) -> None:
        rng = np.random.default_rng(n_trials % 100)
        r = (rng.standard_normal(100) * 0.01 + 0.002).tolist()
        result = deflated_sharpe_ratio(r, n_trials)
        assert 0.0 <= result <= 1.0

    @given(n_trials=st.integers(2, 500))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_dsr_never_exceeds_psr(self, n_trials: int) -> None:
        rng = np.random.default_rng(n_trials)
        r = (rng.standard_normal(200) * 0.01 + 0.003).tolist()
        dsr = deflated_sharpe_ratio(r, n_trials)
        psr = probabilistic_sharpe_ratio(r)
        assert dsr <= psr + 1e-10


class TestMinTRL:
    def test_high_sharpe_fewer_obs(self) -> None:
        assert minimum_track_record_length(3.0) < minimum_track_record_length(1.0)

    def test_below_benchmark_impossible(self) -> None:
        assert minimum_track_record_length(0.5, benchmark_sharpe=1.0) > 1_000_000

    def test_fat_tails_increase_need(self) -> None:
        assert minimum_track_record_length(1.5, excess_kurtosis=5.0) > minimum_track_record_length(
            1.5, excess_kurtosis=0.0
        )

    def test_higher_confidence_more_obs(self) -> None:
        assert minimum_track_record_length(2.0, confidence=0.99) > minimum_track_record_length(
            2.0, confidence=0.90
        )

    def test_returns_positive_integer(self) -> None:
        result = minimum_track_record_length(1.5)
        assert isinstance(result, int)
        assert result >= 1

    def test_equal_target_and_benchmark(self) -> None:
        """target == benchmark → impossible → return sentinel."""
        assert minimum_track_record_length(1.0, benchmark_sharpe=1.0) == 1_000_000_000

    @given(
        target=st.floats(0.5, 5.0, allow_nan=False),
        confidence=st.floats(0.80, 0.999, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_always_positive(self, target: float, confidence: float) -> None:
        result = minimum_track_record_length(target, confidence=confidence)
        assert result >= 1


class TestPBO:
    def test_no_degradation_low(self) -> None:
        # PBO formula: d=0 (no degradation), log_f=log(10)/log(100)=0.5
        # → PBO = 0.5*(1+0)*( 0.5+0.5*0.5) = 0.375 < 0.5 (not overfit threshold).
        assert backtest_overfitting_probability(2.0, 2.0, 10) < 0.5

    def test_large_degradation_high(self) -> None:
        assert backtest_overfitting_probability(3.0, -0.5, 100) > 0.7

    def test_one_trial_zero(self) -> None:
        assert backtest_overfitting_probability(2.0, 1.0, 1) == 0.0

    def test_always_in_range(self) -> None:
        for oos in [0.0, 0.5, 1.0, 2.0, -1.0]:
            result = backtest_overfitting_probability(2.0, oos, 50)
            assert 0.0 <= result <= 1.0

    def test_negative_is_sharpe_returns_one(self) -> None:
        assert backtest_overfitting_probability(-1.0, 1.0, 50) == 1.0

    def test_more_trials_higher_pbo(self) -> None:
        """More candidates → higher chance of overfitting on same degradation."""
        pbo_few = backtest_overfitting_probability(2.0, 0.5, 10)
        pbo_many = backtest_overfitting_probability(2.0, 0.5, 10_000)
        assert pbo_many >= pbo_few

    @given(
        is_sr=st.floats(0.1, 5.0, allow_nan=False),
        oos_sr=st.floats(-3.0, 5.0, allow_nan=False),
        n_trials=st.integers(1, 10_000),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_always_in_zero_one(self, is_sr: float, oos_sr: float, n_trials: int) -> None:
        result = backtest_overfitting_probability(is_sr, oos_sr, n_trials)
        assert 0.0 <= result <= 1.0
