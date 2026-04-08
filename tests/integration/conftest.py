"""
Integration test configuration.
All integration tests require Docker Redis to be running.
Run: docker compose -f docker/docker-compose.test.yml up -d
"""

from __future__ import annotations

import os

import pytest_asyncio
import redis.asyncio as aioredis


@pytest_asyncio.fixture(scope="session")
async def redis_client():  # type: ignore[misc]
    """Real Redis connection for integration tests."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/1")  # db=1, not 0
    client = aioredis.Redis.from_url(url, decode_responses=True)
    await client.ping()
    yield client
    await client.flushdb()  # clean up test data
    await client.aclose()
