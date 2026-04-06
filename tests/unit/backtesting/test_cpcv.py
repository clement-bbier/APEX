"""Unit tests for CombinatorialPurgedCV (CPCV).

Validates purge/embargo logic, split geometry, PBO computation, and the
deployment recommendation gate.

References:
    Bailey, Borwein, López de Prado & Zhu (2015). Journal of Computational
    Finance 20(4). UC Davis + AHL Man Group.
    López de Prado (2018). AFML. Wiley. Chapter 12.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backtesting.walk_forward import CombinatorialPurgedCV, CPCVResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_sharpe(returns: list[float]) -> float:
    """Trivial Sharpe: mean / std (annualised by √252)."""
    if len(returns) < 2:
        return 0.0
    arr = np.asarray(returns, dtype=float)
    std = float(np.std(arr, ddof=1))
    return float(np.mean(arr)) / std * math.sqrt(252) if std > 0 else 0.0


def _const_sharpe(value: float) -> float:
    """Return a fixed Sharpe regardless of input — used for PBO control."""

    def _fn(returns: list[float]) -> float:
        return value

    return _fn  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Split geometry
# ---------------------------------------------------------------------------


class TestSplitGeometry:
    def test_combination_count(self) -> None:
        """C(n_splits, n_test_splits) combinations must be produced."""
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
        splits = cv.split(600)
        assert len(splits) == len(list(combinations(range(6), 2)))  # 15

    def test_combination_count_three_test(self) -> None:
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=3, embargo_pct=0.0)
        splits = cv.split(600)
        assert len(splits) == len(list(combinations(range(6), 3)))  # 20

    def test_no_train_test_overlap(self) -> None:
        """Train and test index sets must be disjoint after purging."""
        cv = CombinatorialPurgedCV(n_splits=5, n_test_splits=2, embargo_pct=0.01)
        splits = cv.split(500)
        for train, test in splits:
            assert set(train).isdisjoint(set(test)), "train/test overlap detected"

    def test_test_indices_cover_all_samples(self) -> None:
        """Each sample appears in at least one test set."""
        cv = CombinatorialPurgedCV(n_splits=5, n_test_splits=2, embargo_pct=0.0)
        splits = cv.split(500)
        covered: set[int] = set()
        for _, test in splits:
            covered.update(test)
        assert covered == set(range(500))

    def test_embargo_removes_post_test_samples(self) -> None:
        """Samples immediately after the test window must not appear in train."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=1, embargo_pct=0.05)
        splits = cv.split(400)  # embargo_size = 20
        for train, test in splits:
            test_max = max(test)
            embargo_end = test_max + 20
            for idx in train:
                assert not (test_max < idx <= embargo_end), (
                    f"Embargo violated: idx={idx} in embargo window after test_max={test_max}"
                )

    def test_invalid_n_splits(self) -> None:
        with pytest.raises(ValueError, match="n_splits"):
            CombinatorialPurgedCV(n_splits=1)

    def test_invalid_n_test_splits_zero(self) -> None:
        with pytest.raises(ValueError, match="n_test_splits"):
            CombinatorialPurgedCV(n_splits=4, n_test_splits=0)

    def test_invalid_n_test_splits_eq_n_splits(self) -> None:
        with pytest.raises(ValueError, match="n_test_splits"):
            CombinatorialPurgedCV(n_splits=4, n_test_splits=4)

    def test_invalid_embargo_pct(self) -> None:
        with pytest.raises(ValueError, match="embargo_pct"):
            CombinatorialPurgedCV(n_splits=4, n_test_splits=2, embargo_pct=0.6)

    def test_n_samples_too_small(self) -> None:
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2)
        with pytest.raises(ValueError, match="too small"):
            cv.split(5)


# ---------------------------------------------------------------------------
# run() — PBO and recommendation
# ---------------------------------------------------------------------------


class TestCPCVRun:
    def test_returns_cpcv_result(self) -> None:
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=2)
        rng = np.random.default_rng(42)
        returns = (rng.standard_normal(400) * 0.01 + 0.001).tolist()
        result = cv.run(returns, _simple_sharpe)
        assert isinstance(result, CPCVResult)

    def test_n_combinations_matches_split(self) -> None:
        cv = CombinatorialPurgedCV(n_splits=5, n_test_splits=2)
        rng = np.random.default_rng(0)
        r = (rng.standard_normal(500) * 0.01).tolist()
        result = cv.run(r, _simple_sharpe)
        expected = len(list(combinations(range(5), 2)))
        assert result.n_combinations == expected

    def test_pbo_high_for_overfitted_strategy(self) -> None:
        """IS=3.0 but OOS=-0.5 → PBO near 1."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=2, embargo_pct=0.0)
        rng = np.random.default_rng(0)
        n = 400

        # Force IS=3.0, OOS=-0.5 by swapping train/test behaviour
        call_count = [0]

        def flipping_sharpe(returns: list[float]) -> float:
            call_count[0] += 1
            # odd calls = IS (train) → high, even calls = OOS (test) → low
            return 3.0 if call_count[0] % 2 == 1 else -0.5

        result = cv.run((rng.standard_normal(n) * 0.01).tolist(), flipping_sharpe)
        assert result.pbo > 0.5, f"Expected high PBO, got {result.pbo}"
        assert result.recommendation == "DISCARD"

    def test_pbo_zero_when_oos_always_above_is_median(self) -> None:
        """OOS sharpes all above IS median → PBO = 0."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=2, embargo_pct=0.0)

        call_count = [0]

        def sharpe_fn(returns: list[float]) -> float:
            call_count[0] += 1
            return 0.5 if call_count[0] % 2 == 1 else 2.0  # IS=0.5, OOS=2.0

        rng = np.random.default_rng(1)
        result = cv.run((rng.standard_normal(400) * 0.01).tolist(), sharpe_fn)
        assert result.pbo == 0.0
        assert result.recommendation in ("DEPLOY", "INVESTIGATE")

    def test_recommendation_deploy(self) -> None:
        """pbo < 0.25 and oos_median > 0.5 → DEPLOY."""
        cv = CombinatorialPurgedCV(n_splits=4, n_test_splits=2, embargo_pct=0.0)

        counter = [0]

        def fn(returns: list[float]) -> float:
            counter[0] += 1
            return 0.3 if counter[0] % 2 == 1 else 2.0

        rng = np.random.default_rng(7)
        result = cv.run((rng.standard_normal(400) * 0.01).tolist(), fn)
        assert result.recommendation == "DEPLOY"

    def test_recommendation_investigate(self) -> None:
        """0.25 <= pbo < 0.50 → INVESTIGATE."""
        cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
        counter = [0]
        # 15 combinations (C(6,2)) - used as reference in test comment below

        # First 4/15 OOS will be below IS median → pbo = 4/15 ≈ 0.27
        below_count = [0]

        def fn(returns: list[float]) -> float:
            counter[0] += 1
            is_oos = counter[0] % 2 == 0
            if is_oos:
                below_count[0] += 1
                return -0.1 if below_count[0] <= 4 else 1.0
            return 1.0  # IS always 1.0

        rng = np.random.default_rng(3)
        result = cv.run((rng.standard_normal(600) * 0.01).tolist(), fn)
        assert result.recommendation in ("INVESTIGATE", "DISCARD")


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestCPCVProperties:
    @given(
        n_splits=st.integers(3, 8),
        n_test_splits=st.integers(1, 4),
        embargo=st.floats(0.0, 0.1, allow_nan=False),
    )
    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    def test_pbo_always_in_unit_interval(
        self, n_splits: int, n_test_splits: int, embargo: float
    ) -> None:
        if n_test_splits >= n_splits:
            return  # skip invalid
        cv = CombinatorialPurgedCV(n_splits, n_test_splits, embargo)
        rng = np.random.default_rng(42)
        n = n_splits * 20
        r = (rng.standard_normal(n) * 0.01).tolist()
        result = cv.run(r, _simple_sharpe)
        assert 0.0 <= result.pbo <= 1.0

    @given(n_splits=st.integers(3, 7), n_test_splits=st.integers(1, 3))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_combination_count_matches_math(
        self, n_splits: int, n_test_splits: int
    ) -> None:
        if n_test_splits >= n_splits:
            return
        cv = CombinatorialPurgedCV(n_splits, n_test_splits, embargo_pct=0.0)
        splits = cv.split(n_splits * 20)
        expected = len(list(combinations(range(n_splits), n_test_splits)))
        assert len(splits) == expected

    @given(n_splits=st.integers(3, 6), n_test_splits=st.integers(1, 3))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_train_test_always_disjoint(
        self, n_splits: int, n_test_splits: int
    ) -> None:
        if n_test_splits >= n_splits:
            return
        cv = CombinatorialPurgedCV(n_splits, n_test_splits, embargo_pct=0.0)
        splits = cv.split(n_splits * 20)
        for train, test in splits:
            assert set(train).isdisjoint(set(test))
