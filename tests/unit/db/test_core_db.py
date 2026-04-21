"""Tests for ``core.db.DBPool`` against a real TimescaleDB container.

These tests are marked ``integration`` because they require a Docker
daemon — they are skipped automatically if either Docker or the
``testcontainers`` package is unavailable, so the unit-test CI lane
stays green on machines without Docker.

The container spins up once per test module (session-scoped fixture is
a future optimisation; per-module keeps fixture code small and
isolation strong).
"""

from __future__ import annotations

import pytest

testcontainers = pytest.importorskip(
    "testcontainers.postgres",
    reason="testcontainers-python is not installed — skipping DB integration tests.",
)

from testcontainers.postgres import PostgresContainer  # noqa: E402

from core.db import DBPool, DBSettings  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def timescale_container() -> PostgresContainer:
    """Spin up a TimescaleDB container for the duration of this module."""
    container = PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        username="apex",
        password="apex_secret",
        dbname="apex_test",
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
def settings(timescale_container: PostgresContainer) -> DBSettings:
    """Build ``DBSettings`` from the live testcontainer."""
    return DBSettings(
        host=timescale_container.get_container_host_ip(),
        port=int(timescale_container.get_exposed_port(5432)),
        user="apex",
        password="apex_secret",
        database="apex_test",
        pool_min=1,
        pool_max=3,
    )


async def test_pool_opens_and_closes(settings: DBSettings) -> None:
    """``DBPool`` enters and exits cleanly against a live TimescaleDB."""
    pool = DBPool(settings)
    assert pool.is_open is False
    async with pool:
        assert pool.is_open is True
    assert pool.is_open is False


async def test_get_connection_runs_select(settings: DBSettings) -> None:
    """``get_connection`` yields a usable asyncpg connection."""
    async with DBPool(settings) as pool:
        async with pool.get_connection() as conn:
            value = await conn.fetchval("SELECT 42")
            assert value == 42


async def test_get_connection_before_enter_raises(settings: DBSettings) -> None:
    """Acquiring a connection before entering the pool must fail loudly."""
    pool = DBPool(settings)
    with pytest.raises(RuntimeError, match="not active"):
        async with pool.get_connection():
            pass  # pragma: no cover — the `with` never yields


async def test_jsonb_roundtrip(settings: DBSettings) -> None:
    """JSONB codec registration round-trips dicts without str serialisation."""
    async with DBPool(settings) as pool:
        async with pool.get_connection() as conn:
            payload = {"strategy_id": "default", "n": 3, "nested": {"a": 1}}
            result = await conn.fetchval("SELECT $1::jsonb", payload)
            assert result == payload
