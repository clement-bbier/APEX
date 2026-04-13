"""Unit tests for RoughVolCalculator (Phase 3.5).

25 tests covering ABC conformity, correctness, Variance Ratio sanity,
look-ahead defense, D028 compliance, edge cases, integration with
ValidationPipeline, report schema stability.

Reference:
    Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is
    rough". Quantitative Finance, 18(6), 933-949.
    Lo, A. W. & MacKinlay, A. C. (1988). "Stock market prices do not
    follow random walks". Review of Financial Studies, 1(1), 41-66.
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

from features.calculators.rough_vol import RoughVolCalculator

# ── Helpers ──────────────────────────────────────────────────────────


def _make_daily_bars(n_days: int, seed: int = 42) -> pl.DataFrame:
    """Generate *n_days* synthetic daily OHLCV bars (GBM)."""
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, tzinfo=UTC)
    price = 100.0

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for i in range(n_days):
        ts = base_time + timedelta(days=i)
        ret = 0.0005 + 0.02 * rng.standard_normal()
        if rng.random() < 0.05:
            ret += rng.choice([-1, 1]) * 0.02 * 3
        o = price
        c = price * np.exp(ret)
        hi = max(o, c) * (1 + abs(rng.standard_normal()) * 0.005)
        lo = min(o, c) * (1 - abs(rng.standard_normal()) * 0.005)

        timestamps.append(ts)
        opens.append(round(o, 4))
        highs.append(round(hi, 4))
        lows.append(round(lo, 4))
        closes.append(round(c, 4))
        volumes.append(round(1000 + rng.random() * 500, 2))
        price = c

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _make_5m_bars(n_days: int, bars_per_day: int = 78, seed: int = 42) -> pl.DataFrame:
    """Generate synthetic 5m intraday OHLCV bars."""
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)
    price = 100.0

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for day in range(n_days):
        day_start = base_time + timedelta(days=day)
        for bar in range(bars_per_day):
            ts = day_start + timedelta(minutes=5 * bar)
            ret = 0.0001 * rng.standard_normal()
            o = price
            c = price * np.exp(ret)
            hi = max(o, c) * 1.001
            lo = min(o, c) * 0.999

            timestamps.append(ts)
            opens.append(round(o, 4))
            highs.append(round(hi, 4))
            lows.append(round(lo, 4))
            closes.append(round(c, 4))
            volumes.append(round(100 + rng.random() * 50, 2))
            price = c

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _make_random_walk(n: int, seed: int = 42) -> pl.DataFrame:
    """Pure random walk (cumulative sum of N(0,1) returns) as daily bars."""
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, tzinfo=UTC)
    log_returns = rng.standard_normal(n) * 0.02
    prices = 100.0 * np.exp(np.cumsum(log_returns))

    return pl.DataFrame(
        {
            "timestamp": [base_time + timedelta(days=i) for i in range(n)],
            "open": prices.tolist(),
            "high": (prices * 1.005).tolist(),
            "low": (prices * 0.995).tolist(),
            "close": prices.tolist(),
            "volume": [1000.0] * n,
        }
    )


def _make_momentum_series(n: int, rho: float = 0.3, seed: int = 42) -> pl.DataFrame:
    """AR(1) with positive autocorrelation → momentum → VR > 1."""
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, tzinfo=UTC)

    log_returns = np.zeros(n)
    for i in range(1, n):
        log_returns[i] = rho * log_returns[i - 1] + rng.standard_normal() * 0.02

    prices = 100.0 * np.exp(np.cumsum(log_returns))

    return pl.DataFrame(
        {
            "timestamp": [base_time + timedelta(days=i) for i in range(n)],
            "open": prices.tolist(),
            "high": (prices * 1.005).tolist(),
            "low": (prices * 0.995).tolist(),
            "close": prices.tolist(),
            "volume": [1000.0] * n,
        }
    )


# ══════════════════════════════════════════════════════════════════════
# ABC conformity (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestABCConformity:
    """Verify RoughVolCalculator honors the FeatureCalculator contract."""

    def test_name_returns_rough_vol(self) -> None:
        calc = RoughVolCalculator()
        assert calc.name() == "rough_vol"

    def test_required_columns_contains_close_volume(self) -> None:
        calc = RoughVolCalculator()
        req = calc.required_columns()
        for col in ["timestamp", "open", "high", "low", "close", "volume"]:
            assert col in req

    def test_output_columns_are_six_expected(self) -> None:
        calc = RoughVolCalculator()
        out = calc.output_columns()
        assert out == [
            "rough_hurst",
            "rough_is_rough",
            "rough_scalping_score",
            "rough_size_multiplier",
            "variance_ratio",
            "vr_signal",
        ]


# ══════════════════════════════════════════════════════════════════════
# Correctness (7 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCorrectness:
    """Verify computational correctness of RoughVolCalculator."""

    def test_compute_produces_six_output_columns(self) -> None:
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(150)
        result = calc.compute(df)
        for col in calc.output_columns():
            assert col in result.columns

    def test_warm_up_produces_nan_on_all_outputs(self) -> None:
        """The first warm_up + 1 rows must have NaN on all outputs (1d mode).

        Row 0 has no RV (no prior close). Rows 1..warm_up map to
        day indices 0..warm_up-1 which are below the warm_up_days threshold.
        """
        warm_up = 60
        calc = RoughVolCalculator(warm_up_days=warm_up)
        df = _make_daily_bars(150)
        result = calc.compute(df)

        for col in calc.output_columns():
            vals = result[col].to_list()
            for i in range(warm_up + 1):
                assert vals[i] is None or (isinstance(vals[i], float) and np.isnan(vals[i])), (
                    f"{col} at row {i} should be NaN but got {vals[i]}"
                )

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_hurst_in_valid_range(self, seed: int) -> None:
        """Hurst exponent must be in [0, 1] (or NaN during warm-up)."""
        rng = np.random.default_rng(seed)
        n = 100
        base_time = datetime(2020, 1, 1, tzinfo=UTC)
        price = 100.0
        timestamps: list[datetime] = []
        closes: list[float] = []
        for i in range(n):
            timestamps.append(base_time + timedelta(days=i))
            price = price * np.exp(0.02 * rng.standard_normal())
            closes.append(price)

        df = pl.DataFrame(
            {
                "timestamp": timestamps,
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1000.0] * n,
            }
        )
        calc = RoughVolCalculator(warm_up_days=30)
        result = calc.compute(df)
        hurst = result["rough_hurst"].to_numpy()
        valid = hurst[~np.isnan(hurst)]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 1.0)

    def test_is_rough_binary(self) -> None:
        """rough_is_rough must be 0.0, 1.0, or NaN only."""
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(150)
        result = calc.compute(df)
        vals = result["rough_is_rough"].to_numpy()
        valid = vals[~np.isnan(vals)]
        unique = set(valid.tolist())
        assert unique <= {0.0, 1.0}, f"Unexpected values: {unique}"

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_scalping_score_bounded(self, seed: int) -> None:
        """Scalping score must be in [-1, +1]."""
        rng = np.random.default_rng(seed)
        n = 100
        base_time = datetime(2020, 1, 1, tzinfo=UTC)
        price = 100.0
        timestamps: list[datetime] = []
        closes: list[float] = []
        for i in range(n):
            timestamps.append(base_time + timedelta(days=i))
            price = price * np.exp(0.02 * rng.standard_normal())
            closes.append(price)

        df = pl.DataFrame(
            {
                "timestamp": timestamps,
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1000.0] * n,
            }
        )
        calc = RoughVolCalculator(warm_up_days=30)
        result = calc.compute(df)
        scores = result["rough_scalping_score"].to_numpy()
        valid = scores[~np.isnan(scores)]
        assert np.all(valid >= -1.0)
        assert np.all(valid <= 1.0)

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_vr_signal_bounded(self, seed: int) -> None:
        """VR signal must be in [-1, +1]."""
        rng = np.random.default_rng(seed)
        n = 100
        base_time = datetime(2020, 1, 1, tzinfo=UTC)
        price = 100.0
        timestamps: list[datetime] = []
        closes: list[float] = []
        for i in range(n):
            timestamps.append(base_time + timedelta(days=i))
            price = price * np.exp(0.02 * rng.standard_normal())
            closes.append(price)

        df = pl.DataFrame(
            {
                "timestamp": timestamps,
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1000.0] * n,
            }
        )
        calc = RoughVolCalculator(warm_up_days=30)
        result = calc.compute(df)
        sigs = result["vr_signal"].to_numpy()
        valid = sigs[~np.isnan(sigs)]
        assert np.all(valid >= -1.0)
        assert np.all(valid <= 1.0)

    def test_size_multiplier_typical_range(self) -> None:
        """rough_size_multiplier must be in plausible range [0.1, 5.0]."""
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(150)
        result = calc.compute(df)
        vals = result["rough_size_multiplier"].to_numpy()
        valid = vals[~np.isnan(vals)]
        assert len(valid) > 0
        assert np.all(valid >= 0.1), f"Min multiplier = {np.min(valid)}"
        assert np.all(valid <= 5.0), f"Max multiplier = {np.max(valid)}"

    def test_size_multiplier_varies_across_regimes(self) -> None:
        """size_multiplier must not be constant — it varies with Hurst regime.

        Gate against the silent bug where clamp to [0,1] made the column
        effectively constant (IC = 0).
        """
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(300, seed=7)
        result = calc.compute(df)
        vals = result["rough_size_multiplier"].to_numpy()
        valid = vals[~np.isnan(vals)]
        assert len(valid) > 50
        std = float(np.std(valid))
        assert std > 0.001, f"size_multiplier std = {std:.6f} — column is effectively constant"


# ══════════════════════════════════════════════════════════════════════
# Variance Ratio sanity (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestVarianceRatioSanity:
    """Verify VR statistical properties on synthetic data."""

    def test_variance_ratio_unity_on_random_walk(self) -> None:
        """On a pure random walk, mean VR should be close to 1.0.

        Tolerance for finite sample: |mean(VR) - 1.0| < 0.15.
        """
        df = _make_random_walk(500, seed=42)
        calc = RoughVolCalculator(warm_up_days=60)
        result = calc.compute(df)
        vr = result["variance_ratio"].to_numpy()
        valid_vr = vr[~np.isnan(vr)]
        assert len(valid_vr) > 100
        mean_vr = float(np.mean(valid_vr))
        assert abs(mean_vr - 1.0) < 0.15, f"mean(VR) = {mean_vr:.4f} on random walk — expected ~1.0"

    def test_variance_ratio_greater_than_one_on_momentum(self) -> None:
        """On an AR(1) series with rho=0.3, mean VR should be > 1.0.

        Positive autocorrelation → VR(q) > 1 (momentum).
        """
        df = _make_momentum_series(500, rho=0.3, seed=42)
        calc = RoughVolCalculator(warm_up_days=60)
        result = calc.compute(df)
        vr = result["variance_ratio"].to_numpy()
        valid_vr = vr[~np.isnan(vr)]
        assert len(valid_vr) > 100
        mean_vr = float(np.mean(valid_vr))
        assert mean_vr > 1.05, f"mean(VR) = {mean_vr:.4f} on AR(1) rho=0.3 — expected > 1.05"


# ══════════════════════════════════════════════════════════════════════
# Look-ahead defense (2 tests — critical, D024)
# ══════════════════════════════════════════════════════════════════════


class TestLookAheadDefense:
    """Characterize that outputs never use future data."""

    def test_hurst_at_t_uses_only_data_before_t(self) -> None:
        """Two DataFrames identical before t, different after, must
        produce identical Hurst at t.

        Parallel to HAR-RV test_forecast_at_t_uses_only_data_before_t.
        """
        df_a = _make_daily_bars(120, seed=42)
        df_b = _make_daily_bars(120, seed=42)

        # Diverge from row 72 onward (day index >= 71).
        closes_b = df_b["close"].to_list()
        rng = np.random.default_rng(99)
        for i in range(72, 120):
            closes_b[i] = closes_b[i] * (1 + 0.1 * rng.standard_normal())
        df_b = df_b.with_columns(pl.Series("close", closes_b))

        calc = RoughVolCalculator(warm_up_days=60)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        # Hurst at rows 61..71 (day indices 60..70) must be identical.
        for row in range(61, 72):
            ha = result_a["rough_hurst"][row]
            hb = result_b["rough_hurst"][row]
            if np.isnan(ha) and np.isnan(hb):
                continue
            assert ha == pytest.approx(hb, rel=1e-12), (
                f"Hurst at row {row} differs: {ha} vs {hb} — look-ahead detected!"
            )

    def test_different_future_same_past_yields_same_vr_signal(self) -> None:
        """Extension: variance_ratio and vr_signal depend only on past."""
        df_a = _make_daily_bars(120, seed=42)
        df_b = _make_daily_bars(120, seed=42)

        closes_b = df_b["close"].to_list()
        rng = np.random.default_rng(99)
        for i in range(72, 120):
            closes_b[i] = closes_b[i] * (1 + 0.1 * rng.standard_normal())
        df_b = df_b.with_columns(pl.Series("close", closes_b))

        calc = RoughVolCalculator(warm_up_days=60)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        for col in ["variance_ratio", "vr_signal"]:
            for row in range(61, 72):
                va = result_a[col][row]
                vb = result_b[col][row]
                if va is None and vb is None:
                    continue
                if isinstance(va, float) and isinstance(vb, float):
                    if np.isnan(va) and np.isnan(vb):
                        continue
                assert va == pytest.approx(vb, rel=1e-12), (
                    f"{col} at row {row} differs: {va} vs {vb}"
                )


# ══════════════════════════════════════════════════════════════════════
# D028 compliance (2 tests — forecast-like broadcast)
# ══════════════════════════════════════════════════════════════════════


class TestD028Compliance:
    """Verify D028: all 6 columns are forecast-like and broadcast in 5m mode.

    Unlike HAR-RV where residual/signal are realization columns (day-close
    only per D027), Rough Vol uses daily_rv[:t] (prior days only, excluding
    current day t). All 6 columns are therefore forecast-like and safe to
    broadcast to all intraday bars of day t (D028).
    """

    def test_5m_mode_outputs_broadcast_after_warmup(self) -> None:
        """In 5m mode, all 6 columns are broadcast to all intraday bars.

        Verifies:
        - All bars of a post-warm-up day have non-NaN values.
        - All bars within the same day have identical values (broadcast).
        """
        n_days = 80
        bars_per_day = 12
        calc = RoughVolCalculator(bar_frequency="5m", warm_up_days=30)
        df = _make_5m_bars(n_days=n_days, bars_per_day=bars_per_day)
        result = calc.compute(df)

        timestamps = result["timestamp"].to_list()
        dates = [str(t)[:10] for t in timestamps]

        unique_dates: list[str] = []
        seen: set[str] = set()
        for d in dates:
            if d not in seen:
                unique_dates.append(d)
                seen.add(d)

        # Check post-warm-up days: all bars should have same non-NaN value.
        post_warmup_dates = unique_dates[35:]  # well past warm-up
        assert len(post_warmup_dates) >= 2

        for date_str in post_warmup_dates[:5]:  # spot-check 5 days
            day_mask = [d == date_str for d in dates]
            day_df = result.filter(pl.Series(day_mask))

            for col in calc.output_columns():
                day_vals = day_df[col].to_numpy()
                non_nan = day_vals[~np.isnan(day_vals)]
                # All bars of the day should have values (broadcast).
                assert len(non_nan) == len(day_vals), (
                    f"Date {date_str}, col {col}: "
                    f"{len(non_nan)}/{len(day_vals)} non-NaN (expected all)"
                )
                # All bars within the day have the same value.
                assert np.all(non_nan == non_nan[0]), (
                    f"Date {date_str}, col {col}: intraday values differ (expected broadcast)"
                )

    def test_rough_hurst_depends_only_on_prior_days(self) -> None:
        """Two 5m DataFrames with different intraday bars on day t but
        identical prior days must produce identical rough_hurst on day t.

        This characterizes the forecast-like semantics: daily_rv[:t]
        does not include day t's data, so intraday differences on day t
        are invisible to the output.
        """
        n_days = 50
        bars_per_day = 12
        calc = RoughVolCalculator(bar_frequency="5m", warm_up_days=30)

        df_a = _make_5m_bars(n_days=n_days, bars_per_day=bars_per_day, seed=42)
        df_b = _make_5m_bars(n_days=n_days, bars_per_day=bars_per_day, seed=42)

        # Modify intraday closes on the last 5 days only.
        diverge_day = n_days - 5
        diverge_row = diverge_day * bars_per_day
        closes_b = df_b["close"].to_list()
        rng = np.random.default_rng(99)
        for i in range(diverge_row, len(closes_b)):
            closes_b[i] = closes_b[i] * (1 + 0.05 * rng.standard_normal())
        df_b = df_b.with_columns(pl.Series("close", closes_b))

        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        # Check all 6 columns on a day BEFORE divergence.
        check_day = diverge_day - 1  # last identical day
        check_start = check_day * bars_per_day
        for col in calc.output_columns():
            va = result_a[col][check_start]
            vb = result_b[col][check_start]
            if isinstance(va, float) and isinstance(vb, float):
                if np.isnan(va) and np.isnan(vb):
                    continue
            assert va == pytest.approx(vb, rel=1e-12), (
                f"{col} on day {check_day} differs: {va} vs {vb} — "
                f"intraday data from later days leaked!"
            )


# ══════════════════════════════════════════════════════════════════════
# Edge cases (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: insufficient data, missing columns, unsorted timestamps."""

    def test_insufficient_data_returns_nan(self) -> None:
        """Series shorter than warm_up_days → all NaN output."""
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(30)
        result = calc.compute(df)

        for col in calc.output_columns():
            vals = result[col].to_numpy()
            assert np.all(np.isnan(vals)), f"Expected all NaN in {col}"

    def test_missing_required_column_raises(self) -> None:
        """DataFrame without 'close' → ValueError."""
        calc = RoughVolCalculator()
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "volume": [1000.0],
            }
        )
        with pytest.raises(ValueError, match="missing required columns"):
            calc.compute(df)

    def test_unsorted_timestamps_raise(self) -> None:
        """Unsorted timestamps must raise ValueError for look-ahead safety."""
        calc = RoughVolCalculator()
        df = _make_daily_bars(50)
        df_unsorted = df.sort("timestamp", descending=True)
        with pytest.raises(ValueError, match="ascending-sorted"):
            calc.compute(df_unsorted)


# ══════════════════════════════════════════════════════════════════════
# Integration (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end tests through the ValidationPipeline."""

    def test_rough_vol_through_validation_pipeline(self) -> None:
        """Run RoughVolCalculator through ValidationPipeline with ICStage."""
        from features.ic.measurer import SpearmanICMeasurer
        from features.validation.stages import ICStage, StageContext

        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(200)
        result_df = calc.compute(df)

        signals = result_df["vr_signal"].to_numpy()
        closes = result_df["close"].to_numpy().astype(np.float64)
        fwd_returns = np.full(len(closes), np.nan)
        fwd_returns[:-1] = np.log(closes[1:] / closes[:-1])

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

    def test_rough_vol_signal_has_measurable_ic_on_synthetic_predictive_data(
        self,
    ) -> None:
        """Build synthetic data where vr_signal predicts forward returns.

        Inject correlation: forward_return = alpha * vr_signal + noise.
        Verify measured IC > 0.1.
        """
        calc = RoughVolCalculator(warm_up_days=60)
        df = _make_daily_bars(300, seed=7)
        result_df = calc.compute(df)

        signals = result_df["vr_signal"].to_numpy()
        closes = result_df["close"].to_numpy().astype(np.float64)

        fwd_raw = np.full(len(closes), np.nan)
        fwd_raw[:-1] = np.log(closes[1:] / closes[:-1])

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
            feature_name="vr_signal",
            horizon_bars=1,
        )
        assert abs(ic_result.ic) > 0.1, (
            f"IC = {ic_result.ic:.4f} — expected > 0.1 on predictive data"
        )


# ══════════════════════════════════════════════════════════════════════
# Report (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestReport:
    """Verify RoughVolValidationReport schema stability."""

    def test_report_summary_schema_stable_on_empty(self) -> None:
        """summary() returns all 4 keys even with empty ic_results."""
        from features.validation.rough_vol_report import RoughVolValidationReport

        report = RoughVolValidationReport(ic_results=())
        summary = report.summary()
        assert set(summary.keys()) == {
            "n_results",
            "mean_ic",
            "mean_ic_ir",
            "any_significant",
        }
        assert summary["any_significant"] is False

    def test_report_to_markdown_renders_none_significance_as_na(self) -> None:
        """is_significant=None renders as 'n/a', not 'no'."""
        from features.ic.base import ICResult
        from features.validation.rough_vol_report import RoughVolValidationReport

        result = ICResult(
            ic=0.03,
            ic_ir=0.6,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="rough_vol",
            is_significant=None,
        )
        report = RoughVolValidationReport(ic_results=(result,))
        md = report.to_markdown()
        assert "n/a" in md
        lines = [ln for ln in md.split("\n") if "rough_vol" in ln and "+0.0300" in ln]
        assert len(lines) == 1
        assert "| no |" not in lines[0]
        assert "| n/a |" in lines[0]


# ══════════════════════════════════════════════════════════════════════
# Additional (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestAdditional:
    """Additional coverage."""

    def test_version_string(self) -> None:
        calc = RoughVolCalculator()
        assert calc.version == "1.0.0"
