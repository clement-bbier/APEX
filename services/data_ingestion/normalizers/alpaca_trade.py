"""Alpaca historical trade normalizer.

Transforms alpaca-py SDK ``Trade`` objects into :class:`~core.models.data.DbTick`
instances for TimescaleDB persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.models.data import Asset, DbTick
from services.data_ingestion.normalizers.base import NormalizerStrategy


class AlpacaTradeNormalizer(NormalizerStrategy[Any, DbTick]):
    """Normalizes alpaca-py ``Trade`` objects to :class:`DbTick`.

    Expected attributes on the raw object (alpaca-py ``Trade``):

    * ``timestamp`` — ``datetime``
    * ``price`` — ``float``
    * ``size`` — ``float``
    * ``exchange`` — ``str``
    * ``id`` — ``int``
    * ``conditions`` — ``list[str]``
    """

    def normalize(self, raw: Any, asset: Asset) -> DbTick:  # noqa: ANN401
        """Convert an alpaca-py Trade to a :class:`DbTick`.

        Args:
            raw: An alpaca-py ``Trade`` instance (or duck-typed equivalent).
            asset: The resolved asset providing ``asset_id``.

        Returns:
            A fully populated :class:`DbTick`.
        """
        ts: datetime = raw.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        trade_id = str(getattr(raw, "id", ""))
        price = Decimal(str(raw.price))
        size = Decimal(str(raw.size))

        return DbTick(
            asset_id=asset.asset_id,
            timestamp=ts,
            trade_id=trade_id,
            price=price,
            quantity=size,
            side="unknown",
        )
