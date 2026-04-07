"""
Integration test configuration.
All integration tests require Docker Redis to be running.
Run: docker compose -f docker/docker-compose.test.yml up -d
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
import redis.asyncio as aioredis


@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    """Session-scoped event loop for all integration tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def redis_client():  # type: ignore[misc]
    """Real Redis connection for integration tests."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/1")  # db=1, not 0
    client = aioredis.Redis.from_url(url, decode_responses=True)
    await client.ping()
    yield client
    await client.flushdb()  # clean up test data
    await client.aclose()
