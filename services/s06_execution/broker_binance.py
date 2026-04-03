"""Binance broker adapter for APEX Trading System - S06 Execution.

Wraps the Binance REST API v3 for spot crypto order management.
Request signing uses HMAC-SHA256 as required by the Binance API.
"""

from __future__ import annotations
from typing import Any

import hashlib
import hmac
import time
import urllib.parse

import aiohttp


class BinanceBroker:
    """Async HTTP client for the Binance spot trading API.

    Supports both mainnet and testnet environments.  The ``base_url``
    controls the endpoint:

    - ``"https://testnet.binance.vision"`` (testnet)
    - ``"https://api.binance.com"`` (mainnet)
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str,
        testnet: bool = True,
    ) -> None:
        """Initialize the Binance broker client.

        Args:
            api_key:    Binance API key.
            secret_key: Binance API secret (used for HMAC signing).
            base_url:   Base URL for the Binance API endpoint.
            testnet:    ``True`` if targeting the Binance testnet.
        """
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._testnet = testnet
        self._session: aiohttp.ClientSession | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the underlying :class:`aiohttp.ClientSession`."""
        self._session = aiohttp.ClientSession(headers={"X-MBX-APIKEY": self._api_key})

    async def disconnect(self) -> None:
        """Close the HTTP session and release resources."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ── Signing ───────────────────────────────────────────────────────────────

    def _sign(self, params: dict[str, str]) -> str:
        """Produce an HMAC-SHA256 signature for the given query parameters.

        The signature covers the URL-encoded query string (sorted by key).

        Args:
            params: Request parameters to sign.

        Returns:
            Hex-encoded HMAC-SHA256 signature string.
        """
        query_string = urllib.parse.urlencode(params)
        return hmac.new(
            self._secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    # ── Order operations ──────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        """Submit a signed order to Binance.

        Args:
            symbol:     Trading pair symbol (e.g. ``"BTCUSDT"``).
            side:       ``"BUY"`` or ``"SELL"``.
            order_type: ``"MARKET"``, ``"LIMIT"``, ``"STOP_LOSS_LIMIT"``, etc.
            quantity:   Order quantity in base asset.
            price:      Limit price (required for LIMIT orders).
            stop_price: Stop price (required for stop orders).

        Returns:
            Binance order response dict[str, Any].
        """
        session = self._ensure_session()
        params: dict[str, str] = {
            "symbol": str(symbol),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timestamp": str(int(time.time() * 1000)),
            "timeInForce": "GTC",
        }
        if price is not None:
            params["price"] = str(price)
        if stop_price is not None:
            params["stopPrice"] = str(stop_price)
        if order_type.upper() == "MARKET":
            params.pop("timeInForce", None)

        params["signature"] = self._sign(params)
        async with session.post(f"{self._base_url}/api/v3/order", params=params) as resp:
            resp.raise_for_status()
            result: dict[str, Any] = dict(await resp.json())
            return result

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        """Cancel an open Binance order.

        Args:
            symbol:   Trading pair symbol.
            order_id: Binance-assigned numeric order ID as a string.
        """
        session = self._ensure_session()
        params: dict[str, str] = {
            "symbol": str(symbol),
            "orderId": str(order_id),
            "timestamp": str(int(time.time() * 1000)),
        }
        params["signature"] = self._sign(params)
        async with session.delete(f"{self._base_url}/api/v3/order", params=params) as resp:
            resp.raise_for_status()

    # ── Account / position queries ────────────────────────────────────────────

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        """Retrieve the current holding for a spot symbol.

        Fetches the account snapshot and returns the balance entry for the
        base asset extracted from the ``symbol`` (e.g. ``"BTC"`` from
        ``"BTCUSDT"``), or ``None`` if the balance is zero.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Balance dict[str, Any] or ``None`` if effectively no open position.
        """
        account = await self.get_account()
        # Derive the base asset by stripping the longest matching quote suffix.
        # Checked longest-first to avoid partial matches (e.g. "ETHBTC" → "ETH",
        # not an erroneous empty string from stripping "BTC" then "ETH").
        _quote_suffixes = ("USDT", "BUSD", "USDC", "BTC", "ETH", "BNB")
        base_asset = symbol
        for suffix in _quote_suffixes:
            if symbol.endswith(suffix):
                base_asset = symbol[: -len(suffix)]
                break
        balances: list[dict[str, Any]] = account.get("balances", [])
        for balance in balances:
            if balance.get("asset") == base_asset:
                free = float(balance.get("free", 0))
                locked = float(balance.get("locked", 0))
                if free + locked > 0:
                    return balance
        return None

    async def get_account(self) -> dict[str, Any]:
        """Retrieve the Binance spot account information.

        Returns:
            Account information dict[str, Any] from Binance.
        """
        session = self._ensure_session()
        params: dict[str, str] = {"timestamp": str(int(time.time() * 1000))}
        params["signature"] = self._sign(params)
        async with session.get(f"{self._base_url}/api/v3/account", params=params) as resp:
            resp.raise_for_status()
            result: dict[str, Any] = dict(await resp.json())
            return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the active HTTP session or raise if not connected.

        Returns:
            Active :class:`aiohttp.ClientSession`.

        Raises:
            RuntimeError: If :meth:`connect` has not been called.
        """
        if self._session is None:
            raise RuntimeError("BinanceBroker not connected. Call connect() first.")
        return self._session
