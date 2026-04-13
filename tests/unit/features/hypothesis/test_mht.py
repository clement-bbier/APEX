"""Tests for Holm-Bonferroni and Benjamini-Hochberg MHT corrections."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from features.hypothesis.mht import benjamini_hochberg, holm_bonferroni


class TestHolmBonferroni:
    """Holm-Bonferroni step-down FWER control (Holm 1979)."""

    def test_all_null_true_few_rejections(self) -> None:
        """Uniform random p-values (all H0 true) → ~0 rejected."""
        rng = np.random.default_rng(42)
        p = rng.uniform(0, 1, size=100).astype(np.float64)
        rejected, _ = holm_bonferroni(p, alpha=0.05)
        # Under H0, expect ≤ 5% FWER (at most ~5 rejections on average)
        assert np.sum(rejected) <= 10  # generous bound

    def test_all_null_false_all_rejected(self) -> None:
        """All p ≈ 0 (all H0 false) → all rejected."""
        p = np.array([1e-10, 1e-8, 1e-6, 1e-4], dtype=np.float64)
        rejected, _ = holm_bonferroni(p, alpha=0.05)
        assert np.all(rejected)

    def test_chain_rejection_stops_correctly(self) -> None:
        """Step-down stops at first non-rejected."""
        p = np.array([0.001, 0.01, 0.06, 0.9], dtype=np.float64)
        rejected, _adjusted = holm_bonferroni(p, alpha=0.05)
        assert rejected[0]  # 0.001 * 4 = 0.004 < 0.05
        assert rejected[1]  # 0.01 * 3 = 0.03 < 0.05
        assert not rejected[2]  # 0.06 * 2 = 0.12 > 0.05
        assert not rejected[3]  # stopped

    def test_adjusted_geq_raw(self) -> None:
        """Adjusted p-values always >= raw p-values."""
        p = np.array([0.01, 0.03, 0.04, 0.10], dtype=np.float64)
        _, adjusted = holm_bonferroni(p)
        assert np.all(adjusted >= p - 1e-15)

    def test_single_hypothesis_unchanged(self) -> None:
        """Single hypothesis: adjusted == raw."""
        p = np.array([0.03], dtype=np.float64)
        rejected, adjusted = holm_bonferroni(p, alpha=0.05)
        assert abs(adjusted[0] - 0.03) < 1e-15
        assert rejected[0]

    def test_equivalent_to_bonferroni_when_smallest_rejected(self) -> None:
        """When only the smallest is rejected, its adjustment matches Bonferroni."""
        p = np.array([0.01, 0.5, 0.8], dtype=np.float64)
        _, adjusted = holm_bonferroni(p)
        # Smallest: p * n = 0.01 * 3 = 0.03
        assert abs(adjusted[0] - 0.03) < 1e-10

    def test_adjusted_clamped_to_one(self) -> None:
        """Adjusted p-values never exceed 1.0."""
        p = np.array([0.9, 0.95], dtype=np.float64)
        _, adjusted = holm_bonferroni(p)
        assert np.all(adjusted <= 1.0)

    def test_validation_alpha_out_of_range(self) -> None:
        p = np.array([0.05], dtype=np.float64)
        with pytest.raises(ValueError, match="alpha must be in"):
            holm_bonferroni(p, alpha=0.0)
        with pytest.raises(ValueError, match="alpha must be in"):
            holm_bonferroni(p, alpha=1.0)

    def test_validation_p_values_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="p_values must be in"):
            holm_bonferroni(np.array([-0.1], dtype=np.float64))
        with pytest.raises(ValueError, match="p_values must be in"):
            holm_bonferroni(np.array([1.1], dtype=np.float64))

    def test_validation_nan_p_values(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            holm_bonferroni(np.array([0.05, float("nan")], dtype=np.float64))

    def test_validation_empty_array(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            holm_bonferroni(np.array([], dtype=np.float64))


class TestBenjaminiHochberg:
    """Benjamini-Hochberg FDR control (Benjamini & Hochberg 1995)."""

    def test_more_permissive_than_holm(self) -> None:
        """BH rejects at least as many as Holm (less conservative)."""
        rng = np.random.default_rng(99)
        # Mix: 5 true signals + 95 null
        p_true = rng.uniform(0, 0.005, size=5).astype(np.float64)
        p_null = rng.uniform(0, 1, size=95).astype(np.float64)
        p = np.concatenate([p_true, p_null])
        rej_holm, _ = holm_bonferroni(p, alpha=0.05)
        rej_bh, _ = benjamini_hochberg(p, alpha=0.05)
        assert np.sum(rej_bh) >= np.sum(rej_holm)

    def test_adjusted_monotone_nondecreasing_sorted(self) -> None:
        """After sorting, adjusted p-values are non-decreasing."""
        p = np.array([0.001, 0.01, 0.02, 0.5, 0.9], dtype=np.float64)
        _, adjusted = benjamini_hochberg(p)
        sorted_adj = adjusted[np.argsort(p)]
        assert np.all(sorted_adj[1:] >= sorted_adj[:-1] - 1e-15)

    def test_single_hypothesis_unchanged(self) -> None:
        """Single hypothesis: adjusted == raw."""
        p = np.array([0.03], dtype=np.float64)
        _, adjusted = benjamini_hochberg(p, alpha=0.05)
        assert abs(adjusted[0] - 0.03) < 1e-15

    def test_all_false_all_rejected(self) -> None:
        p = np.array([1e-10, 1e-8, 1e-6], dtype=np.float64)
        rejected, _ = benjamini_hochberg(p, alpha=0.05)
        assert np.all(rejected)

    def test_fdr_controlled_empirically(self) -> None:
        """Empirical FDR ≤ α over many trials (approximate)."""
        rng = np.random.default_rng(123)
        false_discoveries = 0
        total_discoveries = 0
        n_trials = 200
        alpha = 0.05
        for _ in range(n_trials):
            # 90 null + 10 real signals
            p_null = rng.uniform(0, 1, size=90).astype(np.float64)
            p_real = rng.uniform(0, 0.001, size=10).astype(np.float64)
            p = np.concatenate([p_null, p_real])
            rejected, _ = benjamini_hochberg(p, alpha=alpha)
            n_rej = int(np.sum(rejected))
            total_discoveries += n_rej
            # False discoveries = rejections among the first 90 (null)
            false_discoveries += int(np.sum(rejected[:90]))
        if total_discoveries > 0:
            fdr = false_discoveries / total_discoveries
            # FDR should be close to α or below (with some slack for randomness)
            assert fdr < alpha + 0.05  # generous bound

    def test_adjusted_clamped_to_one(self) -> None:
        p = np.array([0.9, 0.95], dtype=np.float64)
        _, adjusted = benjamini_hochberg(p)
        assert np.all(adjusted <= 1.0)

    def test_validation_alpha_out_of_range(self) -> None:
        p = np.array([0.05], dtype=np.float64)
        with pytest.raises(ValueError, match="alpha must be in"):
            benjamini_hochberg(p, alpha=0.0)

    @given(
        n=st.integers(1, 50),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_adjusted_always_geq_raw(self, n: int) -> None:
        """Property: adjusted p >= raw p for all entries."""
        rng = np.random.default_rng(n)
        p = rng.uniform(0, 1, size=n).astype(np.float64)
        _, adj = benjamini_hochberg(p)
        assert np.all(adj >= p - 1e-15)
