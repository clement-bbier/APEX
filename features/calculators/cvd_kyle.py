"""CVD + Kyle Lambda feature calculator (Kyle 1985).

Computes Cumulative Volume Delta and Kyle's lambda (price impact
coefficient) from tick-level trade data.

Note on S02 MicrostructureAnalyzer.cvd() and kyle_lambda():
    S02's cvd() returns a *normalized* ratio (sum(buy-sell)/total_vol)
    bounded in [-1, 1]. This calculator needs the *raw* cumulative sum
    of signed volume (unbounded, monotonically evolving). S02's
    kyle_lambda() uses Cov(delta_P, Q)/Var(Q) without intercept and
    without expanding-window protection against look-ahead. Since feature
    validation requires (a) raw CVD, (b) OLS with intercept, and (c)
    strict past expanding window, this calculator implements both
    directly rather than wrapping S02. S02 is NOT modified
    (anti-scope-creep). Decision documented as D032.

Output columns (6):
    cvd: Cumulative signed volume from t=0. Realization at tick t.
    cvd_divergence: tanh-normalized divergence score of price vs CVD
        trends over the past cvd_window ticks, in [-1, +1].
        Positive = accumulation (CVD up, price flat/down).
        Negative = distribution (CVD down, price flat/up).
        Realization at tick t (uses [t-cvd_window+1, t] inclusive).
    kyle_lambda: Price impact coefficient from OLS regression
        delta_P = lambda * signed_volume + alpha + epsilon over the
        past kyle_window ticks [t-kyle_window, t-1] EXCLUSIVE of
        current tick. Forecast-like at tick t. Always >= 0 (clamped;
        negative lambda is economically unphysical).
    kyle_lambda_zscore: z-score of kyle_lambda vs its rolling history
        over kyle_zscore_lookback ticks.
    liquidity_signal: tanh-normalized kyle_lambda_zscore in [-1, +1].
        Positive = low liquidity (high lambda). Negative = high
        liquidity (low lambda).
    combined_signal: Weighted combination of cvd_divergence and
        liquidity_signal, tanh in [-1, +1].

D028 classification:
    cvd, cvd_divergence: realization at tick t (include current tick,
        no intra-tick look-ahead).
    kyle_lambda, kyle_lambda_zscore, liquidity_signal,
    combined_signal: forecast-like at tick t (OLS fit uses strict
        past [t-kyle_window, t-1], excluding current tick).

Look-ahead defense:
    Kyle regression uses a rolling window of kyle_window ticks ending
    at t-1 (exclusive of t). The OLS coefficients at tick t never see
    data at or after t. Characterized by dedicated look-ahead test.

Fallback for equities without L2:
    Uses Lee-Ready-style classification: trade direction inferred from
    ``side`` column. Reused pattern from OFI 3.6 trade-based fallback.

Reference:
    Kyle, A. S. (1985). "Continuous Auctions and Insider Trading".
    Econometrica, 53(6), 1315-1335.
    Hasbrouck, J. (2007). Empirical Market Microstructure, Ch. 8.
    Lee, C. M. C. & Ready, M. J. (1991). "Inferring Trade Direction
    from Intraday Data". Journal of Finance, 46(2).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class CVDKyleCalculator(FeatureCalculator):
    """CVD + Kyle Lambda calculator (Kyle 1985).

    Computes:
      - Cumulative Volume Delta (CVD) and price-CVD divergence signal
      - Kyle's lambda (price impact per unit of order flow) via
        rolling-window OLS regression
      - Combined liquidity/directional signal

    Output contract (D028):
        cvd, cvd_divergence: realization at tick t (include current
            tick). No data from ticks after t is used.
        kyle_lambda, kyle_lambda_zscore, liquidity_signal,
        combined_signal: forecast-like at tick t (OLS fit uses strict
            past [t-kyle_window, t-1], excluding current tick).

    Reference:
        Kyle, A. S. (1985). "Continuous Auctions and Insider Trading".
        Econometrica, 53(6), 1315-1335.
        Hasbrouck, J. (2007). Empirical Market Microstructure, Ch. 8.
        Lee, C. M. C. & Ready, M. J. (1991). "Inferring Trade
        Direction from Intraday Data". Journal of Finance, 46(2).
    """

    _REQUIRED_COLUMNS: ClassVar[list[str]] = [
        "timestamp",
        "price",
        "quantity",
        "side",
    ]

    def __init__(
        self,
        cvd_window: int = 20,
        kyle_window: int = 100,
        kyle_zscore_lookback: int = 252,
        cvd_divergence_k: float = 3.0,
        liquidity_signal_k: float = 3.0,
        combined_weights: tuple[float, float] = (0.5, 0.5),
    ) -> None:
        """Initialize CVDKyleCalculator.

        Args:
            cvd_window: Rolling window for CVD-price divergence
                computation. Must be >= 2.
            kyle_window: Number of past ticks for Kyle OLS regression.
                Must be >= 10 for stable OLS.
            kyle_zscore_lookback: Rolling lookback for kyle_lambda
                z-score. Must be >= 2 * kyle_window.
            cvd_divergence_k: Scaling factor for tanh normalization
                of CVD divergence (D025 pattern).
            liquidity_signal_k: Scaling factor for tanh normalization
                of kyle_lambda_zscore (D025 pattern).
            combined_weights: Weights (w_cvd, w_liquidity) for the
                combined signal. Must sum to 1.0.
        """
        if cvd_window < 2:
            raise ValueError(f"cvd_window must be >= 2, got {cvd_window}")
        if kyle_window < 10:
            raise ValueError(f"kyle_window must be >= 10 for stable OLS, got {kyle_window}")
        if kyle_zscore_lookback < kyle_window * 2:
            raise ValueError(
                f"kyle_zscore_lookback must be >= 2 * kyle_window, "
                f"got {kyle_zscore_lookback} < {2 * kyle_window}"
            )
        if abs(sum(combined_weights) - 1.0) > 1e-9:
            raise ValueError(f"combined_weights must sum to 1.0, got {sum(combined_weights)}")
        self._cvd_window = cvd_window
        self._kyle_window = kyle_window
        self._kyle_zscore_lookback = kyle_zscore_lookback
        self._cvd_divergence_k = cvd_divergence_k
        self._liquidity_signal_k = liquidity_signal_k
        self._combined_weights = combined_weights

    # ------------------------------------------------------------------
    # FeatureCalculator ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "cvd_kyle"

    @property
    def version(self) -> str:
        return "1.0.0"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        return [
            "cvd",
            "cvd_divergence",
            "kyle_lambda",
            "kyle_lambda_zscore",
            "liquidity_signal",
            "combined_signal",
        ]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute CVD, Kyle lambda, and derived signals.

        Args:
            df: Input ticks with at least :meth:`required_columns`.

        Returns:
            New DataFrame with 6 additional output columns.
        """
        self.validate_input(df)
        n_rows = len(df)

        # Monotonic timestamp invariant (Phase 3.4+ pattern).
        if n_rows > 1 and not df["timestamp"].is_sorted():
            raise ValueError(
                "CVDKyleCalculator.compute() requires ascending-sorted "
                "'timestamp' to preserve look-ahead safety. "
                "Call df.sort('timestamp') before."
            )

        if n_rows == 0:
            return df.with_columns(
                *[pl.Series(col, [], dtype=pl.Float64) for col in self.output_columns()]
            )

        # Step 1: Signed volume per tick.
        signed_vol = self._compute_signed_volume(df)

        # Step 2: Cumulative CVD.
        cvd = np.cumsum(signed_vol)

        # Step 3: CVD-price divergence (realization at tick t).
        prices = df["price"].to_numpy().astype(np.float64)
        cvd_divergence = self._compute_cvd_divergence(prices, cvd)

        # Step 4: Price changes for Kyle regression.
        delta_p = np.zeros(n_rows, dtype=np.float64)
        delta_p[1:] = np.diff(prices)

        # Step 5: Kyle lambda via rolling-window OLS on [t-kyle_window, t-1].
        kyle_lambda = self._compute_kyle_lambda(delta_p, signed_vol)

        # Step 6: Kyle z-score over kyle_zscore_lookback.
        kyle_lambda_zscore = self._compute_kyle_zscore(kyle_lambda)

        # Step 7: tanh normalizations.
        liquidity_signal = self._tanh_normalize_signal(kyle_lambda_zscore, self._liquidity_signal_k)

        # Step 8: Combined signal.
        combined_signal = self._compute_combined_signal(cvd_divergence, liquidity_signal)

        logger.info(
            "cvd_kyle.compute.complete",
            n_rows=n_rows,
            kyle_window=self._kyle_window,
            cvd_window=self._cvd_window,
            valid_kyle=int(np.sum(~np.isnan(kyle_lambda))),
            valid_cvd_div=int(np.sum(~np.isnan(cvd_divergence))),
        )

        return df.with_columns(
            pl.Series("cvd", cvd),
            pl.Series("cvd_divergence", cvd_divergence),
            pl.Series("kyle_lambda", kyle_lambda),
            pl.Series("kyle_lambda_zscore", kyle_lambda_zscore),
            pl.Series("liquidity_signal", liquidity_signal),
            pl.Series("combined_signal", combined_signal),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_signed_volume(df: pl.DataFrame) -> npt.NDArray[np.float64]:
        """Compute per-tick signed volume: +qty for BUY, -qty for SELL.

        Args:
            df: DataFrame with ``side`` and ``quantity`` columns.

        Returns:
            1-D array of signed volume per tick.
        """
        quantities = df["quantity"].to_numpy().astype(np.float64)
        sides = df["side"].to_list()

        signs = np.ones(len(quantities), dtype=np.float64)
        for i, side in enumerate(sides):
            s = str(side).upper()
            if s in ("SELL", "S", "ASK"):
                signs[i] = -1.0

        return quantities * signs

    def _compute_cvd_divergence(
        self,
        prices: npt.NDArray[np.float64],
        cvd: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Compute CVD-price divergence score over rolling window.

        Divergence = -correlation(price_changes, cvd_changes) over
        the last cvd_window ticks. Negative correlation means CVD
        and price move in opposite directions (divergence).

        Score is tanh-normalized to [-1, +1]:
        - Positive: accumulation (CVD rising, price flat/falling)
        - Negative: distribution (CVD falling, price flat/rising)

        Realization at tick t: uses [t-cvd_window+1, t] inclusive.

        Args:
            prices: Price array.
            cvd: Cumulative volume delta array.

        Returns:
            Divergence signal in [-1, +1] (NaN during warm-up).
        """
        n = len(prices)
        w = self._cvd_window
        result = np.full(n, np.nan, dtype=np.float64)

        if n < w:
            return result

        # Precompute tick-level changes.
        price_changes = np.zeros(n, dtype=np.float64)
        cvd_changes = np.zeros(n, dtype=np.float64)
        price_changes[1:] = np.diff(prices)
        cvd_changes[1:] = np.diff(cvd)

        for t in range(w - 1, n):
            pc_win = price_changes[t - w + 1 : t + 1]
            cc_win = cvd_changes[t - w + 1 : t + 1]

            std_p = float(np.std(pc_win))
            std_c = float(np.std(cc_win))

            if std_p < 1e-15 or std_c < 1e-15:
                result[t] = 0.0
                continue

            corr = float(np.corrcoef(pc_win, cc_win)[0, 1])

            if np.isnan(corr):
                result[t] = 0.0
                continue

            # Negative correlation = divergence → positive signal.
            # Scale by k to control tanh spread.
            result[t] = float(np.tanh(-corr * self._cvd_divergence_k))

        return result

    def _compute_kyle_lambda(
        self,
        delta_p: npt.NDArray[np.float64],
        signed_vol: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Compute Kyle's lambda via rolling-window OLS.

        For each tick t, fits: delta_P = lambda * signed_vol + alpha
        on ticks [t-kyle_window, t-1] (strict past, excluding t).

        Lambda is clamped to >= 0: negative lambda is economically
        unphysical (means "buy pressure lowers price"). When clamping
        occurs, a warning is logged.

        Args:
            delta_p: Per-tick price changes.
            signed_vol: Per-tick signed volume.

        Returns:
            Kyle lambda array (NaN during warm-up).
        """
        n = len(delta_p)
        kw = self._kyle_window
        result = np.full(n, np.nan, dtype=np.float64)
        n_clamped = 0

        for t in range(kw, n):
            # Window: [t-kw, t-1] = kw ticks, all strictly before t.
            start = t - kw
            end = t  # exclusive

            y = delta_p[start:end]
            x = signed_vol[start:end]

            # OLS with intercept: [x, 1] @ [lambda, alpha] = y.
            x_mat = np.column_stack([x, np.ones(kw, dtype=np.float64)])
            coeffs, _, _, _ = np.linalg.lstsq(x_mat, y, rcond=None)
            lam = float(coeffs[0])

            if lam < 0.0:
                lam = 0.0
                n_clamped += 1

            result[t] = lam

        if n_clamped > 0:
            logger.warning(
                "kyle_lambda.negative_ols_clamped",
                n_clamped=n_clamped,
                total_fits=max(0, n - kw),
            )

        return result

    def _compute_kyle_zscore(
        self,
        kyle_lambda: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Compute z-score of kyle_lambda vs rolling history.

        Args:
            kyle_lambda: Kyle lambda array (may contain NaN).

        Returns:
            Z-score array (NaN where insufficient history).
        """
        n = len(kyle_lambda)
        result = np.full(n, np.nan, dtype=np.float64)
        lookback = self._kyle_zscore_lookback

        # Collect valid lambda history for rolling z-score.
        history: list[float] = []

        for t in range(n):
            if np.isnan(kyle_lambda[t]):
                continue

            history.append(float(kyle_lambda[t]))

            if len(history) < 2:
                continue

            window = history[-lookback:]
            mean = float(np.mean(window))
            std = float(np.std(window, ddof=1))

            if std < 1e-15:
                result[t] = 0.0
            else:
                result[t] = (float(kyle_lambda[t]) - mean) / std

        return result

    @staticmethod
    def _tanh_normalize_signal(
        zscore: npt.NDArray[np.float64],
        k: float,
    ) -> npt.NDArray[np.float64]:
        """Normalize z-scores to [-1, +1] via tanh(zscore / k).

        Args:
            zscore: Z-score array (may contain NaN).
            k: Scaling factor (D025 pattern).

        Returns:
            Signal in [-1, +1] (NaN where zscore is NaN).
        """
        n = len(zscore)
        result = np.full(n, np.nan, dtype=np.float64)
        valid = ~np.isnan(zscore)
        result[valid] = np.tanh(zscore[valid] / k)
        return result

    def _compute_combined_signal(
        self,
        cvd_divergence: npt.NDArray[np.float64],
        liquidity_signal: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Compute weighted combination of CVD divergence and liquidity.

        combined = tanh(w0 * cvd_divergence + w1 * liquidity_signal)

        NaN if either input is NaN.

        Args:
            cvd_divergence: CVD divergence signal.
            liquidity_signal: Liquidity signal.

        Returns:
            Combined signal in [-1, +1].
        """
        n = len(cvd_divergence)
        result = np.full(n, np.nan, dtype=np.float64)
        w0, w1 = self._combined_weights

        valid = ~np.isnan(cvd_divergence) & ~np.isnan(liquidity_signal)
        result[valid] = np.tanh(w0 * cvd_divergence[valid] + w1 * liquidity_signal[valid])

        return result
