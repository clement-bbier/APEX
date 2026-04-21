"""Alpaca trade-stream tick normalizer.

Refactored from the monolithic ``normalizer.py`` AlpacaNormalizer.
Produces :class:`~core.models.tick.NormalizedTick` from Alpaca trade events.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from core.models.data import Asset
from core.models.tick import Market, NormalizedTick, RawTick, TradeSide
from services.data_ingestion.normalizers.base import NormalizerStrategy
from services.data_ingestion.normalizers.session_tagger import SessionTagger


class AlpacaTickNormalizer(NormalizerStrategy[dict[str, Any], NormalizedTick]):
    """Normalizes Alpaca trade-stream payloads to :class:`NormalizedTick`.

    Expected raw-data keys (Alpaca ``T="t"`` trade message):

    * ``S`` - symbol (str)
    * ``t`` - ISO 8601 timestamp string
    * ``p`` - price (float)
    * ``s`` - size / volume (float)
    * ``c`` - conditions list (list[str])
    """

    _tagger = SessionTagger()

    def normalize(self, raw: dict[str, Any], asset: Asset) -> NormalizedTick:
        """Convert an Alpaca trade message dict to a :class:`NormalizedTick`.

        Args:
            raw: A single Alpaca trade event dict.
            asset: The resolved asset (reserved for future use).

        Returns:
            A fully populated :class:`NormalizedTick` for the equity market.
        """
        return self._normalize_raw(raw)

    def normalize_legacy(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Legacy API — normalize without requiring an Asset.

        Preserves backward compatibility with code that calls
        ``AlpacaNormalizer().normalize(raw_data)``.
        """
        return self._normalize_raw(raw_data)

    def _normalize_raw(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Core normalization logic (shared by new and legacy APIs)."""
        symbol: str = str(raw_data.get("S", "")).upper()

        raw_ts: str = str(raw_data.get("t", ""))
        ts_utc = self._parse_alpaca_timestamp(raw_ts)
        timestamp_ms: int = int(ts_utc.timestamp() * 1000)

        price = Decimal(str(raw_data["p"]))
        volume = Decimal(str(raw_data["s"]))

        side = TradeSide.UNKNOWN

        session = self._tagger.tag(ts_utc)

        raw_tick = RawTick(
            symbol=symbol,
            market=Market.EQUITY,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            raw_data=raw_data,
        )

        return NormalizedTick(
            symbol=symbol,
            market=Market.EQUITY,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            session=session,
            source_tick=raw_tick,
        )

    @staticmethod
    def _parse_alpaca_timestamp(raw: str) -> datetime:
        """Parse an Alpaca ISO 8601 timestamp to a UTC-aware :class:`datetime`.

        Handles nanosecond precision by truncating to microseconds.

        Args:
            raw: ISO timestamp string, e.g. ``"2024-01-15T14:30:00.123456789Z"``.

        Returns:
            UTC-aware :class:`datetime`.
        """
        normalised = raw.replace("Z", "+00:00")

        if "." in normalised:
            dot_idx = normalised.index(".")
            tz_idx = (
                normalised.index("+", dot_idx) if "+" in normalised[dot_idx:] else len(normalised)
            )
            sub_second = normalised[dot_idx + 1 : tz_idx]
            truncated_sub = sub_second[:6].ljust(6, "0")
            normalised = normalised[: dot_idx + 1] + truncated_sub + normalised[tz_idx:]

        return datetime.fromisoformat(normalised)
