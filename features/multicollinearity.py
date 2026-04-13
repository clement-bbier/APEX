"""Multicollinearity analysis for Phase 3 feature signals.

Detects redundant features via Pearson correlation, VIF (Variance
Inflation Factor), and hierarchical clustering.  Produces a frozen
:class:`MulticollinearityReport` with actionable decisions.

This module is an **analysis tool**, not a calculator — it does not
produce new time-series columns.  It consumes the concatenated output
of the 5 Phase 3 calculators (HAR-RV, Rough Vol, OFI, CVD+Kyle, GEX).

References:
    Belsley, D. A., Kuh, E. & Welsch, R. E. (1980).
    *Regression Diagnostics: Identifying Influential Data and Sources
    of Collinearity*. Wiley.

    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*,
    Ch. 8. Wiley.

    Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*,
    Ch. 6. Cambridge University Press.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from features.ic.base import ICResult

# ---------------------------------------------------------------------------
# Minimum rows required for meaningful correlation / VIF computation.
# With 8 signals, at least 100 non-NaN rows avoids degenerate OLS.
# ---------------------------------------------------------------------------
_MIN_ROWS: int = 100


@dataclass(frozen=True)
class MulticollinearityReport:
    """Report on feature multicollinearity.

    All fields are computed by :meth:`MulticollinearityAnalyzer.analyze`.

    Reference:
        Belsley, D. A., Kuh, E. & Welsch, R. E. (1980).
        *Regression Diagnostics*. Wiley.
    """

    correlation_matrix: dict[str, dict[str, float]]
    """Symmetric Pearson correlation matrix (signal x signal)."""

    vif_scores: dict[str, float]
    """VIF per signal."""

    high_correlation_pairs: list[tuple[str, str, float]]
    """|corr| > threshold.  Sorted descending by |corr|."""

    high_vif_signals: list[tuple[str, float]]
    """Signals with VIF >= max_vif threshold."""

    cluster_assignments: dict[str, int]
    """Signal -> cluster ID from hierarchical clustering."""

    recommended_drops: list[str]
    """Signals to drop (lowest IC in each correlated cluster)."""

    condition_number: float
    """Condition number of the feature matrix (lower = better)."""

    n_rows_used: int
    """Number of finite rows used for computation."""

    signal_columns: list[str]
    """Ordered list of signal column names analysed."""

    max_vif: float
    """VIF threshold used for HIGH/OK status flags."""

    def to_markdown(self) -> str:
        """Render the report as reproducible Markdown."""
        lines: list[str] = []
        lines.append("# Phase 3.9 — Multicollinearity Analysis Report\n")

        # -- Input scope ------------------------------------------------
        lines.append("## Input scope\n")
        lines.append(
            f"- Signal columns (N={len(self.signal_columns)}): {', '.join(self.signal_columns)}"
        )
        lines.append(f"- Non-NaN rows after drop: {self.n_rows_used}")
        lines.append(f"- Condition number: {self.condition_number:.4f}\n")

        # -- Correlation matrix -----------------------------------------
        lines.append("## Correlation matrix (Pearson)\n")
        cols = self.signal_columns
        header = "| | " + " | ".join(cols) + " |"
        sep = "|---|" + "|".join(["---"] * len(cols)) + "|"
        lines.append(header)
        lines.append(sep)
        for row_name in cols:
            vals = " | ".join(f"{self.correlation_matrix[row_name][c]:.4f}" for c in cols)
            lines.append(f"| {row_name} | {vals} |")
        lines.append("")

        # -- VIF per signal ---------------------------------------------
        lines.append(f"## VIF per signal (threshold={self.max_vif})\n")
        lines.append("| Signal | VIF | Status |")
        lines.append("|---|---|---|")
        for sig in cols:
            vif = self.vif_scores[sig]
            status = "HIGH" if vif >= self.max_vif else "OK"
            lines.append(f"| {sig} | {vif:.4f} | {status} |")
        lines.append("")

        # -- Collinear pairs --------------------------------------------
        lines.append("## Collinear pairs\n")
        if self.high_correlation_pairs:
            lines.append("| Signal A | Signal B | rho |")
            lines.append("|---|---|---|")
            for sig_a, sig_b, rho in self.high_correlation_pairs:
                lines.append(f"| {sig_a} | {sig_b} | {rho:.4f} |")
        else:
            lines.append("No pairs exceed the correlation threshold.")
        lines.append("")

        # -- Cluster assignments ----------------------------------------
        lines.append("## Cluster assignments\n")
        lines.append("| Signal | Cluster |")
        lines.append("|---|---|")
        for sig in cols:
            lines.append(f"| {sig} | {self.cluster_assignments[sig]} |")
        lines.append("")

        # -- Recommended drops ------------------------------------------
        lines.append("## Recommended drops\n")
        if self.recommended_drops:
            for sig in self.recommended_drops:
                lines.append(f"- `{sig}`")
        else:
            lines.append("No drops recommended — all features are sufficiently independent.")
        lines.append("")

        # -- References -------------------------------------------------
        lines.append("## References\n")
        lines.append("- Belsley, Kuh & Welsch (1980)")
        lines.append("- Lopez de Prado (2018) Ch. 8")
        lines.append("- Lopez de Prado (2020) Ch. 6")
        lines.append("")

        return "\n".join(lines)


class MulticollinearityAnalyzer:
    """Detects multicollinearity among features.

    Uses VIF (Variance Inflation Factor), Pearson correlation matrix,
    and hierarchical clustering to identify redundant features.

    VIF > 5 indicates problematic multicollinearity.
    VIF > 10 indicates severe multicollinearity.

    Parameters
    ----------
    max_correlation:
        Absolute Pearson threshold above which a pair is flagged.
        Must be in (0, 1].
    max_vif:
        VIF threshold above which a signal is flagged.  Must be > 1.0
        (VIF = 1 means zero collinearity).

    Reference:
        Belsley, Kuh & Welsch (1980), Lopez de Prado (2020) Ch. 6.
    """

    def __init__(
        self,
        max_correlation: float = 0.70,
        max_vif: float = 5.0,
    ) -> None:
        if not 0.0 < max_correlation <= 1.0:
            raise ValueError(f"max_correlation must be in (0, 1], got {max_correlation}")
        if max_vif <= 1.0:
            raise ValueError(f"max_vif must be > 1.0 (VIF=1 means no collinearity), got {max_vif}")
        self._max_correlation = max_correlation
        self._max_vif = max_vif

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        feature_matrix: pl.DataFrame,
        ic_results: list[ICResult],
        signal_columns: list[str] | None = None,
    ) -> MulticollinearityReport:
        """Run full multicollinearity analysis.

        Parameters
        ----------
        feature_matrix:
            DataFrame containing at least the signal columns to analyse.
        ic_results:
            IC measurement results — used to decide which signal to drop
            in a correlated cluster (lowest IC gets dropped).
        signal_columns:
            Explicit list of columns to analyse.  If *None*, all columns
            present in *feature_matrix* that also appear in *ic_results*
            (by ``feature_name``) are used.

        Returns
        -------
        MulticollinearityReport
            Frozen dataclass with all analysis artefacts.

        Raises
        ------
        ValueError
            If fewer than 2 signal columns are found, or if the number
            of non-NaN rows is < 100.
        """
        cols = self._resolve_columns(feature_matrix, ic_results, signal_columns)
        if len(cols) < 2:
            raise ValueError(
                f"Need >= 2 signal columns for multicollinearity analysis, got {len(cols)}: {cols}"
            )

        # Drop rows with any null / NaN / infinite value across selected
        # columns so downstream NumPy statistics receive only finite data.
        # Note: Polars drop_nulls() only removes None, NOT np.nan.
        # Phase 3 calculators emit warm-up gaps as np.nan, so we must
        # also filter for is_finite().
        clean = (
            feature_matrix.select(cols)
            .drop_nulls()
            .filter(pl.all_horizontal(pl.col(c).is_finite() for c in cols))
        )
        n_rows = clean.height
        if n_rows < _MIN_ROWS:
            raise ValueError(
                f"Only {n_rows} finite rows (minimum {_MIN_ROWS}). "
                f"Cannot compute reliable correlations."
            )

        # NumPy matrix (rows x signals) --------------------------------
        arr = clean.to_numpy()  # shape (n_rows, n_signals)

        corr_matrix = self._pearson_correlation(arr, cols)
        vif_scores = self._compute_vif(arr, cols)
        high_vif = [(col, vif) for col, vif in vif_scores.items() if vif >= self._max_vif]
        pairs = self._detect_pairs(corr_matrix, cols)
        clusters = self._cluster_signals(corr_matrix, cols)
        drops = self._recommend_drops(clusters, ic_results, cols)
        cond = float(np.linalg.cond(arr))

        return MulticollinearityReport(
            correlation_matrix=corr_matrix,
            vif_scores=vif_scores,
            high_correlation_pairs=pairs,
            high_vif_signals=high_vif,
            cluster_assignments=clusters,
            recommended_drops=drops,
            condition_number=cond,
            n_rows_used=n_rows,
            signal_columns=cols,
            max_vif=self._max_vif,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_columns(
        df: pl.DataFrame,
        ic_results: list[ICResult],
        explicit: list[str] | None,
    ) -> list[str]:
        """Determine which columns to analyse."""
        if explicit is not None:
            missing = [c for c in explicit if c not in df.columns]
            if missing:
                raise ValueError(f"Signal columns not found in DataFrame: {missing}")
            return list(explicit)
        # Auto-detect: columns present in both df and ic_results
        ic_names = {r.feature_name for r in ic_results if r.feature_name is not None}
        cols = [c for c in df.columns if c in ic_names]
        return sorted(cols)

    @staticmethod
    def _pearson_correlation(
        arr: npt.NDArray[np.float64],
        cols: list[str],
    ) -> dict[str, dict[str, float]]:
        """Compute Pearson correlation matrix.

        Constant columns (std=0) produce NaN in ``np.corrcoef``.
        We replace NaN off-diagonal entries with 0.0 (no linear
        relationship) and NaN diagonal entries with 1.0.
        """
        with np.errstate(invalid="ignore"):
            rho = np.corrcoef(arr, rowvar=False)
        # Fix NaN from zero-variance columns
        np.fill_diagonal(rho, 1.0)
        rho = np.where(np.isnan(rho), 0.0, rho)

        result: dict[str, dict[str, float]] = {}
        for i, ci in enumerate(cols):
            result[ci] = {}
            for j, cj in enumerate(cols):
                result[ci][cj] = float(rho[i, j])
        return result

    @staticmethod
    def _compute_vif(
        arr: npt.NDArray[np.float64],
        cols: list[str],
    ) -> dict[str, float]:
        """VIF_i = 1 / (1 - R^2_i), R^2 from OLS of col_i on remaining.

        Uses ``numpy.linalg.lstsq`` — no statsmodels dependency.
        """
        n_signals = arr.shape[1]
        vif: dict[str, float] = {}
        for i in range(n_signals):
            y = arr[:, i]
            # X = all other columns + intercept
            others = np.delete(arr, i, axis=1)
            x_aug = np.column_stack([others, np.ones(arr.shape[0], dtype=np.float64)])
            coefs, _residuals, _rank, _sv = np.linalg.lstsq(x_aug, y, rcond=None)
            y_hat = x_aug @ coefs
            ss_res = float(np.sum((y - y_hat) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            if ss_tot == 0.0:
                # Constant signal — VIF undefined, treat as infinite
                vif[cols[i]] = float("inf")
                continue
            r_squared = 1.0 - ss_res / ss_tot
            if r_squared >= 1.0:
                vif[cols[i]] = float("inf")
            else:
                vif[cols[i]] = 1.0 / (1.0 - r_squared)
        return vif

    def _detect_pairs(
        self,
        corr_matrix: dict[str, dict[str, float]],
        cols: list[str],
    ) -> list[tuple[str, str, float]]:
        """Return pairs with |corr| >= threshold, sorted desc."""
        pairs: list[tuple[str, str, float]] = []
        for i, ci in enumerate(cols):
            for j in range(i + 1, len(cols)):
                cj = cols[j]
                rho = corr_matrix[ci][cj]
                if abs(rho) >= self._max_correlation:
                    pairs.append((ci, cj, rho))
        pairs.sort(key=lambda t: abs(t[2]), reverse=True)
        return pairs

    def _cluster_signals(
        self,
        corr_matrix: dict[str, dict[str, float]],
        cols: list[str],
    ) -> dict[str, int]:
        """Hierarchical clustering on correlation distance.

        Distance = 1 - |corr|.  Distance cutoff derived from
        ``max_correlation``: ``cutoff = 1.0 - max_correlation``.
        Default ``max_correlation=0.70`` → cutoff=0.30 (groups signals
        with |corr| >= 0.70).

        Reference: Lopez de Prado (2020) Ch. 6.
        """
        n = len(cols)
        # Build distance matrix
        dist_matrix = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(n):
                rho = corr_matrix[cols[i]][cols[j]]
                dist_matrix[i, j] = 1.0 - abs(rho)

        condensed = squareform(dist_matrix, checks=False)
        link = linkage(condensed, method="complete")
        cutoff = 1.0 - self._max_correlation
        labels = fcluster(link, t=cutoff, criterion="distance")

        return {cols[i]: int(labels[i]) for i in range(n)}

    @staticmethod
    def _recommend_drops(
        clusters: dict[str, int],
        ic_results: list[ICResult],
        cols: list[str],
    ) -> list[str]:
        """For each cluster with >1 signal, drop all but highest |IC|.

        Signals not present in *ic_results* are assumed IC = 0 (dropped
        first).
        """
        # Build IC lookup
        ic_map: dict[str, float] = {}
        for r in ic_results:
            if r.feature_name is not None:
                ic_map[r.feature_name] = abs(r.ic)

        # Group signals by cluster
        cluster_groups: dict[int, list[str]] = {}
        for sig in cols:
            cid = clusters[sig]
            cluster_groups.setdefault(cid, []).append(sig)

        drops: list[str] = []
        for _cid, members in sorted(cluster_groups.items()):
            if len(members) <= 1:
                continue
            # Sort by |IC| descending; keep top, drop rest
            members_sorted = sorted(members, key=lambda s: ic_map.get(s, 0.0), reverse=True)
            drops.extend(members_sorted[1:])
        return sorted(drops)
