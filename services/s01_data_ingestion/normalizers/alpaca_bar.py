"""Alpaca historical bar normalizer.

Transforms alpaca-py SDK ``Bar`` objects into :class:`~core.models.data.Bar`
instances for TimescaleDB persistence.

References:
    Alpaca Markets API docs — https://docs.alpaca.markets/
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.models.data import Asset, Bar, BarSize, BarType
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy


class AlpacaBarPayload:
    """Structural type for alpaca-py Bar objects.

    Allows duck-typing against the alpaca-py ``Bar`` without importing the SDK
    at module level, making the normalizer testable without alpaca-py installed.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    trade_count: int | None


class AlpacaBarNormalizer(NormalizerStrategy[Any, Bar]):
    """Normalizes alpaca-py ``Bar`` objects to :class:`Bar`.

    Args:
        bar_size: The bar time-frame size (default M1).
    """

    def __init__(self, bar_size: BarSize = BarSize.M1) -> None:
        self._bar_size = bar_size

    def normalize(self, raw: Any, asset: Asset) -> Bar:  # noqa: ANN401
        """Convert an alpaca-py Bar object to a :class:`Bar`.

        Args:
            raw: An alpaca-py ``Bar`` instance (or duck-typed equivalent).
            asset: The resolved asset providing ``asset_id``.

        Returns:
            A fully populated :class:`Bar`.
        """
        ts: datetime = raw.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        open_price = Decimal(str(raw.open))
        high_price = Decimal(str(raw.high))
        low_price = Decimal(str(raw.low))
        close_price = Decimal(str(raw.close))
        volume = Decimal(str(raw.volume))

        vwap: Decimal | None = None
        if hasattr(raw, "vwap") and raw.vwap is not None:
            vwap = Decimal(str(raw.vwap))

        trade_count: int | None = None
        if hasattr(raw, "trade_count") and raw.trade_count is not None:
            trade_count = int(raw.trade_count)

        return Bar(
            asset_id=asset.asset_id,
            bar_type=BarType.TIME,
            bar_size=self._bar_size,
            timestamp=ts,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            trade_count=trade_count,
            vwap=vwap,
        )
