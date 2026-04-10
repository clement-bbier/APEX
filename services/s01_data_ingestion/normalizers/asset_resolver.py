"""Asset resolver with in-memory cache.

Maps (symbol, exchange) pairs to :class:`~core.models.data.Asset` instances,
backed by :class:`~core.data.timescale_repository.TimescaleRepository`.
"""

from __future__ import annotations

from typing import Any

from core.data.timescale_repository import TimescaleRepository
from core.models.data import Asset


class AssetResolver:
    """Resolves (symbol, exchange) -> Asset with in-memory cache."""

    def __init__(self, repository: TimescaleRepository) -> None:
        self._repo = repository
        self._cache: dict[tuple[str, str], Asset] = {}

    async def resolve(self, symbol: str, exchange: str) -> Asset:
        """Look up an asset by symbol and exchange.

        Args:
            symbol: Trading symbol (uppercased internally).
            exchange: Exchange name.

        Returns:
            The matching :class:`Asset`.

        Raises:
            ValueError: If the asset is not found.
        """
        key = (symbol.upper(), exchange.upper())
        if key in self._cache:
            return self._cache[key]
        asset = await self._repo.get_asset(symbol.upper(), exchange.upper())
        if asset is None:
            raise ValueError(f"Asset not found: {symbol} on {exchange}")
        self._cache[key] = asset
        return asset

    async def resolve_or_create(
        self, symbol: str, exchange: str, defaults: dict[str, Any]
    ) -> Asset:
        """Look up or create an asset.

        Args:
            symbol: Trading symbol (uppercased internally).
            exchange: Exchange name (uppercased internally).
            defaults: Default field values passed to
                :class:`~core.models.data.Asset` if creating a new entry.

        Returns:
            The existing or newly created :class:`Asset`.

        Raises:
            RuntimeError: If asset creation fails.
        """
        key = (symbol.upper(), exchange.upper())
        if key in self._cache:
            return self._cache[key]
        asset = await self._repo.get_asset(symbol.upper(), exchange.upper())
        if asset is None:
            new_asset = Asset(
                symbol=symbol.upper(),
                exchange=exchange.upper(),
                **defaults,
            )
            asset_id = await self._repo.upsert_asset(new_asset)
            asset = await self._repo.get_asset_by_id(asset_id)
            if asset is None:
                raise RuntimeError(f"Failed to create asset: {symbol}@{exchange}")
        self._cache[key] = asset
        return asset

    def clear_cache(self) -> None:
        """Clear the in-memory asset cache."""
        self._cache.clear()
