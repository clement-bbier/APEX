"""Binance historical data connector.

Downloads kline (candlestick) and aggTrades data from Binance's public
data archive (data.binance.vision) with automatic fallback to the REST API.

References:
    Binance API docs — https://github.com/binance/binance-public-data/
    Makarov & Schoar (2020) — "Trading and arbitrage in cryptocurrency markets"
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog

from core.models.data import Asset, AssetClass, Bar, BarSize, DbTick
from services.data_ingestion.connectors.base import DataConnector
from services.data_ingestion.normalizers.base import NormalizerStrategy

logger = structlog.get_logger(__name__)


class BinanceFetchError(Exception):
    """Raised when Binance download retries are exhausted."""


_VISION_BASE = "https://data.binance.vision/data/spot"
_REST_BASE = "https://api.binance.com/api/v3"
_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


def _bar_size_to_binance_interval(bar_size: BarSize) -> str:
    """Map a BarSize enum to the Binance interval string."""
    mapping: dict[BarSize, str] = {
        BarSize.M1: "1m",
        BarSize.M5: "5m",
        BarSize.M15: "15m",
        BarSize.H1: "1h",
        BarSize.H4: "4h",
        BarSize.D1: "1d",
        BarSize.W1: "1w",
        BarSize.MO1: "1M",
    }
    return mapping[bar_size]


def _placeholder_asset(symbol: str) -> Asset:
    """Create a minimal placeholder Asset for normalizer use.

    The real asset_id is assigned later by the backfill script.
    """
    return Asset(
        asset_id=uuid.UUID(int=0),
        symbol=symbol.upper(),
        exchange="BINANCE",
        asset_class=AssetClass.CRYPTO,
        currency="USDT",
    )


class BinanceHistoricalConnector(DataConnector):
    """Downloads historical data from Binance public archives.

    Strategy:
    1. For date ranges > 30 days: download monthly ZIP archives
    2. For date ranges <= 30 days: download daily ZIP archives
    3. On 404: fallback to REST API ``/api/v3/klines``
    4. On 429/5xx: exponential backoff (1s, 2s, 4s), max 3 retries

    Rate limiting: ``asyncio.Semaphore(10)`` + 0.1s sleep between requests.
    """

    def __init__(
        self,
        bar_normalizer_factory: Callable[[BarSize], NormalizerStrategy[list[Any], Bar]],
        concurrency: int = 10,
    ) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._bar_normalizer_factory = bar_normalizer_factory

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "binance_historical"

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Yield batches of bars from Binance archives or REST fallback.

        Args:
            symbol: Binance trading pair (e.g. ``BTCUSDT``).
            bar_size: Bar time-frame resolution.
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`Bar` per batch.
        """
        interval = _bar_size_to_binance_interval(bar_size)
        normalizer = self._bar_normalizer_factory(bar_size)
        placeholder = _placeholder_asset(symbol)
        use_monthly = (end - start).days > 30

        async with httpx.AsyncClient(timeout=60.0) as client:
            batch: list[Bar] = []
            for url, period_start, period_end in self._kline_periods(
                symbol, interval, start, end, use_monthly
            ):
                async with self._semaphore:
                    raw_rows = await self._download_zip_csv(client, url)
                    if raw_rows is None:
                        # 404 — fallback REST on THIS period only
                        raw_rows = await self._fallback_rest_klines(
                            client, symbol, interval, period_start, period_end
                        )
                    for row in raw_rows:
                        kline = self._csv_row_to_kline(row)
                        bar = normalizer.normalize(kline, placeholder)
                        # Filter to requested range
                        if bar.timestamp >= start and bar.timestamp < end:
                            batch.append(bar)
                            if len(batch) >= _BATCH_SIZE:
                                yield batch
                                batch = []
                    await asyncio.sleep(0.1)

            if batch:
                yield batch

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Yield batches of aggTrades from Binance daily archives.

        Args:
            symbol: Binance trading pair (e.g. ``BTCUSDT``).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`DbTick` per batch.
        """
        placeholder = _placeholder_asset(symbol)

        async with httpx.AsyncClient(timeout=60.0) as client:
            batch: list[DbTick] = []
            current = start.replace(hour=0, minute=0, second=0, microsecond=0)
            while current < end:
                date_str = current.strftime("%Y-%m-%d")
                url = (
                    f"{_VISION_BASE}/daily/aggTrades/{symbol.upper()}"
                    f"/{symbol.upper()}-aggTrades-{date_str}.zip"
                )
                next_day = current + timedelta(days=1)
                async with self._semaphore:
                    raw_rows = await self._download_zip_csv(client, url)
                    if raw_rows is None:
                        raw_rows = await self._fallback_rest_agg_trades(
                            client, symbol, current, next_day
                        )
                    for row in raw_rows:
                        tick = self._parse_agg_trade(row, placeholder)
                        if tick.timestamp >= start and tick.timestamp < end:
                            batch.append(tick)
                            if len(batch) >= _BATCH_SIZE:
                                yield batch
                                batch = []
                    await asyncio.sleep(0.1)
                current += timedelta(days=1)

            if batch:
                yield batch

    # ── URL generators ────────────────────────────────────────────────────────

    @staticmethod
    def _monthly_kline_urls(
        symbol: str, interval: str, start: datetime, end: datetime
    ) -> Iterator[str]:
        """Generate monthly kline ZIP URLs for the given range."""
        current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            year_month = current.strftime("%Y-%m")
            yield (
                f"{_VISION_BASE}/monthly/klines/{symbol.upper()}"
                f"/{interval}/{symbol.upper()}-{interval}-{year_month}.zip"
            )
            # Advance to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    @staticmethod
    def _daily_kline_urls(
        symbol: str, interval: str, start: datetime, end: datetime
    ) -> Iterator[str]:
        """Generate daily kline ZIP URLs for the given range."""
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            date_str = current.strftime("%Y-%m-%d")
            yield (
                f"{_VISION_BASE}/daily/klines/{symbol.upper()}"
                f"/{interval}/{symbol.upper()}-{interval}-{date_str}.zip"
            )
            current += timedelta(days=1)

    def _kline_periods(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        monthly: bool,
    ) -> Iterator[tuple[str, datetime, datetime]]:
        """Yield (url, period_start, period_end) tuples for each archive file."""
        if monthly:
            current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while current < end:
                if current.month == 12:
                    next_period = current.replace(year=current.year + 1, month=1)
                else:
                    next_period = current.replace(month=current.month + 1)
                year_month = current.strftime("%Y-%m")
                url = (
                    f"{_VISION_BASE}/monthly/klines/{symbol.upper()}"
                    f"/{interval}/{symbol.upper()}-{interval}-{year_month}.zip"
                )
                yield url, current, next_period
                current = next_period
        else:
            current = start.replace(hour=0, minute=0, second=0, microsecond=0)
            while current < end:
                next_period = current + timedelta(days=1)
                date_str = current.strftime("%Y-%m-%d")
                url = (
                    f"{_VISION_BASE}/daily/klines/{symbol.upper()}"
                    f"/{interval}/{symbol.upper()}-{interval}-{date_str}.zip"
                )
                yield url, current, next_period
                current = next_period

    # ── Download helpers ──────────────────────────────────────────────────────

    async def _download_zip_csv(
        self, client: httpx.AsyncClient, url: str
    ) -> list[list[str]] | None:
        """Download a ZIP from *url*, extract the CSV, return rows.

        Returns None on 404. Retries with exponential backoff on 429/5xx.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    logger.debug("zip_not_found", url=url)
                    return None
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "retrying_download",
                        url=url,
                        status=resp.status_code,
                        wait=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return self._extract_csv_from_zip(resp.content)
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                wait = _BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "download_error",
                    url=url,
                    error=str(exc),
                    wait=wait,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)

        raise BinanceFetchError(f"max retries exceeded: {url}")

    async def _fallback_rest_klines(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        interval: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[list[str]]:
        """Fetch klines from REST API for a specific period, with pagination."""
        all_rows: list[list[str]] = []
        cursor = int(period_start.timestamp() * 1000)
        end_ms = int(period_end.timestamp() * 1000)

        while cursor < end_ms:
            params: dict[str, str | int] = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.get(f"{_REST_BASE}/klines", params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                        continue
                    resp.raise_for_status()
                    data: list[list[Any]] = resp.json()
                    if not data:
                        return all_rows
                    for kline in data:
                        all_rows.append([str(v) for v in kline])
                    # Advance cursor past the last open_time
                    last_open_time = int(data[-1][0])
                    if last_open_time <= cursor:
                        return all_rows
                    cursor = last_open_time + 1
                    break
                except httpx.HTTPError as exc:
                    logger.warning("rest_fallback_error", error=str(exc), attempt=attempt + 1)
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
            else:
                raise BinanceFetchError(f"REST fallback exhausted for {symbol}")
        return all_rows

    async def _fallback_rest_agg_trades(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[list[str]]:
        """Fetch aggTrades from REST API for a specific day."""
        all_rows: list[list[str]] = []
        start_ms = int(period_start.timestamp() * 1000)
        end_ms = int(period_end.timestamp() * 1000)
        cursor = start_ms
        while cursor < end_ms:
            chunk_end = min(cursor + 3600_000, end_ms)
            params: dict[str, str | int] = {
                "symbol": symbol.upper(),
                "startTime": cursor,
                "endTime": chunk_end,
                "limit": 1000,
            }
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.get(f"{_REST_BASE}/aggTrades", params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                        continue
                    resp.raise_for_status()
                    data: list[dict[str, Any]] = resp.json()
                    if not data:
                        cursor += 3600_000
                        break
                    for trade in data:
                        all_rows.append(
                            [
                                str(trade["a"]),
                                str(trade["p"]),
                                str(trade["q"]),
                                str(trade["f"]),
                                str(trade["l"]),
                                str(trade["T"]),
                                "true" if trade["m"] else "false",
                                "true",
                            ]
                        )
                    last_ts = int(data[-1]["T"])
                    cursor = max(cursor + 3600_000, last_ts + 1)
                    break
                except httpx.HTTPError:
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
            else:
                raise BinanceFetchError(f"aggTrades REST exhausted for {symbol} {period_start}")
        return all_rows

    # ── Parsing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_csv_from_zip(content: bytes) -> list[list[str]]:
        """Extract the first CSV file from a ZIP archive in memory."""
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            if not names:
                return []
            with zf.open(names[0]) as csv_file:
                text = io.TextIOWrapper(csv_file, encoding="utf-8")
                reader = csv.reader(text)
                return list(reader)

    @staticmethod
    def _csv_row_to_kline(row: list[str]) -> list[Any]:
        """Convert a CSV row to the list[Any] format expected by BinanceBarNormalizer.

        Binance CSV kline format:
        open_time, open, high, low, close, volume,
        close_time, quote_volume, count, taker_buy_base,
        taker_buy_quote, ignore
        """
        return [
            int(row[0]),  # open_time_ms
            row[1],  # open
            row[2],  # high
            row[3],  # low
            row[4],  # close
            row[5],  # volume
            int(row[6]),  # close_time_ms
            row[7],  # quote_asset_volume
            int(row[8]),  # number_of_trades
            row[9],  # taker_buy_base
            row[10],  # taker_buy_quote
            row[11],  # ignore
        ]

    @staticmethod
    def _parse_agg_trade(row: list[str], asset: Asset) -> DbTick:
        """Parse a Binance aggTrades CSV row into a DbTick.

        Format: agg_id, price, quantity, first_id, last_id, timestamp,
                is_buyer_maker, is_best_match
        """
        timestamp_ms = int(row[5])
        is_buyer_maker = row[6].strip().lower() == "true"
        return DbTick(
            asset_id=asset.asset_id,
            timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
            trade_id=row[0],
            price=Decimal(row[1]),
            quantity=Decimal(row[2]),
            side="sell" if is_buyer_maker else "buy",
        )
