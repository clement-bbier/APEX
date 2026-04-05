from __future__ import annotations

"""Orchestrator for APEX Trading System.

Controls ordered startup and graceful shutdown of all services.
Implements health gate between service starts.
"""


import asyncio
from collections.abc import Awaitable
from typing import Any, cast

from redis import asyncio as aioredis

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import get_settings
from core.logger import get_logger
from core.state import StateStore

logger = get_logger("supervisor.orchestrator")

STARTUP_ORDER = [
    "redis_check",
    "zmq_check",
    "s10_monitor",
    "s01_data_ingestion",
    "s07_quant_analytics",
    "s08_macro_intelligence",
    "s02_signal_engine",
    "s03_regime_detector",
    "s04_fusion_engine",
    "s05_risk_manager",
    "s06_execution",
    "s09_feedback_loop",
]


class Orchestrator:
    """Manages ordered startup and shutdown of all APEX services.

    Startup sequence: Redis → ZMQ → S10 → S01 → S07 → S08 → S02 → S03 → S04 → S05 → S06 → S09
    Health gate: each service must be healthy before the next starts.
    Shutdown: reverse order.
    """

    def __init__(self) -> None:
        """Initialize orchestrator."""
        self._settings = get_settings()
        self._state = StateStore("orchestrator")
        self._started: list[str] = []

    async def startup(self) -> None:
        """Start all services in dependency order.

        Raises:
            RuntimeError: If a critical service fails to start.
        """
        logger.info("Starting APEX Trading System")
        await self._state.connect()

        for service_id in STARTUP_ORDER:
            if service_id == "redis_check":
                ok = await self.check_redis()
                if not ok:
                    raise RuntimeError("Redis is not available - cannot start")
                logger.info("Redis check passed")
                continue

            if service_id == "zmq_check":
                ok = await self.check_zmq()
                if not ok:
                    logger.warning("ZMQ check failed - continuing anyway")
                else:
                    logger.info("ZMQ check passed")
                continue

            logger.info("Starting service", service=service_id)
            # Phase 2: actually spawn subprocess here
            # For now, log the intent
            healthy = await self.health_gate(service_id, timeout_s=30.0)
            if healthy:
                self._started.append(service_id)
                logger.info("Service started and healthy", service=service_id)
            else:
                logger.warning("Service health gate timed out", service=service_id)

        logger.info("Startup complete", services_started=len(self._started))

    async def shutdown(self) -> None:
        """Shutdown services in reverse startup order."""
        logger.info("Shutting down APEX Trading System")
        for service_id in reversed(self._started):
            logger.info("Stopping service", service=service_id)
            # Phase 2: send SIGTERM to subprocess
        self._started.clear()
        await self._state.disconnect()
        logger.info("Shutdown complete")

    async def health_gate(self, service_id: str, timeout_s: float = 30.0) -> bool:
        """Wait for a service to report healthy.

        Polls Redis every second up to timeout_s.

        Args:
            service_id: Service to wait for.
            timeout_s: Maximum wait time in seconds.

        Returns:
            True if service reported healthy within timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                health = await self._state.get(f"service_health:{service_id}")
                if health and health.get("status") == "healthy":
                    return True
            except Exception as exc:
                logger.debug("health_check_redis_failed", error=str(exc))
            await asyncio.sleep(1.0)
        return False

    async def check_redis(self) -> bool:
        """Verify Redis is reachable.

        Returns:
            True if Redis responds to ping.
        """
        try:
            r: Any = aioredis.from_url(self._settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
            await cast(Awaitable[bool], r.ping())
            await cast(Awaitable[None], r.aclose())
            return True
        except Exception as exc:
            logger.error("Redis check failed", error=str(exc))
            return False

    async def check_zmq(self) -> bool:
        """Verify ZMQ port is available.

        Returns:
            True if port binding succeeds.
        """
        try:
            import zmq

            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.PUB)
            sock.bind(f"tcp://*:{self._settings.zmq_pub_port}")
            sock.close(linger=0)
            return True
        except Exception as exc:
            logger.error("ZMQ check failed", error=str(exc))
            return False

if __name__ == '__main__':
    import sys
    from pathlib import Path
    # Add root dir to sys.path so core and services are accessible
    sys.path.insert(0, str(Path(__file__).parent.parent))

    async def main() -> None:
        orchestrator = Orchestrator()
        try:
            await orchestrator.startup()
            # Keep running until shut down
            while orchestrator._started:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            logger.info('Interrupted by user, shutting down...')
            await orchestrator.shutdown()
        except Exception as exc:
            logger.error(f'Fatal error: {exc}')
            await orchestrator.shutdown()
            sys.exit(1)

    asyncio.run(main())

