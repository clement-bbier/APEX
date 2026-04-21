"""Unit tests for HARRVCalculator (Phase 3.4).

24 tests covering ABC conformity, correctness, look-ahead defense,
edge cases, integration with ValidationPipeline, and performance.

Reference:
    Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
    Volatility". Journal of Financial Econometrics, 7(2), 174-196.
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

from features.calculators.har_rv import HARRVCalculator
from services.quant_analytics.realized_vol import RealizedVolEstimator

# ── Helpers ──────────────────────────────────────────────────────────


def _make_daily_bars(n_days: int, seed: int = 42) -> pl.DataFrame:
    """Generate *n_days* synthetic daily OHLCV bars (GBM + jumps).

    Uses a geometric Brownian motion with occasional jumps to produce
    realistic-looking daily bars for HAR-RV testing.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, tzinfo=UTC)
    price = 100.0
    mu = 0.0005  # daily drift
    sigma = 0.02  # daily vol

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for i in range(n_days):
        ts = base_time + timedelta(days=i)
        # GBM step + occasional jump
        ret = mu + sigma * rng.standard_normal()
        if rng.random() < 0.05:  # 5% jump probability
            ret += rng.choice([-1, 1]) * sigma * 3
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
    base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)  # market open
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


# ══════════════════════════════════════════════════════════════════════
# ABC conformity (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestABCConformity:
    """Verify HARRVCalculator honors the FeatureCalculator contract."""

    def test_name_returns_har_rv(self) -> None:
        calc = HARRVCalculator()
        assert calc.name() == "har_rv"

    def test_required_columns_contains_timestamp_and_close(self) -> None:
        calc = HARRVCalculator()
        req = calc.required_columns()
        assert "timestamp" in req
        assert "close" in req
        assert "open" in req
        assert "high" in req
        assert "low" in req
        assert "volume" in req

    def test_output_columns_are_forecast_residual_signal(self) -> None:
        calc = HARRVCalculator()
        out = calc.output_columns()
        assert out == ["har_rv_forecast", "har_rv_residual", "har_rv_signal"]


# ══════════════════════════════════════════════════════════════════════
# Correctness (6 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCorrectness:
    """Verify computational correctness of HARRVCalculator."""

    def test_compute_produces_three_output_columns(self) -> None:
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(100)
        result = calc.compute(df)
        for col in ["har_rv_forecast", "har_rv_residual", "har_rv_signal"]:
            assert col in result.columns

    @given(
        rv_values=st.lists(
            st.floats(min_value=1e-8, max_value=0.1, allow_nan=False),
            min_size=50,
            max_size=100,
        )
    )
    @settings(
        max_examples=100 if os.environ.get("CI") else 1000,
        deadline=None,
    )
    def test_forecast_non_negative(self, rv_values: list[float]) -> None:
        """HAR-RV forecast of realized variance must be >= 0."""
        estimator = RealizedVolEstimator()
        forecast = estimator.har_rv_forecast(rv_values)
        assert forecast.forecast_rv >= 0.0

    @given(
        seed=st.integers(min_value=0, max_value=10000),
    )
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_signal_bounded_in_minus_one_plus_one(self, seed: int) -> None:
        """Signal must be strictly in [-1, +1] for any input."""
        rng = np.random.default_rng(seed)
        n = 60  # Reduced from 80 — still above warm_up + margin
        # Build a minimal daily bars DataFrame.
        base_time = datetime(2020, 1, 1, tzinfo=UTC)
        price = 100.0
        timestamps: list[datetime] = []
        closes: list[float] = []
        for i in range(n):
            timestamps.append(base_time + timedelta(days=i))
            ret = 0.02 * rng.standard_normal()
            price = price * np.exp(ret)
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
        calc = HARRVCalculator(warm_up_periods=30)
        result = calc.compute(df)
        signals = result["har_rv_signal"].to_numpy()
        valid = signals[~np.isnan(signals)]
        assert np.all(valid >= -1.0)
        assert np.all(valid <= 1.0)

    def test_warm_up_produces_nan(self) -> None:
        """The first warm_up + 1 rows must have NaN forecast (1d mode)."""
        warm_up = 30
        calc = HARRVCalculator(warm_up_periods=warm_up)
        df = _make_daily_bars(100)
        result = calc.compute(df)

        forecasts = result["har_rv_forecast"].to_list()
        # Row 0 has no RV (no prior close) → NaN.
        # Rows 1..warm_up map to day indices 0..warm_up-1 → NaN.
        # First non-NaN at row warm_up + 1 (day index warm_up).
        for i in range(warm_up + 1):
            assert forecasts[i] is None or (
                isinstance(forecasts[i], float) and np.isnan(forecasts[i])
            ), f"Row {i} should be NaN but got {forecasts[i]}"

    def test_parity_with_s07_har_rv_forecast(self) -> None:
        """Calculator forecast at day t must equal S07 har_rv_forecast on rv[:t]."""
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(60)
        result = calc.compute(df)

        # Build the same daily RV series the calculator builds.
        closes = df["close"].to_numpy().astype(np.float64)
        log_returns = np.log(closes[1:] / closes[:-1])
        daily_rv = log_returns**2

        # Check forecast at day index 50 (row 51).
        t = 50
        estimator = RealizedVolEstimator()
        expected = estimator.har_rv_forecast(daily_rv[:t].tolist())

        actual_forecast = result["har_rv_forecast"][t + 1]
        assert actual_forecast == pytest.approx(expected.forecast_rv, rel=1e-10)

    def test_deterministic_same_input_same_output(self) -> None:
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(80)
        r1 = calc.compute(df)
        r2 = calc.compute(df)

        for col in calc.output_columns():
            a1 = r1[col].to_numpy()
            a2 = r2[col].to_numpy()
            mask = ~(np.isnan(a1) & np.isnan(a2))
            np.testing.assert_array_equal(a1[mask], a2[mask])


# ══════════════════════════════════════════════════════════════════════
# Look-ahead defense (2 tests — critical)
# ══════════════════════════════════════════════════════════════════════


class TestLookAheadDefense:
    """Characterize that forecasts never use future data."""

    def test_forecast_at_t_uses_only_data_before_t(self) -> None:
        """Two DataFrames identical before t, different after, must
        produce identical forecasts at t.

        This is THE test that characterizes expanding-window correctness.
        """
        # Build two series: identical up to day 50, then diverge.
        df_a = _make_daily_bars(80, seed=42)
        df_b = _make_daily_bars(80, seed=42)

        # Modify closes from row 52 onward in df_b (day index >= 51).
        closes_b = df_b["close"].to_list()
        rng = np.random.default_rng(99)
        for i in range(52, 80):
            closes_b[i] = closes_b[i] * (1 + 0.1 * rng.standard_normal())
        df_b = df_b.with_columns(pl.Series("close", closes_b))

        calc = HARRVCalculator(warm_up_periods=30)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        # Forecast at rows 31..51 (day indices 30..50) must be identical.
        for row in range(31, 52):
            fa = result_a["har_rv_forecast"][row]
            fb = result_b["har_rv_forecast"][row]
            assert fa == pytest.approx(fb, rel=1e-12), (
                f"Forecast at row {row} differs: {fa} vs {fb} — look-ahead detected!"
            )

    def test_different_future_same_past_yields_same_signal(self) -> None:
        """Extension: residual and signal also depend only on past data."""
        df_a = _make_daily_bars(80, seed=42)
        df_b = _make_daily_bars(80, seed=42)

        closes_b = df_b["close"].to_list()
        rng = np.random.default_rng(99)
        for i in range(52, 80):
            closes_b[i] = closes_b[i] * (1 + 0.1 * rng.standard_normal())
        df_b = df_b.with_columns(pl.Series("close", closes_b))

        calc = HARRVCalculator(warm_up_periods=30)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        # Residual and signal at rows up to 51 must be identical.
        for col in ["har_rv_residual", "har_rv_signal"]:
            for row in range(31, 52):
                va = result_a[col][row]
                vb = result_b[col][row]
                if va is None and vb is None:
                    continue
                if np.isnan(va) and np.isnan(vb):
                    continue
                assert va == pytest.approx(vb, rel=1e-12), (
                    f"{col} at row {row} differs: {va} vs {vb}"
                )


# ══════════════════════════════════════════════════════════════════════
# Edge cases (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: insufficient data, missing columns, saturation."""

    def test_insufficient_data_returns_nan_forecast(self) -> None:
        """DataFrame with fewer rows than warm_up → all NaN output."""
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(20)  # < 30 warm_up
        result = calc.compute(df)

        for col in calc.output_columns():
            vals = result[col].to_numpy()
            assert np.all(np.isnan(vals)), f"Expected all NaN in {col}"

    def test_missing_required_column_raises(self) -> None:
        """DataFrame without 'close' → ValueError."""
        calc = HARRVCalculator()
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

    def test_signal_no_saturation_on_normal_input(self) -> None:
        """On well-behaved inputs, mean |signal| should be < 0.7."""
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(200, seed=123)
        result = calc.compute(df)
        signals = result["har_rv_signal"].to_numpy()
        valid = signals[~np.isnan(signals)]
        assert len(valid) > 0
        mean_abs = float(np.mean(np.abs(valid)))
        assert mean_abs < 0.7, f"Mean |signal| = {mean_abs:.3f} — signal is saturating"


# ══════════════════════════════════════════════════════════════════════
# Integration (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end tests through the ValidationPipeline."""

    def test_har_rv_through_validation_pipeline(self) -> None:
        """Run HARRVCalculator through ValidationPipeline with ICStage."""
        from features.ic.measurer import SpearmanICMeasurer
        from features.validation.pipeline import ValidationPipeline
        from features.validation.stages import ICStage, StageContext

        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(150)
        result_df = calc.compute(df)

        # Extract signal and compute forward returns.
        signals = result_df["har_rv_signal"].to_numpy()
        closes = result_df["close"].to_numpy().astype(np.float64)
        fwd_returns = np.full(len(closes), np.nan)
        fwd_returns[:-1] = np.log(closes[1:] / closes[:-1])

        # Align: keep only where both signal and fwd_return are finite.
        mask = np.isfinite(signals) & np.isfinite(fwd_returns)
        feat_clean = signals[mask]
        fwd_clean = fwd_returns[mask]

        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        pipeline = ValidationPipeline(stages=[ICStage(measurer=measurer)])

        # Inject metadata for ICStage.
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

        # We got an IC result (value may be small on random data).
        assert stage_result.stage.value == "ic"
        assert "ic" in stage_result.metrics
        assert "ic_ir" in stage_result.metrics

    def test_har_rv_signal_has_measurable_ic_on_synthetic_predictive_data(
        self,
    ) -> None:
        """Build synthetic data where signal predicts forward returns.

        Inject correlation: forward_return = alpha * signal + noise.
        Verify measured IC > 0.1.
        """
        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(200, seed=7)
        result_df = calc.compute(df)

        signals = result_df["har_rv_signal"].to_numpy()
        closes = result_df["close"].to_numpy().astype(np.float64)

        # Compute raw forward returns.
        fwd_raw = np.full(len(closes), np.nan)
        fwd_raw[:-1] = np.log(closes[1:] / closes[:-1])

        # Inject correlation: replace forward returns with
        # alpha * signal + noise, to guarantee signal has IC.
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
            feature_name="har_rv_signal",
            horizon_bars=1,
        )
        assert abs(ic_result.ic) > 0.1, (
            f"IC = {ic_result.ic:.4f} — expected > 0.1 on predictive data"
        )


# ══════════════════════════════════════════════════════════════════════
# Performance sanity (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestPerformance:
    """Performance bounds for HAR-RV computation."""

    @pytest.mark.skipif(
        os.environ.get("CI_FAST_ONLY") == "1" or os.environ.get("CI", "").lower() in {"1", "true"},
        reason=(
            "Performance timing assertions skipped in CI (shared runners may "
            "be flaky). Run locally to validate."
        ),
    )
    def test_computation_under_5_seconds_on_1_year_daily(self) -> None:
        """252 daily rows must complete in < 5 seconds."""
        import time

        calc = HARRVCalculator(warm_up_periods=30)
        df = _make_daily_bars(252, seed=0)

        start = time.perf_counter()
        calc.compute(df)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"Computation took {elapsed:.2f}s — exceeds 5s budget"


# ══════════════════════════════════════════════════════════════════════
# Additional: version, 5m mode, validation report (3 bonus tests)
# ══════════════════════════════════════════════════════════════════════


class TestAdditional:
    """Additional coverage for version, 5m mode, and report."""

    def test_version_returns_v1(self) -> None:
        calc = HARRVCalculator()
        assert calc.version == "1.0.0"

    def test_5m_bars_produce_valid_output(self) -> None:
        """5m bars aggregated to daily RV produce valid output."""
        calc = HARRVCalculator(bar_frequency="5m", warm_up_periods=25)
        df = _make_5m_bars(n_days=60, bars_per_day=78)
        result = calc.compute(df)

        assert "har_rv_forecast" in result.columns
        signals = result["har_rv_signal"].to_numpy()
        valid = signals[~np.isnan(signals)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    def test_har_rv_validation_report(self) -> None:
        """HARRVValidationReport renders JSON and Markdown."""
        from features.ic.base import ICResult
        from features.validation.har_rv_report import HARRVValidationReport

        ic = ICResult(
            ic=0.03,
            ic_ir=0.55,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="har_rv",
            is_significant=True,
            horizon_bars=1,
        )
        report = HARRVValidationReport(ic_results=(ic,))

        json_str = report.to_json()
        assert "har_rv" in json_str
        assert "0.03" in json_str

        md = report.to_markdown()
        assert "HAR-RV" in md
        assert "| har_rv" in md

        s = report.summary()
        assert s["n_results"] == 1
        assert s["any_significant"] is True


# ══════════════════════════════════════════════════════════════════════
# Copilot review characterization tests (4 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCopilotFixes:
    """Tests characterizing fixes from PR #111 Copilot review."""

    def test_5m_mode_residual_nan_before_day_close(self) -> None:
        """In 5m mode, residual/signal emitted ONLY on day-close bars.

        Broadcasting to all intraday bars would leak future intraday data
        (residual depends on full-day realized_rv). Forecast is safe to
        broadcast (depends only on prior days). See D027.
        """
        n_days = 40
        bars_per_day = 12  # Simplified grid: 12 bars/day
        calc = HARRVCalculator(bar_frequency="5m", warm_up_periods=25)
        df = _make_5m_bars(n_days=n_days, bars_per_day=bars_per_day)
        result = calc.compute(df)

        # Group rows by date and check per-day invariants.
        timestamps = result["timestamp"].to_list()
        dates = [str(t)[:10] for t in timestamps]

        unique_dates: list[str] = []
        seen: set[str] = set()
        for d in dates:
            if d not in seen:
                unique_dates.append(d)
                seen.add(d)

        for date_str in unique_dates:
            day_mask = [d == date_str for d in dates]
            day_residuals = result.filter(pl.Series(day_mask))["har_rv_residual"]
            day_signals = result.filter(pl.Series(day_mask))["har_rv_signal"]
            day_forecasts = result.filter(pl.Series(day_mask))["har_rv_forecast"]

            non_null_res = day_residuals.drop_nulls().filter(~day_residuals.drop_nulls().is_nan())
            non_null_sig = day_signals.drop_nulls().filter(~day_signals.drop_nulls().is_nan())

            # At most 1 non-null residual/signal per day (the last bar).
            assert non_null_res.len() <= 1, (
                f"Date {date_str}: {non_null_res.len()} non-null residuals (expected <= 1)"
            )
            assert non_null_sig.len() <= 1, (
                f"Date {date_str}: {non_null_sig.len()} non-null signals (expected <= 1)"
            )

            # If residual is present, it should be on the LAST bar.
            if non_null_res.len() == 1:
                last_residual = day_residuals[-1]
                assert last_residual is not None, (
                    f"Date {date_str}: residual present but last bar is None"
                )
                assert not np.isnan(last_residual), (
                    f"Date {date_str}: residual present but last bar is NaN"
                )

        # Forecast should be non-NaN on post-warm-up bars (safe to broadcast).
        all_forecasts = result["har_rv_forecast"].to_numpy()
        non_nan_forecasts = all_forecasts[~np.isnan(all_forecasts)]
        assert len(non_nan_forecasts) > 0, "No forecasts produced"

    def test_unsorted_timestamps_raise(self) -> None:
        """Unsorted timestamps must raise ValueError for look-ahead safety."""
        calc = HARRVCalculator()
        df = _make_daily_bars(50)
        df_unsorted = df.sort("timestamp", descending=True)
        with pytest.raises(ValueError, match="ascending-sorted"):
            calc.compute(df_unsorted)

    def test_summary_schema_stable_on_empty(self) -> None:
        """summary() returns all 4 keys even with empty ic_results."""
        from features.validation.har_rv_report import HARRVValidationReport

        report = HARRVValidationReport(ic_results=())
        summary = report.summary()
        assert set(summary.keys()) == {
            "n_results",
            "mean_ic",
            "mean_ic_ir",
            "any_significant",
        }
        assert summary["any_significant"] is False

    def test_to_markdown_renders_none_significance_as_na(self) -> None:
        """is_significant=None renders as 'n/a', not 'no'."""
        from features.ic.base import ICResult
        from features.validation.har_rv_report import HARRVValidationReport

        result = ICResult(
            ic=0.03,
            ic_ir=0.6,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="har_rv",
            is_significant=None,
        )
        report = HARRVValidationReport(ic_results=(result,))
        md = report.to_markdown()
        assert "n/a" in md
        # Specifically not rendered as "no" for None.
        lines = [ln for ln in md.split("\n") if "har_rv" in ln and "+0.0300" in ln]
        assert len(lines) == 1
        assert "| no |" not in lines[0]
        assert "| n/a |" in lines[0]
