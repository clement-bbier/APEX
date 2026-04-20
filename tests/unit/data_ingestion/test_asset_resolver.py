"""Unit tests for AssetResolver."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.data import Asset, AssetClass
from services.s01_data_ingestion.normalizers.asset_resolver import AssetResolver


def _make_asset(symbol: str = "BTCUSDT", exchange: str = "BINANCE") -> Asset:
    """Create a test Asset."""
    return Asset(
        asset_id=uuid.uuid4(),
        symbol=symbol,
        exchange=exchange,
        asset_class=AssetClass.CRYPTO,
        currency="USD",
    )


def _mock_repo() -> MagicMock:
    """Create a mock TimescaleRepository with async methods."""
    repo = MagicMock()
    repo.get_asset = AsyncMock()
    repo.get_asset_by_id = AsyncMock()
    repo.upsert_asset = AsyncMock()
    return repo


class TestAssetResolver:
    """Tests for AssetResolver."""

    @pytest.mark.asyncio
    async def test_resolve_found(self) -> None:
        repo = _mock_repo()
        asset = _make_asset()
        repo.get_asset.return_value = asset

        resolver = AssetResolver(repo)
        result = await resolver.resolve("BTCUSDT", "BINANCE")

        assert result is asset
        repo.get_asset.assert_awaited_once_with("BTCUSDT", "BINANCE")

    @pytest.mark.asyncio
    async def test_resolve_not_found(self) -> None:
        repo = _mock_repo()
        repo.get_asset.return_value = None

        resolver = AssetResolver(repo)
        with pytest.raises(ValueError, match="Asset not found"):
            await resolver.resolve("UNKNOWN", "BINANCE")

    @pytest.mark.asyncio
    async def test_resolve_cache_hit(self) -> None:
        repo = _mock_repo()
        asset = _make_asset()
        repo.get_asset.return_value = asset

        resolver = AssetResolver(repo)
        await resolver.resolve("BTCUSDT", "BINANCE")
        await resolver.resolve("BTCUSDT", "BINANCE")

        # Should only hit repo once due to caching.
        repo.get_asset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_or_create_existing(self) -> None:
        repo = _mock_repo()
        asset = _make_asset()
        repo.get_asset.return_value = asset

        resolver = AssetResolver(repo)
        result = await resolver.resolve_or_create(
            "BTCUSDT", "BINANCE", {"asset_class": "crypto", "currency": "USD"}
        )

        assert result is asset
        repo.upsert_asset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_or_create_new(self) -> None:
        repo = _mock_repo()
        new_asset = _make_asset(symbol="ETHUSDT")
        repo.get_asset.return_value = None
        repo.upsert_asset.return_value = new_asset.asset_id
        repo.get_asset_by_id.return_value = new_asset

        resolver = AssetResolver(repo)
        result = await resolver.resolve_or_create(
            "ETHUSDT",
            "BINANCE",
            {"asset_class": AssetClass.CRYPTO, "currency": "USD"},
        )

        assert result is new_asset
        repo.upsert_asset.assert_awaited_once()
        repo.get_asset_by_id.assert_awaited_once_with(new_asset.asset_id)

    @pytest.mark.asyncio
    async def test_clear_cache(self) -> None:
        repo = _mock_repo()
        asset = _make_asset()
        repo.get_asset.return_value = asset

        resolver = AssetResolver(repo)
        await resolver.resolve("BTCUSDT", "BINANCE")

        resolver.clear_cache()
        await resolver.resolve("BTCUSDT", "BINANCE")

        # After clearing cache, should hit repo again.
        assert repo.get_asset.await_count == 2
