"""Deflated Sharpe Ratio calculator — Phase 3.11.

Wraps the existing ``backtesting.metrics.deflated_sharpe_ratio()`` and
``probabilistic_sharpe_ratio()`` functions into a structured calculator
that produces :class:`DSRResult` dataclasses per feature.

Reference
---------
Bailey, D. H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
*Journal of Portfolio Management*, 40(5), 94-107.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from scipy import stats as scipy_stats

from backtesting.metrics import (
    deflated_sharpe_ratio,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)

# ADR-0004 Step 6 threshold: DSR > 0.95 → significant.
_DSR_SIGNIFICANCE_THRESHOLD: float = 0.95


@dataclass(frozen=True)
class DSRResult:
    """Deflated Sharpe Ratio result for a single feature/strategy.

    Reference: Bailey & López de Prado (2014).
    "The Deflated Sharpe Ratio". JPM, 40(5), 94-107.
    """

    feature_name: str
    sharpe_ratio: float
    psr: float
    dsr: float
    n_trials: int
    n_obs: int
    skewness: float
    kurtosis: float
    min_trl: int
    is_significant: bool  # DSR > 0.95


class DeflatedSharpeCalculator:
    """Compute DSR for a set of features/strategies.

    Accounts for:
    - Number of trials (features tested concurrently)
    - Non-normality of returns (skewness, excess kurtosis)
    - Sample size

    Wraps the battle-tested functions in ``backtesting.metrics`` — no
    reimplementation.

    Reference: Bailey & López de Prado (2014).
    """

    def __init__(
        self,
        significance_threshold: float = _DSR_SIGNIFICANCE_THRESHOLD,
    ) -> None:
        if not (0.0 < significance_threshold < 1.0):
            msg = f"significance_threshold must be in (0, 1), got {significance_threshold}"
            raise ValueError(msg)
        self._threshold = significance_threshold

    def compute(
        self,
        feature_sharpes: dict[str, float],
        returns_data: dict[str, pl.Series],
        benchmark_sharpe: float = 0.0,
    ) -> list[DSRResult]:
        """Compute DSR for each feature.

        Parameters
        ----------
        feature_sharpes : dict
            ``{feature_name: annualised_sharpe_ratio}`` — precomputed
            Sharpes (e.g. from IC-based backtests or CPCV OOS returns).
        returns_data : dict
            ``{feature_name: pl.Series}`` of raw returns used to
            extract skewness, kurtosis, and sample size.
        benchmark_sharpe : float
            Annualised SR* threshold (default 0).

        Returns
        -------
        list[DSRResult]
            One result per feature, ordered by DSR descending.
        """
        if not feature_sharpes:
            return []

        n_trials = len(feature_sharpes)
        results: list[DSRResult] = []

        for name, sr in feature_sharpes.items():
            if name not in returns_data:
                msg = f"Missing returns_data for feature '{name}'"
                raise ValueError(msg)
            ret_series = returns_data[name]
            ret_list = ret_series.to_list()
            n_obs = len(ret_list)

            arr = np.asarray(ret_list, dtype=float)
            skew = float(scipy_stats.skew(arr, bias=False)) if n_obs >= 4 else 0.0
            kurt = float(scipy_stats.kurtosis(arr, bias=False)) if n_obs >= 4 else 0.0

            psr = probabilistic_sharpe_ratio(
                ret_list,
                benchmark_sharpe=benchmark_sharpe,
            )
            dsr = deflated_sharpe_ratio(
                ret_list,
                n_trials=n_trials,
                benchmark_sharpe=benchmark_sharpe,
            )
            min_trl = minimum_track_record_length(
                target_sharpe=max(sr, 1e-10),
                benchmark_sharpe=benchmark_sharpe,
                skewness=skew,
                excess_kurtosis=kurt,
            )

            results.append(
                DSRResult(
                    feature_name=name,
                    sharpe_ratio=sr,
                    psr=psr,
                    dsr=dsr,
                    n_trials=n_trials,
                    n_obs=n_obs,
                    skewness=skew,
                    kurtosis=kurt,
                    min_trl=min_trl,
                    is_significant=dsr > self._threshold,
                )
            )

        results.sort(key=lambda r: r.dsr, reverse=True)
        return results

    def compute_from_returns(
        self,
        returns_data: dict[str, pl.Series],
        benchmark_sharpe: float = 0.0,
    ) -> list[DSRResult]:
        """Convenience: compute Sharpe from returns, then DSR.

        Parameters
        ----------
        returns_data : dict
            ``{feature_name: pl.Series}`` of raw returns.
        benchmark_sharpe : float
            Annualised SR* threshold.

        Returns
        -------
        list[DSRResult]
        """
        feature_sharpes = {
            name: sharpe_ratio(series.to_list()) for name, series in returns_data.items()
        }
        return self.compute(feature_sharpes, returns_data, benchmark_sharpe)
