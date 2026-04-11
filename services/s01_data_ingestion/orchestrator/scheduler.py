"""BackfillScheduler — cron-based scheduling for backfill jobs.

Uses croniter to compute next trigger times and runs each enabled job
in its own asyncio task. Supports graceful shutdown via signal handlers.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from croniter import croniter

from .config import JobConfig
from .job_runner import JobRunner

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_SHUTDOWN_DRAIN_TIMEOUT_SECONDS: float = 30.0


class BackfillScheduler:
    """Cron-based scheduler that runs backfill jobs as asyncio tasks.

    Each enabled job gets its own infinite loop that sleeps until the next
    cron trigger, then delegates to a JobRunner.

    Args:
        jobs: List of job configurations from YAML.
        runner_factory: Callable that creates a JobRunner for a given JobConfig.
    """

    def __init__(
        self,
        jobs: list[JobConfig],
        runner_factory: Callable[[JobConfig], JobRunner],
    ) -> None:
        self._jobs = jobs
        self._runner_factory = runner_factory
        self._tasks: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Launch a task for each enabled job and wait until shutdown."""
        self._install_signal_handlers()
        enabled_jobs = [j for j in self._jobs if j.enabled]

        logger.info(
            "scheduler.starting",
            total_jobs=len(self._jobs),
            enabled_jobs=len(enabled_jobs),
        )

        for job in enabled_jobs:
            task = asyncio.create_task(self._job_loop(job), name=f"backfill:{job.name}")
            self._tasks.append(task)

        await self._shutdown_event.wait()
        await self._drain_tasks()

    async def stop(self) -> None:
        """Signal the scheduler to shut down gracefully."""
        logger.info("scheduler.stop_requested")
        self._shutdown_event.set()

    async def _drain_tasks(self) -> None:
        """Cancel all running tasks and wait for them to finish."""
        logger.info("scheduler.draining", task_count=len(self._tasks))
        for task in self._tasks:
            task.cancel()

        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors = sum(
            1
            for r in results
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)
        )
        logger.info(
            "scheduler.drained",
            cancelled=cancelled,
            errors=errors,
        )

    async def _job_loop(self, job: JobConfig) -> None:
        """Infinite loop: sleep until next cron trigger, then run the job."""
        runner = self._runner_factory(job)

        while not self._shutdown_event.is_set():
            delay = _seconds_until_next(job.schedule)
            logger.info(
                "scheduler.waiting",
                job=job.name,
                next_in_seconds=round(delay, 1),
            )

            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
                break  # shutdown was signaled during sleep
            except TimeoutError:
                pass  # timeout means the cron delay elapsed — time to run

            result = await runner.run()
            logger.info(
                "scheduler.job_completed",
                job=job.name,
                status=result.status,
                rows=result.rows_inserted,
            )

    def _install_signal_handlers(self) -> None:
        """Register OS signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        if sys.platform == "win32":
            # Windows: use signal.signal for SIGINT/SIGBREAK
            signal.signal(
                signal.SIGINT, lambda *_: loop.call_soon_threadsafe(self._shutdown_event.set)
            )
            if hasattr(signal, "SIGBREAK"):
                signal.signal(
                    signal.SIGBREAK, lambda *_: loop.call_soon_threadsafe(self._shutdown_event.set)
                )
        else:
            # Unix: use loop.add_signal_handler
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._shutdown_event.set)


def _seconds_until_next(cron_expr: str) -> float:
    """Compute seconds from now until the next cron trigger.

    Args:
        cron_expr: 5-field cron expression.

    Returns:
        Seconds to sleep (always > 0).
    """
    now = datetime.now(UTC)
    cron = croniter(cron_expr, now)
    next_dt: datetime = cron.get_next(datetime)
    # croniter may return naive datetime — ensure UTC
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=UTC)
    delta = (next_dt - now).total_seconds()
    return max(delta, 0.1)
