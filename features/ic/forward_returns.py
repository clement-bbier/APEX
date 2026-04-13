"""Forward-return computation for IC measurement.

Computes log-returns at a specified horizon *h*.  The forward return
at time *t* is ``log(price_{t+h} / price_t)`` and is **only known
at time t+h**.

This module produces TARGET data for IC evaluation, NOT features.
Using forward returns as features would be look-ahead bias.

Reference:
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
    Management* (2nd ed.), Ch. 6. McGraw-Hill.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import polars as pl


def compute_forward_returns(
    bars: pl.DataFrame,
    horizon_bars: int,
    price_col: str = "close",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Compute forward log-returns at horizon *h*.

    The returned DataFrame has columns ``[timestamp, forward_return]``.
    The **last** *h* rows have ``null`` forward returns because there
    is no future price data to compute them.

    **Look-ahead warning**: ``forward_return`` at row *t* uses
    ``price[t + h]``.  It is observable only at ``t + h`` and must
    NEVER be used as a feature input at time *t*.  It is correct
    only as a **target** for IC measurement (correlation between a
    feature known at *t* and the return realized at *t + h*).

    Args:
        bars: DataFrame with at least ``price_col`` and
            ``timestamp_col`` columns, sorted by time ascending.
        horizon_bars: Number of bars to look ahead (must be >= 1).
        price_col: Column name for the price series.
        timestamp_col: Column name for timestamps.

    Returns:
        DataFrame with columns ``[timestamp, forward_return]``.

    Raises:
        ValueError: If ``horizon_bars < 1`` or required columns
            are missing.
    """
    if horizon_bars < 1:
        raise ValueError(f"horizon_bars must be >= 1, got {horizon_bars}")

    missing = {price_col, timestamp_col} - set(bars.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    prices: npt.NDArray[np.float64] = np.asarray(bars[price_col].to_numpy(), dtype=np.float64)

    # log(price_{t+h} / price_t) for t = 0 .. n-h-1
    fwd = np.full(len(prices), np.nan, dtype=np.float64)
    fwd[: len(prices) - horizon_bars] = np.log(
        prices[horizon_bars:] / prices[: len(prices) - horizon_bars]
    )

    return pl.DataFrame(
        {
            timestamp_col: bars[timestamp_col],
            "forward_return": fwd,
        }
    )
