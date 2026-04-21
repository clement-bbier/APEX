"""Binance trade-stream tick normalizer.

Refactored from the monolithic ``normalizer.py`` BinanceNormalizer.
Produces :class:`~core.models.tick.NormalizedTick` from Binance combined-stream
trade payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.models.data import Asset
from core.models.tick import Market, NormalizedTick, RawTick, TradeSide
from services.data_ingestion.normalizers.base import NormalizerStrategy
from services.data_ingestion.normalizers.session_tagger import SessionTagger


class BinanceTickNormalizer(NormalizerStrategy[dict[str, Any], NormalizedTick]):
    """Normalizes Binance combined-stream trade payloads to :class:`NormalizedTick`.

    Expected raw-data keys (Binance trade stream ``data`` object):

    * ``s`` - symbol (str)
    * ``T`` - trade timestamp UTC ms (int)
    * ``p`` - price (str)
    * ``q`` - quantity / volume (str)
    * ``m`` - is buyer the market maker (bool); ``True`` -> aggressor is SELL

    Optional book-ticker keys:

    * ``b`` - best bid price (str)
    * ``a`` - best ask price (str)
    """

    _tagger = SessionTagger()

    def normalize(self, raw: dict[str, Any], asset: Asset) -> NormalizedTick:
        """Convert a Binance trade ``data`` dict to a :class:`NormalizedTick`.

        Args:
            raw: The ``data`` field from a Binance combined-stream message.
            asset: The resolved asset (reserved for future use).

        Returns:
            A fully populated :class:`NormalizedTick` for the crypto market.
        """
        return self._normalize_raw(raw)

    def normalize_legacy(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Legacy API — normalize without requiring an Asset.

        Preserves backward compatibility with code that calls
        ``BinanceNormalizer().normalize(raw_data)``.
        """
        return self._normalize_raw(raw_data)

    def _normalize_raw(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Core normalization logic (shared by new and legacy APIs)."""
        symbol: str = str(raw_data.get("s", "")).upper()

        raw_ts = raw_data.get("T") or raw_data.get("t")
        if not raw_ts:
            raise ValueError(
                f"Binance trade payload is missing timestamp fields 'T'/'t': {raw_data}"
            )
        timestamp_ms: int = int(raw_ts)

        price = Decimal(str(raw_data["p"]))
        volume = Decimal(str(raw_data["q"]))

        is_maker_buy: bool = bool(raw_data.get("m", False))
        side = TradeSide.SELL if is_maker_buy else TradeSide.BUY

        bid: Decimal | None = Decimal(str(raw_data["b"])) if raw_data.get("b") else None
        ask: Decimal | None = Decimal(str(raw_data["a"])) if raw_data.get("a") else None

        ts_utc = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC)
        session = self._tagger.tag(ts_utc)

        raw_tick = RawTick(
            symbol=symbol,
            market=Market.CRYPTO,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            bid=bid,
            ask=ask,
            raw_data=raw_data,
        )

        return NormalizedTick(
            symbol=symbol,
            market=Market.CRYPTO,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            bid=bid,
            ask=ask,
            session=session,
            source_tick=raw_tick,
        )
