"""Rough Volatility feature calculator (Gatheral, Jaisson & Rosenbaum 2018).

Wraps S07 RoughVolAnalyzer.estimate_hurst_from_vol() and
variance_ratio_test() with expanding-window refit to prevent
look-ahead bias.

Output columns:
    rough_hurst: Hurst exponent estimate (NaN during warm-up).
    rough_is_rough: 1.0 if H < 0.3 else 0.0 (Gatheral 2018 regime).
    rough_scalping_score: tanh-normalized scalping edge in [-1, +1].
    rough_size_multiplier: Volatility-adaptive sizing multiplier
        (typically in [0.5, 2.0]). Raw S07 analyzer output — NOT
        normalized to [0, 1] or [-1, +1]. Multiplicative factor.
    variance_ratio: Lo-MacKinlay VR(q) statistic (1.0 = random walk).
    vr_signal: tanh-normalized direction signal in [-1, +1].
        VR > 1 -> momentum (positive), VR < 1 -> mean-reversion (negative).

Look-ahead defense:
    Every row t's values are fit on data [0, t-1] only. Expanding
    window refit. O(n^2) by design (same trade-off as HAR-RV, D024).

D028 intraday contract (bar_frequency="5m"):
    All 6 output columns are forecast-like: they use daily_rv[0:t]
    (prior days only, excluding current day t) and are therefore
    safe to broadcast to all intraday bars of day t. No information
    from later bars of the same day is used.

    This differs from HAR-RV where residual/signal required full-day
    RV (day-close-only emission per D027). Rough Vol does NOT compute
    a per-day residual — all outputs are estimates based purely on
    prior days' statistics.

Reference:
    Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is
    rough". Quantitative Finance, 18(6), 933-949.
    Lo, A. W. & MacKinlay, A. C. (1988). "Stock market prices do not
    follow random walks". Review of Financial Studies, 1(1), 41-66.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator
from services.s07_quant_analytics.rough_vol import RoughVolAnalyzer

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class RoughVolCalculator(FeatureCalculator):
    """Rough Volatility calculator (Gatheral, Jaisson & Rosenbaum 2018).

    Wraps S07 RoughVolAnalyzer.estimate_hurst_from_vol() and
    variance_ratio_test() with expanding-window refit to prevent
    look-ahead bias.

    Output contract (D028):
        All 6 output columns are forecast-like: they use daily_rv[0:t]
        (prior days only, excluding current day t) and are therefore
        safe to broadcast to all intraday bars of day t in 5m mode.
        No information from later bars of the same day is used.

    Look-ahead defense (D024):
        Expanding window — values at day t are computed on data [0, t-1].
        O(n^2) by design.

    Reference:
        Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is
        rough". Quantitative Finance, 18(6), 933-949.
        Lo, A. W. & MacKinlay, A. C. (1988). "Stock market prices do not
        follow random walks". Review of Financial Studies, 1(1), 41-66.
    """

    _REQUIRED_COLUMNS: ClassVar[list[str]] = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    _OUTPUT_COLUMNS: ClassVar[list[str]] = [
        "rough_hurst",
        "rough_is_rough",
        "rough_scalping_score",
        "rough_size_multiplier",
        "variance_ratio",
        "vr_signal",
    ]

    def __init__(
        self,
        bar_frequency: Literal["5m", "1d"] = "1d",
        warm_up_days: int = 60,
        vr_lag: int = 5,
        scalping_score_k: float = 3.0,
        vr_signal_k: float = 3.0,
        signal_std_window: int = 60,
    ) -> None:
        """Initialize RoughVolCalculator.

        Args:
            bar_frequency: Input bar granularity. ``"5m"`` bars are
                aggregated to daily RV before Hurst/VR fitting.
            warm_up_days: Minimum number of daily RV observations
                before the first output is produced. Must be >= 30.
            vr_lag: Lo-MacKinlay q parameter (e.g. 5 for weekly).
            scalping_score_k: tanh scale for scalping score (D025).
            vr_signal_k: tanh scale for VR signal centered on 1.0.
            signal_std_window: Rolling window for adaptive std scaling.
        """
        if warm_up_days < 30:
            raise ValueError(
                f"warm_up_days must be >= 30 for stable Hurst estimation, got {warm_up_days}"
            )
        self._bar_frequency = bar_frequency
        self._warm_up_days = warm_up_days
        self._vr_lag = vr_lag
        self._scalping_score_k = scalping_score_k
        self._vr_signal_k = vr_signal_k
        self._signal_std_window = signal_std_window
        self._analyzer = RoughVolAnalyzer()

    # ------------------------------------------------------------------
    # FeatureCalculator ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "rough_vol"

    @property
    def version(self) -> str:
        return "1.0.0"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        return list(self._OUTPUT_COLUMNS)

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute Rough Vol and Variance Ratio columns.

        Expanding-window loop ensures values at day *t* use only data
        [0, t-1]. O(n^2) by design.

        Args:
            df: Input bars with at least :meth:`required_columns`.

        Returns:
            New DataFrame with 6 additional output columns.
        """
        self.validate_input(df)
        n_rows = len(df)

        # Monotonic timestamp invariant (D027 prerequisite).
        if n_rows > 1 and not df["timestamp"].is_sorted():
            raise ValueError(
                "RoughVolCalculator.compute() requires ascending-sorted "
                "'timestamp' to preserve look-ahead safety. "
                "Call df.sort('timestamp') before."
            )

        if n_rows == 0:
            return df.with_columns(
                *[pl.Series(col, [], dtype=pl.Float64) for col in self._OUTPUT_COLUMNS]
            )

        # Step 1: Build daily RV series and row-to-day mapping.
        daily_rv, daily_log_returns, row_to_day = self._build_daily_series(df)
        n_days = len(daily_rv)

        # Step 2: Expanding-window Hurst + VR computation (look-ahead safe).
        day_hurst = np.full(n_days, np.nan)
        day_is_rough = np.full(n_days, np.nan)
        day_edge_score = np.full(n_days, np.nan)
        day_size_mult = np.full(n_days, np.nan)
        day_vr = np.full(n_days, np.nan)

        for t in range(self._warm_up_days, n_days):
            # Hurst from realized vol series [0, t) — expanding window.
            rv_window = daily_rv[:t].tolist()
            # Convert RV to annualized vol for estimate_hurst_from_vol.
            vol_window = [float(np.sqrt(max(v, 0.0)) * np.sqrt(252)) for v in rv_window]
            signal = self._analyzer.estimate_hurst_from_vol(vol_window)
            day_hurst[t] = signal.hurst_exponent
            day_is_rough[t] = 1.0 if signal.is_rough else 0.0
            day_edge_score[t] = signal.scalping_edge_score
            day_size_mult[t] = float(signal.size_adjustment)

            # VR from log-return series [0, t) — expanding window.
            lr_window = daily_log_returns[:t].tolist()
            vr_result = self._analyzer.variance_ratio_test(lr_window, q=self._vr_lag)
            day_vr[t] = vr_result.vr_q

        # Step 3: Normalize scalping score and VR signal via tanh (D025).
        day_scalping_score = self._compute_scalping_signal(day_edge_score)
        day_vr_signal = self._compute_vr_signal(day_vr)

        # Step 4: Map daily arrays to bar-level rows.
        out_hurst = np.full(n_rows, np.nan)
        out_is_rough = np.full(n_rows, np.nan)
        out_scalping = np.full(n_rows, np.nan)
        out_size_mult = np.full(n_rows, np.nan)
        out_vr = np.full(n_rows, np.nan)
        out_vr_sig = np.full(n_rows, np.nan)

        # D028: All 6 columns are forecast-like (use daily_rv[:t], prior
        # days only). Safe to broadcast to all intraday bars of day t.
        for row_idx in range(n_rows):
            day_idx = row_to_day[row_idx]
            if day_idx < 0:
                continue
            out_hurst[row_idx] = day_hurst[day_idx]
            out_is_rough[row_idx] = day_is_rough[day_idx]
            out_scalping[row_idx] = day_scalping_score[day_idx]
            out_size_mult[row_idx] = day_size_mult[day_idx]
            out_vr[row_idx] = day_vr[day_idx]
            out_vr_sig[row_idx] = day_vr_signal[day_idx]

        logger.info(
            "rough_vol.compute.complete",
            n_rows=n_rows,
            n_days=n_days,
            warm_up=self._warm_up_days,
            bar_frequency=self._bar_frequency,
            outputs_produced=int(np.sum(~np.isnan(out_hurst))),
        )

        return df.with_columns(
            pl.Series("rough_hurst", out_hurst),
            pl.Series("rough_is_rough", out_is_rough),
            pl.Series("rough_scalping_score", out_scalping),
            pl.Series("rough_size_multiplier", out_size_mult),
            pl.Series("variance_ratio", out_vr),
            pl.Series("vr_signal", out_vr_sig),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_daily_series(
        self, df: pl.DataFrame
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], list[int]]:
        """Build daily RV and log-return series with row-to-day mapping.

        Returns:
            daily_rv: 1-D array of daily realized variance.
            daily_log_returns: 1-D array of daily log-returns.
            row_to_day: List mapping each row to a day index (-1 if none).
        """
        if self._bar_frequency == "5m":
            return self._build_from_5m(df)
        return self._build_from_1d(df)

    def _build_from_1d(
        self, df: pl.DataFrame
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], list[int]]:
        """Daily series from 1d bars: squared log-return as RV proxy."""
        closes = df["close"].to_numpy().astype(np.float64)
        n = len(closes)

        if n < 2:
            return (
                np.array([], dtype=np.float64),
                np.array([], dtype=np.float64),
                [-1] * n,
            )

        log_returns = np.log(closes[1:] / closes[:-1])
        daily_rv = log_returns**2

        row_to_day: list[int] = [-1]  # Row 0 has no prior close.
        for i in range(len(daily_rv)):
            row_to_day.append(i)

        return daily_rv, log_returns, row_to_day

    def _build_from_5m(
        self, df: pl.DataFrame
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], list[int]]:
        """Daily series from 5m bars: sum of squared intraday log-returns."""
        timestamps = df["timestamp"]
        closes = df["close"].to_numpy().astype(np.float64)

        if timestamps.dtype == pl.Utf8:
            dates = timestamps.str.slice(0, 10).to_list()
        else:
            dates = [str(t)[:10] for t in timestamps.to_list()]

        unique_dates: list[str] = []
        date_set: set[str] = set()
        for d in dates:
            if d not in date_set:
                unique_dates.append(d)
                date_set.add(d)

        date_to_idx: dict[str, int] = {d: i for i, d in enumerate(unique_dates)}

        day_rows: list[list[int]] = [[] for _ in range(len(unique_dates))]
        for row_idx, d in enumerate(dates):
            day_rows[date_to_idx[d]].append(row_idx)

        daily_rv_list: list[float] = []
        daily_lr_list: list[float] = []
        for rows in day_rows:
            if len(rows) < 2:
                daily_rv_list.append(0.0)
                daily_lr_list.append(0.0)
                continue
            day_closes = closes[rows]
            intraday_returns = np.log(day_closes[1:] / day_closes[:-1])
            rv = float(np.sum(intraday_returns**2))
            daily_rv_list.append(rv)
            # Daily log-return from close-to-close intraday bars:
            # sum(log(C_t / C_{t-1})) = log(last_close / first_close).
            daily_lr_list.append(float(np.sum(intraday_returns)))

        daily_rv = np.array(daily_rv_list, dtype=np.float64)
        daily_lr = np.array(daily_lr_list, dtype=np.float64)

        row_to_day: list[int] = [date_to_idx[d] for d in dates]
        return daily_rv, daily_lr, row_to_day

    def _compute_scalping_signal(
        self, day_edge_scores: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """Normalize edge scores to [-1, +1] via tanh with adaptive std (D025).

        The raw edge score from S07 is in [0, 1]. We center it around
        its expanding/rolling mean and normalize via tanh.
        """
        n = len(day_edge_scores)
        signals = np.full(n, np.nan)
        history: list[float] = []

        for t in range(n):
            if np.isnan(day_edge_scores[t]):
                continue
            history.append(float(day_edge_scores[t]))
            if len(history) < 2:
                signals[t] = 0.0
                continue

            window = history[-self._signal_std_window :]
            mean = float(np.mean(window))
            std = float(np.std(window, ddof=1))
            scale = self._scalping_score_k * std

            if scale < 1e-15:
                signals[t] = 0.0
            else:
                signals[t] = float(np.tanh((day_edge_scores[t] - mean) / scale))

        return signals

    def _compute_vr_signal(self, day_vr: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Normalize VR around 1.0 to [-1, +1] via tanh (D025).

        VR > 1 → momentum (positive signal).
        VR < 1 → mean-reversion (negative signal).
        VR = 1 → random walk (zero signal).
        """
        n = len(day_vr)
        signals = np.full(n, np.nan)
        history: list[float] = []

        for t in range(n):
            if np.isnan(day_vr[t]):
                continue
            history.append(float(day_vr[t]))
            if len(history) < 2:
                signals[t] = 0.0
                continue

            window = history[-self._signal_std_window :]
            std = float(np.std(window, ddof=1))
            scale = self._vr_signal_k * std

            if scale < 1e-15:
                signals[t] = 0.0
            else:
                # Center on 1.0 (random walk baseline).
                signals[t] = float(np.tanh((day_vr[t] - 1.0) / scale))

        return signals
