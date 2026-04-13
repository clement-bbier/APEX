"""Pure statistical functions for IC measurement.

All functions are side-effect-free and operate on NumPy arrays.
They form the mathematical core of :class:`SpearmanICMeasurer`.

References:
    Newey, W. K. & West, K. D. (1987). "A Simple, Positive
    Semi-Definite, Heteroskedasticity and Autocorrelation Consistent
    Covariance Matrix." *Econometrica*, 55(3), 703-708.

    Politis, D. N. & Romano, J. P. (1994). "The Stationary
    Bootstrap." *JASA*, 89(428), 1303-1313.

    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
    Management* (2nd ed.). McGraw-Hill, Ch. 6, 16.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy import stats as sp_stats

# Minimum valid pairs for a meaningful Spearman correlation.
_MIN_VALID_PAIRS: int = 10


def safe_spearman(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
) -> tuple[float, float]:
    """Spearman rank correlation with NaN/constant-input handling.

    Returns ``(ic, p_value)``.  Returns ``(0.0, 1.0)`` when either
    input is constant, contains fewer than ``_MIN_VALID_PAIRS`` valid
    (non-NaN) observations, or when ``scipy.stats.spearmanr`` produces
    a NaN result.

    Args:
        x: 1-D feature array.
        y: 1-D forward-return array (same length as *x*).

    Returns:
        Tuple ``(ic, p_value)`` with ``ic`` in ``[-1, 1]``.
    """
    if x.size != y.size:
        return 0.0, 1.0

    # Drop pairs where either value is NaN.
    mask = np.isfinite(x) & np.isfinite(y)
    x_clean = x[mask]
    y_clean = y[mask]

    if x_clean.size < _MIN_VALID_PAIRS:
        return 0.0, 1.0

    # Constant input check — std == 0 means all values identical.
    if np.ptp(x_clean) == 0.0 or np.ptp(y_clean) == 0.0:
        return 0.0, 1.0

    result = sp_stats.spearmanr(x_clean, y_clean)
    ic = float(result.statistic)
    pv = float(result.pvalue)

    # Guard against scipy returning nan (edge cases).
    if np.isnan(ic) or np.isnan(pv):
        return 0.0, 1.0

    return ic, pv


def newey_west_se(
    series: npt.NDArray[np.float64],
    lags: int,
) -> float:
    """Newey-West HAC standard error of the sample mean.

    For overlapping forward returns at horizon *h*, use
    ``lags = h - 1`` at minimum.

    When ``lags == 0`` this reduces to the classical standard error
    ``std(series) / sqrt(n)``.

    Args:
        series: 1-D array of per-period IC values.
        lags: Number of autocovariance lags to include.

    Returns:
        HAC-corrected standard error (always >= 0).

    Reference:
        Newey, W. K. & West, K. D. (1987). *Econometrica*, 55(3),
        703-708.
    """
    n = series.size
    if n < 2:
        return 0.0

    demeaned = series - np.mean(series)

    # Gamma_0 = sample variance (biased estimator, standard for NW).
    gamma_0 = float(np.dot(demeaned, demeaned) / n)

    # Bartlett-kernel weighted autocovariances.
    nw_var = gamma_0
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma_j = float(np.dot(demeaned[lag:], demeaned[:-lag]) / n)
        nw_var += 2.0 * weight * gamma_j

    # Clamp to zero (positive semi-definite guarantee of Bartlett kernel
    # can be violated with very small samples due to finite-sample bias).
    nw_var = max(nw_var, 0.0)

    return float(np.sqrt(nw_var / n))


def ic_t_statistic(
    ic_series: npt.NDArray[np.float64],
    horizon_bars: int,
) -> float:
    """HAC-corrected t-statistic for H0: mean(IC) == 0.

    Uses Newey-West with ``lags = max(horizon_bars - 1, 0)`` to
    correct for the autocorrelation induced by overlapping forward
    returns.

    Args:
        ic_series: 1-D array of per-period IC values.
        horizon_bars: Forward-return horizon in bars.

    Returns:
        t-statistic.  Returns 0.0 when the HAC SE is zero (e.g.
        constant series or single observation).

    Reference:
        Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
        Management* (2nd ed.), Ch. 16, p. 403.
    """
    if ic_series.size < 2:
        return 0.0

    lags = max(horizon_bars - 1, 0)
    se = newey_west_se(ic_series, lags=lags)
    if se < 1e-15:
        return 0.0

    return float(np.mean(ic_series) / se)


def ic_bootstrap_ci(
    ic_series: npt.NDArray[np.float64],
    confidence: float = 0.95,
    n_boot: int = 1000,
    block_size: int | None = None,
    seed: int = 42,
) -> tuple[float, float]:
    """Stationary-bootstrap confidence interval on mean(IC).

    Uses the Politis-Romano (1994) stationary bootstrap, which
    samples geometrically-distributed blocks to preserve weak
    dependence structure.

    Args:
        ic_series: 1-D array of per-period IC values.
        confidence: Two-sided confidence level (default 0.95).
        n_boot: Number of bootstrap replications.
        block_size: Expected geometric block length.  Defaults to
            ``max(1, round(n^{1/3}))``.
        seed: RNG seed for reproducibility.

    Returns:
        Tuple ``(ci_low, ci_high)``.  Returns ``(0.0, 0.0)`` for
        fewer than 2 observations.

    Reference:
        Politis, D. N. & Romano, J. P. (1994). "The Stationary
        Bootstrap." *JASA*, 89(428), 1303-1313.
    """
    n = ic_series.size
    if n < 2:
        return 0.0, 0.0

    if block_size is None:
        block_size = max(1, round(n ** (1.0 / 3.0)))

    p = 1.0 / block_size
    rng = np.random.default_rng(seed)
    alpha = 1.0 - confidence

    means = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.intp)
        i = 0
        while i < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(p))
            length = min(length, n - i)
            for k in range(length):
                idx[i + k] = (start + k) % n
            i += length
        means[b] = float(np.mean(ic_series[idx]))

    lo_pct = 100.0 * (alpha / 2.0)
    hi_pct = 100.0 * (1.0 - alpha / 2.0)
    return float(np.percentile(means, lo_pct)), float(np.percentile(means, hi_pct))
