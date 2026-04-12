"""APEX Yahoo Finance historical data backfill CLI.

Downloads bar data from Yahoo Finance via yfinance, validates through
the quality pipeline, and inserts into TimescaleDB. Supports global
indices, FX majors, international ETFs, and commodities.

Usage:
    python -m scripts.backfill_yahoo \\
        --symbol ^GSPC --start 2024-01-01 --end 2024-04-01 --interval 1d

    python -m scripts.backfill_yahoo \\
        --symbol EURUSD=X --start 2024-01-01 --end 2024-04-01 \\
        --interval 1d --asset-class forex --dry-run
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
from scripts._backfill_common import _parse_utc_datetime
from services.s01_data_ingestion.connectors.yahoo_historical import (
    YahooHistoricalConnector,
)
from services.s01_data_ingestion.normalizers.asset_resolver import AssetResolver
from services.s01_data_ingestion.normalizers.yahoo_bar import YahooBarNormalizer
from services.s01_data_ingestion.quality.checker import DataQualityChecker
from services.s01_data_ingestion.quality.db_logger import QualityDbLogger

logger = structlog.get_logger(__name__)

_INTERVAL_MAP: dict[str, BarSize] = {
    "1m": BarSize.M1,
    "5m": BarSize.M5,
    "15m": BarSize.M15,
    "1h": BarSize.H1,
    "1d": BarSize.D1,
    "1wk": BarSize.W1,
    "1mo": BarSize.MO1,
}

_ASSET_CLASS_MAP: dict[str, AssetClass] = {
    "equity": AssetClass.EQUITY,
    "index": AssetClass.INDEX,
    "forex": AssetClass.FOREX,
    "commodity": AssetClass.COMMODITY,
    "bond": AssetClass.BOND,
    "crypto": AssetClass.CRYPTO,
}


async def run_backfill(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str,
    asset_class_str: str,
    currency: str,
    dry_run: bool,
) -> None:
    """Execute the backfill pipeline for a single Yahoo Finance symbol.

    Args:
        symbol: Yahoo Finance ticker (e.g. ``^GSPC``, ``EURUSD=X``).
        start: Start of the date range (UTC).
        end: End of the date range (UTC).
        interval: Bar interval string (e.g. ``1d``, ``1h``).
        asset_class_str: Asset class name (e.g. ``equity``, ``index``).
        currency: Quote currency (e.g. ``USD``).
        dry_run: If True, validate but do not insert into the database.
    """
    asset_class = _ASSET_CLASS_MAP[asset_class_str]
    settings = get_settings()
    repo = TimescaleRepository(settings.timescale_dsn)
    await repo.connect()
    try:
        resolver = AssetResolver(repo)
        asset = await resolver.resolve_or_create(
            symbol,
            "YAHOO",
            {"asset_class": asset_class, "currency": currency},
        )

        connector = YahooHistoricalConnector(
            bar_normalizer_factory=YahooBarNormalizer,  # type: ignore[arg-type]
        )
        run_id = await repo.start_ingestion_run(connector.connector_name, asset.asset_id)

        checker = DataQualityChecker()
        quality_logger = QualityDbLogger(repo)

        total_inserted = 0
        try:
            with tqdm(unit="bars", desc=f"{symbol} {interval}") as pbar:
                async for batch in connector.fetch_bars(
                    symbol, _INTERVAL_MAP[interval], start, end
                ):
                    # Re-assign real asset_id
                    batch = [b.model_copy(update={"asset_id": asset.asset_id}) for b in batch]
                    report = checker.validate_bars(batch, asset)
                    await quality_logger.log_report(report, connector.connector_name)
                    if not dry_run and report.clean_bars:
                        n = await repo.insert_bars(report.clean_bars)
                        total_inserted += n
                        pbar.update(n)
            await repo.finish_ingestion_run(run_id, IngestionStatus.SUCCESS, total_inserted)
            logger.info(
                "backfill_complete",
                symbol=symbol,
                asset_class=asset_class_str,
                total=total_inserted,
            )
        except Exception as exc:
            await repo.finish_ingestion_run(
                run_id, IngestionStatus.FAILED, total_inserted, str(exc)
            )
            raise
    finally:
        await repo.close()


def main() -> None:
    """CLI entry point for the Yahoo Finance backfill script."""
    parser = argparse.ArgumentParser(description="APEX Yahoo Finance backfill")
    parser.add_argument(
        "--symbol",
        required=True,
        help="Yahoo Finance symbol, e.g. ^GSPC, EURUSD=X, SPY, GC=F",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=_parse_utc_datetime,
        help="Start date (ISO format)",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=_parse_utc_datetime,
        help="End date (ISO format)",
    )
    parser.add_argument(
        "--interval",
        default="1d",
        choices=list(_INTERVAL_MAP.keys()),
        help="Yahoo interval (default: 1d)",
    )
    parser.add_argument(
        "--asset-class",
        default="equity",
        choices=list(_ASSET_CLASS_MAP.keys()),
        help="Asset class (default: equity)",
    )
    parser.add_argument(
        "--currency",
        default="USD",
        help="Quote currency (default: USD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only, do not insert",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(
        run_backfill(
            args.symbol,
            args.start,
            args.end,
            args.interval,
            args.asset_class,
            args.currency,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
