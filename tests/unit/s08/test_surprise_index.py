"""Tests for economic surprise index engine."""

from __future__ import annotations

import pytest

from services.s08_macro_intelligence.surprise_index import EconRelease, SurpriseIndexEngine


class TestSurpriseIndexEngine:
    def engine(self) -> SurpriseIndexEngine:
        return SurpriseIndexEngine()

    def test_positive_surprise(self) -> None:
        e = self.engine()
        # Actual 10% above consensus
        surprise = e.compute_surprise(consensus=100.0, actual=110.0)
        assert surprise == pytest.approx(0.10)

    def test_negative_surprise(self) -> None:
        e = self.engine()
        surprise = e.compute_surprise(consensus=100.0, actual=90.0)
        assert surprise == pytest.approx(-0.10)

    def test_zero_consensus_returns_zero(self) -> None:
        e = self.engine()
        assert e.compute_surprise(consensus=0.0, actual=50.0) == 0.0

    def test_no_effect_after_24h(self) -> None:
        e = self.engine()
        mult = e.compute_mult_adjustment(surprise_pct=1.0, impact="high", hours_since_release=24.0)
        assert mult == 1.0

    def test_positive_surprise_increases_mult(self) -> None:
        e = self.engine()
        mult = e.compute_mult_adjustment(surprise_pct=0.5, impact="high", hours_since_release=0.0)
        assert mult > 1.0

    def test_negative_surprise_decreases_mult(self) -> None:
        e = self.engine()
        mult = e.compute_mult_adjustment(surprise_pct=-0.5, impact="high", hours_since_release=0.0)
        assert mult < 1.0

    def test_low_impact_smaller_effect(self) -> None:
        e = self.engine()
        high = e.compute_mult_adjustment(surprise_pct=1.0, impact="high", hours_since_release=0.0)
        low = e.compute_mult_adjustment(surprise_pct=1.0, impact="low", hours_since_release=0.0)
        assert abs(high - 1.0) > abs(low - 1.0)

    def test_decay_at_12h(self) -> None:
        e = self.engine()
        at_0h = e.compute_mult_adjustment(surprise_pct=0.5, impact="high", hours_since_release=0.0)
        at_12h = e.compute_mult_adjustment(
            surprise_pct=0.5, impact="high", hours_since_release=12.0
        )
        assert abs(at_12h - 1.0) < abs(at_0h - 1.0)

    def test_build_release(self) -> None:
        e = self.engine()
        release = e.build_release(name="NFP", consensus=200_000.0, actual=250_000.0, impact="high")
        assert isinstance(release, EconRelease)
        assert release.name == "NFP"
        assert release.surprise_pct == pytest.approx(0.25)
        assert release.impact == "high"
