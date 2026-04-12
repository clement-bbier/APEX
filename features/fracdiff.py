"""Fractional Differentiation wrappers for the feature pipeline.

Delegates entirely to ``core.math.fractional_diff``.  No new math
logic is added here — this module exists solely to provide a
pipeline-friendly interface.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 5 — "Fractionally Differentiated Features".
    Hosking, J. R. M. (1981). "Fractional differencing".
    *Biometrika*, 68(1), 165-176.
"""

from __future__ import annotations

from core.math.fractional_diff import FracDiffResult, FractionalDifferentiator


def compute_fracdiff(
    series: list[float],
    d: float,
    threshold: float = 1e-5,
) -> FracDiffResult:
    """Compute fractional differentiation of *series* at order *d*.

    Wrapper around :meth:`FractionalDifferentiator.differentiate`.

    Args:
        series: Input time series (e.g. log-prices).
        d: Differentiation order in (0, 1].
        threshold: FFD weight truncation cutoff.

    Returns:
        FracDiffResult with differentiated series and metadata.
    """
    fd = FractionalDifferentiator()
    return fd.differentiate(series, d, threshold)


def find_minimum_d(
    series: list[float],
    adf_threshold: float = 0.05,
    d_low: float = 0.0,
    d_high: float = 1.0,
    n_steps: int = 20,
) -> FracDiffResult:
    """Find the minimum *d* that achieves stationarity.

    Wrapper around :meth:`FractionalDifferentiator.find_minimum_d`.

    Args:
        series: Input time series (log-prices recommended).
        adf_threshold: Not used directly (ADF test is internal at 5%).
            Kept in signature for interface compatibility.
        d_low: Lower bound for the d search.
        d_high: Upper bound for the d search.
        n_steps: Number of candidate d values to test.

    Returns:
        FracDiffResult for the minimum stationary d.
    """
    fd = FractionalDifferentiator()
    return fd.find_minimum_d(series, d_low, d_high, n_steps)
