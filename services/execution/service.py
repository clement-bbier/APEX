"""S06 Execution service for APEX Trading System.

Subscribes to ``order.approved`` messages and routes each order to the
appropriate execution back-end via :class:`~.broker_factory.BrokerFactory`.
Maintains live position state in Redis and handles order timeouts.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.base_service import BaseService
from core.config import TradingMode, get_settings
from core.models.order import ApprovedOrder, ExecutedOrder
from services.execution.broker_base import Broker
from services.execution.broker_factory import BrokerFactory
from services.execution.order_manager import OrderManager

_APPROVED_TOPIC = "order.approved"
_FILLED_TOPIC = "order.filled"
_TIMEOUT_CHECK_INTERVAL_S: int = 15


class ExecutionService(BaseService):
    """Routes approved orders to the correct execution back-end.

    Routing is delegated to :class:`~.broker_factory.BrokerFactory`:

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

    service_id = "execution"

    def __init__(self) -> None:
        """Initialize execution components and ZMQ pub/sub."""
        super().__init__(self.service_id)
        settings = get_settings()

        self._order_manager = OrderManager(self.state)
        self._broker_factory = BrokerFactory(settings, self.state)

        # Eagerly create live brokers so they're ready for connect_all().
        if settings.trading_mode == TradingMode.LIVE:
            # Trigger lazy creation of live brokers.
            self._broker_factory.for_symbol("AAPL")  # equity → AlpacaBroker
            self._broker_factory.for_symbol("BTCUSDT")  # crypto → BinanceBroker

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
            await self._broker_factory.connect_all()

        timeout_task = asyncio.create_task(self._timeout_loop())
        try:
            await self.bus.subscribe([_APPROVED_TOPIC], self.on_message)
        except asyncio.CancelledError:
            self.logger.info("ExecutionService subscribe loop cancelled")
            timeout_task.cancel()
            if settings.trading_mode == TradingMode.LIVE:
                await self._broker_factory.disconnect_all()
            raise

    # ── Execution routing ─────────────────────────────────────────────────────

    async def _execute(self, approved: ApprovedOrder) -> None:
        """Route the approved order to the correct back-end and record the fill.

        Args:
            approved: The risk-approved order to execute.
        """
        symbol = approved.symbol

        await self._order_manager.submit(approved)

        try:
            broker: Broker = self._broker_factory.for_symbol(symbol)
            executed: ExecutedOrder | None = await broker.place_order(approved)

            if executed is not None:
                await self._on_filled(executed)

        except Exception as exc:
            await self._order_manager.cancel(approved.order_id, reason=str(exc))
            self.logger.error(
                "Execution failed, order cancelled",
                order_id=approved.order_id,
                symbol=symbol,
                error=str(exc),
                exc_info=exc,
            )

    # ── Post-fill actions ─────────────────────────────────────────────────────

    async def _on_filled(self, executed: ExecutedOrder) -> None:
        """Persist fill data and publish the filled event.

        Args:
            executed: The execution record to persist and publish.
        """
        symbol = executed.symbol
        order_id = executed.order_id

        await self._order_manager.confirm(order_id, executed.fill_price, executed.fill_size)

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


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
