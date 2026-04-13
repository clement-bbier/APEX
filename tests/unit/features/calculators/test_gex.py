"""Unit tests for GEXCalculator (Phase 3.8).

33 tests covering ABC conformity, constructor validation (D030),
input validation, correctness, sign convention sanity, magnitude
sanity, look-ahead defense, D028 compliance, D029 variance gates,
edge cases, integration with ValidationPipeline, report schema,
and version.

Reference:
    Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".
    Working Paper, University of St. Gallen.
    Baltussen et al. (2019). JFQA 54(3).
    Ni, Pearson & Poteshman (2005). JFE 78(2).
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

from features.calculators.gex import GEXCalculator

# ── Helpers ──────────────────────────────────────────────────────────


def _make_option_chain(
    n_snapshots: int,
    n_options_per_snapshot: int = 20,
    seed: int = 42,
    spot_base: float = 400.0,
    spot_drift: float = 0.001,
    oi_base: float = 1000.0,
    gamma_base: float = 0.02,
) -> pl.DataFrame:
    """Generate synthetic option chain data for GEX testing.

    Produces a DataFrame with multiple rows per timestamp (one per
    active option). Strikes are spaced around the spot price.

    Args:
        n_snapshots: Number of timestamps (snapshots).
        n_options_per_snapshot: Options per snapshot (half calls,
            half puts).
        seed: RNG seed.
        spot_base: Starting spot price (SPY-like ~400).
        spot_drift: Per-snapshot drift.
        oi_base: Base open interest per option.
        gamma_base: Base gamma per option.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2020, 1, 1, 16, 0, tzinfo=UTC)
    expiry = datetime(2020, 2, 21, 16, 0, tzinfo=UTC)

    timestamps: list[datetime] = []
    spot_prices: list[float] = []
    strikes: list[float] = []
    expiries: list[datetime] = []
    option_types: list[str] = []
    open_interests: list[float] = []
    gammas: list[float] = []

    spot = spot_base
    n_half = n_options_per_snapshot // 2

    for snap_idx in range(n_snapshots):
        ts = base_time + timedelta(days=snap_idx)
        spot *= np.exp(spot_drift * rng.standard_normal())

        for opt_idx in range(n_options_per_snapshot):
            if opt_idx < n_half:
                opt_type = "call"
            else:
                opt_type = "put"

            # Strikes spread around spot.
            strike_offset = (opt_idx - n_half) * 5.0
            strike = round(spot + strike_offset, 2)

            oi = max(1.0, oi_base + rng.standard_normal() * 200.0)
            # Gamma is always positive; higher near ATM.
            distance = abs(strike - spot) / spot
            gamma = max(
                1e-6,
                gamma_base * np.exp(-5.0 * distance) + rng.random() * 0.005,
            )

            timestamps.append(ts)
            spot_prices.append(round(spot, 4))
            strikes.append(strike)
            expiries.append(expiry)
            option_types.append(opt_type)
            open_interests.append(round(oi, 2))
            gammas.append(round(gamma, 6))

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "spot_price": spot_prices,
            "strike": strikes,
            "expiry": expiries,
            "option_type": option_types,
            "open_interest": open_interests,
            "gamma": gammas,
        }
    )


def _make_calls_only_chain(
    n_snapshots: int = 5,
    seed: int = 42,
) -> pl.DataFrame:
    """Option chain with ONLY calls (all positive OI, positive gamma)."""
    return _make_option_chain(
        n_snapshots=n_snapshots,
        n_options_per_snapshot=10,
        seed=seed,
    ).filter(pl.col("option_type") == "call")


def _make_puts_only_chain(
    n_snapshots: int = 5,
    seed: int = 42,
) -> pl.DataFrame:
    """Option chain with ONLY puts (all positive OI, positive gamma)."""
    return _make_option_chain(
        n_snapshots=n_snapshots,
        n_options_per_snapshot=10,
        seed=seed,
    ).filter(pl.col("option_type") == "put")


# ══════════════════════════════════════════════════════════════════════
# ABC conformity (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestABCConformity:
    """Verify GEXCalculator honors the FeatureCalculator contract."""

    def test_name_returns_gex(self) -> None:
        calc = GEXCalculator()
        assert calc.name() == "gex"

    def test_required_columns_contains_seven_expected(self) -> None:
        calc = GEXCalculator()
        req = calc.required_columns()
        expected = [
            "timestamp",
            "spot_price",
            "strike",
            "expiry",
            "option_type",
            "open_interest",
            "gamma",
        ]
        for col in expected:
            assert col in req, f"Missing required column: {col}"
        assert len(req) == 7

    def test_output_columns_are_five_expected(self) -> None:
        calc = GEXCalculator()
        out = calc.output_columns()
        assert out == [
            "gex_raw",
            "gex_normalized",
            "gex_zscore",
            "gex_regime",
            "gex_signal",
        ]


# ══════════════════════════════════════════════════════════════════════
# Constructor validation — D030 (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestConstructorValidation:
    """D030: all configurable params validated in __init__."""

    def test_zscore_lookback_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="zscore_lookback must be >= 20"):
            GEXCalculator(zscore_lookback=10)

    def test_regime_thresholds_inverted_raises(self) -> None:
        with pytest.raises(
            ValueError,
            match="regime_lower_threshold must be < regime_upper_threshold",
        ):
            GEXCalculator(
                regime_lower_threshold=1.0,
                regime_upper_threshold=-1.0,
            )

    def test_contract_multiplier_non_positive_raises(self) -> None:
        with pytest.raises(ValueError, match="contract_multiplier must be > 0"):
            GEXCalculator(contract_multiplier=0)


# ══════════════════════════════════════════════════════════════════════
# Input validation (4 tests)
# ══════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """Verify input DataFrame is validated before computation."""

    def test_invalid_option_type_raises(self) -> None:
        """option_type='straddle' must raise ValueError."""
        calc = GEXCalculator()
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)],
                "spot_price": [400.0],
                "strike": [400.0],
                "expiry": [datetime(2020, 2, 1, tzinfo=UTC)],
                "option_type": ["straddle"],
                "open_interest": [1000.0],
                "gamma": [0.02],
            }
        )
        with pytest.raises(ValueError, match="option_type must be"):
            calc.compute(df)

    def test_inconsistent_spot_within_timestamp_raises(self) -> None:
        """spot_price must be constant within a timestamp — data quality gate."""
        calc = GEXCalculator()
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)] * 2,
                "spot_price": [400.0, 400.5],  # inconsistent!
                "strike": [400.0, 400.0],
                "expiry": [datetime(2024, 2, 1, tzinfo=UTC)] * 2,
                "option_type": ["call", "put"],
                "open_interest": [1000.0, 1000.0],
                "gamma": [0.02, 0.02],
            }
        )
        with pytest.raises(ValueError, match="spot_price must be constant"):
            calc.compute(df)

    def test_option_type_case_insensitive(self) -> None:
        """option_type accepts CALL/Call/call and PUT/Put/put."""
        calc = GEXCalculator(zscore_lookback=20)
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)] * 4,
                "spot_price": [400.0] * 4,
                "strike": [395.0, 400.0, 405.0, 410.0],
                "expiry": [datetime(2020, 2, 1, tzinfo=UTC)] * 4,
                "option_type": ["CALL", "Call", "PUT", "Put"],
                "open_interest": [1000.0] * 4,
                "gamma": [0.02] * 4,
            }
        )
        result = calc.compute(df)
        # Should not raise, should produce non-NaN gex_raw.
        assert not np.isnan(result["gex_raw"][0])

    def test_missing_required_column_raises(self) -> None:
        """DataFrame without 'gamma' must raise ValueError."""
        calc = GEXCalculator()
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)],
                "spot_price": [400.0],
                "strike": [400.0],
                "expiry": [datetime(2020, 2, 1, tzinfo=UTC)],
                "option_type": ["call"],
                "open_interest": [1000.0],
            }
        )
        with pytest.raises(ValueError, match="missing required columns"):
            calc.compute(df)


# ══════════════════════════════════════════════════════════════════════
# Correctness (7 tests)
# ══════════════════════════════════════════════════════════════════════


class TestCorrectness:
    """Verify computational correctness of GEXCalculator."""

    def test_compute_produces_five_output_columns(self) -> None:
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(50, n_options_per_snapshot=10)
        result = calc.compute(df)
        for col in calc.output_columns():
            assert col in result.columns

    def test_warm_up_produces_nan_on_zscore(self) -> None:
        """gex_zscore must be NaN at the first timestamp (no prior
        history). gex_raw/gex_normalized must NOT be NaN.
        """
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(30, n_options_per_snapshot=10)
        result = calc.compute(df)

        # Get unique timestamps and check first one.
        first_ts = result["timestamp"].unique().sort()[0]
        first_rows = result.filter(pl.col("timestamp") == first_ts)

        # gex_raw available from first timestamp (no warm-up).
        raw_vals = first_rows["gex_raw"].to_numpy()
        assert not np.any(np.isnan(raw_vals)), "gex_raw should be available from first timestamp"

        # gex_normalized also available from first timestamp.
        norm_vals = first_rows["gex_normalized"].to_numpy()
        assert not np.any(np.isnan(norm_vals)), (
            "gex_normalized should be available from first timestamp"
        )

        # gex_zscore NaN at first timestamp (no prior data).
        zscore_vals = first_rows["gex_zscore"].to_numpy()
        assert np.all(np.isnan(zscore_vals)), "gex_zscore should be NaN at the first timestamp"

    def test_gex_raw_available_from_first_timestamp(self) -> None:
        """gex_raw is a snapshot aggregation — no warm-up needed."""
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(5, n_options_per_snapshot=10)
        result = calc.compute(df)

        first_ts = result["timestamp"].unique().sort()[0]
        first_rows = result.filter(pl.col("timestamp") == first_ts)
        raw_vals = first_rows["gex_raw"].to_numpy()
        assert not np.any(np.isnan(raw_vals))

    @given(seed=st.integers(min_value=0, max_value=10000))
    @settings(
        max_examples=50 if os.environ.get("CI") else 300,
        deadline=None,
    )
    def test_gex_signal_bounded(self, seed: int) -> None:
        """gex_signal must be strictly in [-1, +1]."""
        df = _make_option_chain(30, n_options_per_snapshot=10, seed=seed)
        calc = GEXCalculator(zscore_lookback=20)
        result = calc.compute(df)
        vals = result["gex_signal"].to_numpy()
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            assert np.all(valid >= -1.0)
            assert np.all(valid <= 1.0)

    def test_gex_regime_in_minus_one_zero_plus_one(self) -> None:
        """gex_regime values must be {-1, 0, +1} or NaN."""
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(50, n_options_per_snapshot=10)
        result = calc.compute(df)
        vals = result["gex_regime"].to_numpy()
        valid = vals[~np.isnan(vals)]
        unique_valid = set(valid.tolist())
        allowed = {-1.0, 0.0, 1.0}
        assert unique_valid.issubset(allowed), (
            f"gex_regime has unexpected values: {unique_valid - allowed}"
        )

    def test_determinism(self) -> None:
        """Same inputs must produce identical outputs."""
        df = _make_option_chain(50, n_options_per_snapshot=10, seed=42)
        calc = GEXCalculator(zscore_lookback=20)
        r1 = calc.compute(df)
        r2 = calc.compute(df)
        for col in calc.output_columns():
            v1 = r1[col].to_numpy()
            v2 = r2[col].to_numpy()
            mask = ~np.isnan(v1) & ~np.isnan(v2)
            np.testing.assert_array_equal(v1[mask], v2[mask])
            np.testing.assert_array_equal(np.isnan(v1), np.isnan(v2))

    def test_version_is_semver(self) -> None:
        calc = GEXCalculator()
        assert calc.version == "1.0.0"


# ══════════════════════════════════════════════════════════════════════
# Sign convention sanity (2 tests — CRITICAL for Barbon-Buraschi)
# ══════════════════════════════════════════════════════════════════════


class TestSignConventionSanity:
    """Characterize dealer-adjusted sign convention.

    These 2 tests are THE non-negotiable characterization tests.
    Getting the sign wrong inverts the entire signal.
    """

    def test_calls_contribute_negatively(self) -> None:
        """Chain with ONLY calls (positive OI, positive gamma)
        must produce gex_raw < 0 (dealers short calls).
        """
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_calls_only_chain(n_snapshots=5)
        result = calc.compute(df)

        # Every row should have gex_raw < 0.
        raw_vals = result["gex_raw"].to_numpy()
        valid = raw_vals[~np.isnan(raw_vals)]
        assert len(valid) > 0
        assert np.all(valid < 0.0), (
            f"gex_raw for calls-only chain should be < 0, got {valid[:5]} (dealer short convention)"
        )

    def test_puts_contribute_positively(self) -> None:
        """Chain with ONLY puts (positive OI, positive gamma)
        must produce gex_raw > 0 (dealers long puts).
        """
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_puts_only_chain(n_snapshots=5)
        result = calc.compute(df)

        # Every row should have gex_raw > 0.
        raw_vals = result["gex_raw"].to_numpy()
        valid = raw_vals[~np.isnan(raw_vals)]
        assert len(valid) > 0
        assert np.all(valid > 0.0), (
            f"gex_raw for puts-only chain should be > 0, got {valid[:5]} (dealer long convention)"
        )


# ══════════════════════════════════════════════════════════════════════
# Magnitude sanity (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestMagnitudeSanity:
    """Verify GEX magnitude is in a realistic range."""

    def test_gex_magnitude_realistic(self) -> None:
        """Synthetic SPY-like chain (~500 options, OI~1000, gamma~0.01-0.05,
        S=400, mult=100) should produce |gex_raw| in [1e7, 1e12].

        Order of magnitude per option:
        sign * 1000 * 0.02 * 400^2 * 100 = sign * 320,000,000
        Sum over ~500 options with mixed signs → 1e8 to 1e11 range.
        """
        calc = GEXCalculator(zscore_lookback=20, contract_multiplier=100)
        df = _make_option_chain(
            n_snapshots=5,
            n_options_per_snapshot=500,
            seed=42,
            spot_base=400.0,
            oi_base=1000.0,
            gamma_base=0.02,
        )
        result = calc.compute(df)

        first_ts = result["timestamp"].unique().sort()[0]
        first_rows = result.filter(pl.col("timestamp") == first_ts)
        gex_raw = first_rows["gex_raw"][0]

        assert abs(gex_raw) >= 1e7, f"|gex_raw| = {abs(gex_raw):.2e} — too small, unit bug?"
        assert abs(gex_raw) <= 1e12, f"|gex_raw| = {abs(gex_raw):.2e} — too large, unit bug?"


# ══════════════════════════════════════════════════════════════════════
# Look-ahead defense (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestLookAheadDefense:
    """Characterize that forecast-like outputs never use future data."""

    def test_gex_zscore_at_t_uses_only_snapshots_before_t(self) -> None:
        """Two DataFrames identical on timestamps [0, 50], divergent
        on [51, 80]. gex_zscore at timestamps 20-50 must be bitwise
        identical.
        """
        df_a = _make_option_chain(80, n_options_per_snapshot=10, seed=42)
        df_b = _make_option_chain(80, n_options_per_snapshot=10, seed=42)

        # Diverge from snapshot 51 onward: change OI and gamma.
        unique_ts = df_b["timestamp"].unique().sort()
        diverge_ts = unique_ts[51]
        rng = np.random.default_rng(999)

        oi_list = df_b["open_interest"].to_list()
        gamma_list = df_b["gamma"].to_list()
        ts_list = df_b["timestamp"].to_list()

        for i in range(len(ts_list)):
            if ts_list[i] >= diverge_ts:
                oi_list[i] = max(1.0, abs(rng.standard_normal() * 5000.0))
                gamma_list[i] = max(1e-6, abs(rng.standard_normal() * 0.1))

        df_b = df_b.with_columns(
            pl.Series("open_interest", oi_list),
            pl.Series("gamma", gamma_list),
        )

        calc = GEXCalculator(zscore_lookback=20)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        # Compare gex_zscore at timestamps 20-50 (first row per ts).
        for idx in range(20, 51):
            ts_val = unique_ts[idx]
            rows_a = result_a.filter(pl.col("timestamp") == ts_val)
            rows_b = result_b.filter(pl.col("timestamp") == ts_val)

            va = rows_a["gex_zscore"][0]
            vb = rows_b["gex_zscore"][0]

            if isinstance(va, float) and isinstance(vb, float):
                if np.isnan(va) and np.isnan(vb):
                    continue
            assert va == pytest.approx(vb, rel=1e-12), (
                f"gex_zscore at snapshot {idx} differs: {va} vs {vb} — look-ahead detected!"
            )

    def test_different_future_same_past_yields_same_signal(self) -> None:
        """Extension to gex_signal: same past → same signal."""
        df_a = _make_option_chain(80, n_options_per_snapshot=10, seed=42)
        df_b = _make_option_chain(80, n_options_per_snapshot=10, seed=42)

        unique_ts = df_b["timestamp"].unique().sort()
        diverge_ts = unique_ts[51]
        rng = np.random.default_rng(999)

        oi_list = df_b["open_interest"].to_list()
        gamma_list = df_b["gamma"].to_list()
        ts_list = df_b["timestamp"].to_list()

        for i in range(len(ts_list)):
            if ts_list[i] >= diverge_ts:
                oi_list[i] = max(1.0, abs(rng.standard_normal() * 5000.0))
                gamma_list[i] = max(1e-6, abs(rng.standard_normal() * 0.1))

        df_b = df_b.with_columns(
            pl.Series("open_interest", oi_list),
            pl.Series("gamma", gamma_list),
        )

        calc = GEXCalculator(zscore_lookback=20)
        result_a = calc.compute(df_a)
        result_b = calc.compute(df_b)

        for idx in range(20, 51):
            ts_val = unique_ts[idx]
            rows_a = result_a.filter(pl.col("timestamp") == ts_val)
            rows_b = result_b.filter(pl.col("timestamp") == ts_val)

            va = rows_a["gex_signal"][0]
            vb = rows_b["gex_signal"][0]

            if isinstance(va, float) and isinstance(vb, float):
                if np.isnan(va) and np.isnan(vb):
                    continue
            assert va == pytest.approx(vb, rel=1e-12), (
                f"gex_signal at snapshot {idx} differs: {va} vs {vb} — look-ahead detected!"
            )


# ══════════════════════════════════════════════════════════════════════
# D028 compliance (1 test)
# ══════════════════════════════════════════════════════════════════════


class TestD028Compliance:
    """Verify D028: documentation declares correct classification."""

    def test_docstring_declares_classification(self) -> None:
        """GEXCalculator docstring must declare realization at t
        for gex_raw/gex_normalized and forecast-like for others.
        """
        import inspect

        source = inspect.getsource(GEXCalculator)
        assert "realization at t" in source.lower(), (
            "Must document gex_raw/gex_normalized as 'realization at t'"
        )
        assert "forecast-like" in source.lower(), (
            "Must document gex_zscore/gex_regime/gex_signal as 'forecast-like'"
        )


# ══════════════════════════════════════════════════════════════════════
# D029 variance gates (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestSignalVarianceGates:
    """D029: output signal columns must vary across inputs."""

    def test_gex_raw_varies_across_inputs(self) -> None:
        """Over 50 DataFrames, std of mean(gex_raw) > 0."""
        means: list[float] = []
        calc = GEXCalculator(zscore_lookback=20)
        for seed in range(50):
            df = _make_option_chain(30, n_options_per_snapshot=10, seed=seed)
            result = calc.compute(df)
            vals = result["gex_raw"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 40
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(gex_raw)) = {std_of_means:.6f} — D029 variance gate violation"
        )

    def test_gex_zscore_varies_across_inputs(self) -> None:
        """Over 50 DataFrames, std of mean(gex_zscore) > 0."""
        means: list[float] = []
        calc = GEXCalculator(zscore_lookback=20)
        for seed in range(50):
            df = _make_option_chain(30, n_options_per_snapshot=10, seed=seed)
            result = calc.compute(df)
            vals = result["gex_zscore"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 40
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(gex_zscore)) = {std_of_means:.6f} — D029 variance gate violation"
        )

    def test_gex_signal_varies_across_inputs(self) -> None:
        """Over 50 DataFrames, std of mean(gex_signal) > 0."""
        means: list[float] = []
        calc = GEXCalculator(zscore_lookback=20)
        for seed in range(50):
            df = _make_option_chain(30, n_options_per_snapshot=10, seed=seed)
            result = calc.compute(df)
            vals = result["gex_signal"].to_numpy()
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                means.append(float(np.mean(valid)))

        assert len(means) >= 40
        std_of_means = float(np.std(means))
        assert std_of_means > 0.01, (
            f"std(mean(gex_signal)) = {std_of_means:.6f} — D029 variance gate violation"
        )


# ══════════════════════════════════════════════════════════════════════
# Edge cases (3 tests)
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: single option, unsorted timestamps, empty DataFrame."""

    def test_single_timestamp_single_option(self) -> None:
        """1 row, 1 snapshot — should not crash."""
        calc = GEXCalculator(zscore_lookback=20)
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2020, 1, 1, tzinfo=UTC)],
                "spot_price": [400.0],
                "strike": [400.0],
                "expiry": [datetime(2020, 2, 1, tzinfo=UTC)],
                "option_type": ["call"],
                "open_interest": [1000.0],
                "gamma": [0.02],
            }
        )
        result = calc.compute(df)
        assert len(result) == 1
        for col in calc.output_columns():
            assert col in result.columns

        # gex_raw should be non-NaN (snapshot direct).
        assert not np.isnan(result["gex_raw"][0])
        # gex_zscore should be NaN (no prior history).
        assert np.isnan(result["gex_zscore"][0])

    def test_unsorted_timestamps_raise(self) -> None:
        """Unsorted timestamps must raise ValueError."""
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(10, n_options_per_snapshot=5)
        # Reverse the order.
        df_unsorted = df.sort("timestamp", descending=True)
        with pytest.raises(ValueError, match="non-decreasing"):
            calc.compute(df_unsorted)

    def test_empty_dataframe(self) -> None:
        """Empty DataFrame with correct columns returns empty output."""
        calc = GEXCalculator(zscore_lookback=20)
        df = pl.DataFrame(
            {
                "timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                "spot_price": pl.Series([], dtype=pl.Float64),
                "strike": pl.Series([], dtype=pl.Float64),
                "expiry": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                "option_type": pl.Series([], dtype=pl.Utf8),
                "open_interest": pl.Series([], dtype=pl.Float64),
                "gamma": pl.Series([], dtype=pl.Float64),
            }
        )
        result = calc.compute(df)
        assert len(result) == 0
        for col in calc.output_columns():
            assert col in result.columns


# ══════════════════════════════════════════════════════════════════════
# Integration (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end tests through the ValidationPipeline."""

    def test_gex_through_validation_pipeline(self) -> None:
        """Run GEXCalculator through ICStage end-to-end.

        Forward returns are computed at snapshot level (one per unique
        timestamp) — not row-level, since GEX has multiple option rows
        per timestamp (D034 pattern).
        """
        from features.ic.measurer import SpearmanICMeasurer
        from features.validation.stages import ICStage, StageContext

        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(100, n_options_per_snapshot=20, seed=42)
        result_df = calc.compute(df)

        # Aggregate to snapshot level for IC measurement.
        snapshot_df = (
            result_df.group_by("timestamp", maintain_order=True)
            .agg(
                pl.col("spot_price").first(),
                pl.col("gex_signal").first(),
            )
            .sort("timestamp")
        )
        snapshot_spot = snapshot_df["spot_price"].to_numpy().astype(np.float64)
        snapshot_signal = snapshot_df["gex_signal"].to_numpy().astype(np.float64)

        fwd_returns = np.full(len(snapshot_spot), np.nan)
        fwd_returns[:-1] = np.log(snapshot_spot[1:] / snapshot_spot[:-1])

        mask = np.isfinite(snapshot_signal) & np.isfinite(fwd_returns)
        feat_clean = snapshot_signal[mask]
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

    def test_gex_signal_has_measurable_ic_on_synthetic_predictive_data(
        self,
    ) -> None:
        """Build synthetic data where gex_signal predicts forward
        returns at snapshot level. Verify measured IC > 0.1.

        Forward returns are computed per unique timestamp (D034),
        not per option row.
        """
        calc = GEXCalculator(zscore_lookback=20)
        df = _make_option_chain(100, n_options_per_snapshot=20, seed=42)
        result_df = calc.compute(df)

        # Aggregate to snapshot level.
        snapshot_df = (
            result_df.group_by("timestamp", maintain_order=True)
            .agg(
                pl.col("spot_price").first(),
                pl.col("gex_signal").first(),
            )
            .sort("timestamp")
        )
        snapshot_spot = snapshot_df["spot_price"].to_numpy().astype(np.float64)
        snapshot_signal = snapshot_df["gex_signal"].to_numpy().astype(np.float64)

        fwd_raw = np.full(len(snapshot_spot), np.nan)
        fwd_raw[:-1] = np.log(snapshot_spot[1:] / snapshot_spot[:-1])

        rng = np.random.default_rng(42)
        mask = np.isfinite(snapshot_signal) & np.isfinite(fwd_raw)

        # Inject predictive relationship at snapshot level.
        fwd_synthetic = np.copy(fwd_raw)
        alpha = 0.3
        noise = rng.standard_normal(int(mask.sum())) * 0.01
        fwd_synthetic[mask] = alpha * snapshot_signal[mask] + noise

        feat_clean = snapshot_signal[mask]
        fwd_clean = fwd_synthetic[mask]

        from features.ic.measurer import SpearmanICMeasurer

        measurer = SpearmanICMeasurer(rolling_window=50, bootstrap_n=100)
        ic_result = measurer.measure_rich(
            feature=feat_clean,
            forward_returns=fwd_clean,
            feature_name="gex_signal",
            horizon_bars=1,
        )
        assert abs(ic_result.ic) > 0.1, (
            f"IC = {ic_result.ic:.4f} — expected > 0.1 on predictive data"
        )


# ══════════════════════════════════════════════════════════════════════
# Report (2 tests)
# ══════════════════════════════════════════════════════════════════════


class TestReport:
    """Verify GEXValidationReport schema stability."""

    def test_report_summary_schema_stable_on_empty(self) -> None:
        """summary() returns all 4 keys even with empty ic_results."""
        from features.validation.gex_report import (
            GEXValidationReport,
        )

        report = GEXValidationReport(ic_results=())
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
        from features.validation.gex_report import (
            GEXValidationReport,
        )

        result = ICResult(
            ic=0.03,
            ic_ir=0.6,
            p_value=0.04,
            n_samples=100,
            ci_low=0.01,
            ci_high=0.05,
            feature_name="gex_signal",
            is_significant=None,
        )
        report = GEXValidationReport(ic_results=(result,))
        md = report.to_markdown()
        assert "n/a" in md
        lines = [ln for ln in md.split("\n") if "gex_signal" in ln and "+0.0300" in ln]
        assert len(lines) == 1
        assert "| no |" not in lines[0]
        assert "| n/a |" in lines[0]
