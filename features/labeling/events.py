"""Event-time construction helpers for Phase 4.1 triple barrier labeling.

The Meta-Labeler trains on *entry events* (subset of bar timestamps
where a primary signal fires). This module builds that ``events``
DataFrame from primary-signal series while enforcing ADR-0005 D1
fail-loud contracts:

- Tz-naive / non-UTC timestamps raise ``ValueError``.
- Signal series with NaNs raise (no silent ffill).
- Duplicate timestamps raise.
- Long-only MVP: ``direction`` column is always +1 per ADR-0005 D1.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import polars as pl


def _ensure_utc_series(ts_list: list[datetime], name: str) -> None:
    for ts in ts_list:
        if ts.tzinfo is None:
            raise ValueError(
                f"{name} contains tz-naive datetime {ts!r}; "
                "ADR-0005 D1 requires UTC-aware datetimes"
            )
        if ts.utcoffset() != UTC.utcoffset(None):
            raise ValueError(f"{name} contains non-UTC datetime {ts!r} (offset={ts.utcoffset()})")


def build_events_from_signals(
    signals: pl.DataFrame,
    signal_col: str,
    threshold: float,
    symbol: str,
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Construct a Phase 4.1 events DataFrame from a primary-signal series.

    An event is emitted at each bar where ``signal_col > threshold``.
    The resulting frame has three columns:

    - ``timestamp`` (Datetime[UTC]): event entry time.
    - ``symbol`` (Utf8): the traded instrument.
    - ``direction`` (Int8): always ``+1`` for Phase 4 MVP (long-only
      per ADR-0005 D1).

    Args:
        signals: Polars DataFrame with at least ``timestamp_col`` and
            ``signal_col`` columns. Timestamps must be UTC tz-aware,
            strictly monotone increasing, unique.
        signal_col: Name of the primary signal column (numeric).
        threshold: Trigger threshold; bars where ``signal > threshold``
            produce an event. Must be finite.
        symbol: Traded instrument identifier.
        timestamp_col: Name of the timestamp column in ``signals``.

    Returns:
        Polars DataFrame ``[timestamp, symbol, direction]`` preserving
        the chronological order of the input.

    Raises:
        ValueError: On tz-naive / non-UTC timestamps, duplicate
            timestamps, non-monotone order, or NaN in the signal.
    """
    if timestamp_col not in signals.columns:
        raise ValueError(f"signals missing required column: {timestamp_col!r}")
    if signal_col not in signals.columns:
        raise ValueError(f"signals missing required column: {signal_col!r}")
    if not math.isfinite(threshold):
        raise ValueError(
            f"threshold must be finite; got {threshold!r}. "
            "ADR-0005 D1 forbids silent behaviour with NaN/inf comparisons."
        )

    ts_list: list[datetime] = signals[timestamp_col].to_list()
    _ensure_utc_series(ts_list, f"signals.{timestamp_col}")

    for i in range(1, len(ts_list)):
        if ts_list[i] <= ts_list[i - 1]:
            raise ValueError(
                f"signals.{timestamp_col} is not strictly monotonic at "
                f"index {i}: {ts_list[i]} <= {ts_list[i - 1]}"
            )

    raw_values = signals[signal_col].to_list()
    for idx, v in enumerate(raw_values):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            raise ValueError(
                f"signals.{signal_col} has NaN/None at "
                f"timestamp={ts_list[idx]}; ADR-0005 D1 forbids silent ffill"
            )

    triggered_ts: list[datetime] = [
        ts for ts, v in zip(ts_list, raw_values, strict=True) if float(v) > threshold
    ]

    return pl.DataFrame(
        {
            "timestamp": triggered_ts,
            "symbol": [symbol] * len(triggered_ts),
            "direction": [1] * len(triggered_ts),
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "symbol": pl.Utf8,
            "direction": pl.Int8,
        },
    )
