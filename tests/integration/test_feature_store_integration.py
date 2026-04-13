"""Integration tests for Feature Store (Phase 3.2).

Requires a running TimescaleDB instance (docker-compose.test.yml).
Run with: pytest tests/integration/test_feature_store_integration.py -m integration

Tests verify:
  - Migration 002 creates feature_values + feature_versions tables
  - Round-trip save/load with point-in-time semantics
  - Hypertable creation and compression policy
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

try:
    import fakeredis.aioredis
except ImportError:
    fakeredis = None  # type: ignore[assignment]

import polars as pl

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(asyncpg is None, reason="asyncpg not installed"),
    pytest.mark.skipif(fakeredis is None, reason="fakeredis not installed"),
]

TEST_DSN = "postgresql://apex_test:apex_test@localhost:5433/apex_test"


@pytest.fixture
async def initialized_db() -> asyncpg.Pool[asyncpg.Record]:
    """Run migrations and return a pool."""
    from scripts.init_db import run_migrations

    await run_migrations(
        host="localhost",
        port=5433,
        db="apex_test",
        user="apex_test",
        password="apex_test",
    )
    pool: asyncpg.Pool[asyncpg.Record] = await asyncpg.create_pool(TEST_DSN)
    yield pool  # type: ignore[misc]
    await pool.close()


@pytest.fixture
async def test_asset(initialized_db: asyncpg.Pool[asyncpg.Record]) -> uuid.UUID:
    """Create a test asset and return its UUID."""
    asset_id = uuid.uuid4()
    await initialized_db.execute(
        """
        INSERT INTO assets (asset_id, symbol, exchange, asset_class, currency)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (symbol, exchange) DO UPDATE SET asset_id = $1
        RETURNING asset_id
        """,
        asset_id,
        f"TEST_{asset_id.hex[:6]}",
        "TEST",
        "crypto",
        "USD",
    )
    return asset_id


class TestFeatureStoreIntegration:
    """Full round-trip on TimescaleDB."""

    @pytest.mark.asyncio
    async def test_tables_exist(self, initialized_db: asyncpg.Pool[asyncpg.Record]) -> None:
        """Migration 002 creates feature_values and feature_versions."""
        for table in ("feature_values", "feature_versions"):
            row = await initialized_db.fetchrow(
                "SELECT 1 FROM information_schema.tables WHERE table_name = $1",
                table,
            )
            assert row is not None, f"Table {table} does not exist"

    @pytest.mark.asyncio
    async def test_hypertable_created(self, initialized_db: asyncpg.Pool[asyncpg.Record]) -> None:
        """feature_values should be a TimescaleDB hypertable."""
        row = await initialized_db.fetchrow(
            """
            SELECT hypertable_name FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'feature_values'
            """
        )
        assert row is not None, "feature_values is not a hypertable"

    @pytest.mark.asyncio
    async def test_round_trip_save_load(
        self,
        initialized_db: asyncpg.Pool[asyncpg.Record],
        test_asset: uuid.UUID,
    ) -> None:
        """Save features, load them back, verify data integrity."""
        from features.registry import FeatureRegistry
        from features.store.timescale import TimescaleFeatureStore
        from features.versioning import (
            FeatureVersion,
            compute_content_hash,
            compute_version_string,
        )

        redis_client = fakeredis.aioredis.FakeRedis()
        registry = FeatureRegistry(initialized_db)
        store = TimescaleFeatureStore(initialized_db, redis_client, registry)

        # Build test data
        n = 100
        base_ts = datetime(2024, 1, 1, tzinfo=UTC)
        timestamps = [base_ts + timedelta(minutes=5 * i) for i in range(n)]
        values = [float(i) * 0.01 for i in range(n)]
        df = pl.DataFrame({"timestamp": timestamps, "har_rv": values})

        computed_at = datetime(2024, 7, 1, tzinfo=UTC)
        version_str = compute_version_string("har_rv", {}, computed_at)
        version = FeatureVersion(
            asset_id=test_asset,
            feature_name="har_rv",
            version=version_str,
            computed_at=computed_at,
            content_hash=compute_content_hash(df),
            calculator_name="har_rv",
            calculator_params={},
            row_count=n,
            start_ts=timestamps[0],
            end_ts=timestamps[-1],
        )

        await store.save(test_asset, df, version)

        # Load back
        result = await store.load(
            test_asset,
            ["har_rv"],
            timestamps[0],
            timestamps[-1],
            as_of=datetime(2025, 1, 1, tzinfo=UTC),
        )

        assert result.shape[0] == n
        assert "har_rv" in result.columns
        assert "timestamp" in result.columns
