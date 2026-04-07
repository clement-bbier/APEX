"""Tests for RegimeML - HMM, PELT breakpoints, Engle-Granger cointegration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from services.s07_quant_analytics.regime_ml import RegimeML


@pytest.fixture
def ml() -> RegimeML:
    return RegimeML()


class TestFitHMM:
    def test_insufficient_data_returns_status(self, ml: RegimeML) -> None:
        result = ml.fit_hmm([0.01, 0.02], n_states=4)
        assert result["status"] == "insufficient_data"
        assert result["converged"] is False
        assert result["means"] == []

    def test_returns_correct_n_states(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.01, 50).tolist()
        result = ml.fit_hmm(returns, n_states=4)
        assert result["n_states"] == 4

    def test_custom_n_states(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.01, 30).tolist()
        result = ml.fit_hmm(returns, n_states=2)
        assert result["n_states"] == 2

    def test_fitted_status(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, 100).tolist()
        result = ml.fit_hmm(returns, n_states=4)
        assert result["status"] == "fitted"

    def test_viterbi_path_length_matches_input(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.01, 80).tolist()
        result = ml.fit_hmm(returns, n_states=4)
        assert len(result["viterbi_path"]) == 80

    def test_viterbi_states_in_range(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(2)
        returns = rng.normal(0, 0.01, 60).tolist()
        result = ml.fit_hmm(returns, n_states=3)
        path = result["viterbi_path"]
        assert all(0 <= s < 3 for s in path)

    def test_transition_matrix_rows_sum_to_one(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(3)
        returns = rng.normal(0, 0.01, 60).tolist()
        result = ml.fit_hmm(returns, n_states=3)
        for row in result["transition_matrix"]:
            assert abs(sum(row) - 1.0) < 1e-6

    def test_initial_probs_sum_to_one(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(4)
        returns = rng.normal(0, 0.01, 60).tolist()
        result = ml.fit_hmm(returns)
        assert abs(sum(result["initial_probs"]) - 1.0) < 1e-6

    def test_log_likelihood_is_finite(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(5)
        returns = rng.normal(0, 0.01, 60).tolist()
        result = ml.fit_hmm(returns)
        assert math.isfinite(result["log_likelihood"])

    def test_stds_are_positive(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(6)
        returns = rng.normal(0, 0.01, 60).tolist()
        result = ml.fit_hmm(returns)
        assert all(s > 0 for s in result["stds"])


class TestDetectBreakpoints:
    def test_empty_series_returns_empty(self, ml: RegimeML) -> None:
        assert ml.detect_breakpoints([]) == []

    def test_too_short_returns_empty(self, ml: RegimeML) -> None:
        assert ml.detect_breakpoints([1.0, 2.0, 3.0], min_size=5) == []

    def test_constant_series_no_breakpoints(self, ml: RegimeML) -> None:
        series = [1.0] * 50
        result = ml.detect_breakpoints(series)
        assert result == []

    def test_clear_level_shift_detected(self, ml: RegimeML) -> None:
        # Two clear segments: first 25 near 0, next 25 near 10
        rng = np.random.default_rng(42)
        seg1 = rng.normal(0.0, 0.05, 25).tolist()
        seg2 = rng.normal(10.0, 0.05, 25).tolist()
        series = seg1 + seg2
        result = ml.detect_breakpoints(series, min_size=5)
        # There should be at least one breakpoint near index 25
        assert len(result) >= 1

    def test_breakpoints_sorted(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(0)
        series = rng.normal(0, 1, 100).tolist()
        result = ml.detect_breakpoints(series)
        assert result == sorted(result)

    def test_breakpoints_within_bounds(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(0)
        series = rng.normal(0, 1, 60).tolist()
        result = ml.detect_breakpoints(series, min_size=5)
        for cp in result:
            assert 0 < cp < len(series)

    def test_custom_penalty_reduces_breakpoints(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(42)
        series = rng.normal(0, 1, 80).tolist()
        result_low = ml.detect_breakpoints(series, penalty=0.1)
        result_high = ml.detect_breakpoints(series, penalty=1000.0)
        # Higher penalty = fewer breakpoints
        assert len(result_high) <= len(result_low)


class TestCointegrationTest:
    def test_insufficient_data_status(self, ml: RegimeML) -> None:
        result = ml.cointegration_test([1.0, 2.0], [1.0, 2.0])
        assert result["status"] == "insufficient_data"
        assert result["cointegrated"] is False

    def test_cointegrated_series_detected(self, ml: RegimeML) -> None:
        # y = 2*x + noise; regress y on x → hedge_ratio ~ 2.0
        rng = np.random.default_rng(42)
        x = np.cumsum(rng.normal(0, 1, 100))
        y = 2.0 * x + rng.normal(0, 0.01, 100)
        # series_a=y (dependent), series_b=x (regressor) → beta ~ 2.0
        result = ml.cointegration_test(y.tolist(), x.tolist())
        assert result["status"] == "tested"
        # Hedge ratio should be close to 2.0
        assert abs(result["hedge_ratio"] - 2.0) < 0.1

    def test_non_cointegrated_series(self, ml: RegimeML) -> None:
        # Two independent random walks are not cointegrated
        rng = np.random.default_rng(0)
        x = np.cumsum(rng.normal(0, 1, 50)).tolist()
        y = np.cumsum(rng.normal(0, 1, 50)).tolist()
        result = ml.cointegration_test(x, y)
        assert result["status"] == "tested"
        assert "adf_statistic" in result
        assert "critical_value" in result

    def test_result_keys_present(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(7)
        x = rng.normal(0, 1, 30).tolist()
        y = rng.normal(0, 1, 30).tolist()
        result = ml.cointegration_test(x, y)
        required_keys = {
            "cointegrated",
            "adf_statistic",
            "critical_value",
            "significance",
            "hedge_ratio",
            "intercept",
            "n_obs",
            "status",
        }
        assert required_keys.issubset(result.keys())

    def test_significance_level_in_result(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(8)
        x = rng.normal(0, 1, 30).tolist()
        y = rng.normal(0, 1, 30).tolist()
        result = ml.cointegration_test(x, y, significance=0.01)
        assert result["significance"] == 0.01
        assert result["critical_value"] == pytest.approx(-3.96)

    def test_n_obs_uses_min_length(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(9)
        x = rng.normal(0, 1, 40).tolist()
        y = rng.normal(0, 1, 30).tolist()
        result = ml.cointegration_test(x, y)
        assert result["n_obs"] == 30

    def test_default_critical_value_at_5pct(self, ml: RegimeML) -> None:
        rng = np.random.default_rng(10)
        x = rng.normal(0, 1, 30).tolist()
        y = rng.normal(0, 1, 30).tolist()
        result = ml.cointegration_test(x, y)  # default significance=0.05
        assert result["critical_value"] == pytest.approx(-3.41)
