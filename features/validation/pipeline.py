"""ValidationPipeline — ADR-0004 six-step validation orchestrator.

Composes :class:`ValidationStage` instances into a sequential pipeline
that evaluates a feature calculator against the canonical six-step
methodology: IC -> stability -> multicollinearity -> MDA -> CPCV ->
DSR/PBO.

In Phase 3.1, all stages are stubs that log and return ``skipped``.
Concrete stages are wired in sub-phases 3.3, 3.9, 3.10, 3.11.

Reference:
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*.
    Cambridge University Press, Ch. 6 ("Feature Importance").
"""

from __future__ import annotations

import polars as pl
import structlog

from features.base import FeatureCalculator
from features.cv.base import ValidationReport
from features.validation.stages import (
    StageContext,
    StageResult,
    ValidationStage,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class ValidationPipeline:
    """Orchestrator IC -> stability -> multicol -> MDA -> CPCV -> DSR/PBO.

    Implements ADR-0004.  In Phase 3.1, each stage is a no-op stub that
    returns a ``StageResult`` with ``skipped`` set.  The concrete stages
    are wired in sub-phases 3.3 (IC), 3.9 (multicol + MDA), 3.10 (CPCV),
    3.11 (DSR/PBO).

    Reference:
        ADR-0004, Section 2.
        Lopez de Prado, M. (2020). *Machine Learning for Asset
        Managers*. Cambridge University Press, Ch. 6.
    """

    def __init__(self, stages: list[ValidationStage]) -> None:
        self._stages = stages

    @property
    def stages(self) -> list[ValidationStage]:
        """Injected validation stages (in execution order)."""
        return list(self._stages)

    def run(
        self,
        calculator: FeatureCalculator,
        data: pl.DataFrame | None = None,
    ) -> ValidationReport:
        """Execute all validation stages sequentially.

        Args:
            calculator: The feature calculator being validated.
            data: Raw data for validation (type depends on stage).

        Returns:
            ValidationReport aggregating all stage results.
        """
        context = StageContext(
            feature_name=calculator.name(),
            data=data,
        )

        for stage in self._stages:
            result: StageResult = stage.run(context)
            context.results.append(result)

        report = ValidationReport(
            feature_name=calculator.name(),
            stage_results=list(context.results),
        )

        logger.info(
            "validation_pipeline.complete",
            feature=calculator.name(),
            n_stages=len(context.results),
            n_skipped=sum(1 for r in context.results if r.skipped is not None),
            passed=report.passed,
        )

        return report
