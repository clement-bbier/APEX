"""TripleBarrierLabelerAdapter — Polars-friendly wrapper.

Delegates to ``core.math.labeling.TripleBarrierLabeler`` which already
implements the Triple Barrier Method.  This adapter converts between
Polars DataFrames and the labeler's native interface.

.. warning::
    This module does NOT re-implement labeling logic.  All math lives
    in ``core/math/labeling.py``.

ADR-0005 D1 fail-loud contract (enforced here):

- ``σ_t`` is computed over the *strict* half-open window
  ``closes[t - vol_lookback : t]`` — bar ``t`` itself is excluded to
  eliminate look-ahead leakage. Prior Phase 3 behaviour
  (``[t - vol_lookback : t + 1]``) was a bug that silently biased
  labels with the labeled bar's own close. See ``reports/phase_4_1/
  labels_diagnostics.md`` for the diff.
- Bars with insufficient prior history (``t < 2`` after the strict
  window) cannot produce a ``σ_t`` estimate; the adapter raises
  rather than seeding a silent default.
- Events or bar timestamps that are tz-naive or not UTC raise
  ``ValueError`` with the offending timestamp included.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 3, Sections 3.1-3.6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl

from core.math.labeling import BarrierLabel, TripleBarrierConfig, TripleBarrierLabeler


def _ensure_utc(ts: datetime, field: str) -> None:
    """Fail-loud guard: reject naive or non-UTC timestamps."""
    if ts.tzinfo is None:
        raise ValueError(f"{field}={ts!r} is tz-naive; ADR-0005 D1 requires UTC-aware datetimes")
    if ts.utcoffset() != UTC.utcoffset(None):
        raise ValueError(
            f"{field}={ts!r} is not UTC (offset={ts.utcoffset()}); "
            "ADR-0005 D1 requires UTC-aware datetimes"
        )


def _vol_window(
    closes: list[Decimal],
    i: int,
    vol_lookback: int,
) -> list[Decimal]:
    """Return the strict look-back window for bar index ``i``.

    ADR-0005 D1: the window ends strictly before bar ``i`` (``closes[:i]``)
    so the labeled bar's own price cannot leak into ``σ_t``.
    """
    start = max(0, i - vol_lookback)
    return closes[start:i]


class TripleBarrierLabelerAdapter:
    """Polars adapter for the core Triple Barrier labeler.

    Converts a Polars bar DataFrame into the format expected by
    :class:`core.math.labeling.TripleBarrierLabeler` and returns
    results as a Polars DataFrame with columns ``t0``, ``t1``,
    ``label``, ``pt_touch``, ``sl_touch``.

    Emits one labeled row per bar with ``i >= vol_lookback`` (the
    full strict lookback window). Earlier bars are skipped in the
    legacy ``label(df)`` path because they cannot deliver a vol
    estimate that matches the configured span without peeking into
    the labeled bar.

    Reference:
        Lopez de Prado, M. (2018). *Advances in Financial Machine
        Learning*. Wiley, Ch. 3, Sections 3.1-3.6.
    """

    def __init__(self, config: TripleBarrierConfig | None = None) -> None:
        self._labeler = TripleBarrierLabeler(config)

    @property
    def config(self) -> TripleBarrierConfig:
        """Underlying barrier configuration."""
        return self._labeler.config

    def label(
        self,
        df: pl.DataFrame,
        side: int = 1,
        close_col: str = "close",
        timestamp_col: str = "timestamp",
    ) -> pl.DataFrame:
        """Apply Triple Barrier labeling bar-by-bar.

        Every bar with enough prior history (``i >= vol_lookback``)
        is treated as a candidate entry, where ``vol_lookback`` is
        taken from the configured :class:`TripleBarrierConfig`.
        Earlier bars are skipped from the output because there is no
        strict ``σ_t`` estimate for them. The output ``DataFrame``
        therefore has ``len(df) - vol_lookback`` rows.

        Args:
            df: Bar DataFrame with at least *close_col* and
                *timestamp_col* columns. ``timestamp_col`` must be
                UTC tz-aware.
            side: Trade direction — +1 for LONG, -1 for SHORT.
            close_col: Name of the close price column (Decimal values).
            timestamp_col: Name of the timestamp column (UTC datetime).

        Returns:
            DataFrame with columns: ``t0`` (entry time, datetime),
            ``t1`` (exit time, datetime), ``label`` (int in {-1, 0, 1}),
            ``pt_touch`` (bool), ``sl_touch`` (bool).

        Raises:
            ValueError: On invalid ``side`` or insufficient history.
        """
        if side not in (-1, 1):
            raise ValueError(f"side must be +1 (long) or -1 (short), got {side}")

        vol_lookback = self._labeler.config.vol_lookback
        if len(df) <= vol_lookback:
            raise ValueError(
                f"DataFrame has {len(df)} rows; need at least "
                f"{vol_lookback + 1} to produce any label "
                "(strict vol window of width vol_lookback excludes the labeled bar)"
            )

        closes: list[Decimal] = [Decimal(str(v)) for v in df[close_col].to_list()]
        timestamps: list[datetime] = df[timestamp_col].to_list()

        for ts in timestamps:
            _ensure_utc(ts, timestamp_col)

        t0_list: list[datetime] = []
        t1_list: list[datetime] = []
        labels: list[int] = []
        pt_touch_list: list[bool] = []
        sl_touch_list: list[bool] = []

        # Pre-zip (timestamp, close) once to avoid reconstructing
        # tuples per bar inside the loop. Slicing the result still
        # allocates an O(n - i) list, but no per-tuple boxing.
        all_future: list[tuple[datetime, Decimal]] = list(zip(timestamps, closes, strict=True))

        for i in range(vol_lookback, len(closes)):
            vol_window = _vol_window(closes, i, vol_lookback)
            daily_vol = self._labeler.compute_daily_vol(vol_window)

            if daily_vol <= 0:
                raise ValueError(
                    f"daily_vol is non-positive at timestamp={timestamps[i]} "
                    f"(prior window size={len(vol_window)}, value={daily_vol}); "
                    "ADR-0005 D1 forbids silent skipping"
                )

            future_prices = all_future[i + 1 :]

            result = self._labeler.label_event(
                entry_price=closes[i],
                entry_time=timestamps[i],
                side=side,
                future_prices=future_prices,
                daily_vol=daily_vol,
            )

            t0_list.append(result.entry_time)
            t1_list.append(result.exit_time)
            labels.append(result.label)
            pt_touch_list.append(result.barrier_hit.value == 1)
            sl_touch_list.append(result.barrier_hit.value == -1)

        return pl.DataFrame(
            {
                "t0": t0_list,
                "t1": t1_list,
                "label": labels,
                "pt_touch": pt_touch_list,
                "sl_touch": sl_touch_list,
            }
        )

    def label_events(
        self,
        events: pl.DataFrame,
        bars: pl.DataFrame,
        close_col: str = "close",
        timestamp_col: str = "timestamp",
    ) -> list[BarrierLabel]:
        """Batch-label a curated set of entry events against a bar series.

        Phase 4.1 extension of the legacy ``label(df)`` path. The
        caller supplies an *events* frame (subset of the bar
        timeline) and receives one :class:`BarrierLabel` per event.
        Unlike ``label()``, this method preserves the richer native
        dataclass — the Polars projection with a binary target
        lives in :mod:`features.labeling.triple_barrier`.

        Args:
            events: Polars DataFrame with at least a
                ``timestamp`` column (UTC tz-aware). Optional
                ``direction`` column (Int8, default +1) selects long
                vs. short per ADR-0005 D1 long-only Phase 4 MVP.
            bars: Polars DataFrame with ``timestamp`` and ``close``
                columns, sorted by timestamp ascending, unique and
                UTC tz-aware.
            close_col: Name of the close price column in ``bars``.
            timestamp_col: Name of the timestamp column in both
                frames.

        Returns:
            List of ``BarrierLabel`` preserving event order.

        Raises:
            ValueError: On tz-naive / non-UTC timestamps, non-monotone
                bars, orphan events (timestamp missing from ``bars``),
                NaN prices, or insufficient vol history.
        """
        if len(bars) == 0:
            raise ValueError("bars DataFrame is empty")
        if len(events) == 0:
            return []

        bar_ts: list[datetime] = bars[timestamp_col].to_list()
        bar_closes_raw = bars[close_col].to_list()

        for ts in bar_ts:
            _ensure_utc(ts, f"bars.{timestamp_col}")

        for idx in range(1, len(bar_ts)):
            if bar_ts[idx] <= bar_ts[idx - 1]:
                raise ValueError(
                    "bars DataFrame index is not strictly monotonic at "
                    f"bars[{idx}]={bar_ts[idx]} (previous={bar_ts[idx - 1]})"
                )

        for idx, px in enumerate(bar_closes_raw):
            if px is None:
                raise ValueError(
                    f"bars.{close_col} contains NaN/None at "
                    f"timestamp={bar_ts[idx]}; ADR-0005 D1 forbids silent ffill"
                )

        bar_closes: list[Decimal] = [Decimal(str(v)) for v in bar_closes_raw]
        ts_to_idx: dict[datetime, int] = {ts: i for i, ts in enumerate(bar_ts)}

        event_ts: list[datetime] = events[timestamp_col].to_list()
        if "direction" in events.columns:
            directions: list[int] = [int(v) for v in events["direction"].to_list()]
        else:
            directions = [1] * len(event_ts)

        for ts in event_ts:
            _ensure_utc(ts, f"events.{timestamp_col}")

        orphans = [ts for ts in event_ts if ts not in ts_to_idx]
        if orphans:
            raise ValueError(
                f"{len(orphans)} event timestamp(s) not found in bars: "
                f"first 3 orphans = {orphans[:3]}"
            )

        vol_lookback = self._labeler.config.vol_lookback

        # Pre-zip once to avoid rebuilding tuples per event.
        all_future: list[tuple[datetime, Decimal]] = list(zip(bar_ts, bar_closes, strict=True))

        out: list[BarrierLabel] = []
        for ts, direction in zip(event_ts, directions, strict=True):
            if direction != 1:
                raise NotImplementedError(
                    f"direction={direction} at {ts}: Phase 4 MVP is long-only "
                    "per ADR-0005 D1; short-side labeling deferred to Phase 4.X"
                )

            i = ts_to_idx[ts]

            # Strict warmup per ADR-0005 D1: a full vol_lookback of
            # prior bars is required. Aligned with the legacy
            # ``label(df)`` path which starts at ``i = vol_lookback``.
            if i < vol_lookback:
                raise ValueError(
                    f"event at {ts} is inside the volatility warmup region: "
                    f"bar_idx={i}, required_prior_bars={vol_lookback}. "
                    "ADR-0005 D1 requires a strict volatility window of width "
                    "vol_lookback."
                )

            vol_window = _vol_window(bar_closes, i, vol_lookback)
            daily_vol = self._labeler.compute_daily_vol(vol_window)
            if daily_vol <= 0:
                raise ValueError(
                    f"sigma_t is non-positive at event {ts} (value={daily_vol}); "
                    "ADR-0005 D1 forbids silent skipping of statistical evidence"
                )

            future_prices = all_future[i + 1 :]

            label = self._labeler.label_event(
                entry_price=bar_closes[i],
                entry_time=ts,
                side=direction,
                future_prices=future_prices,
                daily_vol=daily_vol,
            )
            out.append(label)

        return out


__all__ = ["TripleBarrierLabelerAdapter"]
