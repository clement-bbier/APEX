"""Tests for BackfillScheduler (cron-based scheduling)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.s01_data_ingestion.orchestrator.config import JobConfig
from services.s01_data_ingestion.orchestrator.scheduler import (
    BackfillScheduler,
    _seconds_until_next,
)
from services.s01_data_ingestion.orchestrator.state import JobRunResult


def _make_job(name: str = "test_job", schedule: str = "* * * * *") -> JobConfig:
    return JobConfig(
        name=name,
        connector="binance_historical",
        schedule=schedule,
        params={"symbol": "BTCUSDT", "bar_size": "M1"},
    )


def _make_runner(result_status: str = "success") -> MagicMock:
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=JobRunResult(
            job_name="test_job",
            status=result_status,
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
            rows_inserted=42,
        )
    )
    return runner


class TestSecondsUntilNext:
    """Tests for cron next-trigger computation."""

    def test_every_minute_is_within_60s(self) -> None:
        delay = _seconds_until_next("* * * * *")
        assert 0 < delay <= 61

    def test_returns_positive(self) -> None:
        delay = _seconds_until_next("0 0 1 1 *")  # once a year
        assert delay > 0

    def test_valid_cron_parses(self) -> None:
        assert isinstance(_seconds_until_next("30 6 * * 1-5"), float)

    def test_invalid_cron_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            _seconds_until_next("invalid cron")


class TestBackfillScheduler:
    """Tests for the scheduler lifecycle."""

    @pytest.mark.asyncio
    async def test_disabled_jobs_not_scheduled(self) -> None:
        disabled_job = JobConfig(
            name="disabled",
            connector="fred",
            schedule="* * * * *",
            enabled=False,
        )
        runner_factory = MagicMock()
        scheduler = BackfillScheduler([disabled_job], runner_factory)

        # Start and immediately stop
        stop_task = asyncio.create_task(_stop_after(scheduler, 0.05))
        await scheduler.start()
        await stop_task

        runner_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self) -> None:
        job = _make_job(schedule="* * * * *")
        runner = _make_runner()
        scheduler = BackfillScheduler([job], lambda j: runner)

        stop_task = asyncio.create_task(_stop_after(scheduler, 0.05))
        await scheduler.start()
        await stop_task

        # Should exit cleanly (no exception = pass)

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        scheduler = BackfillScheduler([], lambda j: MagicMock())
        await scheduler.stop()
        await scheduler.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_multiple_jobs_get_tasks(self) -> None:
        jobs = [_make_job(f"job_{i}") for i in range(3)]
        runner = _make_runner()
        scheduler = BackfillScheduler(jobs, lambda j: runner)

        stop_task = asyncio.create_task(_stop_after(scheduler, 0.05))
        await scheduler.start()
        await stop_task

        # All 3 tasks should have been created (and cancelled during drain)
        assert len(scheduler._tasks) == 3


async def _stop_after(scheduler: BackfillScheduler, delay: float) -> None:
    """Helper: stop the scheduler after a short delay."""
    await asyncio.sleep(delay)
    await scheduler.stop()
