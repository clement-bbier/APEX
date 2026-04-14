"""Phase 4.1 batch Triple Barrier labeler with binary projection.

This is the single entry point of the Phase 4.1 deliverable. It wraps
``core.math.labeling.TripleBarrierLabeler`` with:

- A Polars-native batch API: ``(events, bars, config) -> pl.DataFrame``.
- Fail-loud validation of inputs per ADR-0005 D1 (UTC-only, no NaN,
  no orphan events, strict vol window ``[t - N, t - 1]``, σ_t > 0).
- Explicit ternary + binary projections in the same row, so sub-phase
  4.3 can choose which target to train on without re-computing.
- Long-only enforcement: ``direction != +1`` raises
  ``NotImplementedError`` per ADR-0005 D1 MVP.

Intra-bar tie convention: upper wins. See
:func:`core.math.labeling.to_binary_target` docstring.

Reference:
    Lopez de Prado (2018), Advances in Financial Machine Learning,
    Chapter 3.4 - 3.6.
    ADR-0005 D1 - Triple Barrier Method contract.
    PHASE_4_SPEC section 3.1 - public API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl

from core.math.labeling import (
    BarrierLabel,
    BarrierResult,
    TripleBarrierConfig,
    TripleBarrierLabeler,
    to_binary_target,
)


def _ensure_utc(ts: datetime, field: str) -> None:
    if ts.tzinfo is None:
        raise ValueError(f"{field}={ts!r} is tz-naive; ADR-0005 D1 requires UTC-aware datetimes")
    if ts.utcoffset() != UTC.utcoffset(None):
        raise ValueError(
            f"{field}={ts!r} is not UTC (offset={ts.utcoffset()}); "
            "ADR-0005 D1 requires UTC-aware datetimes"
        )


def _barrier_hit_name(result: BarrierResult) -> str:
    """Project :class:`BarrierResult` to its Phase 4.1 string label."""
    if result == BarrierResult.UPPER:
        return "upper"
    if result == BarrierResult.LOWER:
        return "lower"
    return "vertical"


def _validate_bars(
    bars: pl.DataFrame,
    timestamp_col: str,
    close_col: str,
) -> tuple[list[datetime], list[Decimal]]:
    """Fail-loud validation of the bar series; returns aligned lists."""
    if timestamp_col not in bars.columns:
        raise ValueError(f"bars missing required column: {timestamp_col!r}")
    if close_col not in bars.columns:
        raise ValueError(f"bars missing required column: {close_col!r}")
    if len(bars) == 0:
        raise ValueError("bars DataFrame is empty")

    ts_list: list[datetime] = bars[timestamp_col].to_list()
    for ts in ts_list:
        _ensure_utc(ts, f"bars.{timestamp_col}")

    for i in range(1, len(ts_list)):
        if ts_list[i] <= ts_list[i - 1]:
            raise ValueError(
                f"bars.{timestamp_col} is not strictly monotonic at "
                f"index {i}: {ts_list[i]} <= {ts_list[i - 1]}"
            )

    raw_closes = bars[close_col].to_list()
    closes: list[Decimal] = []
    for idx, v in enumerate(raw_closes):
        if v is None:
            raise ValueError(
                f"bars.{close_col} has NaN/None at timestamp={ts_list[idx]}; "
                "ADR-0005 D1 forbids silent ffill"
            )
        d = Decimal(str(v))
        if d <= 0:
            raise ValueError(
                f"bars.{close_col} must be strictly positive; got {d} at timestamp={ts_list[idx]}"
            )
        closes.append(d)
    return ts_list, closes


def _validate_events(
    events: pl.DataFrame,
    timestamp_col: str,
    bar_ts_index: dict[datetime, int],
) -> tuple[list[datetime], list[int], list[str]]:
    """Fail-loud validation of the events frame; returns aligned lists."""
    if timestamp_col not in events.columns:
        raise ValueError(f"events missing required column: {timestamp_col!r}")

    event_ts: list[datetime] = events[timestamp_col].to_list()
    for ts in event_ts:
        _ensure_utc(ts, f"events.{timestamp_col}")

    if "direction" in events.columns:
        directions: list[int] = [int(v) for v in events["direction"].to_list()]
    else:
        directions = [1] * len(event_ts)

    if "symbol" in events.columns:
        symbols: list[str] = [str(v) for v in events["symbol"].to_list()]
    else:
        symbols = [""] * len(event_ts)

    orphans = [ts for ts in event_ts if ts not in bar_ts_index]
    if orphans:
        raise ValueError(
            f"{len(orphans)} event timestamp(s) not found in bars: first 3 orphans = {orphans[:3]}"
        )

    for ts, d in zip(event_ts, directions, strict=True):
        if d != 1:
            raise NotImplementedError(
                f"direction={d} at {ts}: Phase 4 MVP is long-only "
                "per ADR-0005 D1; short-side labeling deferred to Phase 4.X"
            )

    return event_ts, directions, symbols


def label_events_binary(
    events: pl.DataFrame,
    bars: pl.DataFrame,
    config: TripleBarrierConfig | None = None,
    timestamp_col: str = "timestamp",
    close_col: str = "close",
) -> pl.DataFrame:
    """Batch Triple Barrier labeling with ternary + binary targets.

    Per ADR-0005 D1, each event yields a :class:`BarrierLabel` whose
    ternary ``label`` is preserved verbatim and whose binary projection
    ``y = 1 iff label == +1 else 0`` is emitted alongside.

    Args:
        events: Polars DataFrame with at least a ``timestamp`` column
            (UTC tz-aware). Optional columns:
            - ``symbol``: traded instrument id (Utf8); default empty.
            - ``direction``: Int8 in ``{+1}``; default +1. Any value
              other than ``+1`` raises ``NotImplementedError``.
        bars: Polars DataFrame with ``timestamp`` (UTC tz-aware,
            strictly monotonic, unique) and ``close`` (non-null)
            columns covering at least the event range plus
            ``config.vol_lookback`` prior bars and
            ``config.max_holding_periods`` future bars.
        config: Triple Barrier config. Defaults to
            ``TripleBarrierConfig()`` which matches ADR-0005 D1
            Phase 4 defaults (``pt_multiplier=2.0``,
            ``sl_multiplier=1.0``, ``max_holding_periods=60``,
            ``vol_lookback=20``).
        timestamp_col: Name of the timestamp column in both frames.
        close_col: Name of the close price column in ``bars``.

    Returns:
        Polars DataFrame with one row per event and columns:
        ``symbol, t0, t1, entry_price, exit_price, ternary_label,
        binary_target, barrier_hit, holding_periods``.

    Raises:
        ValueError: On any input contract violation (see module
            docstring for the full list).
        NotImplementedError: On short-side events in Phase 4 MVP.
    """
    cfg = config or TripleBarrierConfig()

    bar_ts, bar_closes = _validate_bars(bars, timestamp_col, close_col)
    bar_ts_index: dict[datetime, int] = {ts: i for i, ts in enumerate(bar_ts)}

    if len(events) == 0:
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "t0": pl.Datetime("us", "UTC"),
                "t1": pl.Datetime("us", "UTC"),
                "entry_price": pl.Float64,
                "exit_price": pl.Float64,
                "ternary_label": pl.Int8,
                "binary_target": pl.Int8,
                "barrier_hit": pl.Utf8,
                "holding_periods": pl.Int32,
            }
        )

    event_ts, _directions, symbols = _validate_events(events, timestamp_col, bar_ts_index)

    labeler = TripleBarrierLabeler(cfg)

    # Pre-zip (timestamp, close) once to avoid reconstructing tuples
    # per event inside the loop. Slicing the result still allocates an
    # O(n - i) list, but no per-tuple boxing.
    all_future: list[tuple[datetime, Decimal]] = list(zip(bar_ts, bar_closes, strict=True))

    labels_out: list[BarrierLabel] = []
    for ts in event_ts:
        i = bar_ts_index[ts]

        # Strict warmup: the event must have the full vol_lookback
        # history of prior bars. ADR-0005 D1 specifies "vol_lookback
        # = 20 bars" and "window must end strictly before t"; a
        # partial window would silently use a differently-calibrated
        # sigma. Callers must filter events out of the warmup region
        # (typically bars[cfg.vol_lookback:] for single-symbol feeds).
        if i < cfg.vol_lookback:
            raise ValueError(
                f"event at {ts} is inside the volatility warmup region: "
                f"bar_idx={i}, required_prior_bars={cfg.vol_lookback}. "
                "ADR-0005 D1 requires a strict volatility window of width "
                "vol_lookback; drop warmup events or extend the bar history."
            )

        vol_window = bar_closes[i - cfg.vol_lookback : i]  # exactly cfg.vol_lookback bars

        daily_vol = labeler.compute_daily_vol(vol_window)
        if daily_vol <= 0:
            raise ValueError(
                f"sigma_t is non-positive at event {ts} (value={daily_vol}); "
                "ADR-0005 D1 forbids silent skipping of statistical evidence"
            )

        future_prices = all_future[i + 1 :]

        labels_out.append(
            labeler.label_event(
                entry_price=bar_closes[i],
                entry_time=ts,
                side=1,
                future_prices=future_prices,
                daily_vol=daily_vol,
            )
        )

    return pl.DataFrame(
        {
            "symbol": symbols,
            "t0": [lab.entry_time for lab in labels_out],
            "t1": [lab.exit_time for lab in labels_out],
            "entry_price": [float(lab.entry_price) for lab in labels_out],
            "exit_price": [float(lab.exit_price) for lab in labels_out],
            "ternary_label": [lab.label for lab in labels_out],
            "binary_target": [to_binary_target(lab) for lab in labels_out],
            "barrier_hit": [_barrier_hit_name(lab.barrier_hit) for lab in labels_out],
            "holding_periods": [lab.holding_periods for lab in labels_out],
        },
        schema={
            "symbol": pl.Utf8,
            "t0": pl.Datetime("us", "UTC"),
            "t1": pl.Datetime("us", "UTC"),
            "entry_price": pl.Float64,
            "exit_price": pl.Float64,
            "ternary_label": pl.Int8,
            "binary_target": pl.Int8,
            "barrier_hit": pl.Utf8,
            "holding_periods": pl.Int32,
        },
    )
