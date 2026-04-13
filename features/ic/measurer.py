"""SpearmanICMeasurer — concrete IC measurement with HAC correction.

Implements the :class:`ICMetric` ABC using Spearman rank correlation
with Newey-West HAC-corrected t-statistics for overlapping forward
returns.

References:
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
    Management* (2nd ed.). McGraw-Hill, Ch. 6, 16.

    Newey, W. K. & West, K. D. (1987). "A Simple, Positive
    Semi-Definite, Heteroskedasticity and Autocorrelation Consistent
    Covariance Matrix." *Econometrica*, 55(3), 703-708.

    Lopez de Prado, M. (2018). *Advances in Financial Machine
    Learning*. Wiley, Ch. 7.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.ic.base import ICMetric, ICResult
from features.ic.stats import (
    ic_bootstrap_ci,
    ic_t_statistic,
    newey_west_se,
    safe_spearman,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Feature must have at least this many non-NaN observations.
_MIN_SAMPLES: int = 20


class SpearmanICMeasurer(ICMetric):
    """Spearman-based IC measurement with HAC-corrected t-stat.

    Computes the Information Coefficient as the Spearman rank
    correlation between feature values at time *t* and forward
    returns over the target horizon.  Rolling IC is computed over
    a sliding window, and the t-statistic is corrected for
    overlapping-return autocorrelation via Newey-West (1987).

    Args:
        rolling_window: Default window size for rolling IC
            computation (in bars).
        horizons: Tuple of horizons (in bars) for IC-decay
            measurement.
        turnover_cost_bps: Assumed turnover cost in basis points
            for turnover-adjusted IC.
        bootstrap_n: Number of bootstrap replications for the
            confidence interval.

    Reference:
        Grinold, R. C. & Kahn, R. N. (1999). Ch. 6, 16.
    """

    def __init__(
        self,
        rolling_window: int = 252,
        horizons: tuple[int, ...] = (1, 5, 10, 20),
        turnover_cost_bps: float = 10.0,
        bootstrap_n: int = 1000,
    ) -> None:
        self._rolling_window = rolling_window
        self._horizons = horizons
        self._turnover_cost_bps = turnover_cost_bps
        self._bootstrap_n = bootstrap_n

    # ── ICMetric ABC ────────────────────────────────────────────────

    def measure(
        self,
        feature: npt.NDArray[np.float64],
        forward_returns: npt.NDArray[np.float64],
    ) -> ICResult:
        """Measure IC of *feature* against *forward_returns*.

        This is the ABC-mandated signature (two numpy arrays in,
        ICResult out).  For the richer API with feature names and
        horizons, use :meth:`measure_rich`.
        """
        return self.measure_rich(
            feature=feature,
            forward_returns=forward_returns,
            feature_name="unknown",
            horizon_bars=1,
        )

    # ── Rich API ────────────────────────────────────────────────────

    def measure_rich(
        self,
        feature: npt.NDArray[np.float64],
        forward_returns: npt.NDArray[np.float64],
        feature_name: str,
        horizon_bars: int = 1,
    ) -> ICResult:
        """Core IC measurement at a single horizon.

        Args:
            feature: 1-D array of feature values.
            forward_returns: 1-D array of forward returns, aligned
                to *feature* timestamps.
            feature_name: Human-readable feature identifier.
            horizon_bars: Forward-return horizon in bars (used for
                Newey-West lag selection).

        Returns:
            Fully populated :class:`ICResult`.
        """
        # Align and clean NaN.
        mask = np.isfinite(feature) & np.isfinite(forward_returns)
        feat_clean = feature[mask]
        ret_clean = forward_returns[mask]

        if feat_clean.size < _MIN_SAMPLES:
            logger.warning(
                "ic.insufficient_data",
                feature=feature_name,
                n_valid=int(feat_clean.size),
                min_required=_MIN_SAMPLES,
            )
            return self._empty_result(feature_name, horizon_bars)

        # Per-period rolling IC series.
        ic_series = self._compute_ic_series(feat_clean, ret_clean, horizon_bars)

        if ic_series.size < 2:
            return self._empty_result(feature_name, horizon_bars)

        ic_mean = float(np.mean(ic_series))
        ic_std = float(np.std(ic_series, ddof=1))

        # Degenerate case: all per-block ICs are identical (e.g.
        # perfect predictor). std==0 means perfectly stable IC —
        # this is the BEST case, not an error.
        if ic_std < 1e-15 and abs(ic_mean) > 1e-15:
            ic_ir = float(np.sign(ic_mean)) * 1e6  # effectively infinite
            t_stat = float(np.sign(ic_mean)) * 1e6
            p_value = 0.0
        elif ic_std < 1e-15:
            ic_ir = 0.0
            t_stat = 0.0
            p_value = 1.0
        else:
            ic_ir = ic_mean / ic_std

            # Newey-West corrected t-stat.
            nw_lags = max(horizon_bars - 1, 0)
            t_stat = ic_t_statistic(ic_series, horizon_bars)

            # p-value from two-sided t-test using HAC SE.
            nw_se = newey_west_se(ic_series, lags=nw_lags)
            if nw_se > 1e-15:
                from scipy import stats as sp_stats

                p_value = float(
                    2.0 * (1.0 - sp_stats.t.cdf(abs(t_stat), df=max(ic_series.size - 1, 1)))
                )
            else:
                p_value = 1.0

        nw_lags = max(horizon_bars - 1, 0)

        # Bootstrap CI.
        ci_low, ci_high = ic_bootstrap_ci(
            ic_series,
            confidence=0.95,
            n_boot=self._bootstrap_n,
            block_size=max(1, horizon_bars),
        )

        # Hit rate — fraction of IC values with correct sign.
        if abs(ic_mean) > 1e-15:
            correct_sign = np.sign(ic_series) == np.sign(ic_mean)
            hit_rate = float(np.mean(correct_sign))
        else:
            hit_rate = 0.5

        # Turnover-adjusted IC.
        turnover_adj = self._turnover_adj(ic_mean, feat_clean)

        is_sig = abs(t_stat) > 1.96

        return ICResult(
            ic=ic_mean,
            ic_ir=ic_ir,
            p_value=p_value,
            n_samples=int(ic_series.size),
            ci_low=ci_low,
            ci_high=ci_high,
            feature_name=feature_name,
            ic_std=ic_std,
            ic_t_stat=t_stat,
            ic_hit_rate=hit_rate,
            turnover_adj_ic=turnover_adj,
            ic_decay=None,  # Populated by measure_all / ic_decay
            is_significant=is_sig,
            horizon_bars=horizon_bars,
            newey_west_lags=nw_lags,
        )

    def measure_all(
        self,
        features: pl.DataFrame,
        forward_returns_by_horizon: dict[int, npt.NDArray[np.float64]],
        feature_names: list[str],
    ) -> list[ICResult]:
        """Batch IC measurement across features and horizons.

        Args:
            features: DataFrame with timestamp + feature columns.
            forward_returns_by_horizon: Mapping from horizon to
                1-D array of forward returns.
            feature_names: Column names in *features* to evaluate.

        Returns:
            List of :class:`ICResult`, one per (feature, horizon).
        """
        results: list[ICResult] = []
        for name in feature_names:
            feat_arr = np.asarray(features[name].to_numpy(), dtype=np.float64)
            # Compute decay once per feature (independent of horizon).
            decay = self._ic_decay(feat_arr, forward_returns_by_horizon)
            for h, fwd in sorted(forward_returns_by_horizon.items()):
                result = self.measure_rich(
                    feature=feat_arr,
                    forward_returns=fwd,
                    feature_name=name,
                    horizon_bars=h,
                )
                result = dataclasses.replace(result, ic_decay=decay)
                results.append(result)
        return results

    def rolling_ic(
        self,
        feature: npt.NDArray[np.float64],
        forward_returns: npt.NDArray[np.float64],
        window: int | None = None,
    ) -> pl.DataFrame:
        """Rolling IC time series.

        Args:
            feature: 1-D feature array.
            forward_returns: 1-D forward-return array.
            window: Rolling window size.  Defaults to
                ``self._rolling_window``.

        Returns:
            DataFrame with columns ``[period, ic]``.
        """
        if window is None:
            window = self._rolling_window

        n = feature.size
        ic_values: list[float] = []
        periods: list[int] = []
        for end in range(window, n + 1):
            start = end - window
            ic_val, _ = safe_spearman(feature[start:end], forward_returns[start:end])
            ic_values.append(ic_val)
            periods.append(end - 1)

        return pl.DataFrame({"period": periods, "ic": ic_values})

    # ── Internal helpers ────────────────────────────────────────────

    def _compute_ic_series(
        self,
        feature: npt.NDArray[np.float64],
        forward_returns: npt.NDArray[np.float64],
        horizon_bars: int,
    ) -> npt.NDArray[np.float64]:
        """Compute per-period IC via stepped rolling windows.

        Uses a rolling window of size ``max(rolling_window, horizon *
        10)`` advanced by ``step = max(horizon_bars, 1)`` positions.
        Windows **may overlap** when ``window > step``; the residual
        autocorrelation this introduces is handled by the Newey-West
        HAC correction applied downstream in :meth:`measure_rich`.

        Falls back to equal-sized non-overlapping blocks when the
        stepped approach yields fewer than 3 IC observations.
        """
        n = feature.size
        block_size = max(horizon_bars, 1)

        # Use rolling window with step = block_size for smoother IC series.
        window = max(self._rolling_window, block_size * 10)
        step = block_size

        ic_vals: list[float] = []
        pos = 0
        while pos + window <= n:
            ic_val, _ = safe_spearman(
                feature[pos : pos + window],
                forward_returns[pos : pos + window],
            )
            ic_vals.append(ic_val)
            pos += step

        # If we got too few blocks, fall back to fewer, larger blocks.
        if len(ic_vals) < 3:
            n_blocks = max(3, n // max(block_size * 10, 1))
            block_len = n // n_blocks if n_blocks > 0 else n
            ic_vals = []
            for i in range(n_blocks):
                s = i * block_len
                e = s + block_len if i < n_blocks - 1 else n
                if e - s >= 5:
                    ic_val, _ = safe_spearman(feature[s:e], forward_returns[s:e])
                    ic_vals.append(ic_val)

        return np.array(ic_vals, dtype=np.float64)

    def _turnover_adj(
        self,
        ic: float,
        feature: npt.NDArray[np.float64],
    ) -> float:
        """IC adjusted for feature turnover cost.

        Turnover is estimated as the mean absolute rank change per
        period, normalized by the number of observations.
        ``turnover_adj_ic = ic - turnover * cost_bps / 10_000``.
        """
        if feature.size < 2:
            return ic

        from scipy.stats import rankdata

        ranks = rankdata(feature)
        # Mean absolute rank change between consecutive periods.
        rank_changes = np.abs(np.diff(ranks))
        mean_change = float(np.mean(rank_changes))
        turnover = mean_change / feature.size

        cost = turnover * self._turnover_cost_bps / 10_000.0
        return ic - cost if ic >= 0 else ic + cost

    def _ic_decay(
        self,
        feature: npt.NDArray[np.float64],
        returns_by_horizon: dict[int, npt.NDArray[np.float64]],
    ) -> tuple[float, ...]:
        """IC at each configured horizon in ``self._horizons``.

        Horizons missing from *returns_by_horizon* or with fewer than
        ``_MIN_SAMPLES`` valid pairs are reported as ``0.0`` to keep
        the decay tuple shape stable and in configured order.
        """
        decay: list[float] = []
        for h in self._horizons:
            fwd = returns_by_horizon.get(h)
            if fwd is None:
                decay.append(0.0)
                continue
            mask = np.isfinite(feature) & np.isfinite(fwd)
            if mask.sum() < _MIN_SAMPLES:
                decay.append(0.0)
                continue
            ic_val, _ = safe_spearman(feature[mask], fwd[mask])
            decay.append(ic_val)
        return tuple(decay)

    @staticmethod
    def _empty_result(
        feature_name: str,
        horizon_bars: int,
    ) -> ICResult:
        """Return a zero-valued ICResult for insufficient data."""
        return ICResult(
            ic=0.0,
            ic_ir=0.0,
            p_value=1.0,
            n_samples=0,
            ci_low=0.0,
            ci_high=0.0,
            feature_name=feature_name,
            ic_std=0.0,
            ic_t_stat=0.0,
            ic_hit_rate=0.0,
            turnover_adj_ic=0.0,
            ic_decay=None,
            is_significant=False,
            horizon_bars=horizon_bars,
            newey_west_lags=max(horizon_bars - 1, 0),
        )
