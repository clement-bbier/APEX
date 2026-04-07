"""Tests RoughVolAnalyzer: Hurst exponent estimation and Variance Ratio Test."""

from __future__ import annotations

import numpy as np

from services.s07_quant_analytics.rough_vol import RoughVolAnalyzer


class TestHurstEstimation:
    a = RoughVolAnalyzer()

    def test_too_short_fallback(self) -> None:
        r = self.a.estimate_hurst_from_vol([0.15, 0.16, 0.14])
        assert r.hurst_exponent == 0.5
        assert r.vol_regime == "classical"

    def test_hurst_in_valid_range(self) -> None:
        rng = np.random.default_rng(42)
        vols = (rng.lognormal(mean=-2, sigma=0.3, size=100)).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert 0.01 <= r.hurst_exponent <= 0.5

    def test_edge_score_inverse_hurst(self) -> None:
        """Lower H → higher edge score."""
        rng = np.random.default_rng(0)
        vols = (rng.lognormal(mean=-2, sigma=0.5, size=80)).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert 0.0 <= r.scalping_edge_score <= 1.0

    def test_size_adjustment_non_negative(self) -> None:
        vols = np.random.default_rng(5).lognormal(size=60).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert r.size_adjustment > 0


class TestVarianceRatio:
    a = RoughVolAnalyzer()

    def test_too_short_fallback(self) -> None:
        r = self.a.variance_ratio_test([0.01, 0.02], q=5)
        assert r.vr_q == 1.0
        assert r.signal == "random_walk"

    def test_momentum_series(self) -> None:
        """Trending series → VR > 1 → momentum signal."""
        trend = [0.005 * i for i in range(1, 101)]
        r = self.a.variance_ratio_test(trend, q=5)
        assert r.vr_q > 1.0
        assert r.signal == "momentum"

    def test_vr_in_reasonable_range(self) -> None:
        returns = np.random.default_rng(42).standard_normal(100).tolist()
        r = self.a.variance_ratio_test(returns, q=5)
        assert r.vr_q > 0
        assert r.q == 5

    def test_signal_strength_in_range(self) -> None:
        returns = np.random.default_rng(1).standard_normal(50).tolist()
        r = self.a.variance_ratio_test(returns, q=3)
        assert 0.0 <= r.signal_strength <= 1.0
