"""Alpaca real-time equity data feed using the official alpaca-py SDK.

Uses :class:`alpaca.data.live.StockDataStream` for WebSocket trade streaming.
Auto-reconnects on failure with exponential back-off.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from alpaca.data.live import StockDataStream

from core.logger import get_logger

logger = get_logger("data_ingestion.alpaca_feed")

_RECONNECT_BASE_SECONDS: float = 1.0
_RECONNECT_MAX_SECONDS: float = 60.0


class AlpacaFeed:
    """Streams real-time equity trades from Alpaca via the ``alpaca-py`` SDK.

    Wraps :class:`alpaca.data.live.StockDataStream`, subscribes to trade
    events for each configured symbol, and forwards raw event dicts to the
    caller-supplied *on_tick* callback.  Reconnects automatically with
    exponential back-off.

    Args:
        symbols: Uppercase equity ticker symbols, e.g. ``["AAPL", "SPY"]``.
        on_tick: Async or sync callable that receives a single trade-event dict[str, Any].
        api_key: Alpaca API key.
        secret_key: Alpaca secret key.
        url: Unused - kept for interface compatibility with BinanceFeed.
    """

    def __init__(
        self,
        symbols: list[str],
        on_tick: Callable[..., Any],
        api_key: str,
        secret_key: str,
        url: str = "",
    ) -> None:
        self._symbols = [s.upper() for s in symbols]
        self._on_tick = on_tick
        self._api_key = api_key
        self._secret_key = secret_key
        self._running = False
        self._stream: StockDataStream | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Alpaca stream, subscribe, and consume trade events.

        Blocks until :meth:`stop` is called.  Reconnects with exponential
        back-off on any error.
        """
        self._running = True
        backoff = _RECONNECT_BASE_SECONDS

        while self._running:
            logger.info("Connecting to Alpaca data stream", symbols=self._symbols)
            try:
                self._stream = StockDataStream(
                    api_key=self._api_key,
                    secret_key=self._secret_key,
                )
                self._stream.subscribe_trades(self._handle_trade, *self._symbols)
                # _run_forever drives the asyncio event loop inside alpaca-py
                await self._stream._run_forever()
                backoff = _RECONNECT_BASE_SECONDS

            except asyncio.CancelledError:
                logger.info("AlpacaFeed cancelled - stopping")
                break
            except Exception as exc:
                logger.warning(
                    "Alpaca stream error - reconnecting",
                    error=str(exc),
                    backoff_seconds=backoff,
                )
            finally:
                self._stream = None

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    async def stop(self) -> None:
        """Gracefully stop the Alpaca data stream."""
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                logger.warning("Error stopping Alpaca stream", error=str(exc))
            self._stream = None
        logger.info("AlpacaFeed stopped")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _handle_trade(self, trade: object) -> None:
        """Convert an alpaca-py Trade object to a dict[str, Any] and dispatch to on_tick.

        Args:
            trade: An :class:`alpaca.data.models.Trade` instance from the SDK.
        """
        try:
            trade_dict: dict[str, Any] = {
                "S": getattr(trade, "symbol", ""),
                "t": str(getattr(trade, "timestamp", "")),
                "p": str(getattr(trade, "price", "0")),
                "s": str(getattr(trade, "size", "0")),
                "c": getattr(trade, "conditions", []),
                "x": getattr(trade, "exchange", ""),
            }
            if asyncio.iscoroutinefunction(self._on_tick):
                await self._on_tick(trade_dict)
            else:
                self._on_tick(trade_dict)
        except Exception as exc:
            logger.error("Error dispatching Alpaca trade", error=str(exc))
