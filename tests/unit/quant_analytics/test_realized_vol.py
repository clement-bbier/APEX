"""Tests RealizedVolEstimator: HAR-RV, Bipower Variation, Jump Detection."""

from __future__ import annotations

import numpy as np
import pytest

from services.quant_analytics.realized_vol import RealizedVolEstimator


class TestRV:
    e = RealizedVolEstimator()

    def test_empty_zero(self) -> None:
        assert self.e.realized_variance([]) == 0.0

    def test_known(self) -> None:
        assert self.e.realized_variance([0.01, 0.02]) == pytest.approx(0.0005)

    def test_non_negative(self) -> None:
        assert self.e.realized_variance(np.random.default_rng(0).standard_normal(100).tolist()) >= 0


class TestBV:
    e = RealizedVolEstimator()

    def test_single_zero(self) -> None:
        assert self.e.bipower_variation([0.01]) == 0.0

    def test_bv_le_rv_with_jump(self) -> None:
        r = [0.001] * 50 + [0.10] + [0.001] * 50
        assert self.e.bipower_variation(r) <= self.e.realized_variance(r)

    def test_non_negative(self) -> None:
        assert self.e.bipower_variation(np.random.default_rng(1).standard_normal(50).tolist()) >= 0


class TestJumpDetection:
    e = RealizedVolEstimator()

    def test_smooth_no_jump(self) -> None:
        m = self.e.jump_detection((np.random.default_rng(42).standard_normal(200) * 0.001).tolist())
        assert m.rv > 0
        assert 0.0 <= m.jump_ratio <= 1.0

    def test_large_jump_detected(self) -> None:
        r = [0.0005] * 100 + [0.05] + [0.0005] * 100
        m = self.e.jump_detection(r)
        assert m.has_significant_jump is True
        assert m.jump_component > 0

    def test_jump_ratio_bounds(self) -> None:
        r = np.random.default_rng(5).standard_normal(50).tolist()
        m = self.e.jump_detection(r)
        assert 0.0 <= m.jump_ratio <= 1.0


class TestHARForecast:
    e = RealizedVolEstimator()

    def test_too_short_fallback(self) -> None:
        f = self.e.har_rv_forecast([0.01] * 5)
        assert f.forecast_rv >= 0
        assert f.n_obs == 5

    def test_positive_forecast(self) -> None:
        rng = np.random.default_rng(42)
        rv = (rng.standard_normal(100) ** 2 * 0.0001 + 0.0001).tolist()
        f = self.e.har_rv_forecast(rv)
        assert f.forecast_rv > 0
        assert f.forecast_vol > 0

    def test_r2_in_range(self) -> None:
        rng = np.random.default_rng(0)
        rv = (rng.standard_normal(60) ** 2 * 0.0001 + 0.0002).tolist()
        f = self.e.har_rv_forecast(rv)
        assert 0.0 <= f.r_squared <= 1.0


class TestVolKelly:
    e = RealizedVolEstimator()

    def test_high_vol_reduces(self) -> None:
        assert self.e.vol_adjusted_kelly(0.10, 0.30) < self.e.vol_adjusted_kelly(0.10, 0.15)

    def test_low_vol_increases(self) -> None:
        assert self.e.vol_adjusted_kelly(0.10, 0.05) > self.e.vol_adjusted_kelly(0.10, 0.15)

    def test_capped(self) -> None:
        assert self.e.vol_adjusted_kelly(0.25, 0.01, max_fraction=0.25) <= 0.25

    def test_always_non_negative(self) -> None:
        assert self.e.vol_adjusted_kelly(0.05, 1.0) >= 0
