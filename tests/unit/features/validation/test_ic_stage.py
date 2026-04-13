"""Tests for ICStage — wired validation stage (Phase 3.3)."""

from __future__ import annotations

import numpy as np

from features.ic.measurer import SpearmanICMeasurer
from features.validation.stages import (
    ICStage,
    PipelineStage,
    StageContext,
)


def _make_context(
    feature: np.ndarray,  # type: ignore[type-arg]
    forward_returns: np.ndarray,  # type: ignore[type-arg]
    feature_name: str = "test_feat",
    horizon_bars: int = 1,
) -> StageContext:
    return StageContext(
        feature_name=feature_name,
        metadata={
            "feature_values": feature,
            "forward_returns": forward_returns,
            "horizon_bars": horizon_bars,
        },
    )


class TestICStage:
    """ICStage concrete implementation (no longer a stub)."""

    def test_perfect_feature_passes(self) -> None:
        """Perfect predictor passes ADR-0004 thresholds."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        stage = ICStage(measurer)

        ctx = _make_context(fwd, fwd)
        result = stage.run(ctx)
        assert result.stage == PipelineStage.IC
        assert result.passed is True
        assert result.skipped is None
        assert abs(result.metrics["ic"]) >= 0.02  # type: ignore[operator]

    def test_random_feature_fails(self) -> None:
        """Random noise fails ADR-0004 thresholds."""
        rng = np.random.default_rng(99)
        n = 500
        feat = rng.normal(0, 1, size=n)
        fwd = rng.normal(0, 1, size=n)
        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        stage = ICStage(measurer)

        ctx = _make_context(feat, fwd)
        result = stage.run(ctx)
        assert result.stage == PipelineStage.IC
        assert result.passed is False

    def test_missing_metadata_skips(self) -> None:
        """Missing feature_values in metadata -> skipped."""
        measurer = SpearmanICMeasurer(bootstrap_n=100)
        stage = ICStage(measurer)
        ctx = StageContext(feature_name="no_data")
        result = stage.run(ctx)
        assert result.skipped is not None
        assert result.passed is False
