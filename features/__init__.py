"""Feature Engineering Pipeline for APEX Trading System — Phase 3.

This package implements the Feature Validation Harness described in
``docs/phases/PHASE_3_SPEC.md``.  Phase 3.1 provides the structural
foundation: ABCs, pipeline orchestrator, labeler adapter, sample
weighter, and the ADR-0004 validation pipeline skeleton.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 2-5.
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management*
    (2nd ed.). McGraw-Hill, Ch. 14.
"""

from features.base import FeatureCalculator
from features.pipeline import FeaturePipeline

__all__: list[str] = [
    "FeatureCalculator",
    "FeaturePipeline",
]
