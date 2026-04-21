"""Alpaca broker adapter for APEX Trading System - S06 Execution.

Uses the official ``alpaca-py`` SDK (NOT the deprecated ``alpaca-trade-api``).
Wraps :class:`alpaca.trading.client.TradingClient` for equity order management.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.models import Order, Position, TradeAccount
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from core.logger import get_logger
from core.models.order import ApprovedOrder, ExecutedOrder
from services.execution.broker_base import Broker, BrokerConnectionError

logger = get_logger("execution.broker_alpaca")


class AlpacaBroker(Broker):
    """Sync/async equity broker backed by the ``alpaca-py`` TradingClient.

    ``alpaca-py``'s :class:`~alpaca.trading.client.TradingClient` is
    synchronous; all heavy operations are lightweight REST calls that
    complete in < 200 ms and are called only on order events (low frequency).
    For the async execution service, each call runs in the asyncio thread
    (no separate thread pool needed at typical order rates).

    Args:
        api_key:    Alpaca API key.
        secret_key: Alpaca secret key.
        base_url:   Unused - kept for interface compatibility; alpaca-py
                    derives the endpoint from the *paper* flag.
        paper:      ``True`` for paper-trading, ``False`` for live.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = "",
        paper: bool = True,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._client: TradingClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Instantiate the TradingClient and verify connectivity."""
        self._client = TradingClient(
            api_key=self._api_key,
            secret_key=self._secret_key,
            paper=self._paper,
        )
        raw = self._client.get_account()
        account: TradeAccount = (
            raw if isinstance(raw, TradeAccount) else TradeAccount.model_validate(raw)
        )
        logger.info(
            "AlpacaBroker connected",
            paper=self._paper,
            account_id=str(account.id),
            equity=str(account.equity),
        )

    async def disconnect(self) -> None:
        """Release the TradingClient (no-op for sync client)."""
        self._client = None
        logger.info("AlpacaBroker disconnected")

    # ── Broker ABC interface ────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """Current connection state."""
        return self._client is not None

    async def place_order(self, order: ApprovedOrder) -> ExecutedOrder | None:
        """Place an equity order via Alpaca from an approved order.

        Extracts symbol, quantity, side, and price from the
        :class:`~core.models.order.ApprovedOrder` and submits to Alpaca.
        Returns ``None`` because live fills are confirmed asynchronously.

        Args:
            order: Risk-approved order.

        Returns:
            ``None`` — fill confirmed asynchronously via Alpaca webhooks.

        Raises:
            BrokerConnectionError: If not connected.
        """
        if not self.is_connected:
            raise BrokerConnectionError("AlpacaBroker not connected. Call connect() first.")
        candidate = order.candidate
        side = "buy" if candidate.direction.value == "long" else "sell"
        resp = await self._submit_raw_order(
            symbol=candidate.symbol,
            qty=float(order.adjusted_size),
            side=side,
            order_type="limit",
            limit_price=float(candidate.entry),
            stop_price=float(candidate.stop_loss),
        )
        logger.info(
            "Alpaca order placed",
            order_id=candidate.order_id,
            alpaca_id=resp.get("id"),
        )
        return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by its Alpaca order UUID.

        Args:
            order_id: Alpaca-assigned order UUID string.

        Returns:
            ``True`` if cancel succeeded.
        """
        client = self._ensure_client()
        client.cancel_order_by_id(UUID(order_id))
        logger.info("Order cancelled", order_id=order_id)
        return True

    # ── Venue-specific operations ────────────────────────────────────────────

    async def _submit_raw_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "limit",
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        """Submit a raw order to Alpaca with venue-specific parameters.

        Args:
            symbol:      Ticker symbol (e.g. ``"AAPL"``).
            qty:         Number of shares (fractional supported by Alpaca).
            side:        ``"buy"`` or ``"sell"``.
            order_type:  ``"market"`` or ``"limit"``.
            limit_price: Required when *order_type* is ``"limit"``.
            stop_price:  Ignored for simple limit/market (use OCO for stops).

        Returns:
            Alpaca order response serialised to a plain dict[str, Any].
        """
        client = self._ensure_client()
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        req: MarketOrderRequest | LimitOrderRequest
        if order_type == "market":
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.GTC,
            )
        else:
            if limit_price is None:
                raise ValueError("limit_price is required for limit orders")
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.GTC,
                limit_price=Decimal(str(limit_price)),
            )

        raw = client.submit_order(order_data=req)
        alpaca_order: Order = raw if isinstance(raw, Order) else Order.model_validate(raw)
        return {
            "id": str(alpaca_order.id),
            "symbol": alpaca_order.symbol,
            "qty": str(alpaca_order.qty),
            "side": str(alpaca_order.side),
            "type": str(alpaca_order.order_type),
            "status": str(alpaca_order.status),
            "limit_price": (str(alpaca_order.limit_price) if alpaca_order.limit_price else None),
        }

    # ── Account / position queries ────────────────────────────────────────────

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        """Retrieve the current open position for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Position dict[str, Any] or ``None`` if no open position exists.
        """
        client = self._ensure_client()
        try:
            raw = client.get_open_position(symbol)
            if not isinstance(raw, Position):
                return None
            pos: Position = raw
            return {
                "symbol": pos.symbol,
                "qty": str(pos.qty),
                "avg_entry_price": str(pos.avg_entry_price),
                "market_value": str(pos.market_value),
                "unrealized_pl": str(pos.unrealized_pl),
                "side": str(pos.side),
            }
        except Exception:
            return None

    async def get_account(self) -> dict[str, Any]:
        """Retrieve the Alpaca account details.

        Returns:
            Account information dict[str, Any].
        """
        client = self._ensure_client()
        raw = client.get_account()
        account: TradeAccount = (
            raw if isinstance(raw, TradeAccount) else TradeAccount.model_validate(raw)
        )
        return {
            "id": str(account.id),
            "equity": str(account.equity),
            "cash": str(account.cash),
            "portfolio_value": str(account.portfolio_value),
            "buying_power": str(account.buying_power),
            "status": str(account.status),
        }

    async def sync_positions(self) -> dict[str, dict[str, Any]]:
        """Fetch all open positions and index them by symbol.

        Returns:
            Mapping of ``{symbol: position_dict}`` for all open positions.
        """
        client = self._ensure_client()
        raw_list = client.get_all_positions()
        positions: list[Position] = [
            p if isinstance(p, Position) else Position.model_validate(p) for p in raw_list
        ]
        return {
            p.symbol: {
                "symbol": p.symbol,
                "qty": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "market_value": str(p.market_value),
                "unrealized_pl": str(p.unrealized_pl),
                "side": str(p.side),
            }
            for p in positions
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_client(self) -> TradingClient:
        """Return the active TradingClient or raise if not connected.

        Returns:
            Active :class:`~alpaca.trading.client.TradingClient`.

        Raises:
            BrokerConnectionError: If :meth:`connect` has not been called.
        """
        if self._client is None:
            raise BrokerConnectionError("AlpacaBroker not connected. Call connect() first.")
        return self._client
