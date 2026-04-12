"""Tests for features.cv.base — BacktestSplitter and FeatureValidator ABCs."""

from __future__ import annotations

import pytest

from features.cv.base import BacktestSplitter, FeatureValidator, ValidationReport
from features.validation.stages import PipelineStage, StageResult


class TestBacktestSplitterABC:
    """BacktestSplitter cannot be instantiated."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BacktestSplitter()  # type: ignore[abstract]


class TestFeatureValidatorABC:
    """FeatureValidator cannot be instantiated."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            FeatureValidator()  # type: ignore[abstract]


class TestValidationReport:
    """ValidationReport aggregates stage results."""

    def test_passed_all_skipped(self) -> None:
        report = ValidationReport(
            feature_name="test",
            stage_results=[
                StageResult(stage=PipelineStage.IC, passed=False, skipped="stub"),
                StageResult(stage=PipelineStage.STABILITY, passed=False, skipped="stub"),
            ],
        )
        assert report.passed is True  # all skipped => vacuously passed

    def test_n_stages_run(self) -> None:
        report = ValidationReport(
            feature_name="test",
            stage_results=[
                StageResult(stage=PipelineStage.IC, passed=True),
                StageResult(stage=PipelineStage.STABILITY, passed=False, skipped="stub"),
            ],
        )
        assert report.n_stages_run == 1

    def test_failed_when_stage_fails(self) -> None:
        report = ValidationReport(
            feature_name="test",
            stage_results=[
                StageResult(stage=PipelineStage.IC, passed=False),
            ],
        )
        assert report.passed is False
