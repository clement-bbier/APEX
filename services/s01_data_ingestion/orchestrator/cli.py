"""CLI for the Backfill Orchestrator.

Provides sub-commands to inspect and control backfill jobs.
Uses the Command pattern: each sub-command is an isolated Command object.

Usage::

    python -m services.s01_data_ingestion.orchestrator.cli list
    python -m services.s01_data_ingestion.orchestrator.cli run --job binance_btcusdt_1m
    python -m services.s01_data_ingestion.orchestrator.cli status --job binance_btcusdt_1m
    python -m services.s01_data_ingestion.orchestrator.cli reset --job binance_btcusdt_1m
    python -m services.s01_data_ingestion.orchestrator.cli gaps
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import structlog
from redis.asyncio import from_url as redis_from_url

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository

from .config import JobConfig, OrchestratorConfig, load_config_from_yaml
from .connector_factory import ConnectorFactory
from .job_runner import JobRunner
from .state import JobStateManager

logger = structlog.get_logger(__name__)

_DEFAULT_CONFIG_PATH: Path = Path(__file__).parent / "jobs.yaml"


# ── Command ABC ──────────────────────────────────────────────────────────────


class Command(ABC):
    """Abstract command — each CLI sub-command implements this."""

    @abstractmethod
    async def execute(self) -> None:
        """Execute the command."""
        ...


# ── Concrete Commands ────────────────────────────────────────────────────────


class ListCommand(Command):
    """List all configured jobs and their enabled status."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    async def execute(self) -> None:
        config = load_config_from_yaml(self._config_path)
        print(f"{'Name':<30} {'Connector':<25} {'Schedule':<20} {'Enabled'}")
        print("-" * 85)
        for job in config.jobs:
            enabled_str = "yes" if job.enabled else "no"
            print(f"{job.name:<30} {job.connector:<25} {job.schedule:<20} {enabled_str}")
        print(f"\nTotal: {len(config.jobs)} jobs")


class RunCommand(Command):
    """Run a specific job immediately."""

    def __init__(self, job_name: str, config_path: Path) -> None:
        self._job_name = job_name
        self._config_path = config_path

    async def execute(self) -> None:
        config = load_config_from_yaml(self._config_path)
        job = self._find_job(config, self._job_name)

        settings = get_settings()
        redis = redis_from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        repo = TimescaleRepository(settings.timescale_dsn)
        await repo.connect()

        try:
            state = JobStateManager(redis)
            factory = ConnectorFactory()
            runner = JobRunner(job, factory, repo, state, settings)
            result = await runner.run()
            print(
                f"Job {self._job_name}: {result.status} "
                f"({result.rows_inserted} rows, "
                f"{(result.finished_at - result.started_at).total_seconds():.1f}s)"
            )
            if result.error_message:
                print(f"Error: {result.error_message}")
        finally:
            await repo.close()
            await redis.aclose()

    @staticmethod
    def _find_job(config: OrchestratorConfig, name: str) -> JobConfig:
        """Find a job by name in the configuration."""
        for job in config.jobs:
            if job.name == name:
                return job
        msg = f"Job {name!r} not found in configuration."
        raise ValueError(msg)


class StatusCommand(Command):
    """Show the status and recent history of a job."""

    def __init__(self, job_name: str) -> None:
        self._job_name = job_name

    async def execute(self) -> None:
        settings = get_settings()
        redis = redis_from_url(settings.redis_url)  # type: ignore[no-untyped-call]

        try:
            state = JobStateManager(redis)
            last_success = await state.get_last_success(self._job_name)
            history = await state.get_run_history(self._job_name, limit=5)

            print(f"Job: {self._job_name}")
            print(f"Last success: {last_success or 'never'}")
            print("\nRecent runs (last 5):")

            if not history:
                print("  (no history)")
            else:
                for run in history:
                    duration = (run.finished_at - run.started_at).total_seconds()
                    print(
                        f"  {run.started_at:%Y-%m-%d %H:%M:%S} "
                        f"| {run.status:<8} "
                        f"| {run.rows_inserted:>6} rows "
                        f"| {duration:.1f}s"
                    )
        finally:
            await redis.aclose()


class ResetCommand(Command):
    """Purge all Redis state for a job (lock, last_success, history)."""

    def __init__(self, job_name: str) -> None:
        self._job_name = job_name

    async def execute(self) -> None:
        settings = get_settings()
        redis = redis_from_url(settings.redis_url)  # type: ignore[no-untyped-call]

        try:
            state = JobStateManager(redis)
            await state.clear_state(self._job_name)
            print(f"State cleared for job {self._job_name!r}.")
        finally:
            await redis.aclose()


class GapsCommand(Command):
    """Detect and list data gaps for bar-type jobs."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    async def execute(self) -> None:
        print("Gap detection is implemented in gap_detector.py but not yet")
        print("wired into the scheduler.")
        print("Manual gap detection via CLI requires Phase 2.12 (Observability).")


# ── CLI wiring ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="APEX Backfill Orchestrator CLI",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG_PATH,
        help="Path to jobs.yaml configuration file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all configured jobs.")

    run_parser = subparsers.add_parser("run", help="Run a specific job immediately.")
    run_parser.add_argument("--job", required=True, help="Job name to run.")

    status_parser = subparsers.add_parser("status", help="Show job status.")
    status_parser.add_argument("--job", required=True, help="Job name to inspect.")

    reset_parser = subparsers.add_parser("reset", help="Purge Redis state for a job.")
    reset_parser.add_argument("--job", required=True, help="Job name to reset.")

    subparsers.add_parser("gaps", help="Detect data gaps.")

    return parser


def resolve_command(args: argparse.Namespace) -> Command:
    """Map parsed CLI args to a Command object."""
    config_path: Path = args.config

    if args.command == "list":
        return ListCommand(config_path)
    if args.command == "run":
        return RunCommand(args.job, config_path)
    if args.command == "status":
        return StatusCommand(args.job)
    if args.command == "reset":
        return ResetCommand(args.job)
    if args.command == "gaps":
        return GapsCommand(config_path)

    msg = f"Unknown command: {args.command!r}"
    raise ValueError(msg)


def cli_main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    command = resolve_command(args)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(command.execute())


if __name__ == "__main__":
    cli_main()
