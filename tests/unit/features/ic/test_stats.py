"""Tests for features.ic.stats — pure statistical functions.

Covers safe_spearman, newey_west_se, ic_t_statistic, ic_bootstrap_ci
with deterministic and Hypothesis property tests.

References:
    Newey, W. K. & West, K. D. (1987). *Econometrica*, 55(3).
    Politis, D. N. & Romano, J. P. (1994). *JASA*, 89(428).
"""

from __future__ import annotations

import os

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from features.ic.stats import (
    ic_bootstrap_ci,
    ic_t_statistic,
    newey_west_se,
    safe_spearman,
)

# ── safe_spearman ───────────────────────────────────────────────────


class TestSafeSpearman:
    """safe_spearman handles edge cases gracefully."""

    def test_constant_input_returns_zero(self) -> None:
        x = np.ones(20)
        y = np.arange(20, dtype=np.float64)
        ic, pv = safe_spearman(x, y)
        assert ic == 0.0
        assert pv == 1.0

    def test_fewer_than_10_samples(self) -> None:
        x = np.arange(5, dtype=np.float64)
        y = np.arange(5, dtype=np.float64)
        ic, pv = safe_spearman(x, y)
        assert ic == 0.0
        assert pv == 1.0

    def test_nan_removal(self) -> None:
        x = np.arange(30, dtype=np.float64)
        y = np.arange(30, dtype=np.float64)
        # Insert NaN — after removal we still have 28 valid pairs.
        x[5] = np.nan
        y[10] = np.nan
        ic, pv = safe_spearman(x, y)
        assert -1.0 <= ic <= 1.0
        # Monotonic relationship should give high |IC|.
        assert abs(ic) > 0.9

    def test_perfect_positive_correlation(self) -> None:
        x = np.arange(50, dtype=np.float64)
        y = np.arange(50, dtype=np.float64)
        ic, pv = safe_spearman(x, y)
        assert ic == pytest.approx(1.0, abs=1e-10)
        assert pv < 0.01

    def test_perfect_negative_correlation(self) -> None:
        x = np.arange(50, dtype=np.float64)
        y = -np.arange(50, dtype=np.float64)
        ic, pv = safe_spearman(x, y)
        assert ic == pytest.approx(-1.0, abs=1e-10)

    def test_mismatched_lengths(self) -> None:
        x = np.arange(20, dtype=np.float64)
        y = np.arange(25, dtype=np.float64)
        ic, pv = safe_spearman(x, y)
        assert ic == 0.0
        assert pv == 1.0

    @given(
        arrays(
            np.float64, shape=st.integers(10, 200), elements=st.floats(-1e6, 1e6, allow_nan=False)
        ),
        arrays(
            np.float64, shape=st.integers(10, 200), elements=st.floats(-1e6, 1e6, allow_nan=False)
        ),
    )
    @settings(max_examples=1000, deadline=None)
    def test_bounds_hypothesis(
        self,
        x: np.ndarray,  # type: ignore[type-arg]
        y: np.ndarray,  # type: ignore[type-arg]
    ) -> None:
        """IC is always in [-1, 1] for non-degenerate inputs."""
        # Ensure same length.
        n = min(len(x), len(y))
        if n < 10:
            return
        ic, pv = safe_spearman(x[:n], y[:n])
        assert -1.0 <= ic <= 1.0
        assert 0.0 <= pv <= 1.0


# ── newey_west_se ───────────────────────────────────────────────────


class TestNeweyWestSE:
    """Newey-West SE reduces to classical SE at lags=0."""

    def test_lags_zero_equals_classical_se(self) -> None:
        rng = np.random.default_rng(42)
        series = rng.normal(0, 1, size=200)
        nw_se = newey_west_se(series, lags=0)
        # Classical SE = sqrt(var/n) using biased variance (N denom).
        classical = float(np.std(series) / np.sqrt(len(series)))
        assert nw_se == pytest.approx(classical, rel=1e-10)

    def test_positive_autocorrelation_increases_se(self) -> None:
        """AR(1) with rho=0.5 should produce NW SE > classical SE."""
        rng = np.random.default_rng(123)
        n = 500
        eps = rng.normal(0, 1, size=n)
        ar1 = np.empty(n)
        ar1[0] = eps[0]
        for i in range(1, n):
            ar1[i] = 0.5 * ar1[i - 1] + eps[i]

        se_0 = newey_west_se(ar1, lags=0)
        se_5 = newey_west_se(ar1, lags=5)
        assert se_5 > se_0

    def test_single_observation(self) -> None:
        assert newey_west_se(np.array([1.0]), lags=3) == 0.0

    @given(
        arrays(
            np.float64, shape=st.integers(2, 100), elements=st.floats(-1e3, 1e3, allow_nan=False)
        ),
    )
    @settings(max_examples=1000, deadline=None)
    def test_lags_zero_matches_classical_hypothesis(
        self,
        series: np.ndarray,  # type: ignore[type-arg]
    ) -> None:
        """NW SE at lags=0 equals classical SE for arbitrary inputs."""
        nw_se = newey_west_se(series, lags=0)
        classical = float(np.std(series) / np.sqrt(len(series)))
        assert nw_se == pytest.approx(classical, abs=1e-8)


# ── ic_t_statistic ──────────────────────────────────────────────────


class TestICTStatistic:
    """t-stat uses Newey-West correction for overlapping returns."""

    def test_iid_approx_classical(self) -> None:
        """On iid data, HAC t-stat ~ classical t-stat."""
        rng = np.random.default_rng(99)
        series = rng.normal(0.05, 0.3, size=500)
        t_hac = ic_t_statistic(series, horizon_bars=1)
        mean = float(np.mean(series))
        se = float(np.std(series, ddof=1) / np.sqrt(len(series)))
        t_classical = mean / se if se > 0 else 0.0
        # Should be close (horizon=1 means lags=0).
        assert t_hac == pytest.approx(t_classical, rel=0.05)

    def test_single_element(self) -> None:
        assert ic_t_statistic(np.array([0.5]), horizon_bars=1) == 0.0


# ── ic_bootstrap_ci ─────────────────────────────────────────────────


class TestICBootstrapCI:
    """Stationary bootstrap CI contains the sample mean."""

    def test_ci_contains_mean(self) -> None:
        rng = np.random.default_rng(77)
        series = rng.normal(0.05, 0.2, size=200)
        ci_low, ci_high = ic_bootstrap_ci(series, n_boot=2000, seed=77)
        mean = float(np.mean(series))
        assert ci_low <= mean <= ci_high

    def test_fewer_than_two_returns_zeros(self) -> None:
        assert ic_bootstrap_ci(np.array([1.0])) == (0.0, 0.0)

    @given(
        arrays(
            np.float64, shape=st.integers(10, 100), elements=st.floats(-1.0, 1.0, allow_nan=False)
        ),
    )
    @settings(
        max_examples=100 if os.environ.get("CI") else 1000,
        deadline=None,
    )
    def test_ci_contains_mean_hypothesis(
        self,
        series: np.ndarray,  # type: ignore[type-arg]
    ) -> None:
        """Bootstrap CI always brackets the sample mean."""
        if series.size < 2:
            return
        if np.ptp(series) < 1e-12:
            return
        n_boot = 200 if os.environ.get("CI") else 500
        ci_low, ci_high = ic_bootstrap_ci(series, n_boot=n_boot, seed=42)
        mean = float(np.mean(series))
        assert ci_low <= mean + 1e-10
        assert ci_high >= mean - 1e-10

    def test_raises_on_invalid_n_boot(self) -> None:
        """n_boot=0 or negative -> ValueError."""
        series = np.array([0.1, 0.2, 0.3])
        with pytest.raises(ValueError, match="n_boot must be >= 1"):
            ic_bootstrap_ci(series, n_boot=0)
        with pytest.raises(ValueError, match="n_boot must be >= 1"):
            ic_bootstrap_ci(series, n_boot=-1)

    def test_raises_on_invalid_confidence(self) -> None:
        """confidence outside (0, 1) -> ValueError."""
        series = np.array([0.1, 0.2, 0.3])
        with pytest.raises(ValueError, match="confidence must be in"):
            ic_bootstrap_ci(series, confidence=0.0)
        with pytest.raises(ValueError, match="confidence must be in"):
            ic_bootstrap_ci(series, confidence=1.0)
        with pytest.raises(ValueError, match="confidence must be in"):
            ic_bootstrap_ci(series, confidence=-0.5)
