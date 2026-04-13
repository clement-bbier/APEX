"""Unit tests for features.multicollinearity.

Tests cover:
- Constructor validation (threshold bounds)
- Pearson correlation matrix properties (symmetry, diagonal, range)
- VIF calculation accuracy (independent, collinear, constant signals)
- Collinear pair detection (threshold, symmetry, no self-pairs)
- Hierarchical clustering and drop recommendations
- Column resolution (explicit, auto-detect, missing)
- Insufficient data handling
- Report markdown generation
- Determinism (same input -> same output)
- End-to-end integration with synthetic 8-signal DataFrame
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from features.ic.base import ICResult
from features.multicollinearity import (
    _MIN_ROWS,
    MulticollinearityAnalyzer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ic(name: str, ic: float) -> ICResult:
    """Build a minimal ICResult with only the fields we need."""
    return ICResult(
        ic=ic,
        ic_ir=1.0,
        p_value=0.01,
        n_samples=200,
        ci_low=ic - 0.01,
        ci_high=ic + 0.01,
        feature_name=name,
    )


def _synthetic_df(
    n: int = 500,
    seed: int = 42,
    rho_ab: float = 0.9,
) -> tuple[pl.DataFrame, list[str]]:
    """Build a synthetic DataFrame with known correlation structure.

    Returns (df, signal_columns) where:
    - sig_a and sig_b have Pearson correlation ~rho_ab
    - sig_c and sig_d are independent of each other and of a/b
    """
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(n)
    noise = rng.standard_normal(n)
    sig_a = base
    sig_b = rho_ab * base + np.sqrt(1 - rho_ab**2) * noise
    sig_c = rng.standard_normal(n)
    sig_d = rng.standard_normal(n)

    cols = ["sig_a", "sig_b", "sig_c", "sig_d"]
    df = pl.DataFrame(
        {
            "sig_a": sig_a,
            "sig_b": sig_b,
            "sig_c": sig_c,
            "sig_d": sig_d,
        }
    )
    return df, cols


def _ic_list_for_cols(cols: list[str]) -> list[ICResult]:
    """Assign decreasing IC to each column."""
    return [_make_ic(c, 0.10 - 0.02 * i) for i, c in enumerate(cols)]


# =========================================================================
# Constructor validation
# =========================================================================


class TestConstructorValidation:
    """D030-style constructor boundary checks."""

    def test_rho_threshold_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_correlation"):
            MulticollinearityAnalyzer(max_correlation=0.0)

    def test_rho_threshold_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_correlation"):
            MulticollinearityAnalyzer(max_correlation=-0.5)

    def test_rho_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="max_correlation"):
            MulticollinearityAnalyzer(max_correlation=1.1)

    def test_rho_threshold_one_ok(self) -> None:
        a = MulticollinearityAnalyzer(max_correlation=1.0)
        assert a._max_correlation == 1.0

    def test_vif_threshold_one_raises(self) -> None:
        with pytest.raises(ValueError, match="max_vif"):
            MulticollinearityAnalyzer(max_vif=1.0)

    def test_vif_threshold_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="max_vif"):
            MulticollinearityAnalyzer(max_vif=0.5)

    def test_defaults_ok(self) -> None:
        a = MulticollinearityAnalyzer()
        assert a._max_correlation == 0.70
        assert a._max_vif == 5.0


# =========================================================================
# Correlation matrix properties
# =========================================================================


class TestCorrelationMatrixProperties:
    """Pearson correlation matrix structural invariants."""

    def test_diagonal_is_one(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        for c in cols:
            assert report.correlation_matrix[c][c] == pytest.approx(1.0)

    def test_symmetry(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        for ci in cols:
            for cj in cols:
                assert report.correlation_matrix[ci][cj] == pytest.approx(
                    report.correlation_matrix[cj][ci]
                )

    def test_values_in_range(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        for ci in cols:
            for cj in cols:
                assert -1.0 <= report.correlation_matrix[ci][cj] <= 1.0

    def test_known_high_correlation(self) -> None:
        """sig_a and sig_b should have |rho| close to 0.9."""
        df, cols = _synthetic_df(rho_ab=0.9)
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        rho = report.correlation_matrix["sig_a"]["sig_b"]
        assert abs(rho) > 0.85

    def test_independent_signals_low_correlation(self) -> None:
        """sig_c and sig_d should have |rho| near 0."""
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        rho_cd = report.correlation_matrix["sig_c"]["sig_d"]
        assert abs(rho_cd) < 0.15


# =========================================================================
# VIF calculation
# =========================================================================


class TestVIFCalculation:
    """VIF accuracy on synthetic data with known R²."""

    def test_independent_signals_vif_near_one(self) -> None:
        """4 independent signals -> VIF ≈ 1 for each."""
        rng = np.random.default_rng(99)
        df = pl.DataFrame({f"ind_{i}": rng.standard_normal(300) for i in range(4)})
        cols = list(df.columns)
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        for c in cols:
            assert report.vif_scores[c] < 1.5

    def test_collinear_pair_vif_high(self) -> None:
        """Two signals with rho=0.9 -> VIF ≈ 1/(1-0.81) ≈ 5.26."""
        df, cols = _synthetic_df(n=500, rho_ab=0.9)
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        # sig_a and sig_b should have elevated VIF
        assert report.vif_scores["sig_a"] > 3.0
        assert report.vif_scores["sig_b"] > 3.0
        # sig_c and sig_d should remain low
        assert report.vif_scores["sig_c"] < 2.0
        assert report.vif_scores["sig_d"] < 2.0

    def test_constant_signal_vif_infinite(self) -> None:
        """A constant column should produce VIF = inf."""
        rng = np.random.default_rng(42)
        df = pl.DataFrame(
            {
                "const": np.ones(200),
                "vary_a": rng.standard_normal(200),
                "vary_b": rng.standard_normal(200),
            }
        )
        cols = list(df.columns)
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        assert report.vif_scores["const"] == float("inf")

    def test_two_signals_minimum(self) -> None:
        """VIF needs at least 2 signals — 1 signal should raise."""
        df = pl.DataFrame({"only": np.random.default_rng(1).standard_normal(200)})
        analyzer = MulticollinearityAnalyzer()
        with pytest.raises(ValueError, match="Need >= 2"):
            analyzer.analyze(df, [_make_ic("only", 0.05)], ["only"])


# =========================================================================
# Collinear pair detection
# =========================================================================


class TestCollinearPairDetection:
    """Pair identification with threshold enforcement."""

    def test_pair_detected_above_threshold(self) -> None:
        df, cols = _synthetic_df(rho_ab=0.9)
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        pair_names = {(a, b) for a, b, _ in report.high_correlation_pairs}
        assert ("sig_a", "sig_b") in pair_names

    def test_no_self_pairs(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        for a, b, _ in report.high_correlation_pairs:
            assert a != b

    def test_pairs_listed_once(self) -> None:
        """(A,B) listed once — not both (A,B) and (B,A)."""
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        seen: set[tuple[str, str]] = set()
        for a, b, _ in report.high_correlation_pairs:
            assert (b, a) not in seen, f"Duplicate pair ({a},{b}) / ({b},{a})"
            seen.add((a, b))

    def test_sorted_descending_by_abs_rho(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        rhos = [abs(r) for _, _, r in report.high_correlation_pairs]
        assert rhos == sorted(rhos, reverse=True)


# =========================================================================
# D030-class: clustering cutoff honors max_correlation
# =========================================================================


class TestClusteringCutoffHonored:
    """D030: configurable parameters must propagate downstream."""

    def test_clustering_cutoff_honors_max_correlation(self) -> None:
        """With max_correlation=0.95, a pair with rho=0.85 must NOT cluster.

        Same input with max_correlation=0.70 DOES cluster them.
        """
        rng = np.random.default_rng(42)
        n = 500
        base = rng.standard_normal(n)
        sig_correlated = 0.85 * base + np.sqrt(1 - 0.85**2) * rng.standard_normal(n)
        df = pl.DataFrame(
            {
                "a": base,
                "b": sig_correlated,
                "c": rng.standard_normal(n),
            }
        )
        ic = [_make_ic("a", 0.08), _make_ic("b", 0.06), _make_ic("c", 0.05)]

        # Loose threshold: rho=0.85 IS above 0.70 -> cluster -> drop
        loose = MulticollinearityAnalyzer(max_correlation=0.70, max_vif=5.0)
        report_loose = loose.analyze(df, ic, ["a", "b", "c"])
        assert "b" in report_loose.recommended_drops

        # Strict threshold: rho=0.85 is BELOW 0.95 -> no cluster -> no drop
        strict = MulticollinearityAnalyzer(max_correlation=0.95, max_vif=5.0)
        report_strict = strict.analyze(df, ic, ["a", "b", "c"])
        assert "b" not in report_strict.recommended_drops
        assert report_strict.recommended_drops == []


# =========================================================================
# D030-class: max_vif drives status flags
# =========================================================================


class TestMaxVIFPropagation:
    """D030: max_vif threshold propagates to high_vif_signals and report."""

    def test_max_vif_drives_high_vif_signals(self) -> None:
        """Two signals with rho~0.91 -> VIF~6. HIGH under max_vif=5, OK under 10."""
        rng = np.random.default_rng(42)
        n = 500
        base = rng.standard_normal(n)
        correlated = 0.91 * base + np.sqrt(1 - 0.91**2) * rng.standard_normal(n)
        df = pl.DataFrame({"a": base, "b": correlated, "c": rng.standard_normal(n)})
        ic = [_make_ic("a", 0.08), _make_ic("b", 0.06), _make_ic("c", 0.05)]

        # max_vif=5 -> signals with VIF >= 5 flagged HIGH
        strict = MulticollinearityAnalyzer(max_correlation=0.99, max_vif=5.0)
        report_strict = strict.analyze(df, ic, ["a", "b", "c"])
        high_names = {s[0] for s in report_strict.high_vif_signals}
        assert high_names & {"a", "b"}, "Expected a or b to have VIF >= 5"
        assert "HIGH" in report_strict.to_markdown()

        # max_vif=10 -> nothing flagged
        loose = MulticollinearityAnalyzer(max_correlation=0.99, max_vif=10.0)
        report_loose = loose.analyze(df, ic, ["a", "b", "c"])
        assert report_loose.high_vif_signals == []


# =========================================================================
# Column resolution
# =========================================================================


class TestColumnResolution:
    """Explicit vs auto-detect column selection."""

    def test_explicit_columns(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), signal_columns=["sig_a", "sig_c"])
        assert report.signal_columns == ["sig_a", "sig_c"]

    def test_missing_column_raises(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        with pytest.raises(ValueError, match="not found"):
            analyzer.analyze(df, _ic_list_for_cols(cols), ["sig_a", "missing"])

    def test_auto_detect_from_ic_results(self) -> None:
        df, _cols = _synthetic_df()
        ic_list = [_make_ic("sig_a", 0.1), _make_ic("sig_c", 0.08)]
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, ic_list)
        assert report.signal_columns == ["sig_a", "sig_c"]


# =========================================================================
# Insufficient data
# =========================================================================


class TestInsufficientData:
    """Edge cases with too few rows."""

    def test_below_min_rows_raises(self) -> None:
        rng = np.random.default_rng(42)
        df = pl.DataFrame(
            {
                "a": rng.standard_normal(_MIN_ROWS - 1),
                "b": rng.standard_normal(_MIN_ROWS - 1),
            }
        )
        analyzer = MulticollinearityAnalyzer()
        with pytest.raises(ValueError, match="finite rows"):
            analyzer.analyze(df, [_make_ic("a", 0.1), _make_ic("b", 0.08)], ["a", "b"])

    def test_nan_rows_reduce_count(self) -> None:
        """Enough total rows but too many Nones."""
        rng = np.random.default_rng(42)
        n = 200
        a_vals = rng.standard_normal(n).tolist()
        b_vals = rng.standard_normal(n).tolist()
        # Set most values to None so fewer than 100 survive
        for i in range(n - 50):
            a_vals[i] = None  # type: ignore[call-overload]
        df = pl.DataFrame({"a": a_vals, "b": b_vals})
        analyzer = MulticollinearityAnalyzer()
        with pytest.raises(ValueError, match="finite rows"):
            analyzer.analyze(df, [_make_ic("a", 0.1), _make_ic("b", 0.08)], ["a", "b"])

    def test_nan_rows_are_dropped(self) -> None:
        """np.nan (not just None) must be dropped — calculators emit np.nan for warm-up."""
        rng = np.random.default_rng(42)
        n = 200
        # Build with explicit np.nan in first 50 rows (simulates warm-up)
        col_a = np.concatenate([np.full(50, np.nan), rng.standard_normal(n - 50)])
        col_b = np.concatenate([np.full(50, np.nan), rng.standard_normal(n - 50)])
        col_c = rng.standard_normal(n)
        df = pl.DataFrame({"a": col_a, "b": col_b, "c": col_c})
        ic = [_make_ic("a", 0.10), _make_ic("b", 0.05), _make_ic("c", 0.08)]

        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, ic, ["a", "b", "c"])
        # n_rows should be n-50 = 150, NOT n=200
        assert report.n_rows_used == 150, (
            f"Expected 150 finite rows after dropping 50 NaN, got {report.n_rows_used}. "
            f"drop_nulls() alone does not drop np.nan."
        )


# =========================================================================
# Determinism
# =========================================================================


class TestDeterminism:
    """Same input -> identical output (bitwise for correlation)."""

    def test_analyze_deterministic(self) -> None:
        df, cols = _synthetic_df(seed=42)
        ic_list = _ic_list_for_cols(cols)
        analyzer = MulticollinearityAnalyzer()
        r1 = analyzer.analyze(df, ic_list, cols)
        r2 = analyzer.analyze(df, ic_list, cols)
        assert r1.correlation_matrix == r2.correlation_matrix
        assert r1.vif_scores == r2.vif_scores
        assert r1.high_correlation_pairs == r2.high_correlation_pairs
        assert r1.cluster_assignments == r2.cluster_assignments
        assert r1.recommended_drops == r2.recommended_drops


# =========================================================================
# Report generation
# =========================================================================


class TestReportGeneration:
    """Markdown report output validation."""

    def test_to_markdown_contains_sections(self) -> None:
        df, cols = _synthetic_df()
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        md = report.to_markdown()
        assert "## Input scope" in md
        assert "## Correlation matrix (Pearson)" in md
        assert "## VIF per signal" in md
        assert "## Collinear pairs" in md
        assert "## Cluster assignments" in md
        assert "## Recommended drops" in md
        assert "## References" in md

    def test_to_markdown_deterministic(self) -> None:
        df, cols = _synthetic_df(seed=42)
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, _ic_list_for_cols(cols), cols)
        assert report.to_markdown() == report.to_markdown()


# =========================================================================
# Integration: 8-signal synthetic DataFrame
# =========================================================================


class TestIntegrationEightSignals:
    """End-to-end with a realistic 8-signal matrix."""

    @pytest.fixture
    def eight_signal_setup(
        self,
    ) -> tuple[pl.DataFrame, list[str], list[ICResult]]:
        """Build synthetic 8-signal DataFrame mimicking Phase 3 outputs.

        Known structure:
        - har_rv_signal and vr_signal: correlated (rho~0.85)
        - ofi_signal and cvd_divergence: correlated (rho~0.80)
        - liquidity_signal, combined_signal, gex_signal, gex_raw: independent
        """
        rng = np.random.default_rng(42)
        n = 500
        base_vol = rng.standard_normal(n)
        base_flow = rng.standard_normal(n)

        signals: dict[str, np.ndarray] = {  # type: ignore[type-arg]
            "har_rv_signal": base_vol,
            "vr_signal": 0.85 * base_vol + np.sqrt(1 - 0.85**2) * rng.standard_normal(n),
            "ofi_signal": base_flow,
            "cvd_divergence": 0.80 * base_flow + np.sqrt(1 - 0.80**2) * rng.standard_normal(n),
            "liquidity_signal": rng.standard_normal(n),
            "combined_signal": rng.standard_normal(n),
            "gex_signal": rng.standard_normal(n),
            "gex_raw": rng.standard_normal(n),
        }
        cols = list(signals.keys())
        df = pl.DataFrame(signals)

        ic_results = [
            _make_ic("har_rv_signal", 0.08),
            _make_ic("vr_signal", 0.06),
            _make_ic("ofi_signal", 0.07),
            _make_ic("cvd_divergence", 0.04),
            _make_ic("liquidity_signal", 0.05),
            _make_ic("combined_signal", 0.03),
            _make_ic("gex_signal", 0.09),
            _make_ic("gex_raw", 0.02),
        ]
        return df, cols, ic_results

    def test_detects_vol_pair(
        self,
        eight_signal_setup: tuple[pl.DataFrame, list[str], list[ICResult]],
    ) -> None:
        df, cols, ic_results = eight_signal_setup
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, ic_results, cols)
        pair_set = {frozenset({a, b}) for a, b, _ in report.high_correlation_pairs}
        assert frozenset({"har_rv_signal", "vr_signal"}) in pair_set

    def test_detects_flow_pair(
        self,
        eight_signal_setup: tuple[pl.DataFrame, list[str], list[ICResult]],
    ) -> None:
        df, cols, ic_results = eight_signal_setup
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, ic_results, cols)
        pair_set = {frozenset({a, b}) for a, b, _ in report.high_correlation_pairs}
        assert frozenset({"ofi_signal", "cvd_divergence"}) in pair_set

    def test_drops_lower_ic_signals(
        self,
        eight_signal_setup: tuple[pl.DataFrame, list[str], list[ICResult]],
    ) -> None:
        """vr_signal (IC=0.06) < har_rv_signal (IC=0.08) -> drop vr_signal.
        cvd_divergence (IC=0.04) < ofi_signal (IC=0.07) -> drop cvd_divergence.
        """
        df, cols, ic_results = eight_signal_setup
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, ic_results, cols)
        assert "vr_signal" in report.recommended_drops
        assert "cvd_divergence" in report.recommended_drops
        # Higher IC signals should NOT be dropped
        assert "har_rv_signal" not in report.recommended_drops
        assert "ofi_signal" not in report.recommended_drops

    def test_condition_number_positive(
        self,
        eight_signal_setup: tuple[pl.DataFrame, list[str], list[ICResult]],
    ) -> None:
        df, cols, ic_results = eight_signal_setup
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, ic_results, cols)
        assert report.condition_number > 0.0

    def test_n_rows_used(
        self,
        eight_signal_setup: tuple[pl.DataFrame, list[str], list[ICResult]],
    ) -> None:
        df, cols, ic_results = eight_signal_setup
        analyzer = MulticollinearityAnalyzer()
        report = analyzer.analyze(df, ic_results, cols)
        assert report.n_rows_used == 500
