"""APEX Binance historical data backfill CLI.

Downloads kline data from Binance public archives, validates through
the quality pipeline, and inserts into TimescaleDB.

Usage:
    python -m scripts.backfill_binance \\
        --symbol BTCUSDT --start 2024-01-01 --end 2024-01-02 --interval 1m

    python -m scripts.backfill_binance \\
        --symbol BTCUSDT --start 2024-01-01 --end 2024-01-02 --interval 1m --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

import structlog
from tqdm import tqdm

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository
from core.models.data import AssetClass, BarSize, IngestionStatus
from services.s01_data_ingestion.connectors.binance_historical import (
    BinanceHistoricalConnector,
)
from services.s01_data_ingestion.normalizers.asset_resolver import AssetResolver
from services.s01_data_ingestion.quality.checker import DataQualityChecker
from services.s01_data_ingestion.quality.db_logger import QualityDbLogger

logger = structlog.get_logger(__name__)


async def run_backfill(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str,
    dry_run: bool,
) -> None:
    """Execute the backfill pipeline for a single symbol.

    Args:
        symbol: Binance trading pair (e.g. ``BTCUSDT``).
        start: Start of the date range (UTC).
        end: End of the date range (UTC).
        interval: Bar interval string (e.g. ``1m``, ``1h``).
        dry_run: If True, validate but do not insert into the database.
    """
    settings = get_settings()
    repo = TimescaleRepository(settings.timescale_dsn)
    await repo.connect()
    try:
        resolver = AssetResolver(repo)
        asset = await resolver.resolve_or_create(
            symbol,
            "BINANCE",
            {"asset_class": AssetClass.CRYPTO, "currency": "USDT"},
        )
        run_id = await repo.start_ingestion_run("binance_historical", asset.asset_id)

        connector = BinanceHistoricalConnector()
        checker = DataQualityChecker()
        quality_logger = QualityDbLogger(repo)

        total_inserted = 0
        try:
            with tqdm(unit="bars", desc=f"{symbol} {interval}") as pbar:
                async for batch in connector.fetch_bars(symbol, BarSize(interval), start, end):
                    # Re-assign real asset_id
                    batch = [b.model_copy(update={"asset_id": asset.asset_id}) for b in batch]
                    report = checker.validate_bars(batch, asset)
                    await quality_logger.log_report(report, "binance_historical")
                    if not dry_run and report.clean_bars:
                        n = await repo.insert_bars(report.clean_bars)
                        total_inserted += n
                        pbar.update(n)
            await repo.finish_ingestion_run(run_id, IngestionStatus.SUCCESS, total_inserted)
            logger.info("backfill_complete", symbol=symbol, total=total_inserted)
        except Exception as exc:
            await repo.finish_ingestion_run(
                run_id, IngestionStatus.FAILED, total_inserted, str(exc)
            )
            raise
    finally:
        await repo.close()


def main() -> None:
    """CLI entry point for the Binance backfill script."""
    parser = argparse.ArgumentParser(description="APEX Binance backfill")
    parser.add_argument("--symbol", required=True, help="Binance symbol, e.g. BTCUSDT")
    parser.add_argument(
        "--start",
        required=True,
        type=lambda s: datetime.fromisoformat(s),
        help="Start date (ISO format)",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=lambda s: datetime.fromisoformat(s),
        help="End date (ISO format)",
    )
    parser.add_argument("--interval", default="1m", help="Bar interval (default: 1m)")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not insert")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_backfill(args.symbol, args.start, args.end, args.interval, args.dry_run))


if __name__ == "__main__":
    main()
