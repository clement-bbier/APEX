"""Tests for features.ic.measurer — SpearmanICMeasurer."""

from __future__ import annotations

import numpy as np
import pytest

from features.ic.base import ICMetric, ICResult
from features.ic.measurer import SpearmanICMeasurer


@pytest.fixture
def measurer() -> SpearmanICMeasurer:
    return SpearmanICMeasurer(
        rolling_window=50,
        horizons=(1, 5, 10, 20),
        turnover_cost_bps=10.0,
        bootstrap_n=200,
    )


class TestSpearmanICMeasurer:
    """SpearmanICMeasurer correctness and ABC compliance."""

    def test_is_ic_metric(self, measurer: SpearmanICMeasurer) -> None:
        """Implements ICMetric ABC."""
        assert isinstance(measurer, ICMetric)

    def test_perfect_feature_ic_one(self, measurer: SpearmanICMeasurer) -> None:
        """feature == forward_return (perfect predictor) -> IC ~ 1.0."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        result = measurer.measure_rich(fwd, fwd, "perfect", horizon_bars=1)
        assert result.ic == pytest.approx(1.0, abs=0.05)
        assert result.is_significant is True

    def test_negated_feature_ic_minus_one(self, measurer: SpearmanICMeasurer) -> None:
        """feature == -forward_return -> IC ~ -1.0."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        result = measurer.measure_rich(-fwd, fwd, "negated", horizon_bars=1)
        assert result.ic == pytest.approx(-1.0, abs=0.05)

    def test_random_feature_ic_near_zero(self, measurer: SpearmanICMeasurer) -> None:
        """iid random feature -> |IC| < 0.15."""
        rng = np.random.default_rng(99)
        n = 500
        feat = rng.normal(0, 1, size=n)
        fwd = rng.normal(0, 1, size=n)
        result = measurer.measure_rich(feat, fwd, "random", horizon_bars=1)
        # With rolling blocks the mean IC should be near zero, but not
        # necessarily *statistically* insignificant (many blocks can
        # amplify tiny IC). We only assert the magnitude is small.
        assert abs(result.ic) < 0.15

    def test_rolling_ic_length(self, measurer: SpearmanICMeasurer) -> None:
        """rolling_ic returns DataFrame of correct length."""
        rng = np.random.default_rng(77)
        n = 200
        feat = rng.normal(0, 1, size=n)
        fwd = rng.normal(0, 1, size=n)
        df = measurer.rolling_ic(feat, fwd, window=50)
        assert len(df) == n - 50 + 1
        assert set(df.columns) == {"period", "ic"}

    def test_horizon_influences_newey_west_lags(self, measurer: SpearmanICMeasurer) -> None:
        """Higher horizon -> more Newey-West lags."""
        rng = np.random.default_rng(55)
        n = 500
        feat = rng.normal(0, 1, size=n)
        fwd = rng.normal(0, 1, size=n)
        r1 = measurer.measure_rich(feat, fwd, "test", horizon_bars=1)
        r5 = measurer.measure_rich(feat, fwd, "test", horizon_bars=5)
        assert r1.newey_west_lags == 0
        assert r5.newey_west_lags == 4

    def test_turnover_adj_ic_less_than_ic(self, measurer: SpearmanICMeasurer) -> None:
        """Turnover-adjusted IC has smaller magnitude than raw IC."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        # Feature with high turnover (random noise added).
        feat = fwd + rng.normal(0, 0.5, size=n)
        result = measurer.measure_rich(feat, fwd, "noisy", horizon_bars=1)
        if result.ic > 0 and result.turnover_adj_ic is not None:
            assert result.turnover_adj_ic <= result.ic + 1e-10

    def test_ic_decay_four_horizons(self, measurer: SpearmanICMeasurer) -> None:
        """measure_all populates ic_decay with correct number of horizons."""
        rng = np.random.default_rng(42)
        n = 500
        feat = rng.normal(0, 1, size=n)
        import polars as pl

        features_df = pl.DataFrame({"feat_a": feat})
        fwd_by_h: dict[int, np.ndarray] = {}  # type: ignore[type-arg]
        for h in (1, 5, 10, 20):
            fwd_by_h[h] = rng.normal(0, 1, size=n)

        results = measurer.measure_all(features_df, fwd_by_h, ["feat_a"])
        assert len(results) == 4  # one per horizon
        for r in results:
            assert r.ic_decay is not None
            assert len(r.ic_decay) == 4

    def test_insufficient_data(self, measurer: SpearmanICMeasurer) -> None:
        """< 20 samples -> is_significant=False, ic=0.0."""
        feat = np.arange(10, dtype=np.float64)
        fwd = np.arange(10, dtype=np.float64)
        result = measurer.measure_rich(feat, fwd, "tiny", horizon_bars=1)
        assert result.ic == 0.0
        assert result.is_significant is False
        assert result.n_samples == 0

    def test_icresult_fields_populated(self, measurer: SpearmanICMeasurer) -> None:
        """All Phase 3.3 fields are populated (not None)."""
        rng = np.random.default_rng(42)
        n = 500
        fwd = rng.normal(0, 1, size=n)
        feat = fwd + rng.normal(0, 0.5, size=n)
        result = measurer.measure_rich(feat, fwd, "full_test", horizon_bars=5)
        assert result.feature_name == "full_test"
        assert result.ic_std is not None
        assert result.ic_t_stat is not None
        assert result.ic_hit_rate is not None
        assert result.turnover_adj_ic is not None
        assert result.is_significant is not None
        assert result.horizon_bars == 5
        assert result.newey_west_lags == 4

    def test_abc_measure_signature(self, measurer: SpearmanICMeasurer) -> None:
        """ABC measure() accepts numpy arrays and returns ICResult."""
        rng = np.random.default_rng(42)
        feat = rng.normal(0, 1, size=100)
        fwd = rng.normal(0, 1, size=100)
        result = measurer.measure(feat, fwd)
        assert isinstance(result, ICResult)
