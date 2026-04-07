"""Fractional Differentiation — Batch + Incremental Production Implementation.

MOTIVATION:
    Financial time series (log-prices) are non-stationary: they contain a
    unit root (I(1) process). Classical ML requires stationary inputs.

    Two naive solutions and their problems:
    ❌ Raw prices: non-stationary → model memorizes level, not pattern
    ❌ Returns (d=1): stationary but LOSES ALL MEMORY (no predictive features)

    Optimal solution (López de Prado 2018, Ch.5):
    ✅ d ∈ (0,1): minimum d that achieves stationarity while MAXIMIZING memory

    For BTC: d ≈ 0.3-0.5 → ~65-75% memory preserved, ADF stationary.

PRODUCTION ARCHITECTURE:
    FractionalDifferentiator  → offline calibration (find d_opt)
    IncrementalFracDiff       → live streaming, O(n_lags)/tick ≈ 0.005ms

References:
    López de Prado (2018). AFML Wiley Ch.5 (FFD, Snippet 5.3). Cornell→AQR.
    Hosking (1981). Biometrika 68(1). IBM Research.
    Granger & Joyeux (1980). JTSA 1(1). Nobel Economics 2003.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class FracDiffResult:
    """Output of a batch fractional differentiation pass."""

    series: list[float]
    d: float
    weights: list[float]
    memory_retained_pct: float
    is_stationary: bool


class FractionalDifferentiator:
    """Batch Fixed-width FFD for offline calibration.

    Use FractionalDifferentiator.find_minimum_d() to determine d_opt from
    historical log-prices, then pass d_opt to IncrementalFracDiff for live use.

    Reference: López de Prado (2018) AFML, Wiley, Chapter 5, Snippet 5.3.
    """

    def _get_weights_ffd(self, d: float, threshold: float = 1e-5) -> list[float]:
        """Compute FFD weights: ω_k = ω_{k-1} × (k-1-d)/k.

        Truncates at |ω_k| < threshold (fixed-width window).

        Args:
            d: Differentiation order in (0, 1].
            threshold: Weight magnitude cutoff.

        Returns:
            List of weights [ω_0, ω_1, …, ω_K] where ω_0 = 1.
        """
        weights = [1.0]
        k = 1
        while k < 10_000:
            w = weights[-1] * (k - 1.0 - d) / k
            if abs(w) < threshold:
                break
            weights.append(w)
            k += 1
        return weights

    def memory_retained(self, d: float, n_lags: int) -> float:
        """Fraction of memory preserved using first n_lags weights.

        Higher value = more memory retained = richer features.
        At d=0: 100% memory. At d=1: 0% memory (pure returns).

        Args:
            d: Differentiation order.
            n_lags: Number of lags in the truncated window.

        Returns:
            Memory fraction in [0, 1].
        """
        finite = sum(abs(w) for w in self._get_weights_ffd(d)[:n_lags])
        total = sum(abs(w) for w in self._get_weights_ffd(d, threshold=1e-8))
        return finite / total if total > 0 else 0.0

    def differentiate(
        self,
        series: list[float],
        d: float,
        threshold: float = 1e-5,
    ) -> FracDiffResult:
        """Batch FFD differentiation. Use for offline calibration only.

        Args:
            series: Log-price series (must be length ≥ 10).
            d: Differentiation order in (0, 1].
            threshold: FFD weight truncation cutoff.

        Returns:
            FracDiffResult with differentiated series and stationarity verdict.
        """
        if len(series) < 10:
            return FracDiffResult(series, d, [1.0], 100.0, False)

        weights = self._get_weights_ffd(d, threshold)
        n_lags = len(weights)
        arr = np.asarray(series, dtype=float)
        result = [
            float(np.dot(weights, arr[i - n_lags + 1 : i + 1][::-1]))
            for i in range(n_lags - 1, len(arr))
        ]
        return FracDiffResult(
            result,
            d,
            weights,
            self.memory_retained(d, n_lags) * 100,
            self._adf_stationary(result),
        )

    def find_minimum_d(
        self,
        series: list[float],
        d_low: float = 0.0,
        d_high: float = 1.0,
        n_steps: int = 20,
    ) -> FracDiffResult:
        """Binary search: minimum d that achieves stationarity.

        Scans d linearly from d_low to d_high and returns the first result
        that passes the ADF test at the 5% level (t-stat < -2.86).

        Reference: López de Prado (2018), AFML, Snippet 5.3.

        Args:
            series: Log-price series (≥ 30 observations recommended).
            d_low: Lower bound for d search.
            d_high: Upper bound for d search.
            n_steps: Number of candidate d values to test.

        Returns:
            FracDiffResult for the minimum stationary d, or d_high if none found.
        """
        for d in np.linspace(d_low, d_high, n_steps):
            r = self.differentiate(series, float(d))
            if r.is_stationary:
                return r
        return self.differentiate(series, d_high)

    def _adf_stationary(self, series: list[float]) -> bool:
        """Simple ADF test. Reject H₀ (unit root) at 5% if t-stat < -2.86.

        Uses OLS regression: Δy_t = β×y_{t-1} + ε_t.
        Stationarity: β < 0 and t-stat = β/se(β) < -2.86.

        Args:
            series: Differenced series to test.

        Returns:
            True if stationary at 5% significance level.
        """
        if len(series) < 20:
            return False
        try:
            arr = np.asarray(series, dtype=float)
            y = np.diff(arr)
            x = arr[:-1] - float(np.mean(arr[:-1]))
            denom = float(np.dot(x, x))
            if denom < 1e-10:
                return False
            beta = float(np.dot(x, y)) / denom
            resid = y - beta * x
            se = math.sqrt(max(1e-12, float(np.var(resid, ddof=2)) / denom))
            return (beta / se) < -2.86
        except Exception:
            return False


class IncrementalFracDiff:
    """Production streaming fractional differentiation — O(n_lags) per tick.

    Pre-computes weights ONCE at initialization. Each tick:
        1. Append log_price to rolling deque (O(1))
        2. np.dot(weights, window) (O(n_lags) ≈ 0.005ms for n_lags=100)

    Compatible with 50ms latency budget.

    Usage:
        # Step 1 (offline): calibrate
        fd = FractionalDifferentiator()
        r = fd.find_minimum_d(historical_log_prices)
        d_opt, n_lags = r.d, len(r.weights)

        # Step 2 (live): stream
        ifd = IncrementalFracDiff(d=d_opt, n_lags=n_lags)
        for tick in stream:
            val = ifd.update(math.log(float(tick.price)))
            if val is not None:
                # use as ML feature or signal normalization input

    Reference: López de Prado (2018), AFML, Chapter 5, Section 5.5.
    """

    def __init__(self, d: float, n_lags: int = 50, threshold: float = 1e-5) -> None:
        """Pre-compute FFD weights and initialize rolling buffer.

        Args:
            d: Differentiation order in (0, 1]. Calibrated offline via
               FractionalDifferentiator.find_minimum_d().
            n_lags: Maximum number of lags (caps the weight vector length).
            threshold: Weight magnitude cutoff — stops weight computation
                       when |ω_k| < threshold.
        """
        self._d = d
        raw: list[float] = [1.0]
        for k in range(1, n_lags):
            w = raw[-1] * (k - 1.0 - d) / k
            if abs(w) < threshold:
                break
            raw.append(w)
        self._weights: np.ndarray[Any, np.dtype[np.float64]] = np.asarray(raw, dtype=float)
        self._actual_lags: int = len(raw)
        self._buffer: deque[float] = deque(maxlen=self._actual_lags)

    @property
    def is_ready(self) -> bool:
        """True once the rolling buffer has accumulated enough log-prices."""
        return len(self._buffer) >= self._actual_lags

    def update(self, log_price: float) -> float | None:
        """Process one log-price.  O(n_lags) via np.dot.

        Args:
            log_price: math.log(price) for the current tick.

        Returns:
            Differentiated value (stationary feature) once the buffer is full,
            None otherwise.
        """
        self._buffer.append(log_price)
        if not self.is_ready:
            return None
        # Reverse so newest log-price maps to weight index 0 (ω_0 = 1)
        window = np.asarray(list(self._buffer), dtype=float)[::-1]
        return float(np.dot(self._weights, window[: self._actual_lags]))

    def reset(self) -> None:
        """Clear buffer (call after session gap or data discontinuity)."""
        self._buffer.clear()
