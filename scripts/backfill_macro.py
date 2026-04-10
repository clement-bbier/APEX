"""APEX Macro-economic data backfill CLI.

Downloads macro time series from FRED, ECB, or BoJ and inserts into
TimescaleDB. Supports multiple series per run via ``--series`` or
``--series-file``.

Usage:
    python -m scripts.backfill_macro \\
        --provider fred --series FEDFUNDS,DFF,T10Y2Y \\
        --start 2010-01-01 --end 2024-12-31

    python -m scripts.backfill_macro \\
        --provider ecb --series "EXR/D.USD.EUR.SP00.A" \\
        --start 2024-01-01 --end 2024-12-31

    python -m scripts.backfill_macro \\
        --provider boj --series boj_policy_rate,boj_cpi \\
        --start 2020-01-01 --end 2024-12-31 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog
from tqdm import tqdm

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository
from core.models.data import IngestionStatus
from scripts._backfill_common import _parse_utc_datetime
from services.s01_data_ingestion.connectors.boj_connector import BoJConnector
from services.s01_data_ingestion.connectors.ecb_connector import ECBConnector
from services.s01_data_ingestion.connectors.fred_connector import FREDConnector
from services.s01_data_ingestion.connectors.macro_base import MacroConnector

logger = structlog.get_logger(__name__)


def _build_connector(provider: str) -> MacroConnector:
    """Instantiate the correct MacroConnector for a provider name.

    Args:
        provider: One of ``fred``, ``ecb``, ``boj``.

    Returns:
        A concrete :class:`MacroConnector` instance.
    """
    if provider == "fred":
        return FREDConnector()
    if provider == "ecb":
        return ECBConnector()
    if provider == "boj":
        return BoJConnector()
    msg = f"Unknown provider: {provider}"
    raise ValueError(msg)


def _load_series_list(series_csv: str | None, series_file: str | None) -> list[str]:
    """Build the list of series IDs from CLI arguments.

    Args:
        series_csv: Comma-separated series IDs from ``--series``.
        series_file: Path to a file with one series ID per line.

    Returns:
        Deduplicated list of series IDs.
    """
    ids: list[str] = []
    if series_csv:
        ids.extend(s.strip() for s in series_csv.split(",") if s.strip())
    if series_file:
        path = Path(series_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                ids.append(stripped)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            unique.append(sid)
    return unique


async def run_backfill(
    provider: str,
    series_ids: list[str],
    start: datetime,
    end: datetime,
    dry_run: bool,
) -> None:
    """Execute the macro backfill pipeline.

    Args:
        provider: Provider name (``fred``, ``ecb``, ``boj``).
        series_ids: List of series identifiers.
        start: Start of the date range (UTC).
        end: End of the date range (UTC).
        dry_run: If True, fetch and log but do not insert.
    """
    connector = _build_connector(provider)

    if dry_run:
        # Pure validation mode — no DB connection at all
        logger.info("dry_run_mode_enabled", provider=provider)
        for series_id in series_ids:
            try:
                meta = await connector.fetch_metadata(series_id)
                point_count = 0
                last_value: float | None = None
                async for batch in connector.fetch_series(series_id, start, end):
                    point_count += len(batch)
                    if batch:
                        last_value = batch[-1].value
                logger.info(
                    "dry_run_series_validated",
                    series_id=series_id,
                    title=meta.name,
                    point_count=point_count,
                    last_value=str(last_value) if last_value is not None else None,
                )
            except Exception as exc:
                logger.error("dry_run_series_failed", series_id=series_id, error=str(exc))
        return

    # Normal mode with DB
    settings = get_settings()
    repo = TimescaleRepository(settings.timescale_dsn)
    await repo.connect()

    try:
        for series_id in series_ids:
            run_id = await repo.start_ingestion_run(connector.connector_name, asset_id=None)
            total_inserted = 0

            try:
                # Fetch and upsert metadata
                meta = await connector.fetch_metadata(series_id)
                await repo.upsert_macro_metadata(meta)
                logger.info(
                    "macro_metadata_fetched",
                    provider=provider,
                    series_id=series_id,
                    name=meta.name,
                    frequency=meta.frequency,
                )

                # Stream data points — track last_value during streaming
                last_value_normal: float | None = None
                with tqdm(
                    unit="pts",
                    desc=f"{provider}:{series_id}",
                ) as pbar:
                    async for batch in connector.fetch_series(series_id, start, end):
                        if batch:
                            last_value_normal = batch[-1].value
                            n = await repo.insert_macro_points(batch)
                            total_inserted += n
                            pbar.update(n)

                await repo.finish_ingestion_run(run_id, IngestionStatus.SUCCESS, total_inserted)
                logger.info(
                    "macro_series_inserted",
                    provider=provider,
                    series_id=series_id,
                    count=total_inserted,
                    range_start=start.isoformat(),
                    range_end=end.isoformat(),
                    last_value=last_value_normal,
                )

            except Exception as exc:
                await repo.finish_ingestion_run(
                    run_id, IngestionStatus.FAILED, total_inserted, str(exc)
                )
                logger.error(
                    "macro_series_failed",
                    provider=provider,
                    series_id=series_id,
                    error=str(exc),
                )
                raise
    finally:
        await repo.close()


def main() -> None:
    """CLI entry point for the macro backfill script."""
    parser = argparse.ArgumentParser(description="APEX Macro-economic data backfill")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["fred", "ecb", "boj"],
        help="Data provider: fred, ecb, or boj",
    )
    parser.add_argument(
        "--series",
        default=None,
        help="Comma-separated series IDs (e.g. FEDFUNDS,DFF)",
    )
    parser.add_argument(
        "--series-file",
        default=None,
        help="Path to file with one series ID per line",
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
        default=datetime.now(UTC),
        help="End date (ISO format, default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and log only, do not insert into database",
    )
    args = parser.parse_args()

    series_ids = _load_series_list(args.series, args.series_file)
    if not series_ids:
        parser.error("provide at least one series via --series or --series-file")

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(
        run_backfill(
            args.provider,
            series_ids,
            args.start,
            args.end,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
