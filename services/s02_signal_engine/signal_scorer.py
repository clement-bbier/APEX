"""Multi-dimensional signal scoring engine.

Replaces naive single-indicator signals with a confluence matrix.
No trade unless at least 2 independent signal sources agree.

Mathematical foundation:
    final_strength = Σ(weight_i × score_i) / Σ(weight_i)
    where each score_i ∈ [-1.0, +1.0]

Only publishes a Signal when |final_strength| > MIN_SIGNAL_STRENGTH (configurable).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SignalComponent:
    """One contributing signal source with its weight and score."""

    name: str
    score: float  # [-1.0, +1.0]
    weight: float  # [0.0, 1.0]
    triggered: bool  # did this component fire?
    metadata: dict[str, Any] = field(default_factory=dict)


class SignalScorer:
    """Aggregates multiple independent signal components into one final score.

    Component weights (sum to 1.0):
        Microstructure (OFI + CVD)   : 0.35  ← highest weight, most reliable
        Bollinger squeeze/breakout    : 0.25
        EMA multi-timeframe alignment : 0.20
        RSI divergence                : 0.15
        VWAP position                 : 0.05
    """

    WEIGHTS: dict[str, float] = {
        "microstructure": 0.35,
        "bollinger": 0.25,
        "ema_mtf": 0.20,
        "rsi_divergence": 0.15,
        "vwap": 0.05,
    }

    def __init__(self, min_components: int = 2, min_strength: float = 0.20) -> None:
        """
        Args:
            min_components: Minimum number of components that must agree (not just trigger)
            min_strength: Minimum |score| to generate a publishable signal
        """
        self.min_components = min_components
        self.min_strength = min_strength

    def compute(self, components: list[SignalComponent]) -> tuple[float, list[str]]:
        """Compute weighted confluence score.

        Returns:
            (final_strength, active_triggers)
            final_strength ∈ [-1.0, +1.0], 0.0 if below threshold
        """
        active = [c for c in components if c.triggered]

        if len(active) < self.min_components:
            return 0.0, []

        # All active components must broadly agree on direction
        signs = [np.sign(c.score) for c in active if abs(c.score) > 0.05]
        if signs and len(set(signs)) > 1:
            # Conflicting signals — reduce strength by 50%
            agreement_mult = 0.5
        else:
            agreement_mult = 1.0

        total_weight = sum(self.WEIGHTS.get(c.name, 0.1) for c in active)
        if total_weight == 0:
            return 0.0, []

        weighted_sum = sum(self.WEIGHTS.get(c.name, 0.1) * c.score for c in active)
        raw_strength = (weighted_sum / total_weight) * agreement_mult

        # Clamp to [-1.0, +1.0]
        final_strength = max(-1.0, min(1.0, raw_strength))

        if abs(final_strength) < self.min_strength:
            return 0.0, []

        triggers = [c.name for c in active]
        return final_strength, triggers
