"""Tests for JobStateManager (Redis state management)."""

from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from services.s01_data_ingestion.orchestrator.state import JobRunResult, JobStateManager


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    """Create a fresh fakeredis instance."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def state(redis: fakeredis.aioredis.FakeRedis) -> JobStateManager:
    return JobStateManager(redis)


@pytest.fixture
def sample_result() -> JobRunResult:
    return JobRunResult(
        job_name="test_job",
        status="success",
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        finished_at=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
        rows_inserted=100,
    )


class TestLocking:
    """Tests for distributed lock acquire/release."""

    @pytest.mark.asyncio
    async def test_acquire_lock_succeeds(self, state: JobStateManager) -> None:
        assert await state.acquire_lock("job_a", ttl_seconds=60) is True

    @pytest.mark.asyncio
    async def test_acquire_lock_fails_when_held(self, state: JobStateManager) -> None:
        await state.acquire_lock("job_a", ttl_seconds=60)
        assert await state.acquire_lock("job_a", ttl_seconds=60) is False

    @pytest.mark.asyncio
    async def test_release_lock(self, state: JobStateManager) -> None:
        await state.acquire_lock("job_a", ttl_seconds=60)
        await state.release_lock("job_a")
        assert await state.acquire_lock("job_a", ttl_seconds=60) is True


class TestLastSuccess:
    """Tests for last_success timestamp storage."""

    @pytest.mark.asyncio
    async def test_get_returns_none_when_unset(self, state: JobStateManager) -> None:
        assert await state.get_last_success("job_a") is None

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self, state: JobStateManager) -> None:
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        await state.set_last_success("job_a", ts)
        result = await state.get_last_success("job_a")
        assert result == ts


class TestRunHistory:
    """Tests for run history stream."""

    @pytest.mark.asyncio
    async def test_append_and_get(
        self,
        state: JobStateManager,
        sample_result: JobRunResult,
    ) -> None:
        await state.append_run_history("test_job", sample_result)
        history = await state.get_run_history("test_job", limit=10)
        assert len(history) == 1
        assert history[0].status == "success"
        assert history[0].rows_inserted == 100

    @pytest.mark.asyncio
    async def test_empty_history(self, state: JobStateManager) -> None:
        history = await state.get_run_history("nonexistent", limit=10)
        assert history == []

    @pytest.mark.asyncio
    async def test_clear_state(
        self,
        state: JobStateManager,
        sample_result: JobRunResult,
    ) -> None:
        await state.acquire_lock("test_job", ttl_seconds=60)
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        await state.set_last_success("test_job", ts)
        await state.append_run_history("test_job", sample_result)

        await state.clear_state("test_job")

        assert await state.acquire_lock("test_job", ttl_seconds=60) is True
        assert await state.get_last_success("test_job") is None
        assert await state.get_run_history("test_job") == []
