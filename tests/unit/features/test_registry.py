"""Tests for features.registry — FeatureRegistry metadata catalog."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from features.registry import FeatureRegistry
from features.versioning import FeatureVersion


def _make_version(
    asset_id: object | None = None,
    feature_name: str = "har_rv",
    version: str = "har_rv-abc12345",
    computed_at: datetime | None = None,
) -> FeatureVersion:
    """Helper to create a FeatureVersion with sane defaults."""
    return FeatureVersion(
        asset_id=asset_id or uuid4(),
        feature_name=feature_name,
        version=version,
        computed_at=computed_at or datetime.now(UTC),
        content_hash="a" * 64,
        calculator_name="har_rv",
        calculator_params={},
        row_count=100,
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _mock_pool() -> AsyncMock:
    """Create a mock asyncpg pool."""
    return AsyncMock()


class TestRegistryRegister:
    """FeatureRegistry.register inserts into feature_versions."""

    @pytest.mark.asyncio
    async def test_register_calls_execute(self) -> None:
        pool = _mock_pool()
        registry = FeatureRegistry(pool)
        version = _make_version()
        await registry.register(version)
        pool.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_passes_all_fields(self) -> None:
        pool = _mock_pool()
        registry = FeatureRegistry(pool)
        version = _make_version()
        await registry.register(version)
        call_args = pool.execute.call_args
        assert call_args[0][1] == version.asset_id
        assert call_args[0][2] == version.feature_name
        assert call_args[0][3] == version.version


class TestRegistryListFeatures:
    """FeatureRegistry.list_features returns distinct feature names."""

    @pytest.mark.asyncio
    async def test_list_features_returns_names(self) -> None:
        pool = _mock_pool()
        pool.fetch.return_value = [
            {"feature_name": "har_rv"},
            {"feature_name": "ofi"},
        ]
        registry = FeatureRegistry(pool)
        result = await registry.list_features(uuid4())
        assert result == ["har_rv", "ofi"]

    @pytest.mark.asyncio
    async def test_list_features_empty(self) -> None:
        pool = _mock_pool()
        pool.fetch.return_value = []
        registry = FeatureRegistry(pool)
        result = await registry.list_features(uuid4())
        assert result == []


class TestRegistryListVersions:
    """FeatureRegistry.list_versions returns FeatureVersion records."""

    @pytest.mark.asyncio
    async def test_list_versions_returns_records(self) -> None:
        pool = _mock_pool()
        aid = uuid4()
        ts = datetime(2024, 6, 1, tzinfo=UTC)
        pool.fetch.return_value = [
            {
                "asset_id": aid,
                "feature_name": "har_rv",
                "version": "har_rv-abc12345",
                "computed_at": ts,
                "content_hash": "a" * 64,
                "calculator_name": "har_rv",
                "calculator_params": {},
                "row_count": 100,
                "start_ts": datetime(2024, 1, 1, tzinfo=UTC),
                "end_ts": datetime(2024, 6, 1, tzinfo=UTC),
            }
        ]
        registry = FeatureRegistry(pool)
        result = await registry.list_versions(aid, "har_rv")
        assert len(result) == 1
        assert result[0].version == "har_rv-abc12345"


class TestRegistryLatestVersion:
    """FeatureRegistry.latest_version with and without as_of."""

    @pytest.mark.asyncio
    async def test_latest_version_found(self) -> None:
        pool = _mock_pool()
        aid = uuid4()
        ts = datetime(2024, 6, 1, tzinfo=UTC)
        pool.fetchrow.return_value = {
            "asset_id": aid,
            "feature_name": "har_rv",
            "version": "har_rv-abc12345",
            "computed_at": ts,
            "content_hash": "a" * 64,
            "calculator_name": "har_rv",
            "calculator_params": {},
            "row_count": 100,
            "start_ts": datetime(2024, 1, 1, tzinfo=UTC),
            "end_ts": datetime(2024, 6, 1, tzinfo=UTC),
        }
        registry = FeatureRegistry(pool)
        result = await registry.latest_version(aid, "har_rv")
        assert result is not None
        assert result.version == "har_rv-abc12345"

    @pytest.mark.asyncio
    async def test_latest_version_none_when_empty(self) -> None:
        pool = _mock_pool()
        pool.fetchrow.return_value = None
        registry = FeatureRegistry(pool)
        result = await registry.latest_version(uuid4(), "har_rv")
        assert result is None

    @pytest.mark.asyncio
    async def test_latest_version_with_as_of(self) -> None:
        pool = _mock_pool()
        pool.fetchrow.return_value = None
        registry = FeatureRegistry(pool)
        as_of = datetime(2024, 1, 1, tzinfo=UTC)
        result = await registry.latest_version(uuid4(), "har_rv", as_of=as_of)
        assert result is None
        # Verify as_of was passed to the query
        call_args = pool.fetchrow.call_args
        assert call_args[0][3] == as_of


class TestRegistryGet:
    """FeatureRegistry.get retrieves a specific version."""

    @pytest.mark.asyncio
    async def test_get_existing(self) -> None:
        pool = _mock_pool()
        aid = uuid4()
        ts = datetime(2024, 6, 1, tzinfo=UTC)
        pool.fetchrow.return_value = {
            "asset_id": aid,
            "feature_name": "har_rv",
            "version": "har_rv-abc12345",
            "computed_at": ts,
            "content_hash": "a" * 64,
            "calculator_name": "har_rv",
            "calculator_params": "{}",
            "row_count": 100,
            "start_ts": datetime(2024, 1, 1, tzinfo=UTC),
            "end_ts": datetime(2024, 6, 1, tzinfo=UTC),
        }
        registry = FeatureRegistry(pool)
        result = await registry.get(aid, "har_rv", "har_rv-abc12345")
        assert result is not None
        assert result.version == "har_rv-abc12345"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self) -> None:
        pool = _mock_pool()
        pool.fetchrow.return_value = None
        registry = FeatureRegistry(pool)
        result = await registry.get(uuid4(), "har_rv", "nonexistent")
        assert result is None
