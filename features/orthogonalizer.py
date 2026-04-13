"""Feature orthogonalization for correlated signal pairs.

Three strategies (in order of preference):

1. **drop_lowest_ic** — drop the lower-IC signal in each correlated
   cluster.  Simplest, most interpretable, recommended default.
2. **residualize** — regress each lower-IC signal on the higher-IC
   signal within each cluster, keep the OLS residual.  Preserves
   unique information but risks look-ahead if not time-indexed.
3. **pca** — replace correlated cluster members with their first
   principal component.  Last resort — components lose interpretability.

This module is an **analysis / research tool**, not a production
calculator.  Production would select one strategy and bake the result
into the feature pipeline.

References:
    Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*,
    Ch. 6. Cambridge University Press.

    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*,
    Ch. 8. Wiley.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import polars as pl

from features.multicollinearity import MulticollinearityReport

# ---------------------------------------------------------------------------
# Type alias for the three supported methods.
# ---------------------------------------------------------------------------
OrthogonalizationMethod = Literal["drop_lowest_ic", "residualize", "pca"]


class FeatureOrthogonalizer:
    """Orthogonalizes correlated features via drop, residualization, or PCA.

    When two features are highly correlated, either:

    1. Drop the one with lower IC (recommended).
    2. Residualize: regress the lower-IC feature on the higher-IC one,
       keep the residual (preserves unique information).
    3. PCA: replace correlated set with its first principal component.

    Reference:
        Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*,
        Ch. 6. Cambridge University Press.
    """

    def orthogonalize(
        self,
        feature_matrix: pl.DataFrame,
        report: MulticollinearityReport,
        method: OrthogonalizationMethod = "drop_lowest_ic",
    ) -> pl.DataFrame:
        """Apply the chosen orthogonalization strategy.

        Parameters
        ----------
        feature_matrix:
            DataFrame containing at least the signal columns listed in
            *report.signal_columns*.
        report:
            Output of :meth:`MulticollinearityAnalyzer.analyze`.
        method:
            ``"drop_lowest_ic"`` | ``"residualize"`` | ``"pca"``.

        Returns
        -------
        pl.DataFrame
            Copy of *feature_matrix* with collinear signals resolved
            according to the chosen method.

        Raises
        ------
        ValueError
            If an unknown method is requested.
        """
        if method == "drop_lowest_ic":
            return self._drop_lowest_ic(feature_matrix, report)
        if method == "residualize":
            return self._residualize(feature_matrix, report)
        if method == "pca":
            return self._pca(feature_matrix, report)
        raise ValueError(
            f"Unknown orthogonalization method: {method!r}. "
            f"Expected one of 'drop_lowest_ic', 'residualize', 'pca'."
        )

    # ------------------------------------------------------------------
    # Strategy 1: drop lowest IC
    # ------------------------------------------------------------------

    @staticmethod
    def _drop_lowest_ic(
        feature_matrix: pl.DataFrame,
        report: MulticollinearityReport,
    ) -> pl.DataFrame:
        """Drop the columns recommended by the analyzer."""
        if not report.recommended_drops:
            return feature_matrix
        cols_to_drop = [c for c in report.recommended_drops if c in feature_matrix.columns]
        return feature_matrix.drop(cols_to_drop)

    # ------------------------------------------------------------------
    # Strategy 2: residualize
    # ------------------------------------------------------------------

    @staticmethod
    def _residualize(
        feature_matrix: pl.DataFrame,
        report: MulticollinearityReport,
    ) -> pl.DataFrame:
        """Replace each dropped signal with its OLS residual.

        For each correlated cluster with > 1 member, the highest-IC
        signal is kept untouched.  Every other signal in the cluster
        is replaced by the OLS residual of that signal regressed on
        the kept signal (+ intercept).

        NaN rows are preserved: OLS is fitted on non-NaN rows only,
        and NaN positions in the output match the original.
        """
        if not report.recommended_drops:
            return feature_matrix

        # Group by cluster — identify keeper vs residualized
        cluster_groups: dict[int, list[str]] = {}
        for sig in report.signal_columns:
            cid = report.cluster_assignments[sig]
            cluster_groups.setdefault(cid, []).append(sig)

        result = feature_matrix.clone()

        for _cid, members in sorted(cluster_groups.items()):
            if len(members) <= 1:
                continue
            # Keeper = the one NOT in recommended_drops
            keepers = [m for m in members if m not in report.recommended_drops]
            to_residualize = [m for m in members if m in report.recommended_drops]
            if not keepers:
                continue  # all would be dropped; skip
            keeper = keepers[0]

            for sig in to_residualize:
                x_series = result[keeper].to_numpy().astype(np.float64)
                y_series = result[sig].to_numpy().astype(np.float64)

                # Mask for non-NaN in both
                valid = np.isfinite(x_series) & np.isfinite(y_series)
                n_valid = int(np.sum(valid))
                if n_valid < 2:
                    continue  # not enough data to regress

                x_valid = x_series[valid]
                y_valid = y_series[valid]

                # OLS: y = a + b*x + residual
                x_aug = np.column_stack([x_valid, np.ones(n_valid, dtype=np.float64)])
                coefs, _res, _rank, _sv = np.linalg.lstsq(x_aug, y_valid, rcond=None)

                # Compute residuals on valid rows
                residuals = y_valid - x_aug @ coefs

                # Build full-length column preserving NaN positions
                new_col = np.full(len(y_series), np.nan, dtype=np.float64)
                new_col[valid] = residuals

                result = result.with_columns(pl.Series(name=sig, values=new_col))

        return result

    # ------------------------------------------------------------------
    # Strategy 3: PCA
    # ------------------------------------------------------------------

    @staticmethod
    def _pca(
        feature_matrix: pl.DataFrame,
        report: MulticollinearityReport,
    ) -> pl.DataFrame:
        """Replace each correlated cluster with its first PC.

        For single-member clusters, the column is kept untouched.
        For multi-member clusters, all members are dropped and replaced
        by a single column named ``pc_{cluster_id}``.

        NaN handling: PCA is fitted on rows where ALL cluster members
        are non-NaN.  NaN rows in the output match the original union
        of NaN positions.
        """
        cluster_groups: dict[int, list[str]] = {}
        for sig in report.signal_columns:
            cid = report.cluster_assignments[sig]
            cluster_groups.setdefault(cid, []).append(sig)

        result = feature_matrix.clone()

        for cid, members in sorted(cluster_groups.items()):
            if len(members) <= 1:
                continue

            # Extract arrays
            arrays = [result[m].to_numpy().astype(np.float64) for m in members]
            stacked = np.column_stack(arrays)  # (n_rows, n_members)
            valid = np.all(np.isfinite(stacked), axis=1)
            n_valid = int(np.sum(valid))
            if n_valid < 2:
                continue

            sub = stacked[valid]
            # Center
            means = sub.mean(axis=0)
            centered = sub - means
            # Covariance and first eigenvector
            cov = centered.T @ centered / (n_valid - 1)
            _eigenvalues, eigenvectors = np.linalg.eigh(cov)
            # eigh returns ascending order — last is largest
            pc1_direction = eigenvectors[:, -1]
            pc1_scores = centered @ pc1_direction

            # Build full-length column
            new_col = np.full(stacked.shape[0], np.nan, dtype=np.float64)
            new_col[valid] = pc1_scores

            # Drop cluster members, add PC column
            result = result.drop(members)
            result = result.with_columns(pl.Series(name=f"pc_{cid}", values=new_col))

        return result
