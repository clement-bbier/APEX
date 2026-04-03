"""APEX Trading System - S10 Monitor Service."""

from __future__ import annotations

import asyncio
from typing import Any

from core.base_service import BaseService
from core.config import get_settings
from core.logger import get_logger
from services.s10_monitor.alert_engine import AlertEngine
from services.s10_monitor.dashboard import DashboardServer
from services.s10_monitor.health_checker import HealthChecker
from services.s10_monitor.pnl_tracker import PnLTracker

logger = get_logger("s10_monitor")


class MonitorService(BaseService):
    """S10 Monitor Service.

    Subscribes to ALL ZMQ topics. Passive observer that aggregates metrics,
    tracks service health, monitors PnL, and serves the real-time dashboard.
    Never sends orders or modifies state beyond metrics.
    """

    def __init__(self) -> None:
        super().__init__("s10_monitor")
        self._health = HealthChecker()
        self._pnl = PnLTracker()
        self._alert = AlertEngine(get_settings())
        self._dashboard: DashboardServer | None = None
        self._signal_count = 0
        self._order_count = 0

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Route incoming ZMQ messages to appropriate handlers.

        Args:
            topic: ZMQ topic string.
            data: Deserialized message payload.
        """
        if topic.startswith("service.health."):
            service_id = topic[len("service.health.") :]
            ts = data.get("timestamp_ms", 0)
            self._health.record_heartbeat(service_id, ts)

        elif topic == "order.filled":
            self._order_count += 1
            logger.info("Order filled", order_id=data.get("order_id"), symbol=data.get("symbol"))

        elif topic == "order.candidate":
            self._signal_count += 1

        elif topic == "regime.update":
            await self.state.set("regime:current", data, ttl=120)

        elif topic.startswith("tick."):
            pass  # High-volume: only log anomalies

    async def run(self) -> None:
        """Start monitor loops: ZMQ subscriber + dashboard + periodic checks."""
        settings = get_settings()

        # Initialize ZMQ subscriber to all topics
        self.bus.init_subscriber([""])  # empty prefix = subscribe to everything

        # Start dashboard server
        self._dashboard = DashboardServer(
            self.state,
            host=settings.dashboard_host,
            port=settings.dashboard_port,
        )

        await asyncio.gather(
            self._subscribe_loop(),
            self._periodic_loop(),
            self._dashboard.start(),
            return_exceptions=True,
        )

    async def _subscribe_loop(self) -> None:
        """Continuous ZMQ message receive loop."""
        while self._running:
            try:
                topic, data = await self.bus.receive()
                await self.on_message(topic, data)
            except Exception as exc:
                logger.error("Monitor receive error", error=str(exc))
                await asyncio.sleep(1)

    async def _periodic_loop(self) -> None:
        """Periodic health checks and alerts every 15 seconds."""
        while self._running:
            try:
                dead = self._health.get_dead_services()
                for sid in dead:
                    self._alert.alert("CRITICAL", f"Service {sid} is unresponsive")

                daily_pnl = await self._pnl.get_daily_pnl(self.state)
                settings = get_settings()
                initial_capital = float(settings.initial_capital)

                pnl_pct = float(daily_pnl) / initial_capital * 100 if initial_capital > 0 else 0
                if pnl_pct <= -settings.max_daily_drawdown_pct:
                    self._alert.alert(
                        "CRITICAL",
                        f"Daily drawdown {pnl_pct:.2f}% exceeds limit "
                        f"{settings.max_daily_drawdown_pct}%",
                    )
                elif pnl_pct <= -settings.max_daily_drawdown_pct * 0.67:
                    self._alert.alert(
                        "WARNING",
                        f"Daily drawdown {pnl_pct:.2f}% approaching limit",
                    )

                await self._alert.flush_alerts()

            except Exception as exc:
                logger.error("Periodic check error", error=str(exc))

            await asyncio.sleep(15)
