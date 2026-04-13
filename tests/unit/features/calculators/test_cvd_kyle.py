"""Unit tests for CVDKyleCalculator (Phase 3.7).

31 tests covering ABC conformity, constructor validation (D030),
correctness, look-ahead defense, D028 compliance, D029 variance
gates, CVD pattern sanity, Kyle lambda sanity, edge cases,
integration with ValidationPipeline, report schema, and version.

Reference:
    Kyle, A. S. (1985). "Continuous Auctions and Insider Trading".
    Econometrica, 53(6), 1315-1335.
    Hasbrouck, J. (2007). Empirical Market Microstructure, Ch. 8.
    Lee, C. M. C. & Ready, M. J. (1991). JoF 46(2).
    ADR-0004 (feature validation methodology).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from features.calculators.cvd_kyle import CVDKyleCalculator

# ── Helpers ──────────────────────────────────────────────────────────


def _make_ticks(
    n_ticks: int,
    seed: int = 42,
    buy_ratio: float = 0.5,
    price_impact: float = 0.0001,
) -> pl.DataFrame:
    """Generate synthetic tick data for CVD/Kyle testing.

    Args:
        n_ticks: Number of ticks.
        seed: RNG seed.
        buy_ratio: Proportion of ticks classified as BUY.
        price_impact: Volatility per tick for price random walk.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)

    timestamps: list[datetime] = []
    prices: list[float] = []
    quantities: list[float] = []
    sides: list[str] = []

    price = 100.0
    for i in range(n_ticks):
        ts = base_time + timedelta(milliseconds=i * 100)
        ret = price_impact * rng.standard_normal()
        price *= np.exp(ret)
        qty = abs(rng.standard_normal() * 10) + 1.0
        side = "BUY" if rng.random() < buy_ratio else "SELL"

        timestamps.append(ts)
        prices.append(round(price, 6))
        quantities.append(round(qty, 4))
        sides.append(side)

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "price": prices,
            "quantity": quantities,
            "side": sides,
        }
    )


def _make_illiquid_ticks(
    n_ticks: int,
    seed: int = 42,
    impact_scale: float = 0.01,
) -> pl.DataFrame:
    """Generate ticks where price moves strongly with order flow.

    Higher impact_scale = more illiquid (price responds more to volume).
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)

    timestamps: list[datetime] = []
    prices: list[float] = []
    quantities: list[float] = []
    sides: list[str] = []

    price = 100.0
    for i in range(n_ticks):
        ts = base_time + timedelta(milliseconds=i * 100)
        qty = abs(rng.standard_normal() * 10) + 1.0
        side = "BUY" if rng.random() < 0.5 else "SELL"
        sign = 1.0 if side == "BUY" else -1.0
        # Price moves proportional to signed volume.
        price += sign * qty * impact_scale + rng.standard_normal() * 0.001
        price = max(price, 1.0)

        timestamps.append(ts)
        prices.append(round(price, 6))
        quantities.append(round(qty, 4))
        sides.append(side)

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "price": prices,
            "quantity": quantities,
            "side": sides,
        }
    )


# ══════════════════════════════════════════════════════════════════════
# ABC conformity (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestABCConformity:
    """Verify CVDKyleCalculator honors the FeatureCalculator contract."""

    def test_name_returns_cvd_kyle(self) -> None:
        calc = CVDKyleCalculator()
        assert calc.name() == "cvd_kyle"

    def test_required_columns_contains_price_quantity_side(self) -> None:
        calc = CVDKyleCalculator()
        req = calc.required_columns()
        for col in ["timestamp", "price", "quantity", "side"]:
            assert col in req

    def test_output_columns_are_six_expected(self) -> None:
        calc = CVDKyleCalculator()
        out = calc.output_columns()
        assert out == [
            "cvd",
            "cvd_divergence",
            "kyle_lambda",
            "kyle_lambda_zscore",
            "liquidity_signal",
            "combined_signal",
        ]


# ══════════════════════════════════════════════════════════════════════
# Constructor validation — D030 (4 tests)
# ══════════════════════════════════════════════════════════════════════


class TestConstructorValidation:
    """D030: all configurable params validated in __init__."""

    def test_cvd_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="cvd_window must be >= 2"):
            CVDKyleCalculator(cvd_window=1)

    def test_kyle_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="kyle_window must be >= 10"):
            CVDKyleCalculator(kyle_window=5)

    def test_kyle_zscore_lookback_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="kyle_zscore_lookback must be >= 2"):
            CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=15)

    def test_combined_weights_not_summing_to_one_raises(self) -> None:
        with pytest.raises(ValueError, match=r"sum to 1\.0"):
            CVDKyleCalculator(combined_weights=(0.6, 0.6))


# ══════════════════════════════════════════════════════════════════════
# Correctness (8 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCorrectness:
    """Verify computational correctness of CVDKyleCalculator."""

    def test_compute_produces_six_output_columns(self) -> None:
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = _make_ticks(200)
        result = calc.compute(df)
        for col in calc.output_columns():
            assert col in result.columns

    def test_warm_up_produces_nan(self) -> None:
        """First kyle_window ticks have NaN on kyle_lambda."""
        kw = 20
        calc = CVDKyleCalculator(kyle_window=kw, kyle_zscore_lookback=kw * 2)
        df = _make_ticks(200)
        result = calc.compute(df)

        kyle_arr = result["kyle_lambda"].to_numpy()
        for i in range(kw):
            assert np.isnan(kyle_arr[i]), f"kyle_lambda at tick {i} should be NaN during warm-up"
        # After warm-up, should have values.
        assert not np.isnan(kyle_arr[kw])

    def test_cvd_is_monotonic_cumulative(self) -> None:
        """CVD is cumulative: diff(cvd) = signed_volume per tick."""
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = _make_ticks(100, seed=42)
        result = calc.compute(df)

        cvd_arr = result["cvd"].to_numpy()
        quantities = df["quantity"].to_numpy().astype(np.float64)
        sides = df["side"].to_list()

        for i in range(1, len(cvd_arr)):
            sign = 1.0 if str(sides[i]).upper() == "BUY" else -1.0
            expected_diff = sign * quantities[i]
            actual_diff = cvd_arr[i] - cvd_arr[i - 1]
            np.testing.assert_allclose(actual_diff, expected_diff, rtol=1e-10)

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_cvd_divergence_bounded(self, seed: int) -> None:
        """cvd_divergence must be strictly in [-1, +1]."""
        df = _make_ticks(50, seed=seed)
        calc = CVDKyleCalculator(cvd_window=10, kyle_window=10, kyle_zscore_lookback=20)
        result = calc.compute(df)
        vals = result["cvd_divergence"].to_numpy()
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_kyle_lambda_non_negative(self, seed: int) -> None:
        """kyle_lambda must always be >= 0 (or NaN during warm-up)."""
        df = _make_ticks(200, seed=seed)
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        result = calc.compute(df)
        vals = result["kyle_lambda"].to_numpy()
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            assert np.all(valid >= 0.0), f"Found negative kyle_lambda: {valid[valid < 0]}"

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_liquidity_signal_bounded(self, seed: int) -> None:
        """liquidity_signal must be strictly in [-1, +1]."""
        df = _make_ticks(200, seed=seed)
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        result = calc.compute(df)
        vals = result["liquidity_signal"].to_numpy()
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_combined_signal_bounded(self, seed: int) -> None:
        """combined_signal must be strictly in [-1, +1]."""
        df = _make_ticks(200, seed=seed)
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        result = calc.compute(df)
        vals = result["combined_signal"].to_numpy()
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    def test_determinism(self) -> None:
        """Same inputs must produce identical outputs."""
        df = _make_ticks(200, seed=42)
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        r1 = calc.compute(df)
        r2 = calc.compute(df)
        for col in calc.output_columns():
            v1 = r1[col].to_numpy()
            v2 = r2[col].to_numpy()
            mask = ~np.isnan(v1) & ~np.isnan(v2)
            np.testing.assert_array_equal(v1[mask], v2[mask])
            np.testing.assert_array_equal(np.isnan(v1), np.isnan(v2))


# ══════════════════════════════════════════════════════════════════════
# Look-ahead defense (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestLookAheadDefense:
    """Characterize that outputs never use future data."""

    def test_kyle_lambda_at_t_uses_only_ticks_before_t(self) -> None:
        """Two DataFrames identical on [0, 150], divergent on [151, 200].
        kyle_lambda at ticks 120-150 must be bitwise identical.
        """
        df_a = _make_ticks(200, seed=42)
        df_b = _make_ticks(200, seed=42)

        # Diverge from tick 151 onward.
        rng = np.random.default_rng(99)
        quantities_b = df_b["quantity"].to_list()
        sides_b = df_b["side"].to_list()
        prices_b = df_b["price"].to_list()
        for i in range(151, 200):
            quantities_b[i] = abs(rng.standard_normal() * 100) + 1.0
            sides_b[i] = "BUY" if rng.random() > 0.5 else "SELL"
            prices_b[i] = 100.0 + rng.standard_normal() * 5.0
        df_b = df_b.with_columns(
            pl.Series("quantity", quantities_b),
            pl.Series("side", sides_b),
            pl.Series("price", prices_b),
        )

        calc = CVDKyleCalculator(kyle_window=20, kyle_zscore_lookback=40)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        for col in ["kyle_lambda", "kyle_lambda_zscore", "liquidity_signal"]:
            for t in range(120, 151):
                va = result_a[col][t]
                vb = result_b[col][t]
                if va is None and vb is None:
                    continue
                if isinstance(va, float) and isinstance(vb, float):
                    if np.isnan(va) and np.isnan(vb):
                        continue
                assert va == pytest.approx(vb, rel=1e-12), (
                    f"{col} at tick {t} differs: {va} vs {vb} — look-ahead detected!"
                )

    def test_cvd_divergence_realization_includes_current_tick(self) -> None:
        """CVD divergence at tick t uses ticks [t-cvd_window+1, t].
        Two DataFrames identical on [0, 19], tick 20 different.
        cvd_divergence[20] must differ (proves current tick is used).
        """
        df_a = _make_ticks(30, seed=42)
        df_b = _make_ticks(30, seed=42)

        # Change tick 20 only.
        quantities_b = df_b["quantity"].to_list()
        sides_b = df_b["side"].to_list()
        quantities_b[20] = 999.0  # Extreme quantity.
        sides_b[20] = "SELL" if sides_b[20] == "BUY" else "BUY"
        df_b = df_b.with_columns(
            pl.Series("quantity", quantities_b),
            pl.Series("side", sides_b),
        )

        calc = CVDKyleCalculator(cvd_window=10, kyle_window=10, kyle_zscore_lookback=20)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        div_a = result_a["cvd_divergence"][20]
        div_b = result_b["cvd_divergence"][20]

        # At least one should not be NaN.
        if isinstance(div_a, float) and isinstance(div_b, float):
            if not np.isnan(div_a) and not np.isnan(div_b):
                assert div_a != pytest.approx(div_b, rel=1e-6), (
                    f"cvd_divergence at tick 20 is identical "
                    f"({div_a} vs {div_b}) — current tick not included!"
                )


# ══════════════════════════════════════════════════════════════════════
# D028 compliance (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestD028Compliance:
    """Verify D028: documentation declares correct classification."""

    def test_docstring_declares_classification(self) -> None:
        """CVDKyleCalculator docstring must declare realization at tick t
        for cvd/divergence and forecast-like for kyle columns.
        """
        import inspect

        source = inspect.getsource(CVDKyleCalculator)
        assert "realization at tick t" in source, (
            "Must document cvd/cvd_divergence as 'realization at tick t'"
        )
        assert "forecast-like at tick t" in source, (
            "Must document kyle columns as 'forecast-like at tick t'"
        )


# ══════════════════════════════════════════════════════════════════════
# D029 variance gates (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestSignalVarianceGates:
    """D029: output signal columns must vary across inputs."""

    def test_cvd_divergence_varies_across_inputs(self) -> None:
        """Over 100 DataFrames, std of mean(cvd_divergence) > 0.01."""
        means: list[float] = []
        calc = CVDKyleCalculator(cvd_window=10, kyle_window=10, kyle_zscore_lookback=20)
        for seed in range(100):
            df = _make_ticks(80, seed=seed)
            result = calc.compute(df)
            vals = result["cvd_divergence"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 90
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(cvd_divergence)) = {std_of_means:.6f} — D029 variance gate violation"
        )

    def test_liquidity_signal_varies_across_inputs(self) -> None:
        """Over 100 DataFrames, std of mean(liquidity_signal) > 0.01."""
        means: list[float] = []
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        for seed in range(100):
            df = _make_ticks(200, seed=seed)
            result = calc.compute(df)
            vals = result["liquidity_signal"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 90
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(liquidity_signal)) = {std_of_means:.6f} — D029 variance gate violation"
        )

    def test_combined_signal_varies_across_inputs(self) -> None:
        """Over 100 DataFrames, std of mean(combined_signal) > 0.01."""
        means: list[float] = []
        calc = CVDKyleCalculator(cvd_window=10, kyle_window=10, kyle_zscore_lookback=20)
        for seed in range(100):
            df = _make_ticks(200, seed=seed)
            result = calc.compute(df)
            vals = result["combined_signal"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 90
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(combined_signal)) = {std_of_means:.6f} — D029 variance gate violation"
        )


# ══════════════════════════════════════════════════════════════════════
# CVD-price divergence sanity (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestCVDDivergenceSanity:
    """Verify CVD divergence detects known accumulation/distribution."""

    def test_cvd_divergence_detects_known_pattern(self) -> None:
        """Divergent vs convergent price-CVD relationship.

        The divergence formula is tanh(-corr(price_changes, cvd_changes))
        over a rolling window. The correlation is computed on tick-level
        changes, so the test must inject tick-level correlation structure.

        - Divergent: price moves AGAINST order flow (buy → price drops).
          corr(price_changes, cvd_changes) < 0 → divergence > 0.
        - Convergent: price moves WITH order flow (buy → price rises).
          corr(price_changes, cvd_changes) > 0 → divergence < 0.
        """
        rng = np.random.default_rng(42)
        base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)
        n = 100

        # Helper: build ticks where price change = direction * impact.
        def _build(direction: float, seed: int) -> pl.DataFrame:
            r = np.random.default_rng(seed)
            ts: list[datetime] = []
            pr: list[float] = []
            qt: list[float] = []
            sd: list[str] = []
            price = 100.0
            for i in range(n):
                ts.append(base_time + timedelta(milliseconds=i * 100))
                qty = 5.0 + r.random() * 10.0
                side = "BUY" if r.random() < 0.6 else "SELL"
                sign = 1.0 if side == "BUY" else -1.0
                # Price change = direction * signed_vol + noise.
                # direction > 0: price follows CVD (convergent).
                # direction < 0: price opposes CVD (divergent).
                price += direction * sign * qty * 0.01 + r.standard_normal() * 0.001
                price = max(price, 1.0)
                pr.append(round(price, 6))
                qt.append(round(qty, 4))
                sd.append(side)
            return pl.DataFrame(
                {
                    "timestamp": ts,
                    "price": pr,
                    "quantity": qt,
                    "side": sd,
                }
            )

        df_divergent = _build(direction=-1.0, seed=42)
        df_convergent = _build(direction=1.0, seed=42)

        calc = CVDKyleCalculator(cvd_window=20, kyle_window=10, kyle_zscore_lookback=20)

        result_div = calc.compute(df_divergent)
        result_conv = calc.compute(df_convergent)

        div_arr = result_div["cvd_divergence"].to_numpy()
        conv_arr = result_conv["cvd_divergence"].to_numpy()

        valid_div = div_arr[-30:]
        valid_conv = conv_arr[-30:]
        valid_div = valid_div[~np.isnan(valid_div)]
        valid_conv = valid_conv[~np.isnan(valid_conv)]

        mean_div = float(np.mean(valid_div))
        mean_conv = float(np.mean(valid_conv))

        assert mean_div > 0.0, f"Divergent pattern score = {mean_div:.4f}, expected > 0"
        assert mean_conv < 0.0, f"Convergent pattern score = {mean_conv:.4f}, expected < 0"


# ══════════════════════════════════════════════════════════════════════
# Kyle lambda sanity (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestKyleLambdaSanity:
    """Verify Kyle lambda is higher on illiquid data."""

    def test_kyle_lambda_higher_on_illiquid_data(self) -> None:
        """Illiquid market (large price impact per unit volume) should
        produce higher mean kyle_lambda than liquid market.
        """
        kw = 20
        calc = CVDKyleCalculator(kyle_window=kw, kyle_zscore_lookback=kw * 2)

        df_liquid = _make_illiquid_ticks(300, seed=42, impact_scale=0.0001)
        df_illiquid = _make_illiquid_ticks(300, seed=42, impact_scale=0.01)

        result_liquid = calc.compute(df_liquid)
        result_illiquid = calc.compute(df_illiquid)

        lam_liquid = result_liquid["kyle_lambda"].to_numpy()
        lam_illiquid = result_illiquid["kyle_lambda"].to_numpy()

        mean_liquid = float(np.nanmean(lam_liquid))
        mean_illiquid = float(np.nanmean(lam_illiquid))

        assert mean_illiquid > mean_liquid, (
            f"Expected illiquid lambda ({mean_illiquid:.6f}) > liquid lambda ({mean_liquid:.6f})"
        )


# ══════════════════════════════════════════════════════════════════════
# Edge cases (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: insufficient data, missing columns, unsorted ts."""

    def test_insufficient_data_returns_nan(self) -> None:
        """DataFrame smaller than kyle_window → all NaN on kyle_lambda."""
        calc = CVDKyleCalculator(kyle_window=100, kyle_zscore_lookback=200)
        df = _make_ticks(50)
        result = calc.compute(df)

        kyle_arr = result["kyle_lambda"].to_numpy()
        assert np.all(np.isnan(kyle_arr)), (
            "Expected all NaN on kyle_lambda with < kyle_window ticks"
        )

    def test_missing_required_column_raises(self) -> None:
        """DataFrame without 'side' must raise ValueError."""
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)],
                "price": [100.0],
                "quantity": [10.0],
            }
        )
        with pytest.raises(ValueError, match="missing required columns"):
            calc.compute(df)

    def test_unsorted_timestamps_raise(self) -> None:
        """Unsorted timestamps must raise ValueError."""
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = _make_ticks(50)
        df_unsorted = df.sort("timestamp", descending=True)
        with pytest.raises(ValueError, match="ascending-sorted"):
            calc.compute(df_unsorted)


# ══════════════════════════════════════════════════════════════════════
# Integration (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end tests through the ValidationPipeline."""

    def test_cvd_kyle_through_validation_pipeline(self) -> None:
        """Run CVDKyleCalculator through ICStage end-to-end."""
        from features.ic.measurer import SpearmanICMeasurer
        from features.validation.stages import ICStage, StageContext

        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = _make_ticks(500, seed=42)
        result_df = calc.compute(df)

        signals = result_df["combined_signal"].to_numpy()
        prices = result_df["price"].to_numpy().astype(np.float64)
        fwd_returns = np.full(len(prices), np.nan)
        fwd_returns[:-1] = np.log(prices[1:] / prices[:-1])

        mask = np.isfinite(signals) & np.isfinite(fwd_returns)
        feat_clean = signals[mask]
        fwd_clean = fwd_returns[mask]

        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        ctx = StageContext(
            feature_name=calc.name(),
            data=result_df,
            metadata={
                "feature_values": feat_clean,
                "forward_returns": fwd_clean,
                "horizon_bars": 1,
            },
        )
        stage_result = ICStage(measurer=measurer).run(ctx)

        assert stage_result.stage.value == "ic"
        assert "ic" in stage_result.metrics
        assert "ic_ir" in stage_result.metrics

    def test_combined_signal_has_measurable_ic_on_synthetic_predictive_data(
        self,
    ) -> None:
        """Build synthetic data where combined_signal predicts
        forward returns. Verify measured IC > 0.1.
        """
        calc = CVDKyleCalculator(kyle_window=10, kyle_zscore_lookback=20)
        df = _make_ticks(500, seed=42)
        result_df = calc.compute(df)

        signals = result_df["combined_signal"].to_numpy()
        prices = result_df["price"].to_numpy().astype(np.float64)

        fwd_raw = np.full(len(prices), np.nan)
        fwd_raw[:-1] = np.log(prices[1:] / prices[:-1])

        rng = np.random.default_rng(42)
        mask = np.isfinite(signals) & np.isfinite(fwd_raw)
        fwd_synthetic = np.copy(fwd_raw)
        alpha = 0.3
        noise = rng.standard_normal(int(mask.sum())) * 0.01
        fwd_synthetic[mask] = alpha * signals[mask] + noise

        feat_clean = signals[mask]
        fwd_clean = fwd_synthetic[mask]

        from features.ic.measurer import SpearmanICMeasurer

        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        ic_result = measurer.measure_rich(
            feature=feat_clean,
            forward_returns=fwd_clean,
            feature_name="combined_signal",
            horizon_bars=1,
        )
        assert abs(ic_result.ic) > 0.1, (
            f"IC = {ic_result.ic:.4f} — expected > 0.1 on predictive data"
        )


# ══════════════════════════════════════════════════════════════════════
# Report (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestReport:
    """Verify CVDKyleValidationReport schema stability."""

    def test_report_summary_schema_stable_on_empty(self) -> None:
        """summary() returns all 4 keys even with empty ic_results."""
        from features.validation.cvd_kyle_report import (
            CVDKyleValidationReport,
        )

        report = CVDKyleValidationReport(ic_results=())
        summary = report.summary()
        assert set(summary.keys()) == {
            "n_results",
            "mean_ic",
            "mean_ic_ir",
            "any_significant",
        }
        assert summary["any_significant"] is False

    def test_report_to_markdown_renders_none_significance_as_na(
        self,
    ) -> None:
        """is_significant=None renders as 'n/a', not 'no'."""
        from features.ic.base import ICResult
        from features.validation.cvd_kyle_report import (
            CVDKyleValidationReport,
        )

        result = ICResult(
            ic=0.03,
            ic_ir=0.6,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="combined_signal",
            is_significant=None,
        )
        report = CVDKyleValidationReport(ic_results=(result,))
        md = report.to_markdown()
        assert "n/a" in md
        lines = [ln for ln in md.split("\n") if "combined_signal" in ln and "+0.0300" in ln]
        assert len(lines) == 1
        assert "| no |" not in lines[0]
        assert "| n/a |" in lines[0]


# ══════════════════════════════════════════════════════════════════════
# Additional (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestAdditional:
    """Miscellaneous tests."""

    def test_version_is_semver(self) -> None:
        calc = CVDKyleCalculator()
        assert calc.version == "1.0.0"
