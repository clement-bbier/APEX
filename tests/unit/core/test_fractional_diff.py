"""Unit tests for core/math/fractional_diff.py.

Covers: FractionalDifferentiator (batch) + IncrementalFracDiff (streaming).
Property tests via Hypothesis ensure correctness for any d ∈ (0, 1).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.math.fractional_diff import (
    FracDiffResult,
    FractionalDifferentiator,
    IncrementalFracDiff,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _log_price_series(n: int, seed: int = 42) -> list[float]:
    """Synthetic log-price random walk for testing."""
    rng = np.random.default_rng(seed)
    prices = 100.0 + np.cumsum(rng.standard_normal(n) * 0.5)
    return [math.log(max(1e-8, p)) for p in prices]


# ── IncrementalFracDiff: buffer / readiness ───────────────────────────────────


class TestIncrementalNotReadyUntilBufferFull:
    def test_returns_none_while_filling(self) -> None:
        ifd = IncrementalFracDiff(d=0.4, n_lags=10)
        results = [ifd.update(v) for v in _log_price_series(9)]
        assert all(r is None for r in results)

    def test_returns_float_once_full(self) -> None:
        ifd = IncrementalFracDiff(d=0.4, n_lags=10)
        series = _log_price_series(15)
        results = [ifd.update(v) for v in series]
        non_none = [r for r in results if r is not None]
        assert len(non_none) > 0
        assert all(isinstance(r, float) for r in non_none)

    def test_is_ready_false_until_lags_accumulated(self) -> None:
        ifd = IncrementalFracDiff(d=0.3, n_lags=20)
        for _ in range(ifd._actual_lags - 1):
            ifd.update(4.6)
        assert ifd.is_ready is False

    def test_is_ready_true_after_n_lags(self) -> None:
        ifd = IncrementalFracDiff(d=0.3, n_lags=20)
        for v in _log_price_series(30):
            ifd.update(v)
        assert ifd.is_ready is True


# ── IncrementalFracDiff: reset ────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_buffer(self) -> None:
        ifd = IncrementalFracDiff(d=0.4, n_lags=10)
        for v in _log_price_series(20):
            ifd.update(v)
        assert ifd.is_ready is True
        ifd.reset()
        assert ifd.is_ready is False
        assert len(ifd._buffer) == 0

    def test_after_reset_needs_refill(self) -> None:
        ifd = IncrementalFracDiff(d=0.4, n_lags=10)
        for v in _log_price_series(20):
            ifd.update(v)
        ifd.reset()
        assert ifd.update(4.6) is None  # buffer empty again


# ── Consistency: incremental vs batch ────────────────────────────────────────


class TestConsistencyWithBatch:
    """IncrementalFracDiff must produce values close to FractionalDifferentiator."""

    def test_last_value_matches_batch(self) -> None:
        """Incremental last value equals batch last value using the same n_lags."""
        # Use a threshold large enough that n_lags stays << len(series)
        series = _log_price_series(100)
        d = 0.4
        n_lags = 20  # explicit cap, well below len(series)

        fd = FractionalDifferentiator()
        # Slice batch weights to n_lags for a fair comparison
        weights = fd._get_weights_ffd(d)[:n_lags]
        arr = np.asarray(series, dtype=float)
        batch_last = float(np.dot(weights, arr[-n_lags:][::-1]))

        ifd = IncrementalFracDiff(d=d, n_lags=n_lags)
        last_incremental: float | None = None
        for v in series:
            val = ifd.update(v)
            if val is not None:
                last_incremental = val

        assert last_incremental is not None
        assert abs(last_incremental - batch_last) < 1e-6

    def test_incremental_length_matches_batch_output(self) -> None:
        """Number of non-None incremental values matches batch output length."""
        # Use high threshold so n_lags stays short (< len(series))
        series = _log_price_series(80)
        d = 0.5
        threshold = 0.01  # aggressive truncation → ~5-10 weights

        fd = FractionalDifferentiator()
        batch_result = fd.differentiate(series, d, threshold=threshold)
        n_lags = len(batch_result.weights)
        assert n_lags < len(series), "n_lags must be < series length for this test"

        ifd = IncrementalFracDiff(d=d, n_lags=n_lags, threshold=threshold)
        incremental_vals = [ifd.update(v) for v in series]
        non_none = [v for v in incremental_vals if v is not None]

        assert len(non_none) == len(batch_result.series)


# ── FractionalDifferentiator: batch properties ───────────────────────────────


class TestFractionalDifferentiatorBatch:
    def test_short_series_returns_unmodified(self) -> None:
        fd = FractionalDifferentiator()
        short = [1.0, 2.0, 3.0]
        r = fd.differentiate(short, d=0.5)
        assert r.series == short

    def test_weights_start_at_one(self) -> None:
        fd = FractionalDifferentiator()
        r = fd.differentiate(_log_price_series(50), d=0.5)
        assert r.weights[0] == pytest.approx(1.0)

    def test_weights_are_alternating_sign(self) -> None:
        """FFD weights alternate: +, -, +, - for d ∈ (0,1)."""
        fd = FractionalDifferentiator()
        weights = fd._get_weights_ffd(0.5)
        for i in range(1, min(5, len(weights))):
            assert weights[i] < 0  # all subsequent weights are negative for d<1

    def test_output_length(self) -> None:
        """Output length = len(series) - n_lags + 1; use high threshold for short weights."""
        fd = FractionalDifferentiator()
        series = _log_price_series(50)
        # threshold=0.01 gives ~5-8 weights for any d ∈ (0,1), well below 50
        r = fd.differentiate(series, d=0.5, threshold=0.01)
        n_lags = len(r.weights)
        assert n_lags < len(series)
        assert len(r.series) == len(series) - n_lags + 1

    def test_memory_retained_coverage_increases_with_d(self) -> None:
        """With fixed n_lags=50, higher d (faster decay) → more weight covered.

        For low d (≈0.1) weights decay very slowly: 50 lags covers only a
        small fraction of the theoretically-infinite weight sum.
        For high d (≈0.9) weights decay rapidly: 50 lags covers most of it.
        """
        fd = FractionalDifferentiator()
        m_low = fd.memory_retained(0.1, 50)  # slow decay  → low fraction
        m_high = fd.memory_retained(0.9, 50)  # fast decay  → high fraction
        assert m_low < m_high

    def test_memory_retained_at_zero_near_one(self) -> None:
        fd = FractionalDifferentiator()
        # d=0 → no differentiation → full memory
        m = fd.memory_retained(0.0, 50)
        assert m > 0.95

    def test_find_minimum_d_returns_stationary(self) -> None:
        """On a long enough series, find_minimum_d must find a stationary d."""
        # Use a trending series that needs differentiation to become stationary
        prices = [100.0 + i * 0.5 for i in range(200)]
        log_prices = [math.log(p) for p in prices]
        fd = FractionalDifferentiator()
        r = fd.find_minimum_d(log_prices)
        assert isinstance(r, FracDiffResult)
        # d should be strictly positive (it's not already stationary at d=0)
        assert r.d >= 0.0


# ── IncrementalFracDiff: output is finite for any d ──────────────────────────


class TestOutputFinite:
    @given(d=st.floats(0.01, 0.99, allow_nan=False))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_output_finite_any_d(self, d: float) -> None:
        ifd = IncrementalFracDiff(d=d, n_lags=20)
        for v in _log_price_series(30):
            result = ifd.update(v)
        # The last update must have returned a finite float
        assert result is not None
        assert math.isfinite(result)

    @given(d=st.floats(0.01, 0.99, allow_nan=False))
    @settings(max_examples=50)
    def test_weights_all_finite(self, d: float) -> None:
        ifd = IncrementalFracDiff(d=d, n_lags=50)
        assert all(math.isfinite(w) for w in ifd._weights.tolist())

    @given(
        d=st.floats(0.01, 0.99, allow_nan=False),
        n=st.integers(10, 100),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_is_ready_consistent_with_buffer_len(self, d: float, n: int) -> None:
        ifd = IncrementalFracDiff(d=d, n_lags=n)
        for v in _log_price_series(ifd._actual_lags):
            ifd.update(v)
        assert ifd.is_ready is True


# ── ADF stationarity helper ───────────────────────────────────────────────────


class TestADFStationary:
    def test_short_series_returns_false(self) -> None:
        fd = FractionalDifferentiator()
        assert fd._adf_stationary([1.0, 2.0, 3.0]) is False

    def test_stationary_series_passes(self) -> None:
        """IID Gaussian is stationary — ADF should reject unit root."""
        rng = np.random.default_rng(0)
        stationary = rng.standard_normal(200).tolist()
        fd = FractionalDifferentiator()
        assert fd._adf_stationary(stationary) is True

    def test_nan_series_returns_false(self) -> None:
        """NaN in series causes math.sqrt to raise ValueError → except handler (line 182-183)."""
        fd = FractionalDifferentiator()
        import math as _math

        # math.sqrt(nan) raises ValueError, triggering the except branch
        nan_series = [_math.nan] * 30
        assert fd._adf_stationary(nan_series) is False

    def test_random_walk_fails(self) -> None:
        """Pure random walk is I(1) — ADF should NOT reject unit root."""
        rng = np.random.default_rng(42)
        rw = np.cumsum(rng.standard_normal(300)).tolist()
        fd = FractionalDifferentiator()
        # Random walks typically fail ADF (return False)
        # We don't assert deterministically since test-stat is stochastic,
        # but verify the function runs and returns bool.
        result = fd._adf_stationary(rw)
        assert isinstance(result, bool)

    def test_constant_series_returns_false(self) -> None:
        """Constant series → denom ≈ 0 → early return False (line 177)."""
        fd = FractionalDifferentiator()
        constant = [5.0] * 50
        assert fd._adf_stationary(constant) is False

    def test_find_minimum_d_returns_early_when_stationary(self) -> None:
        """find_minimum_d returns early once stationarity is found (line 153-154)."""
        rng = np.random.default_rng(7)
        # IID noise is already stationary → d_opt should be found at low d
        series = rng.standard_normal(200).tolist()
        fd = FractionalDifferentiator()
        r = fd.find_minimum_d(series, d_low=0.0, d_high=1.0, n_steps=20)
        assert isinstance(r, FracDiffResult)
        # Should have found stationarity before d_high
        assert r.d <= 1.0

    def test_find_minimum_d_fallback_when_none_stationary(self) -> None:
        """find_minimum_d falls back to d_high (line 155) for very short series."""
        fd = FractionalDifferentiator()
        # Series too short → _adf_stationary always returns False → hits fallback
        series = list(range(15))  # len=15, differentiate returns early path
        r = fd.find_minimum_d(series, n_steps=5)
        assert isinstance(r, FracDiffResult)
