"""APEX Calendar events backfill CLI.

Downloads calendar events (FOMC meetings, ECB Governing Council, BoJ MPM,
US economic data releases) and inserts into TimescaleDB ``economic_events``.

Usage:
    python -m scripts.backfill_calendar \\
        --provider fomc --start 2010-01-01 --end 2026-12-31

    python -m scripts.backfill_calendar \\
        --provider all --start 2010-01-01 --end 2028-12-31

    python -m scripts.backfill_calendar \\
        --provider fred_releases --dry-run

References:
    Lucca & Moench (2015) JF — "The Pre-FOMC Announcement Drift"
    Bernanke & Kuttner (2005) JF — "What Explains the Stock Market's
        Reaction to Federal Reserve Policy?"
    Savor & Wilson (2013) RFS — "How Much Do Investors Care About
        Macroeconomic Risk?"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import structlog
from tqdm import tqdm

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository
from core.models.data import IngestionStatus
from scripts._backfill_common import _parse_utc_datetime
from services.data_ingestion.connectors.boj_calendar_scraper import BoJCalendarScraper
from services.data_ingestion.connectors.calendar_base import CalendarConnector
from services.data_ingestion.connectors.ecb_scraper import ECBScraper
from services.data_ingestion.connectors.fomc_scraper import FOMCScraper
from services.data_ingestion.connectors.fred_releases import FREDReleasesConnector

logger = structlog.get_logger(__name__)

_ALL_PROVIDERS = ("fomc", "ecb", "boj", "fred_releases")


def _build_connector(provider: str) -> CalendarConnector:
    """Instantiate the correct CalendarConnector for a provider name.

    Args:
        provider: One of ``fomc``, ``ecb``, ``boj``, ``fred_releases``.

    Returns:
        A concrete :class:`CalendarConnector` instance.
    """
    if provider == "fomc":
        return FOMCScraper()
    if provider == "ecb":
        return ECBScraper()
    if provider == "boj":
        return BoJCalendarScraper()
    if provider == "fred_releases":
        return FREDReleasesConnector()
    msg = f"Unknown provider: {provider}"
    raise ValueError(msg)


async def run_backfill(
    providers: list[str],
    start: datetime,
    end: datetime,
    dry_run: bool,
) -> None:
    """Execute the calendar events backfill pipeline.

    Args:
        providers: List of provider names.
        start: Start of the date range (UTC).
        end: End of the date range (UTC).
        dry_run: If True, fetch and log but do not insert.
    """
    for provider in providers:
        logger.info("calendar_backfill_start", provider=provider)
        connector = _build_connector(provider)

        if dry_run:
            logger.info("dry_run_mode_enabled", provider=provider)
            event_count = 0
            try:
                async for batch in connector.fetch_events(start, end):
                    event_count += len(batch)
                    for event in batch[:5]:
                        logger.info(
                            "dry_run_event",
                            event_type=event.event_type,
                            scheduled_time=event.scheduled_time.isoformat(),
                            impact_score=event.impact_score,
                        )
                logger.info(
                    "dry_run_provider_done",
                    provider=provider,
                    event_count=event_count,
                )
            except Exception as exc:
                logger.error(
                    "dry_run_provider_failed",
                    provider=provider,
                    error=str(exc),
                )
            continue

        # Normal mode with DB
        settings = get_settings()
        repo = TimescaleRepository(settings.timescale_dsn)
        await repo.connect()

        try:
            run_id = await repo.start_ingestion_run(
                connector.connector_name,
                asset_id=None,
            )
            total_inserted = 0

            try:
                with tqdm(unit="events", desc=provider) as pbar:
                    async for batch in connector.fetch_events(start, end):
                        if batch:
                            n = await repo.insert_economic_events(batch)
                            total_inserted += n
                            pbar.update(n)

                await repo.finish_ingestion_run(
                    run_id,
                    IngestionStatus.SUCCESS,
                    total_inserted,
                )
                logger.info(
                    "calendar_provider_done",
                    provider=provider,
                    count=total_inserted,
                )

            except Exception as exc:
                await repo.finish_ingestion_run(
                    run_id,
                    IngestionStatus.FAILED,
                    total_inserted,
                    str(exc),
                )
                logger.error(
                    "calendar_provider_failed",
                    provider=provider,
                    error=str(exc),
                )
                raise
        finally:
            await repo.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the calendar backfill CLI."""
    parser = argparse.ArgumentParser(
        description="APEX Calendar events backfill (FOMC/ECB/BoJ/US releases)",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=["fomc", "ecb", "boj", "fred_releases", "all"],
        help="Calendar provider or 'all' for all providers",
    )
    parser.add_argument(
        "--start",
        type=_parse_utc_datetime,
        default=_parse_utc_datetime("2010-01-01"),
        help="Start date (ISO format, default: 2010-01-01)",
    )
    parser.add_argument(
        "--end",
        type=_parse_utc_datetime,
        default=datetime.now(UTC) + timedelta(days=730),
        help="End date (ISO format, default: today + 2 years)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and log only, do not insert into database",
    )
    return parser


def main() -> None:
    """CLI entry point for the calendar events backfill script."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.provider == "all":
        providers = list(_ALL_PROVIDERS)
    else:
        providers = [args.provider]

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(
        run_backfill(
            providers,
            args.start,
            args.end,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
