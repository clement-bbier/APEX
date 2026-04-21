"""APEX Fundamentals backfill CLI.

Downloads fundamentals (10-K/10-Q/8-K filings, financial ratios) from
SEC EDGAR and/or SimFin and inserts into TimescaleDB ``fundamentals``.

Usage:
    python -m scripts.backfill_fundamentals \\
        --provider edgar --tickers AAPL,MSFT --filings 10-K,10-Q \\
        --start 2020-01-01 --end 2025-01-01

    python -m scripts.backfill_fundamentals \\
        --provider simfin --tickers AAPL --start 2020-01-01 --dry-run

    python -m scripts.backfill_fundamentals \\
        --provider all --tickers-file tickers.txt --filings 10-K

References:
    Fama & French (1993) JFE — "Common risk factors in the returns
        on stocks and bonds"
    Novy-Marx (2013) JFE — "The other side of value: The gross
        profitability premium"
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
from services.data_ingestion.connectors.fundamentals_base import (
    FundamentalsConnector,
)

logger = structlog.get_logger(__name__)

_ALL_PROVIDERS = ("edgar", "simfin")


def _build_connector(provider: str) -> FundamentalsConnector:
    """Instantiate the correct FundamentalsConnector for a provider name.

    Args:
        provider: One of ``edgar``, ``simfin``.

    Returns:
        A concrete :class:`FundamentalsConnector` instance.
    """
    if provider == "edgar":
        from services.data_ingestion.connectors.edgar_connector import (
            EDGARConnector,
        )

        return EDGARConnector()
    if provider == "simfin":
        from services.data_ingestion.connectors.simfin_connector import (
            SimFinConnector,
        )

        return SimFinConnector()
    msg = f"Unknown provider: {provider}"
    raise ValueError(msg)


def _load_tickers(
    tickers_csv: str | None,
    tickers_file: str | None,
) -> list[str]:
    """Build the list of ticker symbols from CLI arguments.

    Args:
        tickers_csv: Comma-separated tickers from ``--tickers``.
        tickers_file: Path to a file with one ticker per line.

    Returns:
        Deduplicated list of uppercase ticker symbols.
    """
    tickers: list[str] = []
    if tickers_csv:
        tickers.extend(t.strip().upper() for t in tickers_csv.split(",") if t.strip())
    if tickers_file:
        path = Path(tickers_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                tickers.append(stripped.upper())
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


async def run_backfill(
    providers: list[str],
    tickers: list[str],
    filing_types: list[str],
    start: datetime,
    end: datetime,
    dry_run: bool,
) -> None:
    """Execute the fundamentals backfill pipeline.

    Args:
        providers: List of provider names.
        tickers: List of ticker symbols.
        filing_types: Filing types to fetch (e.g. ``["10-K", "10-Q"]``).
        start: Start of the date range (UTC).
        end: End of the date range (UTC).
        dry_run: If True, fetch and log but do not insert.
    """
    for provider in providers:
        logger.info("fundamentals_backfill_start", provider=provider)
        connector = _build_connector(provider)

        if dry_run:
            logger.info("dry_run_mode_enabled", provider=provider)
            for ticker in tickers:
                try:
                    point_count = 0
                    async for batch in connector.fetch_fundamentals(
                        ticker, filing_types, start, end
                    ):
                        point_count += len(batch)
                        for pt in batch[:3]:
                            logger.info(
                                "dry_run_fundamental",
                                ticker=ticker,
                                metric=pt.metric_name,
                                date=str(pt.report_date),
                                value=pt.value,
                            )
                    logger.info(
                        "dry_run_ticker_done",
                        provider=provider,
                        ticker=ticker,
                        point_count=point_count,
                    )
                except Exception as exc:
                    logger.error(
                        "dry_run_ticker_failed",
                        provider=provider,
                        ticker=ticker,
                        error=str(exc),
                    )
            continue

        # Normal mode with DB
        settings = get_settings()
        repo = TimescaleRepository(settings.timescale_dsn)
        await repo.connect()

        try:
            for ticker in tickers:
                run_id = await repo.start_ingestion_run(
                    connector.connector_name,
                    asset_id=None,
                )
                total_inserted = 0

                try:
                    with tqdm(unit="pts", desc=f"{provider}:{ticker}") as pbar:
                        async for batch in connector.fetch_fundamentals(
                            ticker, filing_types, start, end
                        ):
                            if batch:
                                n = await repo.insert_fundamentals(batch)
                                total_inserted += n
                                pbar.update(n)

                    await repo.finish_ingestion_run(
                        run_id,
                        IngestionStatus.SUCCESS,
                        total_inserted,
                    )
                    logger.info(
                        "fundamentals_ticker_done",
                        provider=provider,
                        ticker=ticker,
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
                        "fundamentals_ticker_failed",
                        provider=provider,
                        ticker=ticker,
                        error=str(exc),
                    )
                    raise
        finally:
            await repo.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the fundamentals backfill CLI."""
    parser = argparse.ArgumentParser(
        description="APEX Fundamentals backfill (SEC EDGAR / SimFin)",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=["edgar", "simfin", "all"],
        help="Fundamentals provider or 'all' for both",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated ticker symbols (e.g. AAPL,MSFT,NVDA)",
    )
    parser.add_argument(
        "--tickers-file",
        default=None,
        help="Path to file with one ticker per line",
    )
    parser.add_argument(
        "--filings",
        default="10-K,10-Q",
        help="Comma-separated filing types (default: 10-K,10-Q)",
    )
    parser.add_argument(
        "--start",
        type=_parse_utc_datetime,
        default=_parse_utc_datetime("2015-01-01"),
        help="Start date (ISO format, default: 2015-01-01)",
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
    return parser


def main() -> None:
    """CLI entry point for the fundamentals backfill script."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.provider == "all":
        providers = list(_ALL_PROVIDERS)
    else:
        providers = [args.provider]

    tickers = _load_tickers(args.tickers, args.tickers_file)
    if not tickers:
        parser.error("provide at least one ticker via --tickers or --tickers-file")

    filing_types = [f.strip().upper() for f in args.filings.split(",") if f.strip()]

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(
        run_backfill(
            providers,
            tickers,
            filing_types,
            args.start,
            args.end,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
