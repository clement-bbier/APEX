"""Alpaca historical data connector.

Downloads bars and trades via the alpaca-py SDK's StockHistoricalDataClient.
Uses IEX feed for paper accounts.

References:
    Alpaca Markets API docs — https://docs.alpaca.markets/
    Bouchaud et al. (2018) — "Trades, Quotes and Prices"
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import structlog
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from core.config import Settings
from core.models.data import Asset, AssetClass, Bar, BarSize, DbTick
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.normalizers.alpaca_bar import AlpacaBarNormalizer
from services.s01_data_ingestion.normalizers.alpaca_trade import AlpacaTradeNormalizer

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 1000


class AlpacaFetchError(Exception):
    """Raised when Alpaca API call fails after retries."""


def _bar_size_to_timeframe(bar_size: BarSize) -> TimeFrame:
    """Map a BarSize enum to an alpaca-py TimeFrame."""
    mapping: dict[BarSize, TimeFrame] = {
        BarSize.M1: TimeFrame.Minute,
        BarSize.M5: TimeFrame(5, TimeFrameUnit.Minute),
        BarSize.M15: TimeFrame(15, TimeFrameUnit.Minute),
        BarSize.H1: TimeFrame.Hour,
        BarSize.H4: TimeFrame(4, TimeFrameUnit.Hour),
        BarSize.D1: TimeFrame.Day,
        BarSize.W1: TimeFrame.Week,
        BarSize.MO1: TimeFrame.Month,
    }
    return mapping[bar_size]


def _placeholder_asset(symbol: str) -> Asset:
    """Create a minimal placeholder Asset for normalizer use."""
    return Asset(
        asset_id=uuid.UUID(int=0),
        symbol=symbol.upper(),
        exchange="ALPACA",
        asset_class=AssetClass.EQUITY,
        currency="USD",
    )


class AlpacaHistoricalConnector(DataConnector):
    """Downloads historical equity data via the alpaca-py SDK.

    Uses ``StockHistoricalDataClient`` for bars and trades.
    Rate limiting: ``asyncio.Semaphore(10)`` for concurrent requests.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
        )
        self._semaphore = asyncio.Semaphore(10)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "alpaca_historical"

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Yield batches of bars from the Alpaca SDK.

        Args:
            symbol: Equity ticker (e.g. ``AAPL``).
            bar_size: Bar time-frame resolution.
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`Bar` per batch.
        """
        timeframe = _bar_size_to_timeframe(bar_size)
        normalizer = AlpacaBarNormalizer(bar_size)
        placeholder = _placeholder_asset(symbol)
        page_token: str | None = None

        while True:
            async with self._semaphore:
                request_kwargs: dict[str, object] = {
                    "symbol_or_symbols": symbol.upper(),
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                }
                if page_token is not None:
                    request_kwargs["page_token"] = page_token
                request = StockBarsRequest(**request_kwargs)  # type: ignore[arg-type]
                try:
                    response = await asyncio.to_thread(self._client.get_stock_bars, request)
                except Exception as exc:
                    logger.error(
                        "alpaca_bars_fetch_error",
                        symbol=symbol,
                        error=str(exc),
                    )
                    raise AlpacaFetchError(f"Alpaca bars fetch failed for {symbol}: {exc}") from exc

            resp_data: dict[str, list[object]] = response.data  # type: ignore[union-attr,assignment]
            bars_data = resp_data.get(symbol.upper(), [])
            if not bars_data:
                break

            batch: list[Bar] = []
            for alpaca_bar in bars_data:
                bar = normalizer.normalize(alpaca_bar, placeholder)
                if bar.timestamp >= start and bar.timestamp < end:
                    batch.append(bar)
                    if len(batch) >= _BATCH_SIZE:
                        yield batch
                        batch = []

            if batch:
                yield batch

            page_token = getattr(response, "next_page_token", None)
            if not page_token:
                break

            logger.debug(
                "alpaca_bars_next_page",
                symbol=symbol,
                page_token=page_token,
            )

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Yield batches of trades from the Alpaca SDK.

        Args:
            symbol: Equity ticker (e.g. ``AAPL``).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`DbTick` per batch.
        """
        normalizer = AlpacaTradeNormalizer()
        placeholder = _placeholder_asset(symbol)
        page_token: str | None = None

        while True:
            async with self._semaphore:
                request_kwargs: dict[str, object] = {
                    "symbol_or_symbols": symbol.upper(),
                    "start": start,
                    "end": end,
                }
                if page_token is not None:
                    request_kwargs["page_token"] = page_token
                request = StockTradesRequest(**request_kwargs)  # type: ignore[arg-type]
                try:
                    response = await asyncio.to_thread(self._client.get_stock_trades, request)
                except Exception as exc:
                    logger.error(
                        "alpaca_trades_fetch_error",
                        symbol=symbol,
                        error=str(exc),
                    )
                    raise AlpacaFetchError(
                        f"Alpaca trades fetch failed for {symbol}: {exc}"
                    ) from exc

            resp_data: dict[str, list[object]] = response.data  # type: ignore[union-attr,assignment]
            trades_data = resp_data.get(symbol.upper(), [])
            if not trades_data:
                break

            batch: list[DbTick] = []
            for alpaca_trade in trades_data:
                tick = normalizer.normalize(alpaca_trade, placeholder)
                if tick.timestamp >= start and tick.timestamp < end:
                    batch.append(tick)
                    if len(batch) >= _BATCH_SIZE:
                        yield batch
                        batch = []

            if batch:
                yield batch

            page_token = getattr(response, "next_page_token", None)
            if not page_token:
                break
