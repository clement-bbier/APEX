"""Watchdog service for APEX Trading System.

Pings each service every 5 seconds. Auto-restarts if no response.
Critical alert and suspend if 5 restarts in 10 minutes.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import ClassVar

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("supervisor.watchdog")

PING_INTERVAL_S = 5
MAX_FAILURES_BEFORE_RESTART = 3
MAX_RESTARTS_IN_WINDOW = 5
RESTART_WINDOW_S = 600  # 10 minutes
HEALTH_KEY_PREFIX = "service.health."
HEALTH_TIMEOUT_S = 15


class Watchdog:
    """Monitors all services and triggers restart on failure.

    Tracks consecutive failures per service. After MAX_FAILURES_BEFORE_RESTART
    consecutive pings fail, attempts restart. After MAX_RESTARTS_IN_WINDOW
    restarts in RESTART_WINDOW_S, suspends execution.
    """

    SERVICE_ORDER: ClassVar[list[str]] = [
        "s01_data_ingestion",
        "s02_signal_engine",
        "s03_regime_detector",
        "s04_fusion_engine",
        "s05_risk_manager",
        "s06_execution",
        "s07_quant_analytics",
        "s08_macro_intelligence",
        "s09_feedback_loop",
        "s10_monitor",
    ]

    def __init__(self) -> None:
        """Initialize watchdog state."""
        self._failure_count: dict[str, int] = defaultdict(int)
        self._restart_times: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=MAX_RESTARTS_IN_WINDOW)
        )
        self._suspended: bool = False

    async def ping(self, service_id: str, state: StateStore) -> bool:
        """Check if a service has reported health recently.

        Args:
            service_id: Service to check.
            state: Active StateStore for Redis reads.

        Returns:
            True if service is alive (heartbeat within HEALTH_TIMEOUT_S).
        """
        try:
            health = await state.get(f"service_health:{service_id}")
            if health is None:
                return False
            ts = health.get("timestamp_ms", 0) / 1000
            return (time.time() - ts) < HEALTH_TIMEOUT_S
        except Exception as exc:
            logger.warning("Ping error", service=service_id, error=str(exc))
            return False

    async def watch_loop(self, state: StateStore) -> None:
        """Main watch loop: ping all services every 5 seconds.

        Args:
            state: Active StateStore.
        """
        while True:
            if self._suspended:
                logger.critical("Watchdog suspended - manual intervention required")
                await asyncio.sleep(60)
                continue

            for service_id in self.SERVICE_ORDER:
                alive = await self.ping(service_id, state)
                if alive:
                    self._failure_count[service_id] = 0
                else:
                    self._failure_count[service_id] += 1
                    count = self._failure_count[service_id]
                    logger.warning(
                        "Service not responding",
                        service=service_id,
                        consecutive_failures=count,
                    )
                    if count >= MAX_FAILURES_BEFORE_RESTART:
                        await self.restart_service(service_id, state)
                        self._failure_count[service_id] = 0

            await asyncio.sleep(PING_INTERVAL_S)

    async def restart_service(self, service_id: str, state: StateStore) -> None:
        """Attempt to restart a service.

        Args:
            service_id: Service to restart.
            state: Active StateStore.
        """
        now = time.time()
        self._restart_times[service_id].append(now)

        # Check if too many restarts in window
        recent = [t for t in self._restart_times[service_id] if now - t < RESTART_WINDOW_S]
        if len(recent) >= MAX_RESTARTS_IN_WINDOW:
            logger.critical(
                "Too many restarts - suspending execution",
                service=service_id,
                restart_count=len(recent),
                window_s=RESTART_WINDOW_S,
            )
            await state.set(
                "circuit:suspended", {"reason": f"{service_id} restart loop", "at": now}
            )
            self._suspended = True
            return

        logger.warning(
            "Restarting service",
            service=service_id,
            restart_number=len(recent),
        )
        # Phase 2: actual subprocess restart
        # For now, log the restart and update Redis
        await state.set(
            f"watchdog:restart:{service_id}",
            {"timestamp": now, "count": len(recent)},
            ttl=3600,
        )
