"""Tests for DeflatedSharpeCalculator — Phase 3.11."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from features.hypothesis.dsr import DeflatedSharpeCalculator, DSRResult


class TestDeflatedSharpeCalculator:
    """DeflatedSharpeCalculator wraps backtesting.metrics DSR/PSR."""

    @pytest.fixture
    def calculator(self) -> DeflatedSharpeCalculator:
        return DeflatedSharpeCalculator()

    @pytest.fixture
    def strong_returns(self) -> pl.Series:
        """Strong positive returns → high Sharpe."""
        rng = np.random.default_rng(42)
        return pl.Series("r", (rng.standard_normal(300) * 0.01 + 0.005).tolist())

    @pytest.fixture
    def weak_returns(self) -> pl.Series:
        """Random walk → Sharpe ≈ 0."""
        rng = np.random.default_rng(99)
        return pl.Series("r", (rng.standard_normal(300) * 0.01).tolist())

    def test_strong_strategy_high_dsr(
        self, calculator: DeflatedSharpeCalculator, strong_returns: pl.Series
    ) -> None:
        results = calculator.compute_from_returns({"alpha": strong_returns})
        assert len(results) == 1
        assert results[0].dsr > 0.80

    def test_weak_strategy_low_dsr(
        self, calculator: DeflatedSharpeCalculator, weak_returns: pl.Series
    ) -> None:
        results = calculator.compute_from_returns({"noise": weak_returns})
        assert len(results) == 1
        assert results[0].dsr < 0.80

    def test_dsr_leq_psr(
        self, calculator: DeflatedSharpeCalculator, strong_returns: pl.Series
    ) -> None:
        """DSR must always be ≤ PSR (selection bias can only reduce)."""
        # With 3 features, n_trials=3 → DSR deflated
        data = {
            "a": strong_returns,
            "b": strong_returns,
            "c": strong_returns,
        }
        results = calculator.compute_from_returns(data)
        for r in results:
            assert r.dsr <= r.psr + 1e-10

    def test_more_trials_lower_dsr(self, calculator: DeflatedSharpeCalculator) -> None:
        """More trials deflates DSR further."""
        rng = np.random.default_rng(1)
        ret = pl.Series("r", (rng.standard_normal(200) * 0.005 + 0.004).tolist())

        # 1 trial
        r1 = calculator.compute_from_returns({"only": ret})
        # 5 trials (same returns repeated)
        data5 = {f"s{i}": ret for i in range(5)}
        r5 = calculator.compute_from_returns(data5)

        # Find the same underlying returns in r5
        dsr_1 = r1[0].dsr
        dsr_5 = r5[0].dsr  # any, they're all the same returns
        assert dsr_1 > dsr_5

    def test_result_is_frozen(
        self, calculator: DeflatedSharpeCalculator, strong_returns: pl.Series
    ) -> None:
        results = calculator.compute_from_returns({"a": strong_returns})
        with pytest.raises(AttributeError):
            results[0].dsr = 0.5  # type: ignore[misc]

    def test_result_fields_populated(
        self, calculator: DeflatedSharpeCalculator, strong_returns: pl.Series
    ) -> None:
        results = calculator.compute_from_returns({"a": strong_returns})
        r = results[0]
        assert isinstance(r, DSRResult)
        assert r.feature_name == "a"
        assert r.n_obs == 300
        assert r.n_trials == 1
        assert isinstance(r.skewness, float)
        assert isinstance(r.kurtosis, float)
        assert isinstance(r.min_trl, int)
        assert r.min_trl >= 1

    def test_sorted_by_dsr_descending(self, calculator: DeflatedSharpeCalculator) -> None:
        rng = np.random.default_rng(7)
        data = {
            "strong": pl.Series("r", (rng.standard_normal(200) * 0.01 + 0.008).tolist()),
            "medium": pl.Series("r", (rng.standard_normal(200) * 0.01 + 0.003).tolist()),
            "weak": pl.Series("r", (rng.standard_normal(200) * 0.01).tolist()),
        }
        results = calculator.compute_from_returns(data)
        dsrs = [r.dsr for r in results]
        assert dsrs == sorted(dsrs, reverse=True)

    def test_empty_input(self, calculator: DeflatedSharpeCalculator) -> None:
        assert calculator.compute({}, {}) == []

    def test_missing_returns_data_raises(self, calculator: DeflatedSharpeCalculator) -> None:
        with pytest.raises(ValueError, match="Missing returns_data"):
            calculator.compute({"a": 1.5}, {})

    def test_significance_threshold_validation(self) -> None:
        with pytest.raises(ValueError, match="significance_threshold"):
            DeflatedSharpeCalculator(significance_threshold=0.0)
        with pytest.raises(ValueError, match="significance_threshold"):
            DeflatedSharpeCalculator(significance_threshold=1.0)

    def test_sharpe_in_dsr_result_consistent_with_psr_input(self) -> None:
        """Sharpe stored in DSRResult must use rf=0 to match PSR/DSR convention.

        Bug regression: previously sharpe_ratio() was called with default
        rf=0.05, making DSRResult.sharpe_ratio inconsistent with the SR
        used internally by PSR/DSR (which assume excess returns input).
        """
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(252) * 0.01

        calc = DeflatedSharpeCalculator()
        results = calc.compute_from_returns({"flat": pl.Series("r", returns.tolist())})
        result = results[0]

        # Manual Sharpe with rf=0 should match
        expected_sharpe = float(np.mean(returns) / np.std(returns, ddof=1))
        # Allow for annualisation factor difference — compare per-period SR
        # sharpe_ratio() with rf=0 returns annualised SR = per_period * sqrt(252)
        expected_annualised = expected_sharpe * np.sqrt(252)
        assert abs(result.sharpe_ratio - expected_annualised) < 0.01

    def test_negative_sharpe_returns_sentinel_min_trl(self) -> None:
        """Losing strategy must propagate Min-TRL sentinel, not arbitrary large value.

        Bug regression: previously target_sharpe was clamped to max(sr, 1e-10),
        bypassing the function's "non-viable" sentinel.
        """
        rng = np.random.default_rng(42)
        losing_returns = rng.standard_normal(252) * 0.01 - 0.005

        calc = DeflatedSharpeCalculator()
        results = calc.compute_from_returns({"loser": pl.Series("r", losing_returns.tolist())})
        result = results[0]

        assert result.sharpe_ratio < 0, "Setup check: strategy should have negative Sharpe"
        assert result.min_trl >= 1_000_000_000, (
            f"Losing strategy should get sentinel Min-TRL (1e9), got {result.min_trl}"
        )
