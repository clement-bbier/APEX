"""Order Flow Imbalance feature calculator (Cont, Kukanov & Stoikov 2014).

Computes multi-window OFI at 10/50/100 tick horizons, plus a
tanh-normalized combined signal.

Note on S02 MicrostructureAnalyzer.ofi():
    S02's ofi() uses consecutive changes in best-bid and best-ask
    *prices* as a proxy for queue-volume changes (normalized by total
    volume). This is a simplified real-time proxy, NOT the canonical
    Cont et al. (2014) formula which uses order book *size* deltas
    (Delta_bid_size - Delta_ask_size). Since feature validation
    requires the canonical formula, this calculator implements Cont
    2014 directly rather than wrapping S02's price-delta proxy.
    S02 is NOT modified (anti-scope-creep).

Output columns (all realization-like at tick t):
    ofi_10: OFI over the last 10 ticks [t-9, t].
    ofi_50: OFI over the last 50 ticks [t-49, t].
    ofi_100: OFI over the last 100 ticks [t-99, t].
    ofi_signal: tanh-normalized weighted combination in [-1, +1].

D028 classification:
    All 4 columns are realization-like: ofi_w[t] uses ticks
    [t-w+1, t] inclusive (current tick included). This is safe
    because no data from ticks AFTER t is used. The output at
    tick t is known at tick t. No intra-tick look-ahead possible.

    Unlike HAR-RV/Rough Vol which operate on daily bars with
    intraday modes, OFI operates natively at tick level. D027
    (day-close-only emission) does not apply. Warm-up is
    max(windows)-1 ticks, not days.

Fallback for equities without L2 order book:
    If input DataFrame lacks bid_size/ask_size columns, falls back
    to trade-based OFI using signed volume: +quantity for BUY,
    -quantity for SELL. This is a standard proxy when L2 data is
    unavailable (Bouchaud et al. 2018, Ch. 7).

Reference:
    Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact
    of Order Book Events". Journal of Financial Economics,
    104(2), 293-320.
    Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018).
    Trades, Quotes and Prices: Financial Markets Under the
    Microscope. Cambridge University Press, Ch. 7.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class OFICalculator(FeatureCalculator):
    """Order Flow Imbalance calculator (Cont, Kukanov & Stoikov 2014).

    Computes multi-window OFI at configurable tick horizons, plus a
    tanh-normalized combined signal.

    Output contract (D028):
        All 4 output columns are realization-like at tick t: ofi_w[t]
        uses ticks [t-w+1, t] inclusive. No data from ticks after t
        is used. The output at tick t is known at tick t.

    Mode detection:
        If ``bid_size`` and ``ask_size`` columns are present in the
        input DataFrame, uses the canonical Cont 2014 book-based OFI
        formula (Delta_bid_size - Delta_ask_size). Otherwise, falls
        back to trade-based OFI using signed volume.

    Reference:
        Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact
        of Order Book Events". Journal of Financial Economics,
        104(2), 293-320.
        Bouchaud et al. (2018). Trades, Quotes and Prices, Ch. 7.
    """

    _REQUIRED_COLUMNS: ClassVar[list[str]] = [
        "timestamp",
        "price",
        "quantity",
        "side",
    ]
    _OUTPUT_COLUMNS: ClassVar[list[str]] = [
        "ofi_10",
        "ofi_50",
        "ofi_100",
        "ofi_signal",
    ]

    def __init__(
        self,
        windows: tuple[int, ...] = (10, 50, 100),
        signal_k: float = 3.0,
        weights: tuple[float, ...] = (0.5, 0.3, 0.2),
    ) -> None:
        """Initialize OFICalculator.

        Args:
            windows: Rolling window sizes in ticks for OFI computation.
                Must have the same length as ``weights``.
            signal_k: Multiplier for the rolling std used to normalize
                the combined signal via tanh (D025 pattern).
            weights: Weights for the linear combination of OFI windows
                used in ``ofi_signal``. Must sum to ~1.0 and have the
                same length as ``windows``.
        """
        if len(windows) != len(weights):
            raise ValueError(
                f"windows and weights must have the same length, "
                f"got {len(windows)} and {len(weights)}"
            )
        if any(w < 2 for w in windows):
            raise ValueError(f"All windows must be >= 2, got {windows}")
        self._windows = windows
        self._signal_k = signal_k
        self._weights = weights

    # ------------------------------------------------------------------
    # FeatureCalculator ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "ofi"

    @property
    def version(self) -> str:
        return "1.0.0"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        return list(self._OUTPUT_COLUMNS)

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute multi-window OFI and combined signal.

        Each ofi_w[t] uses ticks [t-w+1, t] inclusive. All information
        is known at tick t. No intra-tick look-ahead possible.

        Args:
            df: Input ticks with at least :meth:`required_columns`.
                Optional ``bid_size`` and ``ask_size`` columns trigger
                book-based OFI mode.

        Returns:
            New DataFrame with 4 additional output columns.
        """
        self.validate_input(df)
        n_rows = len(df)

        # Monotonic timestamp invariant (established since Phase 3.4).
        if n_rows > 1 and not df["timestamp"].is_sorted():
            raise ValueError(
                "OFICalculator.compute() requires ascending-sorted "
                "'timestamp' to preserve look-ahead safety. "
                "Call df.sort('timestamp') before."
            )

        if n_rows == 0:
            return df.with_columns(
                *[pl.Series(col, [], dtype=pl.Float64) for col in self._OUTPUT_COLUMNS]
            )

        # Detect mode: book-based vs trade-based.
        has_book = "bid_size" in df.columns and "ask_size" in df.columns

        # Step 1: Compute per-tick OFI contribution.
        if has_book:
            per_tick_ofi = self._compute_book_ofi(df)
            logger.info("ofi.mode.book", n_rows=n_rows)
        else:
            per_tick_ofi = self._compute_trade_ofi(df)
            logger.info("ofi.mode.trade_fallback", n_rows=n_rows)

        # Step 2: Rolling sums for each window.
        max_window = max(self._windows)
        ofi_columns: list[npt.NDArray[np.float64]] = []
        for w in self._windows:
            rolling = self._rolling_mean(per_tick_ofi, w)
            ofi_columns.append(rolling)

        # Step 3: Combined signal via tanh normalization (D025 pattern).
        ofi_signal = self._compute_signal(ofi_columns, max_window)

        logger.info(
            "ofi.compute.complete",
            n_rows=n_rows,
            mode="book" if has_book else "trade",
            warm_up=max_window - 1,
            outputs_produced=int(np.sum(~np.isnan(ofi_signal))),
        )

        return df.with_columns(
            pl.Series("ofi_10", ofi_columns[0]),
            pl.Series("ofi_50", ofi_columns[1]),
            pl.Series("ofi_100", ofi_columns[2]),
            pl.Series("ofi_signal", ofi_signal),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_book_ofi(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        """Book-based OFI (Cont, Kukanov & Stoikov 2014).

        Per-tick contribution: Delta_bid_size - Delta_ask_size.
        First tick has OFI = 0 (no prior state).

        Args:
            df: DataFrame with ``bid_size`` and ``ask_size`` columns.

        Returns:
            1-D array of per-tick OFI contributions.
        """
        bid_sizes = df["bid_size"].to_numpy().astype(np.float64)
        ask_sizes = df["ask_size"].to_numpy().astype(np.float64)

        n = len(bid_sizes)
        ofi = np.zeros(n, dtype=np.float64)

        if n < 2:
            return ofi

        # Delta_bid_size[t] = bid_size[t] - bid_size[t-1]
        # Delta_ask_size[t] = ask_size[t] - ask_size[t-1]
        # OFI[t] = Delta_bid_size[t] - Delta_ask_size[t]
        delta_bid = np.diff(bid_sizes)
        delta_ask = np.diff(ask_sizes)
        ofi[1:] = delta_bid - delta_ask

        return ofi

    def _compute_trade_ofi(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        """Trade-based OFI fallback using signed volume.

        When L2 order book data is unavailable, uses trade direction
        and quantity as OFI proxy: +quantity for BUY, -quantity for SELL.

        Args:
            df: DataFrame with ``side`` and ``quantity`` columns.

        Returns:
            1-D array of per-tick signed volume.
        """
        quantities = df["quantity"].to_numpy().astype(np.float64)
        sides = df["side"].to_list()

        signs = np.ones(len(quantities), dtype=np.float64)
        for i, side in enumerate(sides):
            s = str(side).upper()
            if s in ("SELL", "S", "ASK"):
                signs[i] = -1.0

        return quantities * signs

    @staticmethod
    def _rolling_mean(arr: npt.NDArray[np.float64], window: int) -> npt.NDArray[np.float64]:
        """Compute rolling mean over a fixed window.

        Uses cumulative sum for O(n) performance. First ``window - 1``
        values are NaN (warm-up).

        The window at tick t covers ticks [t-w+1, t] inclusive.
        """
        n = len(arr)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < window:
            return result

        cumsum = np.cumsum(arr)
        result[window - 1] = cumsum[window - 1] / window
        result[window:] = (cumsum[window:] - cumsum[:-window]) / window

        return result

    def _compute_signal(
        self,
        ofi_columns: list[npt.NDArray[np.float64]],
        max_window: int,
    ) -> npt.NDArray[np.float64]:
        """Compute tanh-normalized weighted combination of OFI windows.

        Signal = tanh(weighted_combination / (k * rolling_std)).
        Uses expanding std until enough data points, then rolling.

        Args:
            ofi_columns: List of rolling OFI arrays (one per window).
            max_window: Largest window size (determines warm-up).

        Returns:
            Signal array in [-1, +1] with NaN during warm-up.
        """
        n = len(ofi_columns[0])
        signal = np.full(n, np.nan, dtype=np.float64)

        # Compute weighted combination at each tick.
        weighted = np.zeros(n, dtype=np.float64)
        all_valid = np.ones(n, dtype=bool)
        for col, w in zip(ofi_columns, self._weights, strict=True):
            all_valid &= ~np.isnan(col)
            # Use nan-safe multiplication; NaN positions filtered by all_valid.
            col_safe = np.nan_to_num(col, nan=0.0)
            weighted += w * col_safe

        # Adaptive tanh normalization (D025 pattern from HAR-RV/Rough Vol).
        history: list[float] = []
        std_window = 60  # Rolling std window.

        for t in range(n):
            if not all_valid[t]:
                continue

            history.append(float(weighted[t]))

            if len(history) < 2:
                signal[t] = 0.0
                continue

            window_data = history[-std_window:]
            std = float(np.std(window_data, ddof=1))
            scale = self._signal_k * std

            if scale < 1e-15:
                signal[t] = 0.0
            else:
                signal[t] = float(np.tanh(weighted[t] / scale))

        return signal
