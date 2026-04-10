"""DEPRECATED — Use services.s01_data_ingestion.normalizers instead.

This module re-exports legacy classes for backward compatibility.
All new code should import from the normalizers package directly.
"""

from __future__ import annotations

from typing import Any

from core.models.tick import Market, NormalizedTick
from services.s01_data_ingestion.normalizers.session_tagger import (
    SessionTagger as SessionTagger,
)


class BinanceNormalizer:
    """Legacy wrapper — delegates to :class:`BinanceTickNormalizer`.

    Preserves the old ``normalize(raw_data)`` single-argument API.
    """

    def __init__(self) -> None:
        from services.s01_data_ingestion.normalizers.binance_tick import (
            BinanceTickNormalizer,
        )

        self._impl = BinanceTickNormalizer()

    def normalize(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Normalize a Binance trade payload (legacy single-arg API)."""
        return self._impl.normalize_legacy(raw_data)


class AlpacaNormalizer:
    """Legacy wrapper — delegates to :class:`AlpacaTickNormalizer`.

    Preserves the old ``normalize(raw_data)`` single-argument API.
    """

    def __init__(self) -> None:
        from services.s01_data_ingestion.normalizers.alpaca_tick import (
            AlpacaTickNormalizer,
        )

        self._impl = AlpacaTickNormalizer()

    def normalize(self, raw_data: dict[str, Any]) -> NormalizedTick:
        """Normalize an Alpaca trade payload (legacy single-arg API)."""
        return self._impl.normalize_legacy(raw_data)


class NormalizerFactory:
    """Factory that returns the appropriate normalizer for a given market.

    Usage::

        normalizer = NormalizerFactory.create(Market.CRYPTO)
        tick = normalizer.normalize(raw_data)
    """

    @staticmethod
    def create(market: Market) -> BinanceNormalizer | AlpacaNormalizer:
        """Return the normalizer for *market*.

        Args:
            market: The :class:`~core.models.tick.Market` to normalise for.

        Returns:
            A :class:`BinanceNormalizer` for crypto or
            :class:`AlpacaNormalizer` for equity.

        Raises:
            ValueError: If *market* is not supported.
        """
        if market == Market.CRYPTO:
            return BinanceNormalizer()
        if market == Market.EQUITY:
            return AlpacaNormalizer()
        raise ValueError(f"No normalizer registered for market: {market!r}")
