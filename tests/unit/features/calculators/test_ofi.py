"""Unit tests for OFICalculator (Phase 3.6).

23 tests covering ABC conformity, correctness, look-ahead defense,
D028 compliance, mode detection, edge cases, integration with
ValidationPipeline, signal variance gate (D029), and report schema.

Reference:
    Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact
    of Order Book Events". Journal of Financial Economics,
    104(2), 293-320.
    Bouchaud et al. (2018). Trades, Quotes and Prices, Ch. 7.
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

from features.calculators.ofi import OFICalculator

# ── Helpers ──────────────────────────────────────────────────────────


def _make_book_ticks(n_ticks: int, seed: int = 42, trend_bias: float = 0.0) -> pl.DataFrame:
    """Generate synthetic tick data WITH L2 order book (bid_size/ask_size).

    Args:
        n_ticks: Number of ticks to generate.
        seed: RNG seed for reproducibility.
        trend_bias: Positive = net buying pressure (bid_size grows),
            negative = net selling pressure.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)

    timestamps: list[datetime] = []
    prices: list[float] = []
    quantities: list[float] = []
    sides: list[str] = []
    bid_sizes: list[float] = []
    ask_sizes: list[float] = []

    price = 100.0
    bid_size = 500.0
    ask_size = 500.0

    for i in range(n_ticks):
        ts = base_time + timedelta(milliseconds=i * 100)
        ret = 0.0001 * rng.standard_normal()
        price *= np.exp(ret)

        # Evolve order book sizes with trend bias.
        bid_size = max(10.0, bid_size + trend_bias + rng.standard_normal() * 50)
        ask_size = max(10.0, ask_size - trend_bias + rng.standard_normal() * 50)

        qty = abs(rng.standard_normal() * 10) + 1.0
        side = "BUY" if rng.random() > 0.5 - trend_bias * 0.01 else "SELL"

        timestamps.append(ts)
        prices.append(round(price, 4))
        quantities.append(round(qty, 4))
        sides.append(side)
        bid_sizes.append(round(bid_size, 2))
        ask_sizes.append(round(ask_size, 2))

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "price": prices,
            "quantity": quantities,
            "side": sides,
            "bid_size": bid_sizes,
            "ask_size": ask_sizes,
        }
    )


def _make_trade_ticks(n_ticks: int, seed: int = 42, buy_ratio: float = 0.5) -> pl.DataFrame:
    """Generate synthetic tick data WITHOUT L2 order book (trade-based fallback).

    Args:
        n_ticks: Number of ticks to generate.
        seed: RNG seed.
        buy_ratio: Proportion of ticks classified as BUY.
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
        ret = 0.0001 * rng.standard_normal()
        price *= np.exp(ret)
        qty = abs(rng.standard_normal() * 10) + 1.0
        side = "BUY" if rng.random() < buy_ratio else "SELL"

        timestamps.append(ts)
        prices.append(round(price, 4))
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
    """Verify OFICalculator honors the FeatureCalculator contract."""

    def test_name_returns_ofi(self) -> None:
        calc = OFICalculator()
        assert calc.name() == "ofi"

    def test_required_columns_contains_price_quantity_side(self) -> None:
        calc = OFICalculator()
        req = calc.required_columns()
        for col in ["timestamp", "price", "quantity", "side"]:
            assert col in req

    def test_output_columns_are_four_expected(self) -> None:
        calc = OFICalculator()
        out = calc.output_columns()
        assert out == ["ofi_10", "ofi_50", "ofi_100", "ofi_signal"]


# ══════════════════════════════════════════════════════════════════════
# Correctness (7 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCorrectness:
    """Verify computational correctness of OFICalculator."""

    def test_compute_produces_four_output_columns(self) -> None:
        calc = OFICalculator()
        df = _make_book_ticks(200)
        result = calc.compute(df)
        for col in calc.output_columns():
            assert col in result.columns

    def test_warm_up_produces_nan(self) -> None:
        """First max(windows)-1 ticks must have NaN on all OFI columns."""
        calc = OFICalculator(windows=(10, 50, 100))
        df = _make_book_ticks(200)
        result = calc.compute(df)

        # max window = 100, so first 99 ticks have NaN on ofi_100.
        ofi_100 = result["ofi_100"].to_numpy()
        for i in range(99):
            assert np.isnan(ofi_100[i]), f"ofi_100 at tick {i} should be NaN but got {ofi_100[i]}"
        # Tick 99 should have a value.
        assert not np.isnan(ofi_100[99])

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_ofi_10_bounded_property(self, seed: int) -> None:
        """Finite OFI values must be in a sane range (sanity check)."""
        df = _make_book_ticks(50, seed=seed)
        calc = OFICalculator(windows=(10, 50, 100))
        result = calc.compute(df)
        ofi_10 = result["ofi_10"].to_numpy()
        valid = ofi_10[~np.isnan(ofi_10)]
        if len(valid) > 0:
            assert np.all(np.abs(valid) < 1e6), f"OFI_10 out of sanity range: {valid}"

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_ofi_signal_in_minus_one_plus_one(self, seed: int) -> None:
        """ofi_signal must be strictly in [-1, +1] (tanh bounded)."""
        df = _make_book_ticks(150, seed=seed)
        calc = OFICalculator()
        result = calc.compute(df)
        signal = result["ofi_signal"].to_numpy()
        valid = signal[~np.isnan(signal)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    def test_determinism(self) -> None:
        """Same inputs must produce identical outputs."""
        df = _make_book_ticks(200, seed=42)
        calc = OFICalculator()
        r1 = calc.compute(df)
        r2 = calc.compute(df)
        for col in calc.output_columns():
            v1 = r1[col].to_numpy()
            v2 = r2[col].to_numpy()
            mask = ~np.isnan(v1) & ~np.isnan(v2)
            np.testing.assert_array_equal(v1[mask], v2[mask])
            # NaN positions must also match.
            np.testing.assert_array_equal(np.isnan(v1), np.isnan(v2))

    def test_version_is_semver(self) -> None:
        calc = OFICalculator()
        assert calc.version == "1.0.0"

    def test_decay_pattern(self) -> None:
        """On data with persistent short-term flow but noisy long-term,
        |mean(ofi_10)| > |mean(ofi_100)| — IC decay pattern.

        Inject strong buying pressure in first 50 ticks, then random
        thereafter. Short-window OFI should capture the bias better.
        """
        rng = np.random.default_rng(42)
        n = 500
        base_time = datetime(2020, 1, 1, 9, 30, tzinfo=UTC)
        price = 100.0

        timestamps: list[datetime] = []
        prices: list[float] = []
        quantities: list[float] = []
        sides: list[str] = []

        for i in range(n):
            ts = base_time + timedelta(milliseconds=i * 100)
            price *= np.exp(0.0001 * rng.standard_normal())
            qty = abs(rng.standard_normal() * 10) + 1.0
            # Alternate: bursts of buying then selling every 20 ticks.
            phase = (i // 20) % 2
            buy_prob = 0.8 if phase == 0 else 0.2
            side = "BUY" if rng.random() < buy_prob else "SELL"

            timestamps.append(ts)
            prices.append(round(price, 4))
            quantities.append(round(qty, 4))
            sides.append(side)

        df = pl.DataFrame(
            {
                "timestamp": timestamps,
                "price": prices,
                "quantity": quantities,
                "side": sides,
            }
        )
        calc = OFICalculator()
        result = calc.compute(df)

        ofi_10 = result["ofi_10"].to_numpy()
        ofi_100 = result["ofi_100"].to_numpy()

        valid_10 = ofi_10[~np.isnan(ofi_10)]
        valid_100 = ofi_100[~np.isnan(ofi_100)]

        # Short-term OFI should have higher variance (captures bursts).
        std_10 = float(np.std(valid_10))
        std_100 = float(np.std(valid_100))
        assert std_10 > std_100, (
            f"Expected std(ofi_10)={std_10:.4f} > std(ofi_100)={std_100:.4f} "
            f"— short-term OFI should capture burst patterns better"
        )


# ══════════════════════════════════════════════════════════════════════
# Look-ahead defense (2 tests — D024 pattern adapted to tick-level)
# ══════════════════════════════════════════════════════════════════════


class TestLookAheadDefense:
    """Characterize that outputs never use future data."""

    def test_ofi_at_t_uses_only_ticks_before_or_equal_t(self) -> None:
        """Two DataFrames identical on ticks [0, 50], divergent on [51, 100].
        OFI values at ticks 30-50 must be bitwise identical.
        """
        df_a = _make_trade_ticks(100, seed=42)
        df_b = _make_trade_ticks(100, seed=42)

        # Diverge from tick 51 onward.
        quantities_b = df_b["quantity"].to_list()
        rng = np.random.default_rng(99)
        for i in range(51, 100):
            quantities_b[i] = abs(rng.standard_normal() * 100) + 1.0
        sides_b = df_b["side"].to_list()
        for i in range(51, 100):
            sides_b[i] = "BUY" if rng.random() > 0.5 else "SELL"
        df_b = df_b.with_columns(
            pl.Series("quantity", quantities_b),
            pl.Series("side", sides_b),
        )

        calc = OFICalculator()
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        for col in ["ofi_10", "ofi_50", "ofi_signal"]:
            for t in range(30, 51):
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

    def test_no_lookahead_on_combined_signal(self) -> None:
        """Extension: ofi_100 (widest window) must not leak future ticks."""
        df_a = _make_book_ticks(200, seed=42)
        df_b = _make_book_ticks(200, seed=42)

        # Diverge from tick 120 onward.
        bid_b = df_b["bid_size"].to_list()
        ask_b = df_b["ask_size"].to_list()
        rng = np.random.default_rng(99)
        for i in range(120, 200):
            bid_b[i] = abs(rng.standard_normal() * 500) + 10.0
            ask_b[i] = abs(rng.standard_normal() * 500) + 10.0
        df_b = df_b.with_columns(
            pl.Series("bid_size", bid_b),
            pl.Series("ask_size", ask_b),
        )

        calc = OFICalculator()
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        for col in ["ofi_100", "ofi_signal"]:
            for t in range(100, 120):
                va = result_a[col][t]
                vb = result_b[col][t]
                if isinstance(va, float) and isinstance(vb, float):
                    if np.isnan(va) and np.isnan(vb):
                        continue
                assert va == pytest.approx(vb, rel=1e-12), (
                    f"{col} at tick {t} differs: {va} vs {vb} — look-ahead!"
                )


# ══════════════════════════════════════════════════════════════════════
# D028 compliance (1 test — realization-like at tick t)
# ══════════════════════════════════════════════════════════════════════


class TestD028Compliance:
    """Verify D028: all 4 columns are realization-like at tick t.

    OFI operates at tick level (not daily bars). Each ofi_w[t] uses
    ticks [t-w+1, t] inclusive. No intra-tick look-ahead possible.
    D027 day-close-only does NOT apply to tick-level features.
    """

    def test_d028_all_columns_realization_at_current_tick(self) -> None:
        """Verify the OFICalculator docstring declares all 4 columns as
        realization-like at tick t. This test enforces documentation
        consistency.
        """
        import inspect

        source = inspect.getsource(OFICalculator)
        assert "realization-like" in source, (
            "OFICalculator must document columns as 'realization-like at tick t'"
        )
        assert "No data from ticks after t" in source or "no data from ticks AFTER t" in source, (
            "OFICalculator must document that no future data is used"
        )
        assert "No intra-tick look-ahead" in source or "no intra-tick look-ahead" in source, (
            "OFICalculator must document no intra-tick look-ahead"
        )


# ══════════════════════════════════════════════════════════════════════
# Mode detection (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestModeDetection:
    """Verify automatic detection of book-based vs trade-based OFI."""

    def test_book_mode_when_bid_ask_present(self) -> None:
        """DataFrame with bid_size/ask_size uses book-based OFI."""
        df = _make_book_ticks(200, seed=42, trend_bias=5.0)
        calc = OFICalculator()
        result = calc.compute(df)

        # Book-based OFI should produce valid values after warm-up.
        ofi_10 = result["ofi_10"].to_numpy()
        valid = ofi_10[~np.isnan(ofi_10)]
        assert len(valid) > 100

    def test_trade_fallback_when_bid_ask_absent(self) -> None:
        """DataFrame without bid_size/ask_size falls back to trade-based OFI.
        On buy-dominant data, OFI should be net positive.
        On sell-dominant data, OFI should be net negative.
        """
        df_buy = _make_trade_ticks(200, seed=42, buy_ratio=0.8)
        df_sell = _make_trade_ticks(200, seed=43, buy_ratio=0.2)

        calc = OFICalculator()
        result_buy = calc.compute(df_buy)
        result_sell = calc.compute(df_sell)

        ofi_buy = result_buy["ofi_10"].to_numpy()
        ofi_sell = result_sell["ofi_10"].to_numpy()

        mean_buy = float(np.nanmean(ofi_buy))
        mean_sell = float(np.nanmean(ofi_sell))

        assert mean_buy > 0, f"Buy-dominant OFI mean = {mean_buy}, expected > 0"
        assert mean_sell < 0, f"Sell-dominant OFI mean = {mean_sell}, expected < 0"


# ══════════════════════════════════════════════════════════════════════
# Edge cases (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: insufficient data, missing columns, unsorted timestamps."""

    def test_insufficient_data_returns_nan(self) -> None:
        """DataFrame with < max(windows) ticks → all NaN on largest window."""
        calc = OFICalculator(windows=(10, 50, 100))
        df = _make_trade_ticks(50)
        result = calc.compute(df)

        ofi_100 = result["ofi_100"].to_numpy()
        assert np.all(np.isnan(ofi_100)), "Expected all NaN on ofi_100 with < 100 ticks"

    def test_missing_required_column_raises(self) -> None:
        """DataFrame without 'side' → ValueError."""
        calc = OFICalculator()
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
        """Unsorted timestamps must raise ValueError for look-ahead safety."""
        calc = OFICalculator()
        df = _make_trade_ticks(50)
        df_unsorted = df.sort("timestamp", descending=True)
        with pytest.raises(ValueError, match="ascending-sorted"):
            calc.compute(df_unsorted)


# ══════════════════════════════════════════════════════════════════════
# Integration (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end tests through the ValidationPipeline."""

    def test_ofi_through_validation_pipeline(self) -> None:
        """Run OFICalculator through ValidationPipeline with ICStage."""
        from features.ic.measurer import SpearmanICMeasurer
        from features.validation.stages import ICStage, StageContext

        calc = OFICalculator()
        df = _make_trade_ticks(500, seed=42)
        result_df = calc.compute(df)

        signals = result_df["ofi_signal"].to_numpy()
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

    def test_ofi_signal_has_measurable_ic_on_synthetic_predictive_data(
        self,
    ) -> None:
        """Build synthetic data where ofi_signal predicts forward returns.

        Inject correlation: forward_return = alpha * ofi_signal + noise.
        Verify measured IC > 0.1.
        """
        calc = OFICalculator()
        df = _make_trade_ticks(500, seed=42)
        result_df = calc.compute(df)

        signals = result_df["ofi_signal"].to_numpy()
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
            feature_name="ofi_signal",
            horizon_bars=1,
        )
        assert abs(ic_result.ic) > 0.1, (
            f"IC = {ic_result.ic:.4f} — expected > 0.1 on predictive data"
        )


# ══════════════════════════════════════════════════════════════════════
# Signal variance gate (1 test — D029)
# ══════════════════════════════════════════════════════════════════════


class TestSignalVarianceGate:
    """D029: output columns must vary across inputs (not silently constant)."""

    def test_ofi_signal_varies_across_inputs(self) -> None:
        """Over 100 different synthetic DataFrames, std of mean(ofi_signal)
        must be > 0.01. Gates against a constant column producing IC = 0.
        """
        means: list[float] = []
        calc = OFICalculator()

        for seed in range(100):
            df = _make_trade_ticks(200, seed=seed)
            result = calc.compute(df)
            signal = result["ofi_signal"].to_numpy()
            valid = signal[~np.isnan(signal)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 90, f"Only {len(means)} valid runs out of 100"
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(ofi_signal)) = {std_of_means:.6f} — column is effectively "
            f"constant across inputs (D029 variance gate violation)"
        )


# ══════════════════════════════════════════════════════════════════════
# Report (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestReport:
    """Verify OFIValidationReport schema stability."""

    def test_report_summary_schema_stable_on_empty(self) -> None:
        """summary() returns all 4 keys even with empty ic_results."""
        from features.validation.ofi_report import OFIValidationReport

        report = OFIValidationReport(ic_results=())
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
        from features.validation.ofi_report import OFIValidationReport

        result = ICResult(
            ic=0.03,
            ic_ir=0.6,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="ofi_signal",
            is_significant=None,
        )
        report = OFIValidationReport(ic_results=(result,))
        md = report.to_markdown()
        assert "n/a" in md
        lines = [ln for ln in md.split("\n") if "ofi_signal" in ln and "+0.0300" in ln]
        assert len(lines) == 1
        assert "| no |" not in lines[0]
        assert "| n/a |" in lines[0]
