"""Orchestrator for APEX Trading System.

Controls ordered startup and graceful shutdown of all services.
Implements a health gate between service starts.

Startup order rationale
-----------------------
The XSUB/XPUB broker (``core.zmq_broker``) is launched **first** as an
in-process asyncio task — it is the only thing that BINDs ZMQ ports, and
every service must be able to CONNECT to it before it boots.

S01 then comes first among the application services because it produces
ticks the rest of the chain consumes.

S10 must come last because it subscribes to the firehose of every topic
(``""``) and is the most invasive observer. Launching it last ensures
it has something useful to observe right after start.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, cast

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Make ``core`` and ``services`` importable when launched directly
# (``python supervisor/orchestrator.py``).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redis import asyncio as aioredis

from core.config import get_settings
from core.logger import get_logger
from core.state import StateStore
from core.zmq_broker import BROKER_SERVICE_ID, ZmqBroker

logger = get_logger("supervisor.orchestrator")

# Startup order — broker first, S01 next (data source), S10 last (firehose).
STARTUP_ORDER: list[str] = [
    "redis_check",
    "zmq_broker",
    "s01_data_ingestion",
    "s07_quant_analytics",
    "s08_macro_intelligence",
    "s02_signal_engine",
    "s03_regime_detector",
    "s04_fusion_engine",
    "s05_risk_manager",
    "s06_execution",
    "s09_feedback_loop",
    "s10_monitor",
]


class Orchestrator:
    """Manages ordered startup and shutdown of all APEX services.

    Startup sequence: Redis → Broker → S01 → S07 → S08 → S02 → S03 → S04 → S05 → S06 → S09 → S10
    Health gate: each service must be healthy before the next starts.
    Shutdown: reverse order.
    """

    def __init__(self) -> None:
        """Initialize orchestrator."""
        self._settings = get_settings()
        self._state = StateStore("orchestrator")
        self._started: list[str] = []
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._broker: ZmqBroker | None = None
        # Hold strong references to background tasks so they are not
        # garbage-collected (RUF006).
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def startup(self) -> None:
        """Start all services in dependency order.

        Raises:
            RuntimeError: If a critical service fails to start.
        """
        logger.info("Starting APEX Trading System")
        await self._state.connect()

        repo_root = str(Path(__file__).resolve().parent.parent)

        for service_id in STARTUP_ORDER:
            if service_id == "redis_check":
                ok = await self.check_redis()
                if not ok:
                    raise RuntimeError("Redis is not available - cannot start")
                logger.info("Redis check passed")
                continue

            if service_id == "zmq_broker":
                if not await self.check_zmq_ports_free():
                    raise RuntimeError(
                        f"ZMQ broker ports already in use "
                        f"(pub={self._settings.zmq_pub_port}, "
                        f"sub={self._settings.zmq_sub_port})"
                    )
                self._broker = ZmqBroker()
                await self._broker.start()
                if not await self.health_gate(BROKER_SERVICE_ID, timeout_s=10.0):
                    raise RuntimeError("ZMQ broker failed health gate")
                self._started.append(BROKER_SERVICE_ID)
                logger.info("zmq_broker_started_and_healthy")
                continue

            logger.info("Starting service", service=service_id)

            python_exe = sys.executable
            cmd = [python_exe, "-m", f"services.{service_id}.service"]

            # Force PYTHONPATH so child interpreters can ``import core`` and
            # ``import services`` regardless of how the orchestrator itself
            # was invoked. PYTHONUNBUFFERED ensures we see tracebacks live.
            child_env = dict(os.environ)
            existing_pp = child_env.get("PYTHONPATH", "")
            child_env["PYTHONPATH"] = (
                repo_root + os.pathsep + existing_pp if existing_pp else repo_root
            )
            child_env.setdefault("PYTHONUNBUFFERED", "1")

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=repo_root,
                    env=child_env,
                )
            except Exception as exc:
                logger.error(
                    "service_spawn_failed",
                    service=service_id,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                continue

            self._processes[service_id] = process
            stream_task = asyncio.create_task(self._stream_child_output(process, service_id))
            self._bg_tasks.add(stream_task)
            stream_task.add_done_callback(self._bg_tasks.discard)

            healthy = await self.health_gate(service_id, timeout_s=30.0)
            if healthy:
                self._started.append(service_id)
                logger.info("Service started and healthy", service=service_id)
            else:
                logger.warning(
                    "Service health gate timed out",
                    service=service_id,
                    pid=process.pid,
                )

        logger.info("Startup complete", services_started=len(self._started))

    @staticmethod
    async def _stream_child_output(proc: asyncio.subprocess.Process, name: str) -> None:
        """Forward every line of a child service's stdout/stderr to the orchestrator log."""
        if proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="ignore").rstrip()
                logger.info("child_output", service=name, line=decoded)
        except Exception as exc:
            logger.debug("child_output_stream_error", service=name, error=str(exc))

    async def shutdown(self) -> None:
        """Shutdown services in reverse startup order then stop the broker."""
        logger.info("Shutting down APEX Trading System")
        for service_id in reversed(self._started):
            if service_id == BROKER_SERVICE_ID:
                continue  # broker stops below, after the children
            logger.info("Stopping service", service=service_id)
            process = self._processes.get(service_id)
            if process:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

        # Cancel any remaining stdout pumps so they don't keep the loop alive.
        for task in list(self._bg_tasks):
            task.cancel()
        for task in list(self._bg_tasks):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("bg_task_shutdown_error", error=str(exc))
        self._bg_tasks.clear()

        if self._broker is not None:
            try:
                await self._broker.stop()
            except Exception as exc:
                logger.warning("broker_stop_failed", error=str(exc))
            self._broker = None

        self._started.clear()
        self._processes.clear()
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
            r: Any = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._settings.redis_url, decode_responses=True
            )
            await cast(Awaitable[bool], r.ping())
            await cast(Awaitable[None], r.aclose())
            return True
        except Exception as exc:
            logger.error("Redis check failed", error=str(exc))
            return False

    async def check_zmq_ports_free(self) -> bool:
        """Verify both broker ports are free before launching the broker.

        Probes XSUB (``zmq_pub_port``) and XPUB (``zmq_sub_port``) with
        ephemeral TCP listeners. This avoids racing the broker for the
        canonical endpoint and survives Windows' lingering TIME_WAIT
        better than a real ``zmq.PUB.bind``.

        Returns:
            ``True`` if both ports are currently free on ``127.0.0.1``.
        """
        import socket as _socket

        for port in (self._settings.zmq_pub_port, self._settings.zmq_sub_port):
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            try:
                sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                logger.error("zmq_port_in_use", port=port, error=str(exc))
                return False
            finally:
                sock.close()
        return True


if __name__ == "__main__":

    async def main() -> None:
        orchestrator = Orchestrator()
        try:
            await orchestrator.startup()
            while orchestrator._started:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down...")
            await orchestrator.shutdown()
        except Exception as exc:
            logger.error(
                "orchestrator_fatal",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            await orchestrator.shutdown()
            sys.exit(1)

    try:
        asyncio.run(main())
    except Exception:
        sys.stderr.write(
            "[orchestrator] Fatal error during bootstrap:\n" + traceback.format_exc() + "\n"
        )
        sys.exit(1)
