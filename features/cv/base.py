"""BacktestSplitter and FeatureValidator ABCs — cross-validation contracts.

BacktestSplitter defines the interface for CPCV (Combinatorial Purged
Cross-Validation) and other CV strategies.  FeatureValidator defines
the full ADR-0004 validation contract.

Concrete implementations arrive in Phase 3.10 (CPCV) and 3.12 (report).

Reference:
    Bailey, D. H. & Lopez de Prado, M. (2017). "An Open-Source
    Implementation of the Critical-Line Algorithm for Portfolio
    Optimization." *Journal of Computational Finance*.
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 12 — "Backtesting through Cross-Validation".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from features.base import FeatureCalculator
from features.validation.stages import StageResult


@dataclass(frozen=True)
class ValidationReport:
    """Full validation report for a single feature calculator.

    Contains results from each stage of the ADR-0004 pipeline:
    IC, stability, multicollinearity, MDA, CPCV, DSR/PBO.

    Reference:
        ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    """

    feature_name: str
    """Name of the validated feature calculator."""

    stage_results: list[StageResult] = field(default_factory=list)
    """Ordered list of results from each validation stage."""

    @property
    def passed(self) -> bool:
        """True if all non-skipped stages passed."""
        return all(r.passed or r.skipped is not None for r in self.stage_results)

    @property
    def n_stages_run(self) -> int:
        """Number of stages that actually executed (not skipped)."""
        return sum(1 for r in self.stage_results if r.skipped is None)


class BacktestSplitter(ABC):
    """Abstract CV splitter interface.

    Concrete implementation (Phase 3.10) provides CPCV with purging
    and embargo.

    Reference:
        Bailey, D. H. & Lopez de Prado, M. (2017). CPCV.
        Lopez de Prado, M. (2018). AFML, Ch. 12.
    """

    @abstractmethod
    def split(
        self,
        x: npt.NDArray[np.float64],
        y: npt.NDArray[np.float64],
    ) -> Iterator[tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]]:
        """Generate (train_indices, test_indices) pairs.

        Args:
            x: Feature matrix (n_samples, n_features).
            y: Target vector (n_samples,).

        Yields:
            Tuples of (train_indices, test_indices) arrays.
        """

    @abstractmethod
    def n_splits(self) -> int:
        """Return the number of CV splits."""


class FeatureValidator(ABC):
    """Abstract feature validation interface.

    Concrete implementation (Phase 3.12) runs the full ADR-0004
    pipeline and produces a ValidationReport.

    Reference:
        ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
        Lopez de Prado, M. (2020). *Machine Learning for Asset
        Managers*. Cambridge University Press, Ch. 6.
    """

    @abstractmethod
    def validate(
        self,
        calculator: FeatureCalculator,
        data: npt.NDArray[np.float64],
    ) -> ValidationReport:
        """Run the full validation pipeline on a feature calculator.

        Args:
            calculator: The feature calculator to validate.
            data: Raw data matrix for validation.

        Returns:
            ValidationReport with results from all ADR-0004 stages.
        """
