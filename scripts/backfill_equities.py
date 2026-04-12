"""APEX US equities historical data backfill CLI.

Downloads bar data from Alpaca or Massive (ex-Polygon), validates through
the quality pipeline, and inserts into TimescaleDB.

Usage:
    python -m scripts.backfill_equities \\
        --symbol AAPL --provider alpaca --start 2024-01-02 --end 2024-01-03 --interval 1m

    python -m scripts.backfill_equities \\
        --symbol AAPL --provider massive --start 2024-01-02 --end 2024-01-03 --interval 1m --dry-run
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
from services.s01_data_ingestion.connectors.alpaca_historical import (
    AlpacaHistoricalConnector,
)
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.connectors.massive_historical import (
    MassiveHistoricalConnector,
)
from services.s01_data_ingestion.normalizers.alpaca_bar import AlpacaBarNormalizer
from services.s01_data_ingestion.normalizers.alpaca_trade import AlpacaTradeNormalizer
from services.s01_data_ingestion.normalizers.asset_resolver import AssetResolver
from services.s01_data_ingestion.normalizers.massive_bar import MassiveBarNormalizer
from services.s01_data_ingestion.quality.checker import DataQualityChecker
from services.s01_data_ingestion.quality.db_logger import QualityDbLogger

logger = structlog.get_logger(__name__)


def _create_connector(provider: str) -> DataConnector:
    """Instantiate the appropriate connector based on provider name.

    Args:
        provider: One of ``alpaca`` or ``massive``.

    Returns:
        A :class:`DataConnector` instance.

    Raises:
        ValueError: If provider is not recognized.
    """
    settings = get_settings()
    if provider == "alpaca":
        return AlpacaHistoricalConnector(
            settings,
            bar_normalizer_factory=AlpacaBarNormalizer,
            trade_normalizer=AlpacaTradeNormalizer(),
        )
    if provider == "massive":
        return MassiveHistoricalConnector(settings, bar_normalizer_factory=MassiveBarNormalizer)
    msg = f"Unknown provider: {provider!r}. Use 'alpaca' or 'massive'."
    raise ValueError(msg)


async def run_backfill(
    symbol: str,
    provider: str,
    start: datetime,
    end: datetime,
    interval: str,
    dry_run: bool,
) -> None:
    """Execute the backfill pipeline for a single equity symbol.

    Args:
        symbol: Equity ticker (e.g. ``AAPL``).
        provider: Data provider name (``alpaca`` or ``massive``).
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
        exchange = "ALPACA" if provider == "alpaca" else "MASSIVE"
        asset = await resolver.resolve_or_create(
            symbol,
            exchange,
            {"asset_class": AssetClass.EQUITY, "currency": "USD"},
        )

        connector = _create_connector(provider)
        connector_name = connector.connector_name
        run_id = await repo.start_ingestion_run(connector_name, asset.asset_id)

        checker = DataQualityChecker()
        quality_logger = QualityDbLogger(repo)

        total_inserted = 0
        try:
            with tqdm(unit="bars", desc=f"{symbol} {interval} ({provider})") as pbar:
                async for batch in connector.fetch_bars(symbol, BarSize(interval), start, end):
                    batch = [b.model_copy(update={"asset_id": asset.asset_id}) for b in batch]
                    report = checker.validate_bars(batch, asset)
                    await quality_logger.log_report(report, connector_name)
                    if not dry_run and report.clean_bars:
                        n = await repo.insert_bars(report.clean_bars)
                        total_inserted += n
                        pbar.update(n)
            await repo.finish_ingestion_run(run_id, IngestionStatus.SUCCESS, total_inserted)
            logger.info(
                "backfill_complete",
                symbol=symbol,
                provider=provider,
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
    """CLI entry point for the equities backfill script."""
    parser = argparse.ArgumentParser(description="APEX equities backfill")
    parser.add_argument("--symbol", required=True, help="Equity ticker, e.g. AAPL")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["alpaca", "massive"],
        help="Data provider",
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
    parser.add_argument("--interval", default="1m", help="Bar interval (default: 1m)")
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
            args.provider,
            args.start,
            args.end,
            args.interval,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
