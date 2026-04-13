"""ValidationStage ABC and PipelineStage enum for ADR-0004 pipeline.

Defines the composable stage interface and the six canonical stages
of the feature validation pipeline.

Reference:
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*.
    Cambridge University Press, Ch. 6 ("Feature Importance").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import polars as pl
import structlog

from features.ic.base import ICMetric

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ADR-0004 acceptance thresholds.
_IC_THRESHOLD: float = 0.02
_IC_IR_THRESHOLD: float = 0.50


class PipelineStage(Enum):
    """Canonical stages of the ADR-0004 validation pipeline.

    Order matters: stages execute in enum-declaration order.
    """

    IC = "ic"
    STABILITY = "stability"
    MULTICOLLINEARITY = "multicollinearity"
    MDA = "mda"
    CPCV = "cpcv"
    DSR_PBO = "dsr_pbo"


@dataclass(frozen=True)
class StageResult:
    """Result of a single validation stage.

    Attributes:
        stage: Which pipeline stage produced this result.
        passed: Whether the feature passed this stage's gate.
        skipped: If not None, the reason the stage was skipped
            (e.g. ``"wired in sub-phase 3.3"``).
        metrics: Stage-specific metrics (IC value, VIF, etc.).
    """

    stage: PipelineStage
    passed: bool = False
    skipped: str | None = None
    metrics: dict[str, object] = field(default_factory=dict)


@dataclass
class StageContext:
    """Shared mutable context passed between pipeline stages.

    Each stage may read from and write to this context to pass
    information to downstream stages.
    """

    feature_name: str
    data: pl.DataFrame | None = None
    results: list[StageResult] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class ValidationStage(ABC):
    """Abstract base for a single validation pipeline stage.

    Each stage inspects the ``StageContext``, performs its check,
    and returns a ``StageResult``.  Stages are composable and
    execute in sequence within :class:`ValidationPipeline`.

    Reference:
        ADR-0004 — each stage corresponds to one of the six
        mandatory validation steps.
    """

    @abstractmethod
    def name(self) -> PipelineStage:
        """Which pipeline stage this implements."""

    @abstractmethod
    def run(self, context: StageContext) -> StageResult:
        """Execute this validation stage.

        Args:
            context: Shared pipeline context with feature data
                and accumulated results.

        Returns:
            StageResult for this stage.
        """


# ── Stub stages for Phase 3.1 ────────────────────────────────────────


class ICStage(ValidationStage):
    """IC measurement stage — Phase 3.3 concrete implementation.

    Computes Spearman rank IC between a feature and forward returns,
    then gates on ADR-0004 thresholds: ``|IC| >= 0.02`` and
    ``IC_IR > 0.50``.

    The feature vector and forward returns must be provided via
    ``context.metadata``:

    - ``"feature_values"``: 1-D ``np.ndarray`` of feature values.
    - ``"forward_returns"``: 1-D ``np.ndarray`` of forward returns.
    - ``"horizon_bars"`` (optional, default 1): int horizon.

    Reference:
        ADR-0004, PHASE_3_SPEC Section 2.3.
    """

    def __init__(self, measurer: ICMetric) -> None:
        self._measurer = measurer

    def name(self) -> PipelineStage:
        return PipelineStage.IC

    def run(self, context: StageContext) -> StageResult:
        feature_values = context.metadata.get("feature_values")
        forward_returns = context.metadata.get("forward_returns")

        if feature_values is None or forward_returns is None:
            logger.info(
                "validation_stage.skipped",
                stage="ic",
                feature=context.feature_name,
                reason="feature_values or forward_returns not in metadata",
            )
            return StageResult(
                stage=PipelineStage.IC,
                passed=False,
                skipped="feature_values or forward_returns not in metadata",
            )

        feat_arr = np.asarray(feature_values, dtype=np.float64)
        fwd_arr = np.asarray(forward_returns, dtype=np.float64)
        raw_horizon = context.metadata.get("horizon_bars", 1)
        horizon: int = int(raw_horizon) if isinstance(raw_horizon, (int, float, str)) else 1

        result = self._measurer.measure(feat_arr, fwd_arr)

        # For richer metrics, re-measure with horizon awareness if the
        # measurer is a SpearmanICMeasurer (duck-typing via hasattr).
        if hasattr(self._measurer, "measure_rich"):
            result = self._measurer.measure_rich(
                feature=feat_arr,
                forward_returns=fwd_arr,
                feature_name=context.feature_name,
                horizon_bars=horizon,
            )

        passed = abs(result.ic) >= _IC_THRESHOLD and result.ic_ir >= _IC_IR_THRESHOLD

        metrics: dict[str, object] = {
            "ic": result.ic,
            "ic_ir": result.ic_ir,
            "p_value": result.p_value,
            "ci_low": result.ci_low,
            "ci_high": result.ci_high,
            "n_samples": result.n_samples,
        }
        if result.ic_t_stat is not None:
            metrics["ic_t_stat"] = result.ic_t_stat
        if result.is_significant is not None:
            metrics["is_significant"] = result.is_significant

        logger.info(
            "validation_stage.ic.complete",
            feature=context.feature_name,
            ic=result.ic,
            ic_ir=result.ic_ir,
            passed=passed,
        )

        return StageResult(
            stage=PipelineStage.IC,
            passed=passed,
            metrics=metrics,
        )


class StabilityStage(ValidationStage):
    """IC stability stage — stub for Phase 3.1.

    Concrete implementation wired in Phase 3.3.
    """

    def name(self) -> PipelineStage:
        return PipelineStage.STABILITY

    def run(self, context: StageContext) -> StageResult:
        logger.info(
            "validation_stage.skipped",
            stage="stability",
            feature=context.feature_name,
            reason="wired in sub-phase 3.3",
        )
        return StageResult(
            stage=PipelineStage.STABILITY,
            passed=False,
            skipped="wired in sub-phase 3.3",
        )


class MulticollinearityStage(ValidationStage):
    """Multicollinearity check stage — stub for Phase 3.1.

    Concrete implementation wired in Phase 3.9.
    """

    def name(self) -> PipelineStage:
        return PipelineStage.MULTICOLLINEARITY

    def run(self, context: StageContext) -> StageResult:
        logger.info(
            "validation_stage.skipped",
            stage="multicollinearity",
            feature=context.feature_name,
            reason="wired in sub-phase 3.9",
        )
        return StageResult(
            stage=PipelineStage.MULTICOLLINEARITY,
            passed=False,
            skipped="wired in sub-phase 3.9",
        )


class MDAStage(ValidationStage):
    """Mean Decrease Accuracy stage — stub for Phase 3.1.

    Concrete implementation wired in Phase 3.9.
    """

    def name(self) -> PipelineStage:
        return PipelineStage.MDA

    def run(self, context: StageContext) -> StageResult:
        logger.info(
            "validation_stage.skipped",
            stage="mda",
            feature=context.feature_name,
            reason="wired in sub-phase 3.9",
        )
        return StageResult(
            stage=PipelineStage.MDA,
            passed=False,
            skipped="wired in sub-phase 3.9",
        )


class CPCVStage(ValidationStage):
    """CPCV backtest stage — stub for Phase 3.1.

    Concrete implementation wired in Phase 3.10.
    """

    def name(self) -> PipelineStage:
        return PipelineStage.CPCV

    def run(self, context: StageContext) -> StageResult:
        logger.info(
            "validation_stage.skipped",
            stage="cpcv",
            feature=context.feature_name,
            reason="wired in sub-phase 3.10",
        )
        return StageResult(
            stage=PipelineStage.CPCV,
            passed=False,
            skipped="wired in sub-phase 3.10",
        )


class DSRPBOStage(ValidationStage):
    """DSR/PBO statistical significance stage — stub for Phase 3.1.

    Concrete implementation wired in Phase 3.11.
    """

    def name(self) -> PipelineStage:
        return PipelineStage.DSR_PBO

    def run(self, context: StageContext) -> StageResult:
        logger.info(
            "validation_stage.skipped",
            stage="dsr_pbo",
            feature=context.feature_name,
            reason="wired in sub-phase 3.11",
        )
        return StageResult(
            stage=PipelineStage.DSR_PBO,
            passed=False,
            skipped="wired in sub-phase 3.11",
        )
