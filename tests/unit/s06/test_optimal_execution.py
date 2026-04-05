"""Tests MarketImpactModel: square-root impact, Kyle linear, Almgren-Chriss."""
from __future__ import annotations

from services.s06_execution.optimal_execution import MarketImpactModel


class TestSqrtImpact:
    m = MarketImpactModel()

    def test_zero_quantity(self) -> None:
        assert self.m.sqrt_impact(0, 1e6, 0.20, 50000) == 0.0

    def test_zero_adv(self) -> None:
        assert self.m.sqrt_impact(100, 0, 0.20, 50000) == 0.0

    def test_positive_for_valid(self) -> None:
        assert self.m.sqrt_impact(1000, 1e6, 0.20, 50000) > 0

    def test_larger_order_more_impact(self) -> None:
        small = self.m.sqrt_impact(100, 1e6, 0.20, 50000)
        large = self.m.sqrt_impact(10000, 1e6, 0.20, 50000)
        assert large > small

    def test_sqrt_scaling(self) -> None:
        """Doubling quantity increases impact by √2, not 2."""
        i1 = self.m.sqrt_impact(1000, 1e6, 0.20, 50000)
        i2 = self.m.sqrt_impact(4000, 1e6, 0.20, 50000)
        assert abs(i2 / i1 - 2.0) < 0.01  # √4 = 2


class TestBestImpact:
    m = MarketImpactModel()

    def test_large_order_uses_sqrt(self) -> None:
        est = self.m.best_impact_estimate(quantity=10000, adv=100000, daily_vol=0.20,
                                          price=50000, kyle_lambda=1e-5, spread_bps=5.0)
        assert est.recommended_model == "sqrt"
        assert est.is_large_order is True

    def test_small_order_uses_linear(self) -> None:
        est = self.m.best_impact_estimate(quantity=10, adv=1e6, daily_vol=0.20,
                                          price=50000, kyle_lambda=1e-5, spread_bps=5.0)
        assert est.recommended_model == "linear"
        assert est.is_large_order is False

    def test_total_slippage_positive(self) -> None:
        est = self.m.best_impact_estimate(1000, 1e6, 0.20, 50000, 1e-5, 5.0)
        assert est.total_slippage_bps > 0

    def test_participation_rate_correct(self) -> None:
        est = self.m.best_impact_estimate(1000, 10000, 0.20, 50000, 1e-5, 5.0)
        assert abs(est.participation_rate - 0.1) < 1e-9


class TestAlmgrenChriss:
    m = MarketImpactModel()

    def test_schedule_sums_to_one(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=10)
        assert abs(sum(s.trade_schedule) - 1.0) < 1e-9

    def test_n_periods_correct(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=5)
        assert len(s.trade_schedule) == 5

    def test_risk_neutral_is_twap(self) -> None:
        """With lambda_risk ≈ 0, schedule ≈ TWAP (equal splits)."""
        s = self.m.almgren_chriss_schedule(1.0, n_periods=4, lambda_risk=0.0)
        for frac in s.trade_schedule:
            assert abs(frac - 0.25) < 0.05

    def test_high_risk_aversion_front_loaded(self) -> None:
        """High risk aversion → sell more early."""
        s_low = self.m.almgren_chriss_schedule(1.0, n_periods=5, lambda_risk=1e-8)
        s_high = self.m.almgren_chriss_schedule(1.0, n_periods=5, lambda_risk=1e-3)
        assert s_high.trade_schedule[0] >= s_low.trade_schedule[0]

    def test_expected_cost_positive(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=10)
        assert s.expected_cost >= 0
