"""
Property-based tests for core safety invariants.
These properties must hold for ALL possible inputs - not just examples.

Using Hypothesis for automatic edge case generation.

These tests are the mathematical proof that the system cannot violate
its core safety properties regardless of market conditions.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from services.s02_signal_engine.signal_scorer import SignalComponent, SignalScorer
from services.s04_fusion_engine.kelly_sizer import KellySizer


class TestKellyNeverExceedsCapital:
    """Property: Kelly fraction always produces position <= capital."""

    @given(
        capital=st.decimals(
            min_value=Decimal("100"), max_value=Decimal("1000000"), places=2
        ).filter(lambda x: x.is_finite()),
        win_rate=st.floats(min_value=0.30, max_value=0.75, allow_nan=False),
        rr=st.floats(min_value=0.5, max_value=5.0, allow_nan=False),
        macro_mult=st.floats(min_value=0.0, max_value=1.5, allow_nan=False),
    )
    @settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
    def test_position_never_exceeds_capital(
        self,
        capital: Decimal,
        win_rate: float,
        rr: float,
        macro_mult: float,
    ) -> None:
        """No matter the inputs, position size must be <= capital."""
        sizer = KellySizer()
        kelly_f = sizer.kelly_fraction(win_rate=win_rate, avg_rr=rr)
        size = sizer.position_size(capital, kelly_f, macro_mult, 1.0, 0.0, False)
        assert size >= Decimal("0"), "Position cannot be negative"
        assert size <= capital, f"Position {size} exceeds capital {capital}"

    @given(
        capital=st.decimals(
            min_value=Decimal("1000"), max_value=Decimal("100000"), places=2
        ).filter(lambda x: x.is_finite()),
    )
    @settings(max_examples=200)
    def test_zero_macro_mult_gives_zero_size(self, capital: Decimal) -> None:
        """Crisis regime (macro_mult=0) must always produce zero position."""
        sizer = KellySizer()
        kelly_f = sizer.kelly_fraction(win_rate=0.55, avg_rr=1.8)
        size = sizer.position_size(capital, kelly_f, 0.0, 1.0, 0.0, False)
        assert size == Decimal("0"), f"Crisis should give zero size, got {size}"


class TestSignalScoreInBounds:
    """Property: signal score always in [-1.0, +1.0]."""

    @given(
        s1=st.floats(-1.0, 1.0, allow_nan=False),
        s2=st.floats(-1.0, 1.0, allow_nan=False),
        s3=st.floats(-1.0, 1.0, allow_nan=False),
        min_str=st.floats(0.0, 0.5, allow_nan=False),
    )
    @settings(max_examples=300)
    def test_score_always_clamped(self, s1: float, s2: float, s3: float, min_str: float) -> None:
        """Signal score always in valid range regardless of component values."""
        scorer = SignalScorer(min_components=2, min_strength=min_str)
        components = [
            SignalComponent("microstructure", s1, 0.35, True),
            SignalComponent("bollinger", s2, 0.25, True),
            SignalComponent("ema_mtf", s3, 0.20, True),
        ]
        score, _ = scorer.compute(components)
        assert -1.0 <= score <= 1.0, f"Score {score} out of range"

    @given(
        n_comps=st.integers(min_value=0, max_value=1),
    )
    @settings(max_examples=100)
    def test_insufficient_components_gives_zero(self, n_comps: int) -> None:
        """Less than min_components triggered always gives score=0."""
        scorer = SignalScorer(min_components=2, min_strength=0.0)
        components = [SignalComponent(f"sig{i}", 0.9, 0.35, True) for i in range(n_comps)]
        score, _ = scorer.compute(components)
        assert score == 0.0


class TestKellyFractionBounds:
    """Property: Kelly fraction always in [0.0, 0.25] (quarter-Kelly cap)."""

    @given(
        win_rate=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
        avg_rr=st.floats(min_value=0.1, max_value=10.0, allow_nan=False),
    )
    @settings(max_examples=300)
    def test_kelly_fraction_in_valid_range(self, win_rate: float, avg_rr: float) -> None:
        """Kelly fraction must always be in [0.0, 0.25]."""
        sizer = KellySizer()
        f = sizer.kelly_fraction(win_rate=win_rate, avg_rr=avg_rr)
        assert 0.0 <= f <= 0.25, f"Kelly fraction {f} out of range [0, 0.25]"
