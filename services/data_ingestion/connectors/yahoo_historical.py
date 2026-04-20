"""Yahoo Finance historical data connector.

Downloads OHLCV bars via the yfinance SDK for global indices, FX majors,
international ETFs, and commodities. Yahoo Finance is a free, no-auth
breadth source — not an execution feed.

References:
    yfinance docs — https://github.com/ranaroussi/yfinance
    Bouchaud et al. (2018) — "Trades, Quotes and Prices"
    Lo (2002) — "The Statistics of Sharpe Ratios"
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import structlog
import yfinance as yf

from core.models.data import Asset, AssetClass, Bar, BarSize, DbTick
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy

if TYPE_CHECKING:
    from services.s01_data_ingestion.normalizers.yahoo_bar import YahooBarPayload

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class YahooFetchError(Exception):
    """Raised when Yahoo Finance fetch fails after retries."""


def _bar_size_to_yahoo_interval(bar_size: BarSize) -> str:
    """Map a BarSize enum to the Yahoo Finance interval string."""
    mapping: dict[BarSize, str] = {
        BarSize.M1: "1m",
        BarSize.M5: "5m",
        BarSize.M15: "15m",
        BarSize.H1: "1h",
        BarSize.D1: "1d",
        BarSize.W1: "1wk",
        BarSize.MO1: "1mo",
    }
    if bar_size not in mapping:
        msg = f"Unsupported bar size for Yahoo Finance: {bar_size}"
        raise ValueError(msg)
    return mapping[bar_size]


def _placeholder_asset(symbol: str) -> Asset:
    """Create a minimal placeholder Asset for normalizer use.

    The real asset_id is assigned later by the backfill script.
    """
    return Asset(
        asset_id=uuid.UUID(int=0),
        symbol=symbol.upper(),
        exchange="YAHOO",
        asset_class=AssetClass.EQUITY,
        currency="USD",
    )


class YahooHistoricalConnector(DataConnector):
    """Downloads historical OHLCV data via the yfinance SDK.

    Supports global indices (^GSPC, ^DJI), FX pairs (EURUSD=X),
    ETFs (SPY, QQQ), and commodities (GC=F, CL=F).

    Rate limiting: ``asyncio.Semaphore`` to control concurrent requests.
    Retry: exponential backoff (1s, 2s, 4s), max 3 attempts.
    """

    def __init__(
        self,
        bar_normalizer_factory: Callable[[BarSize], NormalizerStrategy[YahooBarPayload, Bar]],
        concurrency: int = 5,
    ) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._bar_normalizer_factory = bar_normalizer_factory

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "yahoo_historical"

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Yield batches of bars from Yahoo Finance.

        Args:
            symbol: Yahoo Finance ticker (e.g. ``^GSPC``, ``EURUSD=X``).
            bar_size: Bar time-frame resolution.
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`Bar` per batch.
        """
        interval = _bar_size_to_yahoo_interval(bar_size)
        normalizer = self._bar_normalizer_factory(bar_size)
        placeholder = _placeholder_asset(symbol)

        async with self._semaphore:
            df = await self._fetch_with_retry(symbol, interval, start, end)

        batch: list[Bar] = []
        for ts, row in df.iterrows():
            # Filter to requested [start, end) window after Yahoo returns
            bar_ts: datetime = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=UTC)
            if bar_ts < start or bar_ts >= end:
                continue
            payload = (ts, row.to_dict())
            bar = normalizer.normalize(payload, placeholder)
            batch.append(bar)
            if len(batch) >= _BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch

    async def _fetch_with_retry(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Fetch data from Yahoo Finance with exponential backoff.

        Args:
            symbol: Yahoo Finance ticker.
            interval: Yahoo interval string (e.g. ``1d``).
            start: Start datetime.
            end: End datetime.

        Returns:
            A pandas DataFrame with OHLCV data.

        Raises:
            YahooFetchError: If all retries are exhausted.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                df: pd.DataFrame = await asyncio.to_thread(
                    self._sync_fetch, symbol, interval, start, end
                )
                if df is None or df.empty:
                    if attempt == _MAX_RETRIES - 1:
                        raise YahooFetchError(f"empty dataframe for {symbol}")
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                return df
            except YahooFetchError:
                raise
            except Exception as exc:
                logger.warning(
                    "yahoo_fetch_error",
                    symbol=symbol,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise YahooFetchError(f"failed for {symbol}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        raise YahooFetchError(f"unreachable for {symbol}")

    @staticmethod
    def _sync_fetch(symbol: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Synchronous yfinance download — called via ``asyncio.to_thread``.

        Args:
            symbol: Yahoo Finance ticker.
            interval: Yahoo interval string.
            start: Start datetime.
            end: End datetime.

        Returns:
            A pandas DataFrame with OHLCV columns.
        """
        ticker = yf.Ticker(symbol)
        df: pd.DataFrame = ticker.history(
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            actions=False,
        )
        return df

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Yahoo Finance does not provide historical tick data.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Yahoo Finance does not provide historical tick data")
        yield []  # pragma: no cover
