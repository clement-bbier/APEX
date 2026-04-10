"""Yahoo Finance bar normalizer.

Transforms yfinance DataFrame rows into :class:`~core.models.data.Bar`
instances for TimescaleDB persistence. Handles NaN volumes (common for
indices and FX pairs) and timezone conversion.

References:
    yfinance docs — https://github.com/ranaroussi/yfinance
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pandas as pd

from core.models.data import Asset, Bar, BarSize, BarType
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy

type YahooBarPayload = tuple[pd.Timestamp, Mapping[str, object]]


class YahooBarNormalizer(NormalizerStrategy[YahooBarPayload, Bar]):
    """Normalizes yfinance DataFrame rows to :class:`Bar`.

    Each row is a ``(pd.Timestamp, dict)`` tuple extracted from
    ``DataFrame.iterrows()``.  The normalizer handles:

    * Timezone-naive timestamps (localized to UTC)
    * Timezone-aware timestamps (converted to UTC)
    * NaN / None volume (defaulted to 0 for indices and FX)

    Args:
        bar_size: The bar time-frame size.
    """

    def __init__(self, bar_size: BarSize) -> None:
        self._bar_size = bar_size

    def normalize(self, raw: YahooBarPayload, asset: Asset) -> Bar:
        """Convert a single yfinance row to a :class:`Bar`.

        Args:
            raw: A ``(pd.Timestamp, row_dict)`` tuple.
            asset: The resolved asset providing ``asset_id``.

        Returns:
            A fully populated :class:`Bar`.
        """
        ts, row = raw

        # Ensure UTC-aware timestamp
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        # Volume can be NaN for indices/FX — default to 0
        # pd.isna handles both Python float NaN and numpy.float64 NaN
        volume = row.get("Volume", 0)
        if volume is None or pd.isna(volume):
            volume = 0

        return Bar(
            asset_id=asset.asset_id,
            bar_type=BarType.TIME,
            bar_size=self._bar_size,
            timestamp=ts.to_pydatetime(),
            open=Decimal(str(row["Open"])),
            high=Decimal(str(row["High"])),
            low=Decimal(str(row["Low"])),
            close=Decimal(str(row["Close"])),
            volume=Decimal(str(volume)),
        )
