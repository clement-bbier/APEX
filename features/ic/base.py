"""ICMetric ABC and ICResult dataclass — IC measurement framework.

The Information Coefficient (IC) is the Spearman rank correlation
between a feature value at time *t* and the forward return over a
specified horizon.  It is the single most important metric for
evaluating alpha features.

Concrete implementation arrives in Phase 3.3.

Reference:
    Grinold, R. C. (1989). "The Fundamental Law of Active Management."
    *Journal of Portfolio Management*, 15(3), 30-37.
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management*
    (2nd ed.). McGraw-Hill, Ch. 4, 6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class ICResult:
    """Result of IC measurement for a single feature.

    All fields are populated by the concrete ICMetric implementation
    (Phase 3.3).

    Reference:
        Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
        Management* (2nd ed.), Ch. 6. McGraw-Hill.
    """

    ic: float
    """Mean Spearman rank IC across the evaluation period."""

    ic_ir: float
    """IC Information Ratio: mean(IC) / std(IC). Stability measure."""

    p_value: float
    """p-value for the null hypothesis IC == 0."""

    n_samples: int
    """Number of observation periods used."""

    ci_low: float
    """Lower bound of the 95% confidence interval for IC."""

    ci_high: float
    """Upper bound of the 95% confidence interval for IC."""


class ICMetric(ABC):
    """Abstract IC measurement interface.

    Concrete implementation (Phase 3.3) computes Spearman rank IC
    between feature values and forward returns.

    Reference:
        Grinold, R. C. (1989). "The Fundamental Law of Active
        Management." *Journal of Portfolio Management*, 15(3), 30-37.
    """

    @abstractmethod
    def measure(
        self,
        feature: npt.NDArray[np.float64],
        forward_returns: npt.NDArray[np.float64],
    ) -> ICResult:
        """Measure the IC of a feature against forward returns.

        Args:
            feature: 1-D array of feature values at each time step.
            forward_returns: 1-D array of realized forward returns
                over the target horizon.

        Returns:
            ICResult with IC, IC_IR, p-value, and confidence interval.
        """
