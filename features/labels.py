"""TripleBarrierLabelerAdapter — Polars-friendly wrapper.

Delegates to ``core.math.labeling.TripleBarrierLabeler`` which already
implements the Triple Barrier Method.  This adapter converts between
Polars DataFrames and the labeler's native interface.

.. warning::
    This module does NOT re-implement labeling logic.  All math lives
    in ``core/math/labeling.py``.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 3, Sections 3.1-3.6.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import polars as pl

from core.math.labeling import TripleBarrierConfig, TripleBarrierLabeler


class TripleBarrierLabelerAdapter:
    """Polars adapter for the core Triple Barrier labeler.

    Converts a Polars bar DataFrame into the format expected by
    :class:`core.math.labeling.TripleBarrierLabeler` and returns
    results as a Polars DataFrame with columns ``label``, ``t1``,
    ``pt_touch``, ``sl_touch``.

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
        """Apply Triple Barrier labeling to a bar DataFrame.

        Args:
            df: Bar DataFrame with at least *close_col* and
                *timestamp_col* columns.
            side: Trade direction — +1 for LONG, -1 for SHORT.
            close_col: Name of the close price column (Decimal values).
            timestamp_col: Name of the timestamp column (UTC datetime).

        Returns:
            DataFrame with columns: ``label`` (int), ``t1`` (datetime),
            ``pt_touch`` (bool), ``sl_touch`` (bool).
        """
        if side not in (-1, 1):
            raise ValueError(f"side must be +1 (long) or -1 (short), got {side}")

        closes: list[Decimal] = [Decimal(str(v)) for v in df[close_col].to_list()]
        timestamps: list[datetime] = df[timestamp_col].to_list()

        vol_lookback = self._labeler.config.vol_lookback

        labels: list[int] = []
        t1_list: list[datetime] = []
        pt_touch_list: list[bool] = []
        sl_touch_list: list[bool] = []

        for i in range(len(closes)):
            vol_window = closes[max(0, i - vol_lookback) : i + 1]
            daily_vol = self._labeler.compute_daily_vol(vol_window)

            future_prices: list[tuple[datetime, Decimal]] = [
                (timestamps[j], closes[j]) for j in range(i + 1, len(closes))
            ]

            result = self._labeler.label_event(
                entry_price=closes[i],
                entry_time=timestamps[i],
                side=side,
                future_prices=future_prices,
                daily_vol=daily_vol,
            )

            labels.append(result.label)
            t1_list.append(result.exit_time)
            pt_touch_list.append(result.barrier_hit.value == 1)
            sl_touch_list.append(result.barrier_hit.value == -1)

        return pl.DataFrame(
            {
                "label": labels,
                "t1": t1_list,
                "pt_touch": pt_touch_list,
                "sl_touch": sl_touch_list,
            }
        )
