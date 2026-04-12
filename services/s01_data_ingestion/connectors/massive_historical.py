"""Massive (ex-Polygon) historical data connector.

Downloads minute-agg bar data from Massive S3 flat files with automatic
fallback to the Polygon-compatible REST API.

References:
    Polygon.io flat files docs — https://polygon.io/flat-files
    Bouchaud et al. (2018) — "Trades, Quotes and Prices"
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import io
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog
from botocore.exceptions import ClientError

from core.config import Settings
from core.models.data import Asset, AssetClass, Bar, BarSize, DbTick
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class MassiveFetchError(Exception):
    """Raised when Massive download retries are exhausted."""


def _placeholder_asset(symbol: str) -> Asset:
    """Create a minimal placeholder Asset for normalizer use."""
    return Asset(
        asset_id=uuid.UUID(int=0),
        symbol=symbol.upper(),
        exchange="MASSIVE",
        asset_class=AssetClass.EQUITY,
        currency="USD",
    )


class MassiveHistoricalConnector(DataConnector):
    """Downloads historical equity bar data from Massive S3 flat files.

    Strategy:
    1. For each day in range: download ``us_stocks_sip/minute_aggs_v1/{Y}/{M}/{date}.csv.gz``
    2. On S3 NoSuchKey: fallback to Polygon REST ``/v2/aggs/ticker/...``
    3. Rate limiting: ``asyncio.Semaphore(5)``
    """

    def __init__(
        self,
        settings: Settings,
        bar_normalizer_factory: (
            Callable[[BarSize], NormalizerStrategy[list[str], Bar]] | None
        ) = None,
    ) -> None:
        import boto3

        self._s3_client: Any = boto3.client(
            "s3",
            endpoint_url=settings.massive_s3_endpoint,
            aws_access_key_id=settings.massive_s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.massive_s3_secret_key.get_secret_value(),
        )
        self._bucket = settings.massive_s3_bucket
        self._api_key = settings.massive_api_key.get_secret_value()
        self._semaphore = asyncio.Semaphore(5)
        self._bar_normalizer_factory = bar_normalizer_factory

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "massive_historical"

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Yield batches of bars from Massive S3 or REST fallback.

        Args:
            symbol: Equity ticker (e.g. ``AAPL``).
            bar_size: Bar time-frame resolution (only M1 from flat files).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`Bar` per batch.
        """
        if self._bar_normalizer_factory is None:
            msg = "MassiveHistoricalConnector requires a bar_normalizer_factory"
            raise RuntimeError(msg)
        normalizer = self._bar_normalizer_factory(bar_size)
        placeholder = _placeholder_asset(symbol)

        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            date_str = current.strftime("%Y-%m-%d")
            year = current.strftime("%Y")
            month = current.strftime("%m")
            s3_key = f"us_stocks_sip/minute_aggs_v1/{year}/{month}/{date_str}.csv.gz"

            async with self._semaphore:
                rows = await self._download_s3_csv_gz_filtered(s3_key, symbol)
                if rows is None:
                    rows = await self._fallback_rest(symbol, date_str)

            batch: list[Bar] = []
            for row in rows:
                bar = normalizer.normalize(row, placeholder)
                if bar.timestamp >= start and bar.timestamp < end:
                    batch.append(bar)
                    if len(batch) >= _BATCH_SIZE:
                        yield batch
                        batch = []

            if batch:
                yield batch

            current += timedelta(days=1)

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Not implemented — flat file trades exceed 1GB/day.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Phase 2.6 deferred — flat file trades > 1GB/day")
        yield  # pragma: no cover — makes this an async generator

    async def _download_s3_csv_gz_filtered(
        self, key: str, target_symbol: str
    ) -> list[list[str]] | None:
        """Stream S3 gzip CSV and return only rows matching target_symbol.

        Streams the gzipped file instead of buffering the entire contents,
        preventing OOM on multi-GB flat files that contain all US tickers.

        Returns None if the key does not exist (NoSuchKey).
        """
        try:
            response = await asyncio.to_thread(
                self._s3_client.get_object,
                Bucket=self._bucket,
                Key=key,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "NoSuchKey":
                logger.debug("s3_key_not_found", key=key)
                return None
            raise MassiveFetchError(f"S3 error {code} on {key}") from exc
        except Exception as exc:
            raise MassiveFetchError(f"unexpected S3 error on {key}") from exc

        target_upper = target_symbol.upper()

        def _stream_filter() -> list[list[str]]:
            body = response["Body"]
            with gzip.GzipFile(fileobj=body, mode="rb") as gz:
                text_stream = io.TextIOWrapper(gz, encoding="utf-8")
                reader = csv.reader(text_stream)
                header = next(reader, None)
                if header is None:
                    return []
                try:
                    ticker_idx = header.index("ticker")
                except ValueError:
                    ticker_idx = 0
                return [row for row in reader if row and row[ticker_idx].upper() == target_upper]

        return await asyncio.to_thread(_stream_filter)

    async def _fallback_rest(self, symbol: str, date_str: str) -> list[list[str]]:
        """Fetch minute aggs from the Polygon-compatible REST API.

        Returns rows in the same format as the CSV:
        [ticker, volume, open, close, high, low, window_start_ns, transactions]
        """
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}"
            f"/range/1/minute/{date_str}/{date_str}"
        )
        params: dict[str, str | int] = {
            "apiKey": self._api_key,
            "limit": 50000,
            "adjusted": "true",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        wait = _BACKOFF_BASE * (2**attempt)
                        logger.warning(
                            "massive_rest_retry",
                            status=resp.status_code,
                            wait=wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    results: list[dict[str, Any]] = data.get("results", [])
                    rows: list[list[str]] = []
                    for r in results:
                        # Convert REST response to CSV-like row format
                        # window_start (t) is in milliseconds, convert to ns
                        window_start_ns = int(r.get("t", 0)) * 1_000_000
                        rows.append(
                            [
                                symbol.upper(),
                                str(r.get("v", 0)),
                                str(r.get("o", 0)),
                                str(r.get("c", 0)),
                                str(r.get("h", 0)),
                                str(r.get("l", 0)),
                                str(window_start_ns),
                                str(r.get("n", 0)),
                            ]
                        )
                    return rows
                except httpx.HTTPError as exc:
                    logger.warning(
                        "massive_rest_error",
                        error=str(exc),
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))

        raise MassiveFetchError(f"Massive REST fallback exhausted for {symbol} on {date_str}")
