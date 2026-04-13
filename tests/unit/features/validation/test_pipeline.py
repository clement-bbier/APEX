"""Tests for features.validation.pipeline — ValidationPipeline orchestrator.

The KEY test for Phase 3.1: verify that the pipeline executes all 6
stub stages in the correct ADR-0004 order and produces a complete
ValidationReport.
"""

from __future__ import annotations

import polars as pl
import pytest

from features.base import FeatureCalculator
from features.ic.measurer import SpearmanICMeasurer
from features.validation.pipeline import ValidationPipeline
from features.validation.stages import (
    CPCVStage,
    DSRPBOStage,
    ICStage,
    MDAStage,
    MulticollinearityStage,
    PipelineStage,
    StabilityStage,
)

_IC_MEASURER = SpearmanICMeasurer(bootstrap_n=50)

# ── Dummy calculator for testing ─────────────────────────────────────


class _StubCalculator(FeatureCalculator):
    def name(self) -> str:
        return "stub_feature"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df

    def required_columns(self) -> list[str]:
        return []

    def output_columns(self) -> list[str]:
        return []


# ── Tests ────────────────────────────────────────────────────────────


class TestValidationPipelineStubs:
    """ValidationPipeline with all 6 ADR-0004 stub stages."""

    @pytest.fixture
    def all_stages_pipeline(self) -> ValidationPipeline:
        return ValidationPipeline(
            stages=[
                ICStage(_IC_MEASURER),
                StabilityStage(),
                MulticollinearityStage(),
                MDAStage(),
                CPCVStage(),
                DSRPBOStage(),
            ]
        )

    def test_executes_all_six_stages(self, all_stages_pipeline: ValidationPipeline) -> None:
        """KEY TEST: all 6 stages execute and appear in the report."""
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        assert len(report.stage_results) == 6

    def test_stages_in_correct_order(self, all_stages_pipeline: ValidationPipeline) -> None:
        """Stages appear in ADR-0004 canonical order."""
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        expected_order = [
            PipelineStage.IC,
            PipelineStage.STABILITY,
            PipelineStage.MULTICOLLINEARITY,
            PipelineStage.MDA,
            PipelineStage.CPCV,
            PipelineStage.DSR_PBO,
        ]
        actual_order = [r.stage for r in report.stage_results]
        assert actual_order == expected_order

    def test_all_stages_skipped(self, all_stages_pipeline: ValidationPipeline) -> None:
        """All stubs report skipped with reason."""
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        for result in report.stage_results:
            assert result.skipped is not None

    def test_report_feature_name(self, all_stages_pipeline: ValidationPipeline) -> None:
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        assert report.feature_name == "stub_feature"

    def test_report_passed_vacuously(self, all_stages_pipeline: ValidationPipeline) -> None:
        """All-skipped pipeline is vacuously passed."""
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        assert report.passed is True

    def test_no_stages_run_count(self, all_stages_pipeline: ValidationPipeline) -> None:
        calc = _StubCalculator()
        report = all_stages_pipeline.run(calc)
        assert report.n_stages_run == 0

    def test_empty_pipeline(self) -> None:
        pipeline = ValidationPipeline(stages=[])
        calc = _StubCalculator()
        report = pipeline.run(calc)
        assert len(report.stage_results) == 0
        assert report.passed is True

    def test_stages_property_returns_copy(self) -> None:
        pipeline = ValidationPipeline(stages=[ICStage(_IC_MEASURER)])
        pipeline.stages.append(StabilityStage())
        assert len(pipeline.stages) == 1
