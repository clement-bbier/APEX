"""Tests for rolling correlation and cross-asset block logic."""

from __future__ import annotations

import math

import numpy as np

from services.quant_analytics.market_stats import MarketStatsEngine


class TestCorrelation:
    def engine(self) -> MarketStatsEngine:
        return MarketStatsEngine()

    def test_perfect_positive_correlation(self) -> None:
        e = self.engine()
        a = np.linspace(0, 1, 100)
        corr = e.compute_rolling_correlation(a, a * 2, window=60)
        assert abs(corr - 1.0) < 0.001

    def test_perfect_negative_correlation(self) -> None:
        e = self.engine()
        a = np.linspace(0, 1, 100)
        corr = e.compute_rolling_correlation(a, -a, window=60)
        assert abs(corr + 1.0) < 0.001

    def test_cross_asset_block_triggers(self) -> None:
        e = self.engine()
        blocked, reason = e.check_cross_asset_block(
            btc_spy_correlation=0.85,
            spy_1h_return_pct=-0.8,
            signal_direction="long",
        )
        assert blocked is True
        assert "SPY" in reason

    def test_no_block_when_uncorrelated(self) -> None:
        e = self.engine()
        blocked, _ = e.check_cross_asset_block(
            btc_spy_correlation=0.30,
            spy_1h_return_pct=-0.8,
            signal_direction="long",
        )
        assert blocked is False

    def test_no_block_for_short_direction(self) -> None:
        e = self.engine()
        blocked, _ = e.check_cross_asset_block(
            btc_spy_correlation=0.95,
            spy_1h_return_pct=-1.0,
            signal_direction="short",
        )
        assert blocked is False

    def test_no_block_when_spy_up(self) -> None:
        e = self.engine()
        blocked, _ = e.check_cross_asset_block(
            btc_spy_correlation=0.90,
            spy_1h_return_pct=0.5,
            signal_direction="long",
        )
        assert blocked is False

    def test_insufficient_data_returns_nan(self) -> None:
        e = self.engine()
        short = np.array([1.0, 2.0, 3.0])
        result = e.compute_rolling_correlation(short, short, window=60)
        assert math.isnan(result)

    def test_constant_series_returns_zero(self) -> None:
        """A constant series has std=0 → correlation is 0.0 (not NaN or error)."""
        e = self.engine()
        a = np.ones(100)
        b = np.linspace(0, 1, 100)
        result = e.compute_rolling_correlation(a, b, window=60)
        assert result == 0.0

    def test_correlation_in_valid_range(self) -> None:
        e = self.engine()
        rng = np.random.default_rng(42)
        a = rng.standard_normal(100)
        b = rng.standard_normal(100)
        corr = e.compute_rolling_correlation(a, b, window=60)
        assert -1.0 <= corr <= 1.0
