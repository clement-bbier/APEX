"""Abstract base service for APEX Trading System.

All services inherit from BaseService which provides:
- ZeroMQ PUB/SUB via MessageBus
- Redis state via StateStore
- Structured logging via structlog
- Health-check heartbeat publishing
- Graceful start/stop lifecycle
- Abstract on_message() to implement per service
"""

from __future__ import annotations

import asyncio
import sys
import time
from abc import ABC, abstractmethod
from typing import Any

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from core.bus import MessageBus
from core.config import get_settings
from core.logger import get_logger
from core.state import StateStore

# ZMQ topic for service health heartbeats
HEALTH_TOPIC_PREFIX = "service.health."


class BaseService(ABC):
    """Abstract base class for all APEX Trading System services.

    Subclasses must implement:
        - on_message(topic, data): Handle an incoming ZMQ message.
        - run(): Define the main service loop (called within start()).

    Lifecycle:
        1. await service.start()   → connects Redis, starts loops
        2. Runs until interrupted
        3. await service.stop()    → graceful shutdown
    """

    def __init__(self, service_id: str) -> None:
        """Initialize the base service.

        Args:
            service_id: Unique human-readable identifier, e.g. 's01_data_ingestion'.
        """
        self.service_id = service_id
        self._settings = get_settings()
        self.logger = get_logger(service_id)
        self.bus = MessageBus(service_id)
        self.state = StateStore(service_id)
        self._running = False
        self._heartbeat_task: asyncio.Task[None] | None = None

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Handle an incoming ZMQ message.

        Args:
            topic: ZMQ topic string.
            data: Deserialized message payload.
        """

    @abstractmethod
    async def run(self) -> None:
        """Main service logic loop.

        Called once after setup is complete (Redis connected, ZMQ initialized).
        Should run until self._running is False.
        """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the service: connect dependencies and run loops.

        Connects Redis, starts heartbeat, then calls run().
        """
        self._running = True
        self.logger.info("Service starting", service=self.service_id)

        try:
            await self.state.connect()
        except Exception as exc:
            self.logger.error(
                "Redis connection failed",
                service=self.service_id,
                error=str(exc),
            )
            raise

        self.bus.init_publisher()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            await self.run()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown: cancel heartbeat, close connections."""
        if not self._running:
            return
        self._running = False
        self.logger.info("Service stopping", service=self.service_id)

        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        try:
            self.bus.close()
        except Exception as exc:
            self.logger.warning("Error closing bus", service=self.service_id, error=str(exc))

        try:
            await self.state.disconnect()
        except Exception as exc:
            self.logger.warning(
                "Error disconnecting state", service=self.service_id, error=str(exc)
            )

        self.logger.info("Service stopped", service=self.service_id)

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Publish a heartbeat to ZMQ and return health status dict.

        Returns:
            Health status dictionary with service_id, timestamp, and status.
        """
        status = {
            "service_id": self.service_id,
            "timestamp_ms": int(time.time() * 1000),
            "status": "healthy" if self._running else "stopped",
        }
        try:
            await self.bus.publish(f"{HEALTH_TOPIC_PREFIX}{self.service_id}", status)
            await self.state.set(f"service_health:{self.service_id}", status, ttl=15)
        except Exception as exc:
            self.logger.warning(
                "Heartbeat publish failed",
                service=self.service_id,
                error=str(exc),
            )
        return status

    async def _heartbeat_loop(self) -> None:
        """Publish heartbeats every 5 seconds while running."""
        while self._running:
            try:
                await self.health_check()
            except Exception as exc:
                self.logger.warning(
                    "Heartbeat error",
                    service=self.service_id,
                    error=str(exc),
                )
            await asyncio.sleep(5)
