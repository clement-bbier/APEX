"""Massive (ex-Polygon) minute bar normalizer.

Transforms CSV rows from Massive S3 flat files into
:class:`~core.models.data.Bar` instances for TimescaleDB persistence.

CSV format: ticker,volume,open,close,high,low,window_start,transactions
``window_start`` is nanoseconds since epoch.

References:
    Polygon.io flat files docs — https://polygon.io/flat-files
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.models.data import Asset, Bar, BarSize, BarType
from services.data_ingestion.normalizers.base import NormalizerStrategy


class MassiveBarNormalizer(NormalizerStrategy[list[str], Bar]):
    """Normalizes Massive CSV rows to :class:`Bar`.

    CSV column order:
        0: ticker, 1: volume, 2: open, 3: close, 4: high,
        5: low, 6: window_start (ns), 7: transactions

    Args:
        bar_size: The bar time-frame size (default M1).
    """

    def __init__(self, bar_size: BarSize = BarSize.M1) -> None:
        self._bar_size = bar_size

    def normalize(self, raw: list[str], asset: Asset) -> Bar:
        """Convert a Massive CSV row to a :class:`Bar`.

        Args:
            raw: A list of 8 string values from the CSV.
            asset: The resolved asset providing ``asset_id``.

        Returns:
            A fully populated :class:`Bar`.
        """
        # Column indices
        volume = Decimal(raw[1])
        open_price = Decimal(raw[2])
        close_price = Decimal(raw[3])
        high_price = Decimal(raw[4])
        low_price = Decimal(raw[5])
        window_start_ns = int(raw[6])
        transactions = int(raw[7])

        timestamp = datetime.fromtimestamp(window_start_ns / 1_000_000_000, tz=UTC)

        vwap: Decimal | None = None

        return Bar(
            asset_id=asset.asset_id,
            bar_type=BarType.TIME,
            bar_size=self._bar_size,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            trade_count=transactions,
            vwap=vwap,
        )
