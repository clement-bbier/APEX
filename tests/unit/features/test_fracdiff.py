"""Tests for features.fracdiff — wrapper parity with core/math."""

from __future__ import annotations

from core.math.fractional_diff import FractionalDifferentiator
from features.fracdiff import compute_fracdiff, find_minimum_d


class TestComputeFracdiff:
    """compute_fracdiff delegates to FractionalDifferentiator."""

    def test_parity_with_core(self) -> None:
        series = [float(i) for i in range(50)]
        d = 0.4
        wrapper_result = compute_fracdiff(series, d)
        core_result = FractionalDifferentiator().differentiate(series, d)
        assert wrapper_result.d == core_result.d
        assert wrapper_result.series == core_result.series
        assert wrapper_result.weights == core_result.weights

    def test_short_series(self) -> None:
        series = [1.0, 2.0, 3.0]
        result = compute_fracdiff(series, 0.5)
        assert result.d == 0.5


class TestFindMinimumD:
    """find_minimum_d delegates to FractionalDifferentiator."""

    def test_parity_with_core(self) -> None:
        # Create a series with enough data for ADF test
        import math

        series = [math.log(100 + i * 0.5 + (i % 7) * 0.3) for i in range(100)]
        wrapper_result = find_minimum_d(series)
        core_result = FractionalDifferentiator().find_minimum_d(series)
        assert wrapper_result.d == core_result.d
        assert wrapper_result.is_stationary == core_result.is_stationary

    def test_returns_fracdiff_result(self) -> None:
        series = [float(i) for i in range(50)]
        result = find_minimum_d(series)
        assert hasattr(result, "d")
        assert hasattr(result, "is_stationary")
        assert hasattr(result, "series")
