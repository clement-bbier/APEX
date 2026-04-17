"""APEX Trading System - S10 Monitor Service."""

from __future__ import annotations

import asyncio
from typing import Any

from core.base_service import BaseService
from core.config import get_settings
from core.logger import get_logger
from core.topics import Topics
from services.s10_monitor.alert_engine import AlertEngine
from services.s10_monitor.dashboard import DashboardServer
from services.s10_monitor.health_checker import HealthChecker
from services.s10_monitor.pnl_tracker import PnLTracker

logger = get_logger("s10_monitor")

REDIS_RISK_SYSTEM_STATE_LATEST_KEY = "risk:system:state_change:latest"
REDIS_RISK_SYSTEM_STATE_LATEST_TTL_SECONDS = 300


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
        self._last_risk_system_state: dict[str, Any] | None = None

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Route incoming ZMQ messages to appropriate handlers.

        Args:
            topic: ZMQ topic string.
            data: Deserialized message payload.
        """
        _health_prefix = f"{Topics.SERVICE_HEALTH}."
        if topic.startswith(_health_prefix):
            service_id = topic[len(_health_prefix) :]
            ts = data.get("timestamp_ms", 0)
            self._health.record_heartbeat(service_id, ts)

        elif topic == Topics.ORDER_FILLED:
            self._order_count += 1
            logger.info("Order filled", order_id=data.get("order_id"), symbol=data.get("symbol"))

        elif topic == Topics.ORDER_CANDIDATE:
            self._signal_count += 1

        elif topic == Topics.REGIME_UPDATE:
            await self.state.set("regime:current", data, ttl=120)

        elif topic == Topics.RISK_SYSTEM_STATE_CHANGE:
            await self._handle_risk_system_state_change(data)

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

    async def _handle_risk_system_state_change(self, data: dict[str, Any]) -> None:
        """Persist + alert on SystemRiskState transitions (ADR-0006 observability).

        Listening to :attr:`Topics.RISK_SYSTEM_STATE_CHANGE` closes the Phase 5.1
        dashboard-observability gap identified by STRATEGIC_AUDIT_2026-04-17.

        Args:
            data: Deserialized :class:`SystemRiskStateChange` envelope.
        """
        self._last_risk_system_state = data
        try:
            await self.state.set(
                REDIS_RISK_SYSTEM_STATE_LATEST_KEY,
                data,
                ttl=REDIS_RISK_SYSTEM_STATE_LATEST_TTL_SECONDS,
            )
        except Exception as exc:
            logger.error(
                "risk_state_change_persist_failed",
                error=str(exc),
                exc_info=exc,
            )

        new_state = str(data.get("new_state", "")).lower()
        previous_state = str(data.get("previous_state", "")).lower()
        cause = str(data.get("cause", "unknown"))
        logger.warning(
            "risk_system_state_change_observed",
            previous_state=previous_state,
            new_state=new_state,
            cause=cause,
        )
        if new_state and new_state != "healthy":
            self._alert.alert(
                "CRITICAL",
                f"Risk system state {previous_state!s} -> {new_state!s} ({cause})",
            )


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
