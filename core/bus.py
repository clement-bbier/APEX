"""ZeroMQ message bus wrapper for APEX Trading System.

Provides async PUB/SUB and PUSH/PULL patterns using pyzmq.
All messages are serialized as JSON.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable, Optional

import zmq
import zmq.asyncio

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("core.bus")


class MessageBus:
    """ZeroMQ message bus with PUB/SUB and PUSH/PULL patterns.

    All sockets are non-blocking (asyncio-compatible via zmq.asyncio).
    JSON is used for serialization of all payloads.
    """

    def __init__(self, service_id: str) -> None:
        """Initialize the message bus for a service.

        Args:
            service_id: Unique identifier for the owning service (used in logs).
        """
        self._service_id = service_id
        self._settings = get_settings()
        self._context: zmq.asyncio.Context = zmq.asyncio.Context.instance()

        self._pub_socket: Optional[zmq.asyncio.Socket] = None
        self._sub_socket: Optional[zmq.asyncio.Socket] = None
        self._push_socket: Optional[zmq.asyncio.Socket] = None
        self._pull_socket: Optional[zmq.asyncio.Socket] = None

    # ── PUB/SUB ───────────────────────────────────────────────────────────────

    def init_publisher(self) -> None:
        """Initialize and bind the PUB socket."""
        if self._pub_socket is not None:
            return
        self._pub_socket = self._context.socket(zmq.PUB)
        addr = f"tcp://*:{self._settings.zmq_pub_port}"
        self._pub_socket.bind(addr)
        logger.info("ZMQ PUB socket bound", service=self._service_id, addr=addr)

    def init_subscriber(self, topics: list[str]) -> None:
        """Initialize the SUB socket and subscribe to given topics.

        Args:
            topics: List of topic prefixes to subscribe to (empty string = all).
        """
        if self._sub_socket is not None:
            return
        self._sub_socket = self._context.socket(zmq.SUB)
        addr = (
            f"tcp://{self._settings.zmq_host}:{self._settings.zmq_sub_port}"
        )
        self._sub_socket.connect(addr)
        for topic in topics:
            self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        logger.info(
            "ZMQ SUB socket connected",
            service=self._service_id,
            addr=addr,
            topics=topics,
        )

    # ── PUSH/PULL ─────────────────────────────────────────────────────────────

    def init_pusher(self) -> None:
        """Initialize and bind the PUSH socket."""
        if self._push_socket is not None:
            return
        self._push_socket = self._context.socket(zmq.PUSH)
        addr = f"tcp://*:{self._settings.zmq_push_port}"
        self._push_socket.bind(addr)
        logger.info("ZMQ PUSH socket bound", service=self._service_id, addr=addr)

    def init_puller(self) -> None:
        """Initialize the PULL socket and connect."""
        if self._pull_socket is not None:
            return
        self._pull_socket = self._context.socket(zmq.PULL)
        addr = (
            f"tcp://{self._settings.zmq_host}:{self._settings.zmq_pull_port}"
        )
        self._pull_socket.connect(addr)
        logger.info("ZMQ PULL socket connected", service=self._service_id, addr=addr)

    # ── Send ──────────────────────────────────────────────────────────────────

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        """Publish a message on the PUB socket.

        Args:
            topic: ZMQ topic string, e.g. 'tick.crypto.BTCUSDT'.
            data: Dictionary payload to serialize as JSON.
        """
        if self._pub_socket is None:
            raise RuntimeError(
                f"[{self._service_id}] PUB socket not initialized. "
                "Call init_publisher() first."
            )
        payload = json.dumps(data, default=str)
        await self._pub_socket.send_multipart(
            [topic.encode(), payload.encode()]
        )

    async def push(self, data: dict[str, Any]) -> None:
        """Push a message on the PUSH socket.

        Args:
            data: Dictionary payload to serialize as JSON.
        """
        if self._push_socket is None:
            raise RuntimeError(
                f"[{self._service_id}] PUSH socket not initialized. "
                "Call init_pusher() first."
            )
        payload = json.dumps(data, default=str)
        await self._push_socket.send_string(payload)

    # ── Receive ───────────────────────────────────────────────────────────────

    async def receive(self) -> tuple[str, dict[str, Any]]:
        """Receive a single message from the SUB socket.

        Returns:
            Tuple of (topic, data_dict).

        Raises:
            RuntimeError: If SUB socket is not initialized.
        """
        if self._sub_socket is None:
            raise RuntimeError(
                f"[{self._service_id}] SUB socket not initialized. "
                "Call init_subscriber() first."
            )
        parts = await self._sub_socket.recv_multipart()
        topic = parts[0].decode()
        data = json.loads(parts[1].decode())
        return topic, data

    async def pull(self) -> dict[str, Any]:
        """Pull a single message from the PULL socket.

        Returns:
            Deserialized data dictionary.

        Raises:
            RuntimeError: If PULL socket is not initialized.
        """
        if self._pull_socket is None:
            raise RuntimeError(
                f"[{self._service_id}] PULL socket not initialized. "
                "Call init_puller() first."
            )
        raw = await self._pull_socket.recv_string()
        return json.loads(raw)

    async def subscribe(
        self, topics: list[str], handler: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        """Run an infinite loop receiving messages and dispatching to handler.

        Args:
            topics: Topics to subscribe to.
            handler: Async or sync callable(topic, data).
        """
        self.init_subscriber(topics)
        while True:
            topic, data = await self.receive()
            try:
                result = handler(topic, data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "Error in message handler",
                    service=self._service_id,
                    topic=topic,
                    error=str(exc),
                    exc_info=exc,
                )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close all open sockets."""
        for name, sock in [
            ("pub", self._pub_socket),
            ("sub", self._sub_socket),
            ("push", self._push_socket),
            ("pull", self._pull_socket),
        ]:
            if sock is not None:
                try:
                    sock.close(linger=0)
                except Exception as exc:
                    logger.warning(
                        "Error closing socket",
                        service=self._service_id,
                        socket=name,
                        error=str(exc),
                    )
        logger.info("ZMQ sockets closed", service=self._service_id)
