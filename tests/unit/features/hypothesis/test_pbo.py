"""Tests for PBOCalculator — Phase 3.11."""

from __future__ import annotations

import pytest

from features.hypothesis.pbo import PBOCalculator, PBOResult


class TestPBOCalculator:
    """Rank-based PBO from IS/OOS fold metrics."""

    @pytest.fixture
    def calculator(self) -> PBOCalculator:
        return PBOCalculator()

    def test_perfect_overfit_high_pbo(self, calculator: PBOCalculator) -> None:
        """IS-best always OOS-worst → PBO = 1.0."""
        # 5 features, 10 folds
        # Feature 0 is IS-best every fold but OOS-worst
        is_metrics: dict[str, list[float]] = {}
        oos_metrics: dict[str, list[float]] = {}
        for i in range(5):
            is_metrics[f"f{i}"] = [float(4 - i)] * 10  # f0 is IS-best
            oos_metrics[f"f{i}"] = [float(i)] * 10  # f0 is OOS-worst

        result = calculator.compute(is_metrics, oos_metrics)
        assert result.pbo == 1.0
        assert result.is_overfit

    def test_no_overfit_low_pbo(self, calculator: PBOCalculator) -> None:
        """IS-best always OOS-best → PBO = 0.0."""
        is_metrics: dict[str, list[float]] = {}
        oos_metrics: dict[str, list[float]] = {}
        for i in range(5):
            is_metrics[f"f{i}"] = [float(4 - i)] * 10
            oos_metrics[f"f{i}"] = [float(4 - i)] * 10  # same ranking

        result = calculator.compute(is_metrics, oos_metrics)
        assert result.pbo == 0.0
        assert not result.is_overfit
        assert result.passes_adr0004

    def test_random_pbo_near_half(self, calculator: PBOCalculator) -> None:
        """Random IS/OOS → PBO ≈ 0.5 (no systematic pattern)."""
        import numpy as np

        rng = np.random.default_rng(42)
        n_features = 10
        n_folds = 50

        is_metrics = {f"f{i}": rng.standard_normal(n_folds).tolist() for i in range(n_features)}
        oos_metrics = {f"f{i}": rng.standard_normal(n_folds).tolist() for i in range(n_features)}

        result = calculator.compute(is_metrics, oos_metrics)
        # With independent random data, PBO should be around 0.5
        assert 0.2 < result.pbo < 0.8

    def test_result_is_frozen(self, calculator: PBOCalculator) -> None:
        is_m = {"a": [1.0, 2.0], "b": [0.5, 1.0]}
        oos_m = {"a": [1.5, 1.8], "b": [0.3, 0.8]}
        result = calculator.compute(is_m, oos_m)
        with pytest.raises(AttributeError):
            result.pbo = 0.5  # type: ignore[misc]

    def test_result_fields(self, calculator: PBOCalculator) -> None:
        is_m = {"a": [1.0, 2.0, 3.0], "b": [0.5, 1.0, 1.5]}
        oos_m = {"a": [1.5, 1.8, 2.5], "b": [0.3, 0.8, 1.0]}
        result = calculator.compute(is_m, oos_m)
        assert isinstance(result, PBOResult)
        assert result.n_folds == 3
        assert result.n_features == 2
        assert len(result.rank_logits) == 3
        assert 0.0 <= result.pbo <= 1.0

    def test_fewer_than_2_features_raises(self, calculator: PBOCalculator) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            calculator.compute({"a": [1.0]}, {"a": [1.0]})

    def test_mismatched_keys_raises(self, calculator: PBOCalculator) -> None:
        with pytest.raises(ValueError, match="same feature keys"):
            calculator.compute({"a": [1.0], "b": [2.0]}, {"a": [1.0], "c": [2.0]})

    def test_mismatched_fold_lengths_raises(self, calculator: PBOCalculator) -> None:
        with pytest.raises(ValueError, match="folds"):
            calculator.compute({"a": [1.0, 2.0], "b": [1.0]}, {"a": [1.0, 2.0], "b": [1.0, 2.0]})

    def test_no_folds_raises(self, calculator: PBOCalculator) -> None:
        with pytest.raises(ValueError, match="No folds"):
            calculator.compute({"a": [], "b": []}, {"a": [], "b": []})
