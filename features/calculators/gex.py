"""Gamma Exposure (GEX) feature calculator (Barbon & Buraschi 2020).

Computes aggregate dealer gamma exposure from option chain snapshots.
Dealer-adjusted sign convention: calls contribute negatively (dealers
short calls sold to retail), puts positively (dealers long puts bought
for hedge).

Note on S02 CrowdBehaviorAnalyzer.update_gex():
    S02's update_gex() uses the *opposite* sign convention (calls +1,
    puts -1) and a simpler formula (gamma * OI * 100, no S^2 factor).
    It also uses float, not Decimal, and has no strict-past protection.
    Since feature validation requires (a) dealer-adjusted Barbon-Buraschi
    sign convention, (b) S^2 scaling for dollar GEX, and (c) strict-past
    z-score for forecast-like columns, this calculator implements GEX
    directly rather than wrapping S02.
    S02 is NOT modified (anti-scope-creep). Decision documented as D033.

GEX = Sigma_i (sign_i * OI_i * gamma_i * S^2 * multiplier)
where sign_i = -1 for calls, +1 for puts (Barbon-Buraschi 2020).

Output columns (5):
    gex_raw: Raw dollar GEX at timestamp t. Realization at t (uses
        OI/gamma observed at t). Unit: dollars.
    gex_normalized: gex_raw / spot_price, cross-asset comparable.
        Realization at t.
    gex_zscore: z-score of gex_raw over strict-past zscore_lookback
        window [t-lookback, t-1] (forecast-like). Excludes current t.
    gex_regime: Discrete {-1, 0, +1} based on zscore thresholds.
        -1 = short gamma (amplifying), 0 = neutral, +1 = long gamma
        (stabilizing). Forecast-like (derived from gex_zscore).
    gex_signal: tanh-normalized zscore in [-1, +1] (forecast-like).

D028 classification:
    gex_raw, gex_normalized: realization at t (uses OI/gamma at t).
    gex_zscore, gex_regime, gex_signal: forecast-like (use strict
        past window [t-lookback, t-1]).

Sign convention (dealer-adjusted):
    Calls: dealers typically short (sold to retail) -> contribute
        negatively to GEX.
    Puts: dealers typically long (bought as hedge) -> contribute
        positively.
    This is the Barbon-Buraschi (2020) standard. See also
    Baltussen et al. (2019) for alternative conventions.

Reference:
    Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".
        Working Paper, University of St. Gallen.
    Baltussen, G., van Bekkum, S. & Da, Z. (2019). "Indexing and
        Stock Market Serial Dependence Around the World".
        Journal of Financial and Quantitative Analysis, 54(3).
    Ni, Pearson & Poteshman (2005). "Stock price clustering on
        option expiration dates". Journal of Financial
        Economics, 78(2), 49-87.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class GEXCalculator(FeatureCalculator):
    """Gamma Exposure calculator (Barbon & Buraschi 2020).

    Computes aggregate dealer gamma exposure from option chain
    snapshots. Dealer-adjusted sign convention: calls contribute
    negatively (dealers short calls sold to retail), puts positively
    (dealers long puts bought for hedge).

    Output contract (D028):
        gex_raw, gex_normalized: realization at t (snapshot-based,
            uses OI/gamma observed at t).
        gex_zscore, gex_regime, gex_signal: forecast-like (strict
            past zscore_lookback window [t-lookback, t-1]).

    Input format:
        DataFrame with columns [timestamp, spot_price, strike, expiry,
        option_type ('call'|'put'), open_interest, gamma]. Multiple
        rows per timestamp (one per active option). Calculator
        aggregates per timestamp.

    Sign convention (dealer-adjusted):
        Calls: -1 (dealers short). Puts: +1 (dealers long).
        Characterized by test_calls_contribute_negatively and
        test_puts_contribute_positively.

    Reference:
        Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".
        Working Paper, University of St. Gallen.
        Baltussen et al. (2019). JFQA 54(3).
        Ni, Pearson & Poteshman (2005). JFE 78(2).
    """

    _REQUIRED_COLUMNS: ClassVar[list[str]] = [
        "timestamp",
        "spot_price",
        "strike",
        "expiry",
        "option_type",
        "open_interest",
        "gamma",
    ]

    _OUTPUT_COLUMNS: ClassVar[list[str]] = [
        "gex_raw",
        "gex_normalized",
        "gex_zscore",
        "gex_regime",
        "gex_signal",
    ]

    def __init__(
        self,
        zscore_lookback: int = 252,
        regime_lower_threshold: float = -1.0,
        regime_upper_threshold: float = 1.0,
        signal_k: float = 3.0,
        contract_multiplier: int = 100,
    ) -> None:
        """Initialize GEXCalculator.

        Args:
            zscore_lookback: Number of past timestamps for z-score
                rolling window. Must be >= 20.
            regime_lower_threshold: Z-score below which regime is -1
                (short gamma / amplifying).
            regime_upper_threshold: Z-score above which regime is +1
                (long gamma / stabilizing).
            signal_k: Scaling factor for tanh normalization (D025).
            contract_multiplier: Standard US equity option multiplier
                (typically 100 shares per contract).
        """
        # D030 constructor validation.
        if zscore_lookback < 20:
            raise ValueError(f"zscore_lookback must be >= 20, got {zscore_lookback}")
        if regime_lower_threshold >= regime_upper_threshold:
            raise ValueError(
                f"regime_lower_threshold must be < regime_upper_threshold, "
                f"got {regime_lower_threshold} >= {regime_upper_threshold}"
            )
        if contract_multiplier <= 0:
            raise ValueError(f"contract_multiplier must be > 0, got {contract_multiplier}")
        self._zscore_lookback = zscore_lookback
        self._regime_lower = regime_lower_threshold
        self._regime_upper = regime_upper_threshold
        self._signal_k = signal_k
        self._contract_multiplier = contract_multiplier

    # ------------------------------------------------------------------
    # FeatureCalculator ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "gex"

    @property
    def version(self) -> str:
        return "1.0.0"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        return list(self._OUTPUT_COLUMNS)

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute GEX and derived signals from option chain snapshots.

        Each timestamp may have multiple rows (one per active option).
        The calculator aggregates per timestamp and broadcasts the
        result back to all rows of that timestamp.

        Args:
            df: Input option chain with at least :meth:`required_columns`.

        Returns:
            New DataFrame with 5 additional output columns.
        """
        self.validate_input(df)
        n_rows = len(df)

        if n_rows == 0:
            return df.with_columns(
                *[pl.Series(col, [], dtype=pl.Float64) for col in self.output_columns()]
            )

        # Monotonic timestamp invariant (Phase 3.4+ pattern).
        # Options chain has multiple rows per timestamp — we only
        # require non-decreasing order (ties allowed within snapshot).
        # Use is_sorted() which handles Duration/Datetime natively.
        if n_rows > 1 and not df["timestamp"].is_sorted():
            raise ValueError(
                "GEXCalculator.compute() requires non-decreasing "
                "'timestamp' to preserve look-ahead safety. "
                "Call df.sort('timestamp') before."
            )

        # Validate option_type values.
        unique_types = df.select(pl.col("option_type").unique()).to_series().to_list()
        invalid = set(unique_types) - {"call", "put"}
        if invalid:
            raise ValueError(f"option_type must be 'call' or 'put', got invalid values: {invalid}")

        # Step 1: Per-option contribution (dealer-adjusted sign).
        # sign = -1 for calls, +1 for puts (Barbon-Buraschi 2020).
        # contribution = sign * OI * gamma * S^2 * multiplier
        sign_expr = (
            pl.when(pl.col("option_type") == "call").then(pl.lit(-1.0)).otherwise(pl.lit(1.0))
        )
        df_with_contrib = df.with_columns(
            (
                sign_expr
                * pl.col("open_interest").cast(pl.Float64)
                * pl.col("gamma").cast(pl.Float64)
                * pl.col("spot_price").cast(pl.Float64).pow(2)
                * pl.lit(float(self._contract_multiplier))
            ).alias("_gex_contribution")
        )

        # Step 2: Aggregate per timestamp -> per-snapshot GEX.
        agg_df = df_with_contrib.group_by("timestamp", maintain_order=True).agg(
            pl.col("_gex_contribution").sum().alias("gex_raw"),
            pl.col("spot_price").first().alias("_spot_first"),
        )

        # Step 3: gex_normalized = gex_raw / spot_price.
        agg_df = agg_df.with_columns(
            (pl.col("gex_raw") / pl.col("_spot_first")).alias("gex_normalized")
        )

        # Steps 4-6: zscore, regime, signal (numpy for rolling logic).
        gex_raw_arr = agg_df["gex_raw"].to_numpy().astype(np.float64)
        n_snapshots = len(gex_raw_arr)

        gex_zscore = self._compute_zscore(gex_raw_arr)
        gex_regime = self._compute_regime(gex_zscore)
        gex_signal = self._compute_signal(gex_zscore)

        agg_df = agg_df.with_columns(
            pl.Series("gex_zscore", gex_zscore),
            pl.Series("gex_regime", gex_regime),
            pl.Series("gex_signal", gex_signal),
        )

        # Step 7: Join back — broadcast per-timestamp aggregates.
        join_cols = [
            "gex_raw",
            "gex_normalized",
            "gex_zscore",
            "gex_regime",
            "gex_signal",
        ]
        result = df_with_contrib.drop("_gex_contribution").join(
            agg_df.select(["timestamp", *join_cols]),
            on="timestamp",
            how="left",
        )

        logger.info(
            "gex.compute.complete",
            n_rows=n_rows,
            n_snapshots=n_snapshots,
            zscore_lookback=self._zscore_lookback,
            valid_zscore=int(np.sum(~np.isnan(gex_zscore))),
        )

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_zscore(
        self,
        gex_raw: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Z-score of gex_raw over strict past window.

        At timestamp t, uses gex_raw values from [t-lookback, t-1]
        (excluding t). Forecast-like: never sees current observation.

        Args:
            gex_raw: Per-snapshot GEX values.

        Returns:
            Z-score array (NaN during warm-up).
        """
        n = len(gex_raw)
        result = np.full(n, np.nan, dtype=np.float64)

        for t in range(1, n):
            start = max(0, t - self._zscore_lookback)
            window = gex_raw[start:t]  # strict past, excludes t

            if len(window) < 2:
                continue

            mean = float(np.mean(window))
            std = float(np.std(window, ddof=1))

            if std < 1e-15:
                result[t] = 0.0
            else:
                result[t] = (gex_raw[t] - mean) / std

        return result

    def _compute_regime(
        self,
        zscore: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Map z-score to discrete regime {-1, 0, +1}.

        -1 = short gamma (amplifying moves).
         0 = neutral.
        +1 = long gamma (stabilizing / dampening).

        NaN where zscore is NaN.

        Args:
            zscore: Z-score array.

        Returns:
            Regime array.
        """
        n = len(zscore)
        result = np.full(n, np.nan, dtype=np.float64)
        valid = ~np.isnan(zscore)

        result[valid & (zscore < self._regime_lower)] = -1.0
        result[valid & (zscore > self._regime_upper)] = 1.0
        result[valid & (zscore >= self._regime_lower) & (zscore <= self._regime_upper)] = 0.0

        return result

    def _compute_signal(
        self,
        zscore: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Normalize z-score to [-1, +1] via tanh(zscore / k).

        NaN where zscore is NaN. D025 pattern.

        Args:
            zscore: Z-score array.

        Returns:
            Signal in [-1, +1].
        """
        n = len(zscore)
        result = np.full(n, np.nan, dtype=np.float64)
        valid = ~np.isnan(zscore)
        result[valid] = np.tanh(zscore[valid] / self._signal_k)
        return result
