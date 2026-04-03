"""Data Ingestion Service (S01) for the APEX Trading System.

Orchestrates live market-data feeds from Binance (crypto) and Alpaca (equity),
normalizes each raw trade event into a :class:`~core.models.tick.NormalizedTick`,
publishes it on the ZMQ message bus under the topic ``tick.{market}.{SYMBOL}``,
and caches the latest tick in Redis.

A :class:`MacroFeed` polls FRED and Yahoo Finance for macroeconomic context that
downstream services consume for regime detection.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.base_service import BaseService
from core.config import get_settings
from core.logger import get_logger
from services.s01_data_ingestion.alpaca_feed import AlpacaFeed
from services.s01_data_ingestion.binance_feed import BinanceFeed
from services.s01_data_ingestion.macro_feed import MacroFeed
from services.s01_data_ingestion.normalizer import AlpacaNormalizer, BinanceNormalizer

logger = get_logger("s01_data_ingestion.service")

_DEFAULT_CRYPTO_SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT"]
_DEFAULT_EQUITY_SYMBOLS: list[str] = ["AAPL", "SPY", "QQQ"]


class DataIngestionService(BaseService):
    """Source service that ingests and normalises live market-data ticks.

    Responsibilities:

    * Connect to Binance combined trade streams (crypto).
    * Connect to Alpaca real-time trade stream (equity).
    * Poll FRED/Yahoo Finance for macro indicators.
    * Normalise every raw event to :class:`~core.models.tick.NormalizedTick`.
    * Publish on ZMQ topic ``tick.{market}.{symbol}``.
    * Cache the latest tick in Redis under key ``tick:{symbol}``.

    This service is a *source* – it does not subscribe to any ZMQ topics.
    """

    service_id: str = "s01_data_ingestion"

    def __init__(self) -> None:
        """Initialise feeds, normalisers, and the ZMQ publisher."""
        super().__init__(self.service_id)

        settings = get_settings()

        # Bind the ZMQ PUB socket so we can publish ticks immediately.
        self.bus.init_publisher()

        # Crypto feed (Binance).
        self._binance_normalizer = BinanceNormalizer()
        self._binance_feed = BinanceFeed(
            symbols=_DEFAULT_CRYPTO_SYMBOLS,
            on_tick=self._on_binance_tick,
        )

        # Equity feed (Alpaca).
        self._alpaca_normalizer = AlpacaNormalizer()
        self._alpaca_feed = AlpacaFeed(
            symbols=_DEFAULT_EQUITY_SYMBOLS,
            on_tick=self._on_alpaca_tick,
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            url=settings.alpaca_data_url,
        )

        # Macro data feed.
        self._macro_feed = MacroFeed(fred_api_key=settings.fred_api_key)

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """No-op: this service is a source and subscribes to no ZMQ topics.

        Args:
            topic: Incoming ZMQ topic (unused).
            data: Incoming message payload (unused).
        """

    async def run(self) -> None:
        """Start all feeds concurrently and run until the service is stopped.

        Launches :class:`BinanceFeed`, :class:`AlpacaFeed`, and
        :class:`MacroFeed` via :func:`asyncio.gather`.
        """
        logger.info(
            "DataIngestionService starting feeds",
            crypto_symbols=_DEFAULT_CRYPTO_SYMBOLS,
            equity_symbols=_DEFAULT_EQUITY_SYMBOLS,
        )

        await self._macro_feed.start()

        try:
            await asyncio.gather(
                self._binance_feed.start(),
                self._alpaca_feed.start(),
                return_exceptions=False,
            )
        finally:
            await self._macro_feed.stop()
            await self._binance_feed.stop()
            await self._alpaca_feed.stop()

    # ── Tick callbacks ────────────────────────────────────────────────────────

    async def _on_binance_tick(self, raw_data: dict) -> None:
        """Normalise a Binance trade event and publish/cache the result.

        Args:
            raw_data: The ``data`` payload from a Binance combined-stream message.
        """
        try:
            tick = self._binance_normalizer.normalize(raw_data)
            topic = f"tick.{tick.market.value}.{tick.symbol}"
            tick_dict = tick.model_dump()

            await asyncio.gather(
                self.bus.publish(topic, tick_dict),
                self.state.set(f"tick:{tick.symbol}", tick_dict),
            )

            logger.debug(
                "Binance tick published",
                symbol=tick.symbol,
                price=str(tick.price),
                session=tick.session.value,
            )
        except Exception as exc:
            logger.error(
                "Failed to process Binance tick",
                error=str(exc),
                raw=raw_data,
            )

    async def _on_alpaca_tick(self, raw_data: dict) -> None:
        """Normalise an Alpaca trade event and publish/cache the result.

        Args:
            raw_data: A single Alpaca trade event dict (``T="t"``).
        """
        try:
            tick = self._alpaca_normalizer.normalize(raw_data)
            topic = f"tick.{tick.market.value}.{tick.symbol}"
            tick_dict = tick.model_dump()

            await asyncio.gather(
                self.bus.publish(topic, tick_dict),
                self.state.set(f"tick:{tick.symbol}", tick_dict),
            )

            logger.debug(
                "Alpaca tick published",
                symbol=tick.symbol,
                price=str(tick.price),
                session=tick.session.value,
            )
        except Exception as exc:
            logger.error(
                "Failed to process Alpaca tick",
                error=str(exc),
                raw=raw_data,
            )
