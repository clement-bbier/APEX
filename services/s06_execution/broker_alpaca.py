"""Alpaca broker adapter for APEX Trading System - S06 Execution.

Wraps the Alpaca REST API v2 for equity order management.
All HTTP communication is handled via a shared :mod:`aiohttp` session.
"""

from __future__ import annotations

from typing import Optional

import aiohttp


class AlpacaBroker:
    """Async HTTP client for the Alpaca brokerage API.

    Supports both live and paper endpoints.  The ``base_url`` parameter
    controls which environment is targeted; typical values are:

    - ``"https://paper-api.alpaca.markets"`` (paper trading)
    - ``"https://api.alpaca.markets"`` (live trading)
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str,
        paper: bool = True,
    ) -> None:
        """Initialize the Alpaca broker client.

        Args:
            api_key:    Alpaca API key ID.
            secret_key: Alpaca secret key.
            base_url:   Base URL for the Alpaca API endpoint.
            paper:      ``True`` if this is a paper-trading session.
        """
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._paper = paper
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the underlying :class:`aiohttp.ClientSession`."""
        self._session = aiohttp.ClientSession(
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            }
        )

    async def disconnect(self) -> None:
        """Close the HTTP session and release resources."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ── Order operations ──────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> dict:
        """Submit an order to Alpaca.

        Args:
            symbol:      Ticker symbol (e.g. ``"AAPL"``).
            qty:         Number of shares.
            side:        ``"buy"`` or ``"sell"``.
            order_type:  ``"market"``, ``"limit"``, ``"stop"``, or
                         ``"stop_limit"``.
            limit_price: Limit price (required for limit/stop_limit orders).
            stop_price:  Stop price (required for stop/stop_limit orders).

        Returns:
            Alpaca order response dict.
        """
        session = self._ensure_session()
        payload: dict = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": "gtc",
        }
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)

        async with session.post(
            f"{self._base_url}/v2/orders", json=payload
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by its Alpaca order ID.

        Args:
            order_id: Alpaca-assigned order ID.
        """
        session = self._ensure_session()
        async with session.delete(
            f"{self._base_url}/v2/orders/{order_id}"
        ) as resp:
            resp.raise_for_status()

    # ── Account / position queries ────────────────────────────────────────────

    async def get_position(self, symbol: str) -> Optional[dict]:
        """Retrieve the current open position for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Position dict or ``None`` if no open position exists.
        """
        session = self._ensure_session()
        async with session.get(
            f"{self._base_url}/v2/positions/{symbol}"
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def get_account(self) -> dict:
        """Retrieve the Alpaca account details.

        Returns:
            Account information dict from Alpaca.
        """
        session = self._ensure_session()
        async with session.get(f"{self._base_url}/v2/account") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def sync_positions(self) -> dict[str, dict]:
        """Fetch all open positions and index them by symbol.

        Returns:
            Mapping of ``{symbol: position_dict}`` for all open positions.
        """
        session = self._ensure_session()
        async with session.get(f"{self._base_url}/v2/positions") as resp:
            resp.raise_for_status()
            positions: list[dict] = await resp.json()
        return {p["symbol"]: p for p in positions}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the active HTTP session or raise if not connected.

        Returns:
            Active :class:`aiohttp.ClientSession`.

        Raises:
            RuntimeError: If :meth:`connect` has not been called.
        """
        if self._session is None:
            raise RuntimeError("AlpacaBroker not connected. Call connect() first.")
        return self._session
