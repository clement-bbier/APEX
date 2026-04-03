"""S06 Execution service for APEX Trading System.

Subscribes to ``order.approved`` messages and routes each order to the
appropriate execution back-end (paper, Alpaca equity, or Binance crypto).
Maintains live position state in Redis and handles order timeouts.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any, Optional

from core.base_service import BaseService
from core.config import TradingMode, get_settings
from core.models.order import ApprovedOrder, ExecutedOrder
from core.models.tick import NormalizedTick, Market
from services.s06_execution.broker_alpaca import AlpacaBroker
from services.s06_execution.broker_binance import BinanceBroker
from services.s06_execution.order_manager import OrderManager
from services.s06_execution.paper_trader import PaperTrader

_APPROVED_TOPIC = "order.approved"
_FILLED_TOPIC = "order.filled"
_TIMEOUT_CHECK_INTERVAL_S: int = 15

# Crypto symbols share a common suffix pattern.
_CRYPTO_SUFFIXES = ("USDT", "BUSD", "BTC", "ETH", "USDC")


def _is_crypto_symbol(symbol: str) -> bool:
    """Return ``True`` if the symbol appears to be a crypto pair.

    Args:
        symbol: Uppercase trading symbol.

    Returns:
        ``True`` for crypto symbols.
    """
    return any(symbol.endswith(s) for s in _CRYPTO_SUFFIXES)


class ExecutionService(BaseService):
    """Routes approved orders to the correct execution back-end.

    Routing logic:

    - ``TradingMode.PAPER`` → :class:`~.paper_trader.PaperTrader`
    - ``TradingMode.LIVE`` + equity → :class:`~.broker_alpaca.AlpacaBroker`
    - ``TradingMode.LIVE`` + crypto → :class:`~.broker_binance.BinanceBroker`

    After a fill the service:

    1. Publishes the :class:`~core.models.order.ExecutedOrder` on
       ``order.filled``.
    2. Writes/updates the position in Redis under ``positions:{symbol}``.

    A background task checks for timed-out submitted orders every 15 seconds
    and cancels them automatically.
    """

    service_id = "s06_execution"

    def __init__(self) -> None:
        """Initialize execution components and ZMQ pub/sub."""
        super().__init__(self.service_id)
        settings = get_settings()

        self._paper = PaperTrader()
        self._order_manager = OrderManager(self.state)

        self._alpaca: Optional[AlpacaBroker] = None
        self._binance: Optional[BinanceBroker] = None

        if settings.trading_mode == TradingMode.LIVE:
            self._alpaca = AlpacaBroker(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                base_url=settings.alpaca_base_url,
                paper=False,
            )
            self._binance = BinanceBroker(
                api_key=settings.binance_api_key,
                secret_key=settings.binance_secret_key,
                base_url=settings.binance_base_url,
                testnet=False,
            )

        self.bus.init_publisher()

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Parse an approved order and dispatch to execution.

        Args:
            topic: ZMQ topic string.
            data:  JSON-decoded message payload.
        """
        try:
            approved = ApprovedOrder.model_validate(data)
            await self._execute(approved)
        except Exception as exc:
            self.logger.error(
                "Error processing approved order",
                topic=topic,
                error=str(exc),
                exc_info=exc,
            )

    async def run(self) -> None:
        """Connect brokers, subscribe to approved-order topic, start timeout loop."""
        self.logger.info("ExecutionService starting", service=self.service_id)
        settings = get_settings()

        if settings.trading_mode == TradingMode.LIVE:
            if self._alpaca is not None:
                await self._alpaca.connect()
            if self._binance is not None:
                await self._binance.connect()

        timeout_task = asyncio.create_task(self._timeout_loop())
        try:
            await self.bus.subscribe([_APPROVED_TOPIC], self.on_message)
        except asyncio.CancelledError:
            self.logger.info("ExecutionService subscribe loop cancelled")
            timeout_task.cancel()
            if settings.trading_mode == TradingMode.LIVE:
                if self._alpaca is not None:
                    await self._alpaca.disconnect()
                if self._binance is not None:
                    await self._binance.disconnect()
            raise

    # ── Execution routing ─────────────────────────────────────────────────────

    async def _execute(self, approved: ApprovedOrder) -> None:
        """Route the approved order to the correct back-end and record the fill.

        Args:
            approved: The risk-approved order to execute.
        """
        settings = get_settings()
        symbol = approved.symbol
        is_crypto = _is_crypto_symbol(symbol)

        broker_order_id = await self._order_manager.submit(approved)

        try:
            executed: Optional[ExecutedOrder] = None

            if settings.trading_mode == TradingMode.PAPER:
                # Build a minimal synthetic tick for liquidity checks.
                synthetic_tick = await self._get_or_build_tick(symbol, approved, is_crypto)
                executed = await self._paper.execute(approved, synthetic_tick)

            elif settings.trading_mode == TradingMode.LIVE:
                if is_crypto and self._binance is not None:
                    await self._live_execute_binance(approved, broker_order_id)
                elif not is_crypto and self._alpaca is not None:
                    await self._live_execute_alpaca(approved, broker_order_id)
                else:
                    raise RuntimeError(
                        f"No live broker available for {'crypto' if is_crypto else 'equity'} "
                        f"symbol {symbol}"
                    )
                return  # Live path handles its own confirmation separately.

            if executed is not None:
                await self._on_filled(executed)

        except Exception as exc:
            await self._order_manager.cancel(
                approved.order_id, reason=str(exc)
            )
            self.logger.error(
                "Execution failed, order cancelled",
                order_id=approved.order_id,
                symbol=symbol,
                error=str(exc),
                exc_info=exc,
            )

    async def _live_execute_alpaca(
        self,
        approved: ApprovedOrder,
        broker_order_id: str,
    ) -> None:
        """Place a live equity order via Alpaca.

        Args:
            approved:        The approved order.
            broker_order_id: Internal broker order ID (for Redis tracking).
        """
        assert self._alpaca is not None  # guarded by caller
        candidate = approved.candidate
        side = "buy" if candidate.direction.value == "long" else "sell"
        resp = await self._alpaca.place_order(
            symbol=candidate.symbol,
            qty=float(approved.adjusted_size),
            side=side,
            order_type="limit",
            limit_price=float(candidate.entry),
            stop_price=float(candidate.stop_loss),
        )
        self.logger.info(
            "Alpaca order placed",
            order_id=candidate.order_id,
            alpaca_id=resp.get("id"),
        )

    async def _live_execute_binance(
        self,
        approved: ApprovedOrder,
        broker_order_id: str,
    ) -> None:
        """Place a live crypto order via Binance.

        Args:
            approved:        The approved order.
            broker_order_id: Internal broker order ID (for Redis tracking).
        """
        assert self._binance is not None  # guarded by caller
        candidate = approved.candidate
        side = "BUY" if candidate.direction.value == "long" else "SELL"
        resp = await self._binance.place_order(
            symbol=candidate.symbol,
            side=side,
            order_type="LIMIT",
            quantity=float(approved.adjusted_size),
            price=float(candidate.entry),
        )
        self.logger.info(
            "Binance order placed",
            order_id=candidate.order_id,
            binance_id=resp.get("orderId"),
        )

    # ── Post-fill actions ─────────────────────────────────────────────────────

    async def _on_filled(self, executed: ExecutedOrder) -> None:
        """Persist fill data and publish the filled event.

        Args:
            executed: The execution record to persist and publish.
        """
        symbol = executed.symbol
        order_id = executed.order_id

        await self._order_manager.confirm(
            order_id, executed.fill_price, executed.fill_size
        )

        # Upsert position in Redis.
        position = {
            "symbol": symbol,
            "direction": executed.approved_order.candidate.direction.value,
            "entry": str(executed.fill_price),
            "size": str(executed.fill_size),
            "stop_loss": str(executed.approved_order.candidate.stop_loss),
            "target_scalp": str(executed.approved_order.candidate.target_scalp),
            "target_swing": str(executed.approved_order.candidate.target_swing),
            "opened_at_ms": executed.fill_timestamp_ms,
            "is_paper": executed.is_paper,
        }
        await asyncio.gather(
            self.state.set(f"positions:{symbol}", position),
            self.bus.publish(_FILLED_TOPIC, executed.model_dump(mode="json")),
        )

        self.logger.info(
            "Order filled",
            order_id=order_id,
            symbol=symbol,
            fill_price=str(executed.fill_price),
            fill_size=str(executed.fill_size),
            is_paper=executed.is_paper,
        )

    # ── Timeout handling ──────────────────────────────────────────────────────

    async def _timeout_loop(self) -> None:
        """Periodically cancel orders that have not filled within the timeout."""
        while self._running:
            try:
                await asyncio.sleep(_TIMEOUT_CHECK_INTERVAL_S)
                timed_out = await self._order_manager.timeout_check()
                for order_id in timed_out:
                    await self._order_manager.cancel(order_id, reason="submission timeout")
                    self.logger.warning(
                        "Order cancelled due to timeout",
                        order_id=order_id,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(
                    "Timeout loop error",
                    error=str(exc),
                    exc_info=exc,
                )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_or_build_tick(
        self,
        symbol: str,
        approved: ApprovedOrder,
        is_crypto: bool,
    ) -> NormalizedTick:
        """Return the latest cached tick or synthesise a minimal one.

        Args:
            symbol:    Trading symbol.
            approved:  Approved order (used to derive entry price / volume).
            is_crypto: ``True`` for crypto symbols.

        Returns:
            A :class:`~core.models.tick.NormalizedTick` suitable for paper execution.
        """
        raw = await self.state.get(f"tick:{symbol}")
        if raw is not None:
            try:
                return NormalizedTick.model_validate(raw)
            except Exception:
                pass

        # Synthesise a tick with generous volume so liquidity checks pass.
        entry = approved.candidate.entry
        size = approved.adjusted_size
        return NormalizedTick(
            symbol=symbol,
            market=Market.CRYPTO if is_crypto else Market.EQUITY,
            timestamp_ms=int(time.time() * 1000),
            price=entry,
            volume=size * Decimal("100"),
            spread_bps=Decimal("5"),
        )
