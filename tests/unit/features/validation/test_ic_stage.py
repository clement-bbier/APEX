"""Tests for ICStage — wired validation stage (Phase 3.3)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from features.ic.base import ICResult
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

    def test_calls_measure_rich_only_once(self) -> None:
        """RichICMeasurer.measure_rich is called once; measure() is never called."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)

        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=50)
        # Spy on both methods.
        original_measure = measurer.measure
        original_measure_rich = measurer.measure_rich
        measure_calls: list[int] = [0]
        measure_rich_calls: list[int] = [0]

        def spy_measure(
            feature: npt.NDArray[np.float64],
            forward_returns: npt.NDArray[np.float64],
        ) -> ICResult:
            measure_calls[0] += 1
            return original_measure(feature, forward_returns)

        def spy_measure_rich(
            feature: npt.NDArray[np.float64],
            forward_returns: npt.NDArray[np.float64],
            feature_name: str,
            horizon_bars: int = 1,
        ) -> ICResult:
            measure_rich_calls[0] += 1
            return original_measure_rich(feature, forward_returns, feature_name, horizon_bars)

        measurer.measure = spy_measure  # type: ignore[assignment]
        measurer.measure_rich = spy_measure_rich  # type: ignore[assignment]

        stage = ICStage(measurer)
        ctx = _make_context(fwd, fwd)
        stage.run(ctx)

        assert measure_calls[0] == 0, "measure() should never be called when measure_rich exists"
        assert measure_rich_calls[0] == 1, "measure_rich() should be called exactly once"

    def test_invalid_horizon_falls_back_to_1(self) -> None:
        """Invalid horizon_bars string -> no crash, uses horizon=1."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=50)
        stage = ICStage(measurer)

        ctx = StageContext(
            feature_name="test_feat",
            metadata={
                "feature_values": fwd,
                "forward_returns": fwd,
                "horizon_bars": "nope",
            },
        )
        result = stage.run(ctx)
        # Should not crash; falls back to horizon=1.
        assert result.stage == PipelineStage.IC
        assert result.skipped is None
