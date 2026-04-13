"""Unit tests for features.orthogonalizer.

Tests cover:
- drop_lowest_ic: columns removed, no-op when no drops
- residualize: OLS residual orthogonal to keeper, NaN preservation,
  determinism
- pca: cluster members replaced by PC1, NaN preservation, single-member
  clusters untouched
- Unknown method raises ValueError
- Integration with MulticollinearityAnalyzer output
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from features.ic.base import ICResult
from features.multicollinearity import MulticollinearityAnalyzer, MulticollinearityReport
from features.orthogonalizer import FeatureOrthogonalizer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ic(name: str, ic: float) -> ICResult:
    """Build a minimal ICResult."""
    return ICResult(
        ic=ic,
        ic_ir=1.0,
        p_value=0.01,
        n_samples=200,
        ci_low=ic - 0.01,
        ci_high=ic + 0.01,
        feature_name=name,
    )


def _correlated_df(
    n: int = 500,
    seed: int = 42,
    rho: float = 0.9,
) -> tuple[pl.DataFrame, list[str], list[ICResult]]:
    """Build a DataFrame with 2 correlated + 2 independent signals."""
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(n)
    noise = rng.standard_normal(n)
    signals = {
        "sig_a": base,
        "sig_b": rho * base + np.sqrt(1 - rho**2) * noise,
        "sig_c": rng.standard_normal(n),
        "sig_d": rng.standard_normal(n),
    }
    cols = list(signals.keys())
    df = pl.DataFrame(signals)
    ic_results = [
        _make_ic("sig_a", 0.10),  # higher IC -> kept
        _make_ic("sig_b", 0.05),  # lower IC -> dropped
        _make_ic("sig_c", 0.08),
        _make_ic("sig_d", 0.03),
    ]
    return df, cols, ic_results


def _get_report(
    df: pl.DataFrame,
    cols: list[str],
    ic_results: list[ICResult],
) -> MulticollinearityReport:
    analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
    return analyzer.analyze(df, ic_results, cols)


# =========================================================================
# drop_lowest_ic
# =========================================================================


class TestDropLowestIC:
    """Strategy 1: remove recommended_drops columns."""

    def test_drops_lower_ic_column(self) -> None:
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="drop_lowest_ic")
        assert "sig_b" not in result.columns
        assert "sig_a" in result.columns

    def test_no_drops_returns_same_columns(self) -> None:
        """When no pairs exceed threshold, all columns survive."""
        rng = np.random.default_rng(99)
        df = pl.DataFrame({f"ind_{i}": rng.standard_normal(300) for i in range(4)})
        cols = list(df.columns)
        ic_results = [_make_ic(c, 0.1 - 0.02 * i) for i, c in enumerate(cols)]
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="drop_lowest_ic")
        assert set(result.columns) == set(df.columns)

    def test_row_count_preserved(self) -> None:
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="drop_lowest_ic")
        assert result.height == df.height


# =========================================================================
# residualize
# =========================================================================


class TestResidualize:
    """Strategy 2: OLS residual replaces lower-IC signal."""

    def test_residual_orthogonal_to_keeper(self) -> None:
        """After residualization, sig_b should have ~0 corr with sig_a."""
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")
        # sig_b is now the residual
        a = result["sig_a"].to_numpy()
        b = result["sig_b"].to_numpy()
        corr = np.corrcoef(a, b)[0, 1]
        assert abs(corr) < 0.05

    def test_keeper_untouched(self) -> None:
        """sig_a (higher IC) should be bitwise identical."""
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")
        np.testing.assert_array_equal(df["sig_a"].to_numpy(), result["sig_a"].to_numpy())

    def test_independent_signals_untouched(self) -> None:
        """sig_c and sig_d should be bitwise identical."""
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")
        np.testing.assert_array_equal(df["sig_c"].to_numpy(), result["sig_c"].to_numpy())
        np.testing.assert_array_equal(df["sig_d"].to_numpy(), result["sig_d"].to_numpy())

    def test_nan_rows_preserved(self) -> None:
        """NaN positions in input should remain NaN in output."""
        rng = np.random.default_rng(42)
        n = 300
        base = rng.standard_normal(n)
        a_vals = base.tolist()
        b_vals = (0.9 * base + 0.1 * rng.standard_normal(n)).tolist()
        # Inject NaN at known positions
        a_vals[0] = None  # type: ignore[call-overload]
        a_vals[5] = None  # type: ignore[call-overload]
        b_vals[10] = None  # type: ignore[call-overload]
        c_vals = rng.standard_normal(n).tolist()
        df = pl.DataFrame({"sig_a": a_vals, "sig_b": b_vals, "sig_c": c_vals})
        cols = ["sig_a", "sig_b", "sig_c"]
        ic_results = [_make_ic("sig_a", 0.10), _make_ic("sig_b", 0.05), _make_ic("sig_c", 0.08)]
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")
        # NaN positions for sig_b: original NaN at index 10 + propagated from sig_a NaN at 0,5
        b_result = result["sig_b"].to_numpy()
        assert np.isnan(b_result[0])
        assert np.isnan(b_result[5])
        assert np.isnan(b_result[10])

    def test_deterministic(self) -> None:
        df, cols, ic_results = _correlated_df(seed=42)
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        r1 = ortho.orthogonalize(df, report, method="residualize")
        r2 = ortho.orthogonalize(df, report, method="residualize")
        for c in r1.columns:
            np.testing.assert_array_equal(r1[c].to_numpy(), r2[c].to_numpy())

    def test_all_columns_preserved(self) -> None:
        """Residualize keeps all columns (unlike drop)."""
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")
        assert set(result.columns) == set(df.columns)


# =========================================================================
# PCA
# =========================================================================


class TestPCA:
    """Strategy 3: replace cluster members with first PC."""

    def test_cluster_replaced_by_pc_column(self) -> None:
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="pca")
        # sig_a and sig_b should be replaced by pc_<cluster_id>
        assert "sig_a" not in result.columns
        assert "sig_b" not in result.columns
        pc_cols = [c for c in result.columns if c.startswith("pc_")]
        assert len(pc_cols) >= 1

    def test_single_member_clusters_untouched(self) -> None:
        """sig_c and sig_d (independent) should survive as-is."""
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="pca")
        assert "sig_c" in result.columns
        assert "sig_d" in result.columns
        np.testing.assert_array_equal(df["sig_c"].to_numpy(), result["sig_c"].to_numpy())

    def test_pc_column_has_correct_length(self) -> None:
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="pca")
        pc_cols = [c for c in result.columns if c.startswith("pc_")]
        for pc in pc_cols:
            assert result[pc].len() == df.height

    def test_deterministic(self) -> None:
        df, cols, ic_results = _correlated_df(seed=42)
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        r1 = ortho.orthogonalize(df, report, method="pca")
        r2 = ortho.orthogonalize(df, report, method="pca")
        for c in r1.columns:
            np.testing.assert_array_equal(r1[c].to_numpy(), r2[c].to_numpy())


# =========================================================================
# Error handling
# =========================================================================


class TestErrorHandling:
    """Unknown methods and edge cases."""

    def test_unknown_method_raises(self) -> None:
        df, cols, ic_results = _correlated_df()
        report = _get_report(df, cols, ic_results)
        ortho = FeatureOrthogonalizer()
        with pytest.raises(ValueError, match="Unknown orthogonalization method"):
            ortho.orthogonalize(df, report, method="invalid")  # type: ignore[arg-type]


# =========================================================================
# Integration: full pipeline
# =========================================================================


class TestIntegrationPipeline:
    """End-to-end: analyze -> orthogonalize -> verify."""

    def test_drop_reduces_condition_number(self) -> None:
        """Dropping collinear signals should reduce the condition number."""
        df, cols, ic_results = _correlated_df()
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, ic_results, cols)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="drop_lowest_ic")

        # Re-analyze the cleaned matrix
        remaining_cols = [c for c in cols if c in result.columns]
        remaining_ic = [r for r in ic_results if r.feature_name in remaining_cols]
        report2 = analyzer.analyze(result, remaining_ic, remaining_cols)
        assert report2.condition_number <= report.condition_number

    def test_residualize_removes_high_correlation(self) -> None:
        """After residualization, no pair should exceed threshold."""
        df, cols, ic_results = _correlated_df()
        analyzer = MulticollinearityAnalyzer(max_correlation=0.7)
        report = analyzer.analyze(df, ic_results, cols)
        ortho = FeatureOrthogonalizer()
        result = ortho.orthogonalize(df, report, method="residualize")

        report2 = analyzer.analyze(result, ic_results, cols)
        assert len(report2.high_correlation_pairs) == 0
