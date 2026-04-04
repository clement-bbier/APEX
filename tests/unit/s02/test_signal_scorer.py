"""Tests for multi-dimensional signal scoring confluence."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from services.s02_signal_engine.signal_scorer import SignalComponent, SignalScorer


def make_component(name: str, score: float, triggered: bool = True) -> SignalComponent:
    return SignalComponent(name=name, score=score, weight=0.2, triggered=triggered)


class TestSignalScorer:
    def test_no_signal_below_min_components(self) -> None:
        scorer = SignalScorer(min_components=2)
        components = [
            make_component("microstructure", 0.8, triggered=True),
            make_component("bollinger", 0.7, triggered=False),
        ]
        score, _ = scorer.compute(components)
        assert score == 0.0

    def test_strong_bullish_confluence(self) -> None:
        scorer = SignalScorer(min_components=2, min_strength=0.15)
        components = [
            make_component("microstructure", 0.9),
            make_component("bollinger", 0.8),
            make_component("ema_mtf", 1.0),
        ]
        score, triggers = scorer.compute(components)
        assert score > 0.5
        assert "microstructure" in triggers

    def test_strong_bearish_confluence(self) -> None:
        scorer = SignalScorer(min_components=2, min_strength=0.15)
        components = [
            make_component("microstructure", -0.9),
            make_component("bollinger", -0.8),
        ]
        score, _ = scorer.compute(components)
        assert score < -0.2

    def test_conflicting_signals_reduce_strength(self) -> None:
        scorer = SignalScorer(min_components=2)
        components = [
            make_component("microstructure", 0.9),  # bullish
            make_component("bollinger", -0.8),  # bearish
        ]
        score_conflict, _ = scorer.compute(components)

        components_agree = [
            make_component("microstructure", 0.9),
            make_component("bollinger", 0.8),
        ]
        score_agree, _ = scorer.compute(components_agree)
        # Conflicting signals should produce weaker score
        assert abs(score_conflict) < abs(score_agree)

    def test_below_min_strength_returns_zero(self) -> None:
        scorer = SignalScorer(min_components=2, min_strength=0.90)
        components = [
            make_component("microstructure", 0.3),
            make_component("bollinger", 0.2),
        ]
        score, triggers = scorer.compute(components)
        assert score == 0.0
        assert triggers == []

    def test_triggers_list_contains_active_names(self) -> None:
        scorer = SignalScorer(min_components=2, min_strength=0.0)
        components = [
            make_component("microstructure", 0.9),
            make_component("bollinger", 0.8),
            make_component("ema_mtf", 0.5, triggered=False),
        ]
        _, triggers = scorer.compute(components)
        assert "microstructure" in triggers
        assert "bollinger" in triggers
        assert "ema_mtf" not in triggers

    def test_empty_components_returns_zero(self) -> None:
        scorer = SignalScorer(min_components=2)
        score, triggers = scorer.compute([])
        assert score == 0.0
        assert triggers == []

    def test_single_component_below_min(self) -> None:
        scorer = SignalScorer(min_components=2)
        components = [make_component("microstructure", 1.0)]
        score, _ = scorer.compute(components)
        assert score == 0.0

    def test_score_always_in_valid_range(self) -> None:
        @given(
            s1=st.floats(-1.0, 1.0),
            s2=st.floats(-1.0, 1.0),
            s3=st.floats(-1.0, 1.0),
        )
        @settings(max_examples=200)
        def inner(s1: float, s2: float, s3: float) -> None:
            scorer = SignalScorer(min_components=2)
            comps = [
                make_component("microstructure", s1),
                make_component("bollinger", s2),
                make_component("ema_mtf", s3),
            ]
            score, _ = scorer.compute(comps)
            assert -1.0 <= score <= 1.0

        inner()

    def test_uses_weights_from_class(self) -> None:
        """Known weights: microstructure=0.35, bollinger=0.25. Full agreement."""
        scorer = SignalScorer(min_components=2, min_strength=0.0)
        components = [
            SignalComponent(name="microstructure", score=1.0, weight=0.35, triggered=True),
            SignalComponent(name="bollinger", score=1.0, weight=0.25, triggered=True),
        ]
        score, _ = scorer.compute(components)
        # weighted_sum = 0.35*1.0 + 0.25*1.0 = 0.60; total_weight = 0.60 → raw = 1.0
        assert abs(score - 1.0) < 1e-6
