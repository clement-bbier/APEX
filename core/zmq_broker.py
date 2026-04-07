"""APEX ZMQ XSUB/XPUB broker.

The APEX bus is a single, broker-mediated PUB/SUB topology:

* Every APEX service that wants to **publish** connects its PUB socket to
  the broker's XSUB facing port (``zmq_pub_port``, default 5555).
* Every APEX service that wants to **subscribe** connects its SUB socket
  to the broker's XPUB facing port (``zmq_sub_port``, default 5556).
* The broker is the **only** process that BINDs anything. It runs
  ``zmq.proxy(xsub, xpub)`` which forwards every message it receives on
  XSUB to all subscribers on XPUB.

This is the canonical fan-in/fan-out pattern from the ZeroMQ guide
(`Forwarder` device): it lets *any* number of services publish *and*
subscribe to the same logical bus without races over a single TCP port.
The previous topology (S01 binds, others connect their PUB sockets to
S01) was broken — a PUB socket cannot deliver messages to another PUB
socket, so signals from S02-S10 silently disappeared.

The broker also publishes a heartbeat to Redis under
``service_health:zmq_broker`` so the orchestrator's health gate can wait
for it before launching services.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
import time
import traceback

import zmq

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from core.config import get_settings
from core.logger import get_logger
from core.state import StateStore

logger = get_logger("core.zmq_broker")

#: Service identifier used in heartbeats / health gate.
BROKER_SERVICE_ID = "zmq_broker"


def _run_proxy(
    xsub_endpoint: str,
    xpub_endpoint: str,
    ready_event: threading.Event,
) -> None:
    """Bind XSUB / XPUB sockets and run the blocking proxy in a thread.

    Args:
        xsub_endpoint: Endpoint where publishers will CONNECT (e.g.
            ``tcp://*:5555``). The broker BINDs the XSUB side here.
        xpub_endpoint: Endpoint where subscribers will CONNECT (e.g.
            ``tcp://*:5556``). The broker BINDs the XPUB side here.
        ready_event: Set as soon as both sockets are bound, so the
            asyncio caller can release its ``await`` and report ready.

    Raises:
        zmq.ZMQError: If either bind fails.
    """
    ctx = zmq.Context.instance()
    xsub = ctx.socket(zmq.XSUB)
    xpub = ctx.socket(zmq.XPUB)
    xpub.setsockopt(zmq.XPUB_VERBOSER, 1)
    try:
        xsub.bind(xsub_endpoint)
        xpub.bind(xpub_endpoint)
        logger.info(
            "zmq_broker_bound",
            xsub=xsub_endpoint,
            xpub=xpub_endpoint,
            service=BROKER_SERVICE_ID,
        )
        ready_event.set()
        # Blocking proxy — runs until the context is terminated by the
        # outer asyncio task. Keeping it in a daemon thread lets the
        # asyncio side handle SIGINT / SIGTERM cleanly.
        zmq.proxy(xsub, xpub)
    except zmq.ContextTerminated:
        logger.info("zmq_broker_context_terminated", service=BROKER_SERVICE_ID)
    except Exception as exc:
        logger.error(
            "zmq_broker_proxy_error",
            error=str(exc),
            service=BROKER_SERVICE_ID,
            traceback=traceback.format_exc(),
        )
        raise
    finally:
        try:
            xsub.close(linger=0)
        except Exception as exc:
            logger.debug("xsub_close_error", error=str(exc))
        try:
            xpub.close(linger=0)
        except Exception as exc:
            logger.debug("xpub_close_error", error=str(exc))


class ZmqBroker:
    """Async wrapper around the blocking ``zmq.proxy`` device.

    Lifecycle::

        broker = ZmqBroker()
        await broker.start()        # blocks until both sockets bound
        await broker.run_forever()  # blocks until SIGINT / stop()
        await broker.stop()
    """

    def __init__(self) -> None:
        """Initialise the broker (no sockets opened yet)."""
        self._settings = get_settings()
        self._state = StateStore(BROKER_SERVICE_ID)
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def xsub_endpoint(self) -> str:
        """Endpoint that publishers must CONNECT to (XSUB facing port)."""
        return f"tcp://*:{self._settings.zmq_pub_port}"

    @property
    def xpub_endpoint(self) -> str:
        """Endpoint that subscribers must CONNECT to (XPUB facing port)."""
        return f"tcp://*:{self._settings.zmq_sub_port}"

    async def start(self) -> None:
        """Spawn the proxy thread and wait until both sockets are bound."""
        if self._running:
            return
        self._running = True

        try:
            await self._state.connect()
        except Exception as exc:
            logger.warning(
                "zmq_broker_redis_unavailable",
                error=str(exc),
                hint="broker still starts; heartbeat disabled",
            )

        self._thread = threading.Thread(
            target=_run_proxy,
            args=(self.xsub_endpoint, self.xpub_endpoint, self._ready),
            name="zmq-broker-proxy",
            daemon=True,
        )
        self._thread.start()

        # Wait up to 5 seconds for both binds to succeed.
        loop = asyncio.get_running_loop()
        bound = await loop.run_in_executor(None, self._ready.wait, 5.0)
        if not bound:
            raise RuntimeError(
                f"ZMQ broker failed to bind within 5s "
                f"(xsub={self.xsub_endpoint!r}, xpub={self.xpub_endpoint!r})"
            )

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            "zmq_broker_started",
            xsub=self.xsub_endpoint,
            xpub=self.xpub_endpoint,
        )

    async def run_forever(self) -> None:
        """Block until :meth:`stop` is called or SIGINT is received."""
        try:
            while self._running:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("zmq_broker_run_forever_cancelled")
            raise

    async def stop(self) -> None:
        """Tear down the proxy thread, the heartbeat task, and Redis."""
        if not self._running:
            return
        self._running = False
        logger.info("zmq_broker_stopping")

        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # Terminating the global context unblocks ``zmq.proxy`` inside the
        # daemon thread (it raises ``ContextTerminated``).
        try:
            zmq.Context.instance().term()
        except Exception as exc:
            logger.debug("zmq_context_term_error", error=str(exc))

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        try:
            await self._state.disconnect()
        except Exception as exc:
            logger.debug("zmq_broker_state_disconnect_error", error=str(exc))

        logger.info("zmq_broker_stopped")

    async def _heartbeat_loop(self) -> None:
        """Publish ``service_health:zmq_broker`` to Redis every 5 s."""
        while self._running:
            try:
                status = {
                    "service_id": BROKER_SERVICE_ID,
                    "timestamp_ms": int(time.time() * 1000),
                    "status": "healthy",
                    "xsub": self.xsub_endpoint,
                    "xpub": self.xpub_endpoint,
                }
                await self._state.set(f"service_health:{BROKER_SERVICE_ID}", status, ttl=15)
            except Exception as exc:
                logger.debug("zmq_broker_heartbeat_error", error=str(exc))
            await asyncio.sleep(5)


async def _amain() -> None:
    """Async entry-point used by the ``__main__`` block."""
    broker = ZmqBroker()
    stop_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # Windows: signal handlers not supported on the proactor loop
            # — fall back to KeyboardInterrupt only.
            pass

    await broker.start()
    try:
        await asyncio.wait(
            {asyncio.create_task(stop_event.wait()), asyncio.create_task(broker.run_forever())},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        await broker.stop()


def main() -> None:
    """Synchronous entry-point with hard traceback surfacing."""
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        sys.stderr.write(f"[{BROKER_SERVICE_ID}] interrupted by user\n")
    except Exception:
        sys.stderr.write(f"[{BROKER_SERVICE_ID}] fatal error:\n{traceback.format_exc()}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
