"""Tests for RegimeEngine legacy API (compute_vol_regime, compute_macro_mult,
compute_trend_regime, compute_risk_mode).
"""
from __future__ import annotations

import pytest

from core.models.regime import RiskMode, TrendRegime, VolRegime
from services.s03_regime_detector.regime_engine import RegimeEngine


@pytest.fixture
def engine() -> RegimeEngine:
    return RegimeEngine()


class TestComputeVolRegime:
    def test_crisis_regime(self, engine: RegimeEngine) -> None:
        assert engine.compute_vol_regime(35.0) == VolRegime.CRISIS

    def test_high_regime(self, engine: RegimeEngine) -> None:
        assert engine.compute_vol_regime(25.0) == VolRegime.HIGH

    def test_normal_regime(self, engine: RegimeEngine) -> None:
        assert engine.compute_vol_regime(15.0) == VolRegime.NORMAL

    def test_low_regime(self, engine: RegimeEngine) -> None:
        assert engine.compute_vol_regime(10.0) == VolRegime.LOW

    def test_none_returns_normal(self, engine: RegimeEngine) -> None:
        assert engine.compute_vol_regime(None) == VolRegime.NORMAL

    def test_boundary_25_is_high(self, engine: RegimeEngine) -> None:
        # vix < 25 is normal; exactly 25 hits HIGH branch
        assert engine.compute_vol_regime(25.0) == VolRegime.HIGH

    def test_boundary_15_is_normal(self, engine: RegimeEngine) -> None:
        # vix < 15 is low; exactly 15 hits NORMAL branch
        assert engine.compute_vol_regime(15.0) == VolRegime.NORMAL


class TestComputeMacroMult:
    def test_vix_above_30_reduces_mult(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=32.0, dxy=None, yield_spread=None)
        assert mult == pytest.approx(0.6)

    def test_vix_above_20_reduces_mult(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=22.0, dxy=None, yield_spread=None)
        assert mult == pytest.approx(0.8)

    def test_vix_below_20_no_reduction(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=15.0, dxy=None, yield_spread=None)
        assert mult == pytest.approx(1.0)

    def test_none_vix_no_reduction(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=None, dxy=None, yield_spread=None)
        assert mult == pytest.approx(1.0)

    def test_inverted_yield_curve_reduces_mult(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=15.0, dxy=None, yield_spread=-0.5)
        assert mult == pytest.approx(0.9)

    def test_normal_yield_curve_no_reduction(self, engine: RegimeEngine) -> None:
        mult = engine.compute_macro_mult(vix=15.0, dxy=None, yield_spread=0.5)
        assert mult == pytest.approx(1.0)

    def test_vix_30_and_inverted_yield(self, engine: RegimeEngine) -> None:
        # 0.6 * 0.9 = 0.54
        mult = engine.compute_macro_mult(vix=32.0, dxy=None, yield_spread=-0.5)
        assert mult == pytest.approx(0.54)

    def test_result_clamped_to_zero_to_one(self, engine: RegimeEngine) -> None:
        # Extreme case: mult should never exceed 1.0
        mult = engine.compute_macro_mult(vix=5.0, dxy=None, yield_spread=1.0)
        assert 0.0 <= mult <= 1.0

    def test_dxy_ignored_in_legacy_api(self, engine: RegimeEngine) -> None:
        # DXY param is reserved but not used in legacy API
        mult1 = engine.compute_macro_mult(vix=18.0, dxy=None, yield_spread=None)
        mult2 = engine.compute_macro_mult(vix=18.0, dxy=120.0, yield_spread=None)
        assert mult1 == mult2


class TestComputeTrendRegime:
    def _prices_uptrend(self) -> list[float]:
        """50 prices in a strong uptrend."""
        return [100.0 + i * 0.5 for i in range(60)]

    def _prices_downtrend(self) -> list[float]:
        """50 prices in a strong downtrend."""
        return [200.0 - i * 0.5 for i in range(60)]

    def _prices_ranging(self) -> list[float]:
        """50 prices oscillating tightly."""
        import math
        return [100.0 + math.sin(i * 0.1) * 0.001 for i in range(60)]

    def test_insufficient_data_returns_ranging(self, engine: RegimeEngine) -> None:
        assert engine.compute_trend_regime([100.0] * 40) == TrendRegime.RANGING

    def test_empty_returns_ranging(self, engine: RegimeEngine) -> None:
        assert engine.compute_trend_regime([]) == TrendRegime.RANGING

    def test_uptrend_detected(self, engine: RegimeEngine) -> None:
        result = engine.compute_trend_regime(self._prices_uptrend())
        assert result == TrendRegime.TRENDING_UP

    def test_downtrend_detected(self, engine: RegimeEngine) -> None:
        result = engine.compute_trend_regime(self._prices_downtrend())
        assert result == TrendRegime.TRENDING_DOWN

    def test_ranging_when_ema_close(self, engine: RegimeEngine) -> None:
        result = engine.compute_trend_regime(self._prices_ranging())
        assert result == TrendRegime.RANGING

    def test_exactly_50_prices(self, engine: RegimeEngine) -> None:
        # Exactly 50 prices should work
        prices = [100.0 + i * 0.5 for i in range(50)]
        result = engine.compute_trend_regime(prices)
        assert result in (TrendRegime.TRENDING_UP, TrendRegime.RANGING)


class TestComputeRiskMode:
    def test_crisis_vol_gives_crisis_mode(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.CRISIS, False, False)
        assert result == RiskMode.CRISIS

    def test_event_active_gives_reduced(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.NORMAL, True, False)
        assert result == RiskMode.REDUCED

    def test_circuit_open_gives_blocked(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.NORMAL, False, True)
        assert result == RiskMode.BLOCKED

    def test_high_vol_gives_reduced(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.HIGH, False, False)
        assert result == RiskMode.REDUCED

    def test_normal_conditions_gives_normal(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.NORMAL, False, False)
        assert result == RiskMode.NORMAL

    def test_low_vol_normal_conditions_gives_normal(self, engine: RegimeEngine) -> None:
        result = engine.compute_risk_mode(VolRegime.LOW, False, False)
        assert result == RiskMode.NORMAL

    def test_crisis_takes_priority_over_event(self, engine: RegimeEngine) -> None:
        # Crisis > event active
        result = engine.compute_risk_mode(VolRegime.CRISIS, True, True)
        assert result == RiskMode.CRISIS

    def test_event_takes_priority_over_circuit(self, engine: RegimeEngine) -> None:
        # Event active (checked before circuit_open)
        result = engine.compute_risk_mode(VolRegime.NORMAL, True, True)
        assert result == RiskMode.REDUCED


class TestRegimeEnginePhase2BtcFunding:
    """Test Phase-2 compute() with BTC funding rate."""

    def test_extreme_funding_rate_reduces_mult(self) -> None:
        engine = RegimeEngine()
        r_clean = engine.compute(vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        r_funding = engine.compute(
            vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3,
            btc_funding_rate=0.05,
        )
        assert r_funding.macro_mult < r_clean.macro_mult

    def test_normal_funding_rate_no_reduction(self) -> None:
        engine = RegimeEngine()
        r1 = engine.compute(vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        r2 = engine.compute(
            vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3,
            btc_funding_rate=0.01,
        )
        assert r1.macro_mult == r2.macro_mult

    def test_risk_on_in_calm_markets(self) -> None:
        engine = RegimeEngine()
        from services.s03_regime_detector.regime_engine import RiskMode
        r = engine.compute(vix=12.0, dxy_1h_change_pct=0.1, yield_10y=4.5, yield_2y=4.3)
        assert r.risk_mode == RiskMode.RISK_ON

    def test_vix_threshold_boundary(self) -> None:
        """VIX exactly at boundary values."""
        engine = RegimeEngine()
        from services.s03_regime_detector.regime_engine import VolRegime
        r_crisis = engine.compute(vix=35.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        r_high = engine.compute(vix=25.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        r_normal = engine.compute(vix=15.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        assert r_crisis.vol_regime == VolRegime.CRISIS
        assert r_high.vol_regime == VolRegime.HIGH_VOL
        assert r_normal.vol_regime == VolRegime.NORMAL
