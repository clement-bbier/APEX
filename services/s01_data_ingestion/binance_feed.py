"""Binance WebSocket trade-stream feed for the APEX Trading System.

Connects to the Binance combined-stream endpoint, forwards raw trade events to
a caller-supplied callback, and auto-reconnects on failure with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import websockets
import websockets.exceptions

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("s01_data_ingestion.binance_feed")

_RECONNECT_BASE_SECONDS: float = 1.0
_RECONNECT_MAX_SECONDS: float = 60.0
_PRODUCTION_WS_BASE: str = "wss://stream.binance.com:9443"
_TESTNET_WS_BASE: str = "wss://testnet.binance.vision"


class BinanceFeed:
    """Subscribes to Binance combined trade streams and delivers raw tick dicts.

    For each configured symbol the feed subscribes to the ``{symbol}@trade``
    stream.  Each incoming trade message is parsed and forwarded to *on_tick*.
    The connection is automatically re-established after any error using
    exponential back-off capped at :data:`_RECONNECT_MAX_SECONDS`.

    Args:
        symbols: List of Binance symbols to subscribe to, e.g. ``["BTCUSDT"]``.
        on_tick: Async (or sync) callable receiving a single ``dict`` - the
            ``data`` payload from the combined-stream message.
    """

    def __init__(self, symbols: list[str], on_tick: Callable) -> None:
        """Initialise the feed.

        Args:
            symbols: Uppercase Binance trading-pair symbols.
            on_tick: Callback invoked with each raw trade ``data`` dict.
        """
        self._symbols = [s.upper() for s in symbols]
        self._on_tick = on_tick
        self._settings = get_settings()
        self._running = False
        self._ws = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Binance trade streams and start consuming messages.

        Blocks until :meth:`stop` is called.  Reconnects automatically with
        exponential back-off (initial 1 s, max 60 s) on any connection error.
        """
        self._running = True
        backoff = _RECONNECT_BASE_SECONDS

        while self._running:
            url = self._build_url()
            logger.info("Connecting to Binance WebSocket", url=url)
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    backoff = _RECONNECT_BASE_SECONDS  # reset on successful connect
                    logger.info("Binance WebSocket connected", symbols=self._symbols)
                    await self._consume(ws)
            except asyncio.CancelledError:
                logger.info("BinanceFeed cancelled - stopping")
                break
            except websockets.exceptions.WebSocketException as exc:
                logger.warning(
                    "Binance WebSocket error - reconnecting",
                    error=str(exc),
                    backoff_seconds=backoff,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected BinanceFeed error - reconnecting",
                    error=str(exc),
                    backoff_seconds=backoff,
                )
            finally:
                self._ws = None

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    async def stop(self) -> None:
        """Gracefully disconnect from Binance WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.warning("Error closing Binance WebSocket", error=str(exc))
        logger.info("BinanceFeed stopped")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_url(self) -> str:
        """Construct the Binance combined-stream WebSocket URL.

        Returns:
            Full WSS URL with all symbol stream subscriptions.
        """
        streams = "/".join(f"{s.lower()}@trade" for s in self._symbols)
        base = _TESTNET_WS_BASE if self._settings.binance_testnet else _PRODUCTION_WS_BASE
        return f"{base}/stream?streams={streams}"

    async def _consume(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Read messages from *ws* until the connection closes or we stop.

        Parses the combined-stream envelope and invokes *on_tick* with the
        inner ``data`` dict.

        Args:
            ws: An active :mod:`websockets` connection.
        """
        async for raw_message in ws:
            if not self._running:
                break
            try:
                envelope: dict = json.loads(raw_message)
                data: dict | None = envelope.get("data")
                if data is None:
                    continue
                await self._dispatch(data)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse Binance message", error=str(exc))
            except Exception as exc:
                logger.error("Error processing Binance tick", error=str(exc))

    async def _dispatch(self, data: dict) -> None:
        """Call *on_tick* with *data*, supporting both async and sync callables.

        Args:
            data: The trade ``data`` object from the Binance combined stream.
        """
        try:
            if asyncio.iscoroutinefunction(self._on_tick):
                await self._on_tick(data)
            else:
                self._on_tick(data)
        except Exception as exc:
            logger.error("on_tick callback raised an exception", error=str(exc))
