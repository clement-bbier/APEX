"""Multiple Hypothesis Testing corrections.

Provides family-wise error rate (FWER) and false discovery rate (FDR)
corrections for p-values arising from simultaneous hypothesis tests
across multiple features/strategies.

References
----------
- Holm, S. (1979). "A simple sequentially rejective multiple test
  procedure." *Scandinavian Journal of Statistics*, 6:65-70.
- Benjamini, Y. & Hochberg, Y. (1995). "Controlling the False Discovery
  Rate: a practical and powerful approach to multiple testing."
  *JRSS B*, 57(1):289-300.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def _validate_inputs(
    p_values: npt.NDArray[np.float64],
    alpha: float,
) -> None:
    """Validate p_values and alpha shared by both corrections.

    Raises
    ------
    ValueError
        If *alpha* is not in ``(0, 1)`` or any p-value is outside
        ``[0, 1]`` or non-finite.
    """
    if not (0.0 < alpha < 1.0):
        msg = f"alpha must be in (0, 1), got {alpha}"
        raise ValueError(msg)
    arr = np.asarray(p_values, dtype=np.float64)
    if arr.ndim != 1 or arr.size == 0:
        msg = f"p_values must be a non-empty 1-D array, got shape {arr.shape}"
        raise ValueError(msg)
    if not np.all(np.isfinite(arr)):
        msg = "All p_values must be finite"
        raise ValueError(msg)
    if np.any(arr < 0.0) or np.any(arr > 1.0):
        msg = "All p_values must be in [0, 1]"
        raise ValueError(msg)


def holm_bonferroni(
    p_values: npt.NDArray[np.float64],
    alpha: float = 0.05,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.float64]]:
    """Holm-Bonferroni step-down correction (Holm 1979).

    Provides **strong control** of the family-wise error rate (FWER).
    Less conservative than vanilla Bonferroni (uniform divide-by-*n*)
    — uses sequential ``α / (n − i + 1)`` at each step.

    Algorithm
    ---------
    1. Sort p-values ascending → ``p_(1) ≤ p_(2) ≤ … ≤ p_(n)``.
    2. For ``i = 1, …, n``: if ``p_(i) > α / (n − i + 1)`` → stop;
       reject hypotheses 1 … (i − 1).
    3. Adjusted p-values: ``p̃_(i) = max(p̃_(i−1), (n − i + 1) × p_(i))``,
       clamped to 1.

    Parameters
    ----------
    p_values : 1-D float array
        Raw p-values, each in ``[0, 1]``.
    alpha : float
        FWER significance level.  Default ``0.05``.

    Returns
    -------
    rejected : bool array
        ``True`` where H₀ is rejected at level *alpha*.
    p_adjusted : float array
        Holm-adjusted p-values (same order as input).

    Reference
    ---------
    Holm, S. (1979). *Scand. J. Statist.* 6:65-70.
    """
    _validate_inputs(p_values, alpha)
    m = len(p_values)
    order = np.argsort(p_values)
    sorted_p = p_values[order]

    # Compute adjusted p-values in sorted order
    adjusted = np.empty(m, dtype=np.float64)
    for i in range(m):
        adjusted[i] = sorted_p[i] * (m - i)
    # Enforce monotonicity (step-down: running maximum)
    np.maximum.accumulate(adjusted, out=adjusted)
    # Clamp to [0, 1]
    np.clip(adjusted, 0.0, 1.0, out=adjusted)

    # Unsort back to original order
    p_adjusted = np.empty(m, dtype=np.float64)
    p_adjusted[order] = adjusted

    rejected = p_adjusted <= alpha
    return rejected, p_adjusted


def benjamini_hochberg(
    p_values: npt.NDArray[np.float64],
    alpha: float = 0.05,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.float64]]:
    """Benjamini-Hochberg FDR control (Benjamini & Hochberg 1995).

    Controls the **expected proportion of false discoveries** among
    rejected hypotheses.  Less conservative than Holm — accepts some
    false positives in exchange for more true positives.

    Algorithm
    ---------
    1. Sort p-values ascending → ``p_(1) ≤ … ≤ p_(n)``.
    2. For ``i = n, n−1, …, 1``: adjusted ``p̃_(i) = min(p̃_(i+1), n/i × p_(i))``,
       clamped to 1.
    3. Reject where ``p̃_(i) ≤ α``.

    Parameters
    ----------
    p_values : 1-D float array
        Raw p-values, each in ``[0, 1]``.
    alpha : float
        FDR significance level.  Default ``0.05``.

    Returns
    -------
    rejected : bool array
        ``True`` where H₀ is rejected at level *alpha*.
    p_adjusted : float array
        BH-adjusted p-values (same order as input).

    Reference
    ---------
    Benjamini, Y. & Hochberg, Y. (1995). *JRSS B* 57(1):289-300.
    """
    _validate_inputs(p_values, alpha)
    m = len(p_values)
    order = np.argsort(p_values)
    sorted_p = p_values[order]

    # Compute adjusted p-values in sorted order (step-up)
    adjusted = np.empty(m, dtype=np.float64)
    for i in range(m):
        adjusted[i] = sorted_p[i] * m / (i + 1)
    # Enforce monotonicity (step-up: running minimum from the right)
    for i in range(m - 2, -1, -1):
        adjusted[i] = min(adjusted[i], adjusted[i + 1])
    # Clamp to [0, 1]
    np.clip(adjusted, 0.0, 1.0, out=adjusted)

    # Unsort back to original order
    p_adjusted = np.empty(m, dtype=np.float64)
    p_adjusted[order] = adjusted

    rejected = p_adjusted <= alpha
    return rejected, p_adjusted
