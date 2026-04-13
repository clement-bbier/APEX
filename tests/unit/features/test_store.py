"""Tests for features.store.timescale — TimescaleFeatureStore.

Tests use AsyncMock for asyncpg and fakeredis for Redis, following
CLAUDE.md Section 7 (no real Redis in unit tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import fakeredis.aioredis
import polars as pl
import pytest

from features.exceptions import (
    FeatureVersionExistsError,
    FeatureVersionNotFoundError,
)
from features.registry import FeatureRegistry
from features.store.timescale import TimescaleFeatureStore
from features.versioning import FeatureVersion

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_version(
    asset_id: object | None = None,
    feature_name: str = "har_rv",
    version: str = "har_rv-abc12345",
    computed_at: datetime | None = None,
    row_count: int = 3,
) -> FeatureVersion:
    return FeatureVersion(
        asset_id=asset_id or uuid4(),
        feature_name=feature_name,
        version=version,
        computed_at=computed_at or datetime(2024, 6, 1, tzinfo=UTC),
        content_hash="a" * 64,
        calculator_name="har_rv",
        calculator_params={},
        row_count=row_count,
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _make_feature_df(
    feature_name: str = "har_rv",
    n: int = 3,
    base_ts: datetime | None = None,
) -> pl.DataFrame:
    base = base_ts or datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [base + timedelta(minutes=5 * i) for i in range(n)],
            feature_name: [float(i + 1) for i in range(n)],
        }
    )


@pytest.fixture
def redis_client() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def mock_pool() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_registry() -> AsyncMock:
    return AsyncMock(spec=FeatureRegistry)


@pytest.fixture
def store(
    mock_pool: AsyncMock,
    redis_client: fakeredis.aioredis.FakeRedis,
    mock_registry: AsyncMock,
) -> TimescaleFeatureStore:
    return TimescaleFeatureStore(
        pg_pool=mock_pool,
        redis_client=redis_client,
        registry=mock_registry,
    )


# ── Save tests ───────────────────────────────────────────────────────────


class TestStoreSave:
    """TimescaleFeatureStore.save persists features and registers version."""

    @pytest.mark.asyncio
    async def test_save_copies_records(
        self, store: TimescaleFeatureStore, mock_pool: AsyncMock, mock_registry: AsyncMock
    ) -> None:
        mock_registry.get.return_value = None
        aid = uuid4()
        version = _make_version(asset_id=aid)
        df = _make_feature_df()

        await store.save(aid, df, version)

        mock_pool.copy_records_to_table.assert_awaited_once()
        call_args = mock_pool.copy_records_to_table.call_args
        assert call_args[1]["columns"][0] == "asset_id"

    @pytest.mark.asyncio
    async def test_save_registers_version(
        self, store: TimescaleFeatureStore, mock_registry: AsyncMock
    ) -> None:
        mock_registry.get.return_value = None
        aid = uuid4()
        version = _make_version(asset_id=aid)
        df = _make_feature_df()

        await store.save(aid, df, version)

        mock_registry.register.assert_awaited_once_with(version)

    @pytest.mark.asyncio
    async def test_save_duplicate_raises(
        self, store: TimescaleFeatureStore, mock_registry: AsyncMock
    ) -> None:
        existing = _make_version()
        mock_registry.get.return_value = existing
        aid = uuid4()
        version = _make_version(asset_id=aid)
        df = _make_feature_df()

        with pytest.raises(FeatureVersionExistsError, match="already exists"):
            await store.save(aid, df, version)


# ── Load tests ───────────────────────────────────────────────────────────


class TestStoreLoad:
    """TimescaleFeatureStore.load with point-in-time semantics."""

    @pytest.mark.asyncio
    async def test_load_empty_feature_names(self, store: TimescaleFeatureStore) -> None:
        result = await store.load(
            uuid4(), [], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
        )
        assert result.shape[0] == 0
        assert "timestamp" in result.columns

    @pytest.mark.asyncio
    async def test_load_resolves_latest_version(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        aid = uuid4()
        version = _make_version(asset_id=aid)
        mock_registry.latest_version.return_value = version
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 7, 1, tzinfo=UTC)

        mock_pool.fetch.return_value = [
            {"timestamp": ts1, "value": 1.0},
            {"timestamp": ts1 + timedelta(minutes=5), "value": 2.0},
        ]

        result = await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of)
        mock_registry.latest_version.assert_awaited_once_with(aid, "har_rv", as_of)
        assert "har_rv" in result.columns

    @pytest.mark.asyncio
    async def test_load_with_explicit_version(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        aid = uuid4()
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 7, 1, tzinfo=UTC)

        mock_pool.fetch.return_value = [
            {"timestamp": ts1, "value": 1.0},
        ]

        result = await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of, version="har_rv-explicit")
        # Should NOT call latest_version when version is explicit
        mock_registry.latest_version.assert_not_awaited()
        assert "har_rv" in result.columns

    @pytest.mark.asyncio
    async def test_load_version_not_found_raises(
        self,
        store: TimescaleFeatureStore,
        mock_registry: AsyncMock,
    ) -> None:
        mock_registry.latest_version.return_value = None
        aid = uuid4()
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 7, 1, tzinfo=UTC)

        with pytest.raises(FeatureVersionNotFoundError, match="No version found"):
            await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of)

    @pytest.mark.asyncio
    async def test_load_empty_result(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        mock_registry.latest_version.return_value = _make_version()
        mock_pool.fetch.return_value = []
        aid = uuid4()
        result = await store.load(
            aid,
            ["har_rv"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 6, 1, tzinfo=UTC),
            as_of=datetime(2024, 7, 1, tzinfo=UTC),
        )
        assert result.shape[0] == 0
        assert "har_rv" in result.columns

    @pytest.mark.asyncio
    async def test_load_multiple_features_pivoted(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        aid = uuid4()
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 7, 1, tzinfo=UTC)

        ver_a = _make_version(asset_id=aid, feature_name="feat_a")
        ver_b = _make_version(asset_id=aid, feature_name="feat_b", version="feat_b-xyz")
        mock_registry.latest_version.side_effect = [ver_a, ver_b]

        # First call for feat_a, second for feat_b
        mock_pool.fetch.side_effect = [
            [{"timestamp": ts1, "value": 1.0}],
            [{"timestamp": ts1, "value": 2.0}],
        ]

        result = await store.load(aid, ["feat_a", "feat_b"], ts1, ts2, as_of=as_of)
        assert "feat_a" in result.columns
        assert "feat_b" in result.columns
        assert result.shape[0] == 1

    @pytest.mark.asyncio
    async def test_load_warns_without_as_of(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        """load() without as_of defaults to now(UTC) and logs warning."""
        mock_registry.latest_version.return_value = _make_version()
        mock_pool.fetch.return_value = []

        # Should not raise — just warn
        await store.load(
            uuid4(),
            ["har_rv"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 6, 1, tzinfo=UTC),
        )


# ── Cache tests ──────────────────────────────────────────────────────────


class TestStoreCache:
    """Redis cache hit/miss behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
        redis_client: fakeredis.aioredis.FakeRedis,
    ) -> None:
        aid = uuid4()
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 7, 1, tzinfo=UTC)
        version = _make_version(asset_id=aid)
        mock_registry.latest_version.return_value = version

        mock_pool.fetch.return_value = [
            {"timestamp": ts1, "value": 42.0},
        ]

        # First load: cache miss, hits DB
        result1 = await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of)
        assert mock_pool.fetch.await_count == 1

        # Second load: cache hit, does NOT hit DB again
        result2 = await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of)
        assert mock_pool.fetch.await_count == 1  # still 1


# ── Point-in-time / Look-Ahead tests ────────────────────────────────────


class TestStoreLookAhead:
    """Structural look-ahead bias defense (PHASE_3_SPEC Section 5.1)."""

    @pytest.mark.asyncio
    async def test_load_as_of_filters_computed_at(
        self,
        store: TimescaleFeatureStore,
        mock_pool: AsyncMock,
        mock_registry: AsyncMock,
    ) -> None:
        """SQL query must include computed_at <= as_of."""
        aid = uuid4()
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 6, 1, tzinfo=UTC)
        as_of = datetime(2024, 3, 1, tzinfo=UTC)
        mock_registry.latest_version.return_value = _make_version(asset_id=aid)
        mock_pool.fetch.return_value = []

        await store.load(aid, ["har_rv"], ts1, ts2, as_of=as_of)

        call_args = mock_pool.fetch.call_args
        sql = call_args[0][0]
        assert "computed_at <= $6" in sql.replace("\n", " ").replace("  ", " ")
        # The 6th positional arg should be as_of
        assert call_args[0][6] == as_of

    @pytest.mark.asyncio
    async def test_pit_v1_before_v2(
        self,
        mock_pool: AsyncMock,
        redis_client: fakeredis.aioredis.FakeRedis,
    ) -> None:
        """save(v1) at t1 then save(v2) at t2 > t1:
        load(as_of=t1) returns v1, load(as_of=t2) returns v2."""
        aid = uuid4()
        t1 = datetime(2024, 3, 1, tzinfo=UTC)
        t2 = datetime(2024, 6, 1, tzinfo=UTC)
        ts_bar = datetime(2024, 2, 1, tzinfo=UTC)

        v1 = _make_version(asset_id=aid, version="v1", computed_at=t1, feature_name="har_rv")
        v2 = _make_version(asset_id=aid, version="v2", computed_at=t2, feature_name="har_rv")

        # Mock registry to return v1 for as_of=t1, v2 for as_of=t2
        registry = AsyncMock(spec=FeatureRegistry)

        async def _latest(
            a: object, fname: str, as_of: datetime | None = None
        ) -> FeatureVersion | None:
            if as_of is not None and as_of < t2:
                return v1
            return v2

        registry.latest_version.side_effect = _latest

        store = TimescaleFeatureStore(mock_pool, redis_client, registry)

        # as_of=t1 resolves v1
        mock_pool.fetch.return_value = [{"timestamp": ts_bar, "value": 10.0}]
        await store.load(aid, ["har_rv"], ts_bar, ts_bar, as_of=t1)
        call_args = mock_pool.fetch.call_args
        assert call_args[0][3] == "v1"  # version param

        # Reset for second call
        mock_pool.fetch.reset_mock()
        # Clear cache to force DB hit
        await redis_client.flushall()

        mock_pool.fetch.return_value = [{"timestamp": ts_bar, "value": 20.0}]
        await store.load(aid, ["har_rv"], ts_bar, ts_bar, as_of=t2)
        call_args = mock_pool.fetch.call_args
        assert call_args[0][3] == "v2"


# ── Delegate tests ───────────────────────────────────────────────────────


class TestStoreDelegates:
    """list_versions and latest_version delegate to registry."""

    @pytest.mark.asyncio
    async def test_list_versions_delegates(
        self, store: TimescaleFeatureStore, mock_registry: AsyncMock
    ) -> None:
        aid = uuid4()
        mock_registry.list_versions.return_value = []
        result = await store.list_versions(aid, "har_rv")
        mock_registry.list_versions.assert_awaited_once_with(aid, "har_rv")
        assert result == []

    @pytest.mark.asyncio
    async def test_latest_version_delegates(
        self, store: TimescaleFeatureStore, mock_registry: AsyncMock
    ) -> None:
        aid = uuid4()
        mock_registry.latest_version.return_value = None
        result = await store.latest_version(aid, "har_rv")
        mock_registry.latest_version.assert_awaited_once()
        assert result is None
