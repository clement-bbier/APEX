"""Tests for Phase-2 dynamic regime detection engine."""

from __future__ import annotations

import pytest

from core.models.regime import RiskMode, VolRegime
from services.s03_regime_detector.regime_engine import RegimeEngine


class TestRegimeEngine:
    def engine(self) -> RegimeEngine:
        return RegimeEngine()

    def test_crisis_regime_halts_trading(self) -> None:
        r = self.engine().compute(vix=38.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        assert r.vol_regime == VolRegime.CRISIS
        assert r.macro_mult == 0.0  # system must halt

    def test_low_vol_increases_sizing(self) -> None:
        r = self.engine().compute(vix=12.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        assert r.vol_regime == VolRegime.LOW
        assert r.macro_mult > 1.0

    def test_inverted_yield_reduces_mult(self) -> None:
        r_normal = self.engine().compute(
            vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3
        )
        r_inverted = self.engine().compute(
            vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.3, yield_2y=4.5
        )
        assert r_inverted.macro_mult < r_normal.macro_mult
        assert r_inverted.yield_curve_inverted is True

    def test_dxy_spike_is_risk_off(self) -> None:
        r = self.engine().compute(vix=18.0, dxy_1h_change_pct=0.8, yield_10y=4.5, yield_2y=4.3)
        assert r.risk_mode == RiskMode.REDUCED
        assert r.macro_mult < 1.0

    def test_macro_mult_always_non_negative(self) -> None:
        for vix in [10, 20, 30, 40]:
            r = self.engine().compute(
                vix=float(vix),
                dxy_1h_change_pct=1.0,
                yield_10y=4.0,
                yield_2y=5.0,
            )
            assert r.macro_mult >= 0.0

    def test_reasoning_populated(self) -> None:
        r = self.engine().compute(vix=38.0, dxy_1h_change_pct=0.8, yield_10y=4.3, yield_2y=4.5)
        assert len(r.reasoning) >= 1

    def test_normal_regime_mult_is_one(self) -> None:
        r = self.engine().compute(vix=22.0, dxy_1h_change_pct=0.2, yield_10y=4.5, yield_2y=4.3)
        assert r.vol_regime == VolRegime.NORMAL
        assert r.macro_mult == 1.0

    def test_high_vol_reduces_sizing(self) -> None:
        r = self.engine().compute(vix=28.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        assert r.vol_regime == VolRegime.HIGH
        assert r.macro_mult == pytest.approx(0.3)

    def test_multiple_risk_off_stack_multiplicatively(self) -> None:
        """DXY spike + inverted yield → mult multiplied both reductions."""
        r_clean = self.engine().compute(
            vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3
        )
        r_both = self.engine().compute(vix=18.0, dxy_1h_change_pct=0.8, yield_10y=4.3, yield_2y=4.5)
        # Both DXY (×0.7) and yield inversion (×0.8) applied
        assert r_both.macro_mult < r_clean.macro_mult * 0.8
