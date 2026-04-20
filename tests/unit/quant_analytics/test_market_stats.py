"""Tests for MarketStats econometric methods."""

from __future__ import annotations

import pytest

from services.s07_quant_analytics.market_stats import MarketStats


class TestMarketStats:
    def stats(self) -> MarketStats:
        return MarketStats()

    # ── ljung_box ────────────────────────────────────────────────────────────

    def test_ljung_box_insufficient_data(self) -> None:
        result = self.stats().ljung_box([1.0, 2.0], lags=10)
        assert result["q_stat"] == 0.0
        assert result["significant"] is False

    def test_ljung_box_constant_series(self) -> None:
        result = self.stats().ljung_box([1.0] * 50, lags=5)
        assert result["q_stat"] == 0.0

    def test_ljung_box_autocorrelated_series(self) -> None:
        # Highly autocorrelated series (cumsum of ones)
        import numpy as np

        series = list(np.cumsum(np.ones(100)))
        result = self.stats().ljung_box(series, lags=5)
        assert "q_stat" in result
        assert "significant" in result

    # ── hurst_exponent ────────────────────────────────────────────────────────

    def test_hurst_returns_half_for_short_series(self) -> None:
        result = self.stats().hurst_exponent([1.0, 2.0, 3.0])
        assert result == 0.5

    def test_hurst_trending_series_above_half(self) -> None:
        prices = [float(i) for i in range(1, 101)]
        h = self.stats().hurst_exponent(prices)
        assert h > 0.5

    def test_hurst_constant_series_returns_half(self) -> None:
        prices = [5.0] * 30
        h = self.stats().hurst_exponent(prices)
        assert h == 0.5

    # ── garch_volatility ──────────────────────────────────────────────────────

    def test_garch_empty_returns_sqrt_omega(self) -> None:
        import math

        result = self.stats().garch_volatility([], omega=0.0001)
        assert result == pytest.approx(math.sqrt(0.0001))

    def test_garch_positive_returns(self) -> None:
        import numpy as np

        returns = list(np.random.default_rng(42).standard_normal(50) * 0.01)
        vol = self.stats().garch_volatility(returns)
        assert vol > 0

    # ── realized_vs_implied_ratio ─────────────────────────────────────────────

    def test_ratio_zero_implied_returns_none(self) -> None:
        result = self.stats().realized_vs_implied_ratio(0.20, 0.0)
        assert result is None

    def test_ratio_normal(self) -> None:
        result = self.stats().realized_vs_implied_ratio(0.20, 0.25)
        assert result == pytest.approx(0.8)
