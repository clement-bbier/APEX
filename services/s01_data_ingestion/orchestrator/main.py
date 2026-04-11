"""Daemon entrypoint for the Backfill Orchestrator.

Loads configuration, initializes dependencies, and starts the scheduler.
Handles graceful shutdown via OS signals.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import structlog
from redis.asyncio import from_url as redis_from_url

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository

from .config import JobConfig, load_config_from_yaml
from .connector_factory import ConnectorFactory
from .job_runner import JobRunner
from .scheduler import BackfillScheduler
from .state import JobStateManager

logger = structlog.get_logger(__name__)

_DEFAULT_CONFIG_PATH: Path = Path(__file__).parent / "jobs.yaml"


async def main() -> None:
    """Initialize all dependencies and start the backfill scheduler."""
    settings = get_settings()
    config = load_config_from_yaml(_DEFAULT_CONFIG_PATH)

    redis = redis_from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    repo = TimescaleRepository(settings.timescale_dsn)
    await repo.connect()

    state = JobStateManager(redis)
    factory = ConnectorFactory()

    def runner_factory(job: JobConfig) -> JobRunner:
        return JobRunner(job, factory, repo, state, settings)

    scheduler = BackfillScheduler(config.jobs, runner_factory)

    logger.info(
        "orchestrator.starting",
        jobs=len(config.jobs),
        config_path=str(_DEFAULT_CONFIG_PATH),
    )

    try:
        await scheduler.start()
    finally:
        await repo.close()
        await redis.aclose()
        logger.info("orchestrator.stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
