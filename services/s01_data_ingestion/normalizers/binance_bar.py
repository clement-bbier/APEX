"""Binance kline (candlestick) bar normalizer.

Transforms Binance REST/WS kline arrays into :class:`~core.models.data.Bar`
instances for TimescaleDB persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.models.data import Asset, Bar, BarSize, BarType
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy


class BinanceBarNormalizer(NormalizerStrategy[list[Any], Bar]):
    """Normalizes Binance kline arrays to :class:`Bar`.

    Binance kline format (list indices):

    * [0]  open_time_ms      (int)
    * [1]  open              (str)
    * [2]  high              (str)
    * [3]  low               (str)
    * [4]  close             (str)
    * [5]  volume            (str)
    * [6]  close_time_ms     (int)
    * [7]  quote_asset_volume (str)
    * [8]  number_of_trades  (int)
    * [9]  taker_buy_base_asset_volume (str)
    * [10] taker_buy_quote_asset_volume (str)
    * [11] ignore            (str)

    Args:
        bar_size: The bar time-frame size (default M1).
    """

    def __init__(self, bar_size: BarSize = BarSize.M1) -> None:
        self._bar_size = bar_size

    def normalize(self, raw: list[Any], asset: Asset) -> Bar:
        """Convert a single Binance kline array to a :class:`Bar`.

        Args:
            raw: A Binance kline array (12 elements).
            asset: The resolved asset providing ``asset_id``.

        Returns:
            A fully populated :class:`Bar`.
        """
        open_time_ms = int(raw[0])
        open_price = Decimal(str(raw[1]))
        high_price = Decimal(str(raw[2]))
        low_price = Decimal(str(raw[3]))
        close_price = Decimal(str(raw[4]))
        volume = Decimal(str(raw[5]))
        quote_volume = Decimal(str(raw[7]))
        trade_count = int(raw[8])

        timestamp = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC)

        vwap: Decimal | None = None
        if volume > 0:
            vwap = quote_volume / volume

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
            trade_count=trade_count,
            vwap=vwap,
        )
