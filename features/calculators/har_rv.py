"""HAR-RV feature calculator (Corsi 2009).

Wraps S07 RealizedVolEstimator.har_rv_forecast() with an expanding-window
refit to prevent look-ahead bias. The HAR-RV model decomposes realized
volatility into daily, weekly (5-day avg), and monthly (22-day avg)
components, capturing heterogeneous market participant horizons.

Output columns:
    har_rv_forecast: Next-period RV forecast (NaN during warm-up).
    har_rv_residual: realized_rv - har_rv_forecast (NaN during warm-up).
    har_rv_signal: tanh-normalized residual in [-1, +1]. Positive = vol
        higher than forecast (potential mean-reversion). Sign convention
        is NOT a trading direction — that is Signal Engine's concern.

Look-ahead defense:
    Forecasts at time t are fit on data [0, t-1] only (expanding window).
    The coefficients beta_D, beta_W, beta_M never see future data. This is O(n^2)
    by design — correctness before optimization.

Reference:
    Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
    Volatility". Journal of Financial Econometrics, 7(2), 174-196.
    Andersen, T. G., Bollerslev, T., Diebold, F. X. & Labys, P. (2003).
    "Modeling and Forecasting Realized Volatility". Econometrica, 71(2).
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator
from services.quant_analytics.realized_vol import RealizedVolEstimator

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class HARRVCalculator(FeatureCalculator):
    """HAR-RV feature calculator (Corsi 2009).

    Wraps S07 RealizedVolEstimator.har_rv_forecast() with an expanding-window
    refit to prevent look-ahead bias. The HAR-RV model decomposes realized
    volatility into daily, weekly (5-day avg), and monthly (22-day avg)
    components, capturing heterogeneous market participant horizons.

    Output contract:
        har_rv_forecast: Available on every row after warm-up (depends only on
            past days — safe to broadcast to all intraday bars).
        har_rv_residual / har_rv_signal:
            - Daily mode: available on every row after warm-up.
            - 5m mode: available ONLY on the last bar of each complete day,
              because residual = realized_rv - forecast and realized_rv
              requires full-day data. Broadcasting to earlier bars would leak
              future intraday bars into them (D027).

    Look-ahead defense:
        Forecasts at time t are fit on data [0, t-1] only (expanding window).
        The coefficients beta_D, beta_W, beta_M never see future data. This is
        O(n^2) by design — correctness before optimization.

    Reference:
        Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
        Volatility". Journal of Financial Econometrics, 7(2), 174-196.
        Andersen, T. G., Bollerslev, T., Diebold, F. X. & Labys, P. (2003).
        "Modeling and Forecasting Realized Volatility". Econometrica, 71(2).
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
        "har_rv_forecast",
        "har_rv_residual",
        "har_rv_signal",
    ]

    def __init__(
        self,
        bar_frequency: Literal["5m", "1d"] = "1d",
        warm_up_periods: int = 30,
        signal_scale_k: float = 3.0,
        signal_std_window: int = 60,
    ) -> None:
        """Initialize HARRVCalculator.

        Args:
            bar_frequency: Input bar granularity. ``"5m"`` bars are
                aggregated to daily RV before HAR-RV fitting.
                ``"1d"`` uses squared daily log-returns as RV proxy.
            warm_up_periods: Minimum number of daily RV observations
                before the first HAR-RV forecast is produced.
                Must be >= 25 (monthly lag requirement).
            signal_scale_k: Multiplier for the rolling std used to
                normalize residuals via tanh. Default 3.0 prevents
                saturation to +/-1 on normally distributed residuals.
            signal_std_window: Rolling window (in days) for the
                residual standard deviation used in signal scaling.
        """
        if warm_up_periods < 25:
            raise ValueError(
                f"warm_up_periods must be >= 25 (HAR monthly lag), got {warm_up_periods}"
            )
        self._bar_frequency = bar_frequency
        self._warm_up_periods = warm_up_periods
        self._signal_scale_k = signal_scale_k
        self._signal_std_window = signal_std_window
        self._estimator = RealizedVolEstimator()

    # ------------------------------------------------------------------
    # FeatureCalculator ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "har_rv"

    @property
    def version(self) -> str:
        return "1.0.0"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        return list(self._OUTPUT_COLUMNS)

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute HAR-RV forecast, residual, and signal columns.

        The expanding-window loop ensures that the forecast at day *t*
        is fitted on daily RV observations ``[0, t-1]`` only — no
        look-ahead.  This is O(n^2) by design.

        Args:
            df: Input bars with at least the columns declared by
                :meth:`required_columns`.

        Returns:
            New DataFrame with three additional columns:
            ``har_rv_forecast``, ``har_rv_residual``, ``har_rv_signal``.
        """
        self.validate_input(df)
        n_rows = len(df)

        # Monotonic timestamp invariant — prerequisite for look-ahead defense.
        if n_rows > 1 and not df["timestamp"].is_sorted():
            raise ValueError(
                "HARRVCalculator.compute() requires ascending-sorted "
                "'timestamp' to preserve look-ahead safety. "
                "Call df.sort('timestamp') before."
            )

        if n_rows == 0:
            return df.with_columns(
                pl.Series("har_rv_forecast", [], dtype=pl.Float64),
                pl.Series("har_rv_residual", [], dtype=pl.Float64),
                pl.Series("har_rv_signal", [], dtype=pl.Float64),
            )

        # Step 1: Build daily RV series and row-to-day mapping.
        daily_rv, row_to_day = self._build_daily_rv(df)
        n_days = len(daily_rv)

        # Step 2: Expanding-window HAR-RV forecasts (look-ahead safe).
        day_forecasts = np.full(n_days, np.nan)
        for t in range(self._warm_up_periods, n_days):
            forecast = self._estimator.har_rv_forecast(daily_rv[:t].tolist())
            day_forecasts[t] = forecast.forecast_rv

        # Step 3: Residuals = realized - forecast.
        day_residuals = np.full(n_days, np.nan)
        valid = ~np.isnan(day_forecasts)
        day_residuals[valid] = daily_rv[valid] - day_forecasts[valid]

        # Step 4: Signal = tanh(residual / scale).
        day_signals = self._compute_signal(day_residuals)

        # Step 5: Map daily-level arrays back to bar-level rows.
        forecasts = np.full(n_rows, np.nan)
        residuals = np.full(n_rows, np.nan)
        signals = np.full(n_rows, np.nan)

        # In 5m mode, residual/signal depend on full-day RV and are only
        # point-in-time safe at the last bar of each day.  Forecast depends
        # only on prior days and is safe to broadcast to all bars (D027).
        day_last_row = np.full(n_days, -1, dtype=np.int64)
        for row_idx in range(n_rows):
            day_idx = row_to_day[row_idx]
            if day_idx >= 0:
                day_last_row[day_idx] = row_idx

        intraday_last_bar_only = self._bar_frequency == "5m"

        for row_idx in range(n_rows):
            day_idx = row_to_day[row_idx]
            if day_idx >= 0:
                forecasts[row_idx] = day_forecasts[day_idx]
                if (not intraday_last_bar_only) or (row_idx == day_last_row[day_idx]):
                    residuals[row_idx] = day_residuals[day_idx]
                    signals[row_idx] = day_signals[day_idx]

        logger.info(
            "har_rv.compute.complete",
            n_rows=n_rows,
            n_days=n_days,
            warm_up=self._warm_up_periods,
            bar_frequency=self._bar_frequency,
            forecasts_produced=int(np.sum(~np.isnan(forecasts))),
        )

        return df.with_columns(
            pl.Series("har_rv_forecast", forecasts),
            pl.Series("har_rv_residual", residuals),
            pl.Series("har_rv_signal", signals),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_daily_rv(self, df: pl.DataFrame) -> tuple[npt.NDArray[np.float64], list[int]]:
        """Compute daily RV series and row-to-day index mapping.

        Returns:
            daily_rv: 1-D array of daily realized variance values.
            row_to_day: List mapping each original row index to a
                daily RV index, or -1 if no RV is available for
                that row.
        """
        if self._bar_frequency == "5m":
            return self._build_daily_rv_from_5m(df)
        return self._build_daily_rv_from_1d(df)

    def _build_daily_rv_from_1d(
        self, df: pl.DataFrame
    ) -> tuple[npt.NDArray[np.float64], list[int]]:
        """Daily RV from 1d bars: squared log-return per day.

        Row 0 has no prior close, so it maps to day_idx = -1.
        Row i (i >= 1) maps to day_idx = i - 1.
        """
        closes = df["close"].to_numpy().astype(np.float64)
        n = len(closes)

        if n < 2:
            return np.array([], dtype=np.float64), [-1] * n

        log_returns = np.log(closes[1:] / closes[:-1])
        daily_rv = log_returns**2

        row_to_day: list[int] = [-1]  # Row 0 → no RV
        for i in range(len(daily_rv)):
            row_to_day.append(i)

        return daily_rv, row_to_day

    def _build_daily_rv_from_5m(
        self, df: pl.DataFrame
    ) -> tuple[npt.NDArray[np.float64], list[int]]:
        """Daily RV from 5m bars: sum of squared intraday log-returns per day.

        Groups bars by calendar date. Within each day, computes
        intraday log-returns and sums their squares (realized variance).
        """
        timestamps = df["timestamp"]
        closes = df["close"].to_numpy().astype(np.float64)

        # Extract date from timestamp for grouping.
        if timestamps.dtype == pl.Utf8:
            dates = timestamps.str.slice(0, 10).to_list()
        else:
            dates = [str(t)[:10] for t in timestamps.to_list()]

        # Identify unique dates in order.
        unique_dates: list[str] = []
        date_set: set[str] = set()
        for d in dates:
            if d not in date_set:
                unique_dates.append(d)
                date_set.add(d)

        date_to_idx: dict[str, int] = {d: i for i, d in enumerate(unique_dates)}

        # Group row indices by date.
        day_rows: list[list[int]] = [[] for _ in range(len(unique_dates))]
        for row_idx, d in enumerate(dates):
            day_rows[date_to_idx[d]].append(row_idx)

        # Compute RV per day from intraday returns.
        daily_rv_list: list[float] = []
        for rows in day_rows:
            if len(rows) < 2:
                daily_rv_list.append(0.0)
                continue
            day_closes = closes[rows]
            intraday_returns = np.log(day_closes[1:] / day_closes[:-1])
            rv = float(np.sum(intraday_returns**2))
            daily_rv_list.append(rv)

        daily_rv = np.array(daily_rv_list, dtype=np.float64)

        # Map each row to its day index.
        row_to_day: list[int] = [date_to_idx[d] for d in dates]

        return daily_rv, row_to_day

    def _compute_signal(
        self,
        day_residuals: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Normalize residuals to [-1, +1] via tanh with adaptive scaling.

        Uses expanding std until ``signal_std_window`` residuals are
        available, then switches to rolling std. This avoids unnecessary
        NaN propagation while maintaining a stable scale estimate.

        Args:
            day_residuals: Daily residual array (may contain NaN).

        Returns:
            Signal array in [-1, +1] with NaN where residual is NaN.
        """
        n = len(day_residuals)
        signals = np.full(n, np.nan)
        residual_history: list[float] = []

        for t in range(n):
            if np.isnan(day_residuals[t]):
                continue

            residual_history.append(float(day_residuals[t]))

            if len(residual_history) < 2:
                # Single residual: no scale reference, emit neutral signal.
                signals[t] = 0.0
                continue

            # Rolling (or expanding if < window) std for scale.
            window_data = residual_history[-self._signal_std_window :]
            std = float(np.std(window_data, ddof=1))
            scale = self._signal_scale_k * std

            if scale < 1e-15:
                # Degenerate case: all residuals identical.
                signals[t] = 0.0
            else:
                signals[t] = float(np.tanh(day_residuals[t] / scale))

        return signals
