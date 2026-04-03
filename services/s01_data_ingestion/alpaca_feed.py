"""Alpaca WebSocket trade-stream feed for the APEX Trading System.

Connects to the Alpaca market-data streaming endpoint, authenticates, subscribes
to trade updates for the configured symbols, and delivers raw event dicts to
a caller-supplied callback.  Reconnects automatically with exponential back-off.
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable

import websockets
import websockets.exceptions

from core.logger import get_logger

logger = get_logger("s01_data_ingestion.alpaca_feed")

_RECONNECT_BASE_SECONDS: float = 1.0
_RECONNECT_MAX_SECONDS: float = 60.0


class AlpacaFeed:
    """Streams real-time equity trades from the Alpaca data WebSocket.

    The connection lifecycle is:

    1. Connect to *url*.
    2. Wait for the ``"connected"`` confirmation message.
    3. Send authentication credentials.
    4. Wait for the ``"authenticated"`` confirmation.
    5. Subscribe to the requested trade symbols.
    6. Forward each incoming trade message to *on_tick*.

    Reconnects automatically with exponential back-off (initial 1 s, max 60 s).

    Args:
        symbols: Equity ticker symbols to subscribe to, e.g. ``["AAPL", "SPY"]``.
        on_tick: Async (or sync) callable receiving a single trade event ``dict``.
        api_key: Alpaca API key.
        secret_key: Alpaca secret key.
        url: Alpaca data streaming WebSocket URL.
    """

    def __init__(
        self,
        symbols: list[str],
        on_tick: Callable,
        api_key: str,
        secret_key: str,
        url: str,
    ) -> None:
        """Initialise the feed.

        Args:
            symbols: Uppercase equity ticker symbols.
            on_tick: Callback invoked for each raw trade event dict.
            api_key: Alpaca API key for authentication.
            secret_key: Alpaca secret key for authentication.
            url: Alpaca WebSocket streaming URL.
        """
        self._symbols = [s.upper() for s in symbols]
        self._on_tick = on_tick
        self._api_key = api_key
        self._secret_key = secret_key
        self._url = url
        self._running = False
        self._ws = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Alpaca, authenticate, subscribe, and consume trade events.

        Blocks until :meth:`stop` is called.  Reconnects automatically with
        exponential back-off on any error.
        """
        self._running = True
        backoff = _RECONNECT_BASE_SECONDS

        while self._running:
            logger.info("Connecting to Alpaca WebSocket", url=self._url)
            try:
                async with websockets.connect(
                    self._url, ping_interval=20, ping_timeout=20
                ) as ws:
                    self._ws = ws
                    backoff = _RECONNECT_BASE_SECONDS  # reset on successful connect
                    logger.info("Alpaca WebSocket connected")

                    authenticated = await self._authenticate(ws)
                    if not authenticated:
                        logger.error("Alpaca authentication failed – will retry")
                        continue

                    await self._subscribe(ws)
                    await self._consume(ws)

            except asyncio.CancelledError:
                logger.info("AlpacaFeed cancelled – stopping")
                break
            except websockets.exceptions.WebSocketException as exc:
                logger.warning(
                    "Alpaca WebSocket error – reconnecting",
                    error=str(exc),
                    backoff_seconds=backoff,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected AlpacaFeed error – reconnecting",
                    error=str(exc),
                    backoff_seconds=backoff,
                )
            finally:
                self._ws = None

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    async def stop(self) -> None:
        """Gracefully disconnect from the Alpaca WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.warning("Error closing Alpaca WebSocket", error=str(exc))
        logger.info("AlpacaFeed stopped")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _authenticate(self, ws) -> bool:
        """Send auth credentials and wait for Alpaca's confirmation.

        Args:
            ws: An active :mod:`websockets` connection.

        Returns:
            ``True`` if authentication succeeded, ``False`` otherwise.
        """
        auth_msg = json.dumps(
            {"action": "auth", "key": self._api_key, "secret": self._secret_key}
        )
        await ws.send(auth_msg)

        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            messages: list[dict] = json.loads(raw)
            for msg in messages:
                if msg.get("T") == "success" and msg.get("msg") == "authenticated":
                    logger.info("Alpaca authentication successful")
                    return True
                if msg.get("T") == "error":
                    logger.error(
                        "Alpaca auth error",
                        code=msg.get("code"),
                        detail=msg.get("msg"),
                    )
                    return False
        except asyncio.TimeoutError:
            logger.error("Alpaca auth response timed out")
            return False

        return False

    async def _subscribe(self, ws) -> None:
        """Subscribe to trade updates for the configured symbols.

        Args:
            ws: An authenticated :mod:`websockets` connection.
        """
        sub_msg = json.dumps(
            {"action": "subscribe", "trades": self._symbols}
        )
        await ws.send(sub_msg)
        logger.info("Alpaca trade subscription sent", symbols=self._symbols)

    async def _consume(self, ws) -> None:
        """Read messages from *ws* and forward trade events to *on_tick*.

        Args:
            ws: An active, subscribed :mod:`websockets` connection.
        """
        async for raw_message in ws:
            if not self._running:
                break
            try:
                messages: list[dict] = json.loads(raw_message)
                for msg in messages:
                    msg_type = msg.get("T", "")
                    if msg_type == "t":
                        await self._dispatch(msg)
                    elif msg_type == "error":
                        logger.warning(
                            "Alpaca stream error message",
                            code=msg.get("code"),
                            detail=msg.get("msg"),
                        )
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse Alpaca message", error=str(exc))
            except Exception as exc:
                logger.error("Error processing Alpaca message", error=str(exc))

    async def _dispatch(self, trade: dict) -> None:
        """Invoke *on_tick* with *trade*, supporting async and sync callables.

        Args:
            trade: A single Alpaca trade event dict.
        """
        try:
            if asyncio.iscoroutinefunction(self._on_tick):
                await self._on_tick(trade)
            else:
                self._on_tick(trade)
        except Exception as exc:
            logger.error("on_tick callback raised an exception", error=str(exc))
