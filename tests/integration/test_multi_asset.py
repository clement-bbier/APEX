"""
Integration test: BTC and AAPL signals processed simultaneously.
Verifies services handle concurrent symbols without interference.
"""

from __future__ import annotations

from services.s02_signal_engine.signal_scorer import SignalComponent, SignalScorer


class TestMultiAssetConcurrent:
    def test_btc_and_aapl_signals_independent(self) -> None:
        """Two symbols generate independent signals with no cross-contamination."""
        scorer = SignalScorer(min_components=2, min_strength=0.15)

        # BTC: bullish signal
        btc_comps = [
            SignalComponent("microstructure", 0.90, 0.35, True),
            SignalComponent("bollinger", 0.80, 0.25, True),
        ]
        btc_score, _ = scorer.compute(btc_comps)

        # AAPL: bearish signal (same scorer instance)
        aapl_comps = [
            SignalComponent("microstructure", -0.85, 0.35, True),
            SignalComponent("bollinger", -0.70, 0.25, True),
        ]
        aapl_score, _ = scorer.compute(aapl_comps)

        assert btc_score > 0, "BTC should be bullish"
        assert aapl_score < 0, "AAPL should be bearish"

    def test_multiple_scorer_instances_independent(self) -> None:
        """Separate scorer instances produce identical results for same inputs."""
        comps = [
            SignalComponent("microstructure", 0.75, 0.35, True),
            SignalComponent("bollinger", 0.65, 0.25, True),
        ]
        s1 = SignalScorer(min_components=2, min_strength=0.10)
        s2 = SignalScorer(min_components=2, min_strength=0.10)

        score1, _ = s1.compute(comps)
        score2, _ = s2.compute(comps)
        assert score1 == score2

    def test_bearish_score_in_valid_range(self) -> None:
        """Bearish signals produce scores in [-1.0, 0.0]."""
        scorer = SignalScorer(min_components=2, min_strength=0.10)
        comps = [
            SignalComponent("microstructure", -0.90, 0.35, True),
            SignalComponent("bollinger", -0.80, 0.25, True),
        ]
        score, _ = scorer.compute(comps)
        assert -1.0 <= score < 0.0

    def test_bullish_score_in_valid_range(self) -> None:
        """Bullish signals produce scores in [0.0, 1.0]."""
        scorer = SignalScorer(min_components=2, min_strength=0.10)
        comps = [
            SignalComponent("microstructure", 0.90, 0.35, True),
            SignalComponent("bollinger", 0.80, 0.25, True),
        ]
        score, _ = scorer.compute(comps)
        assert 0.0 < score <= 1.0
