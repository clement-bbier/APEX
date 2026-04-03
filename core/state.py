"""Redis async state wrapper for APEX Trading System.

Provides get/set/delete/hget/hset/publish/stream operations with TTL support.
All operations are async using redis[asyncio].
"""

from __future__ import annotations

import importlib
import json
import types
from typing import Any, Awaitable, cast

aioredis: types.ModuleType | None
try:
    aioredis = importlib.import_module("redis.asyncio")
except ModuleNotFoundError:
    aioredis = None

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("core.state")


class StateStore:
    """Async Redis wrapper for shared system state.

    Handles JSON serialization/deserialization transparently.
    All methods are async and safe for concurrent access.
    """

    def __init__(self, service_id: str) -> None:
        """Initialize the state store for a service.

        Args:
            service_id: Owning service identifier (used in logs).
        """
        self._service_id = service_id
        self._settings = get_settings()
        self._redis: Any | None = None

    async def connect(self) -> None:
        """Create the Redis connection pool.

        Must be called before any other operation.
        """
        if aioredis is None:
            raise RuntimeError(
                "The 'redis' package is required. Install it with: pip install redis"
            )
        client = aioredis.from_url(
            self._settings.redis_url,
            max_connections=self._settings.redis_max_connections,
            decode_responses=True,
        )
        self._redis = client
        # Verify connection
        await cast(Awaitable[bool], client.ping())
        logger.info(
            "Redis connected",
            service=self._service_id,
            url=self._settings.redis_url,
        )

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            await cast(Awaitable[None], self._redis.aclose())
            self._redis = None
            logger.info("Redis disconnected", service=self._service_id)

    def _ensure_connected(self) -> Any:
        """Return the Redis client or raise if not connected.

        Returns:
            Active Redis client.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        if self._redis is None:
            raise RuntimeError(
                f"[{self._service_id}] StateStore not connected. Call connect() first."
            )
        return self._redis

    # ── Key/Value ────────────────────────────────────────────────────────────

    async def get(self, key: str) -> Any | None:  # noqa: ANN401
        """Get a JSON-deserialized value by key.

        Args:
            key: Redis key.

        Returns:
            Deserialized Python object or None if not found.
        """
        r = self._ensure_connected()
        raw = await cast(Awaitable[str | None], r.get(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self,
        key: str,
        value: Any,  # noqa: ANN401
        ttl: int | None = None,
    ) -> None:
        """Set a key with JSON-serialized value.

        Args:
            key: Redis key.
            value: Python object to serialize as JSON.
            ttl: Optional TTL in seconds. Defaults to settings.redis_ttl_seconds.
        """
        r = self._ensure_connected()
        effective_ttl = ttl if ttl is not None else self._settings.redis_ttl_seconds
        await cast(
            Awaitable[bool],
            r.set(key, json.dumps(value, default=str), ex=effective_ttl),
        )

    async def delete(self, key: str) -> None:
        """Delete a key from Redis.

        Args:
            key: Redis key to delete.
        """
        r = self._ensure_connected()
        await cast(Awaitable[int], r.delete(key))

    async def exists(self, key: str) -> bool:
        """Check if a key exists.

        Args:
            key: Redis key.

        Returns:
            True if the key exists.
        """
        r = self._ensure_connected()
        return bool(await cast(Awaitable[int], r.exists(key)))

    # ── Hash ──────────────────────────────────────────────────────────────────

    async def hget(self, name: str, field: str) -> Any | None:  # noqa: ANN401
        """Get a field from a Redis hash.

        Args:
            name: Hash key name.
            field: Field within the hash.

        Returns:
            Deserialized value or None.
        """
        r = self._ensure_connected()
        raw = await cast(Awaitable[str | None], r.hget(name, field))
        if raw is None:
            return None
        return json.loads(raw)

    async def hset(self, name: str, field: str, value: Any) -> None:  # noqa: ANN401
        """Set a field in a Redis hash.

        Args:
            name: Hash key name.
            field: Field within the hash.
            value: Python object to serialize as JSON.
        """
        r = self._ensure_connected()
        await cast(Awaitable[int], r.hset(name, field, json.dumps(value, default=str)))

    async def hgetall(self, name: str) -> dict[str, Any]:
        """Get all fields of a Redis hash as a dict.

        Args:
            name: Hash key name.

        Returns:
            Dictionary of field→deserialized value.
        """
        r = self._ensure_connected()
        raw = await cast(Awaitable[dict[str, str]], r.hgetall(name))
        return {k: json.loads(v) for k, v in raw.items()}

    async def hdel(self, name: str, field: str) -> None:
        """Delete a field from a Redis hash.

        Args:
            name: Hash key name.
            field: Field to delete.
        """
        r = self._ensure_connected()
        await cast(Awaitable[int], r.hdel(name, field))

    # ── Pub/Sub ───────────────────────────────────────────────────────────────

    async def publish(self, channel: str, message: Any) -> None:  # noqa: ANN401
        """Publish a message to a Redis Pub/Sub channel.

        Args:
            channel: Channel name.
            message: Python object to serialize as JSON.
        """
        r = self._ensure_connected()
        await cast(Awaitable[int], r.publish(channel, json.dumps(message, default=str)))

    # ── Streams ───────────────────────────────────────────────────────────────

    async def stream_add(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int = 10000,
    ) -> str:
        """Append an entry to a Redis Stream.

        Args:
            stream: Stream key name.
            data: Dictionary of field values (will be JSON-stringified per field).
            max_len: Maximum stream length (approximate).

        Returns:
            The generated stream entry ID.
        """
        r = self._ensure_connected()
        fields: dict[str | bytes, str | bytes | int | float] = {
            k: json.dumps(v, default=str) for k, v in data.items()
        }
        entry_id = await cast(
            Awaitable[bytes | None],
            r.xadd(stream, fields, maxlen=max_len, approximate=True),
        )
        return str(entry_id) if entry_id is not None else ""

    async def stream_read(
        self,
        stream: str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read entries from a Redis Stream.

        Args:
            stream: Stream key name.
            last_id: Read entries after this ID ('0' = from beginning, '$' = new only).
            count: Maximum entries to return.
            block_ms: If set, block for this many milliseconds waiting for new entries.

        Returns:
            List of (entry_id, data_dict) tuples.
        """
        r = self._ensure_connected()
        results = await cast(
            Awaitable[list[Any]],
            r.xread({stream: last_id}, count=count, block=block_ms),
        )
        entries: list[tuple[str, dict[str, Any]]] = []
        if results:
            for _stream_name, records in results:
                for entry_id, raw_fields in records:
                    parsed = {k: json.loads(v) for k, v in raw_fields.items()}
                    entries.append((entry_id, parsed))
        return entries

    # ── Lists ─────────────────────────────────────────────────────────────────

    async def lpush(self, key: str, *values: Any) -> None:  # noqa: ANN401
        """Push values to the left of a Redis list.

        Args:
            key: List key.
            values: Values to push (serialized as JSON).
        """
        r = self._ensure_connected()
        await cast(
            Awaitable[int],
            r.lpush(key, *[json.dumps(v, default=str) for v in values]),
        )

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        """Get a range of elements from a Redis list.

        Args:
            key: List key.
            start: Start index (0-based).
            end: End index (-1 = last element).

        Returns:
            List of deserialized elements.
        """
        r = self._ensure_connected()
        raw = await cast(Awaitable[list[str]], r.lrange(key, start, end))
        return [json.loads(v) for v in raw]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        """Trim a list to the specified range.

        Args:
            key: List key.
            start: Start index to keep.
            end: End index to keep (-1 = last).
        """
        r = self._ensure_connected()
        await cast(Awaitable[bool], r.ltrim(key, start, end))

    # ── Increment ─────────────────────────────────────────────────────────────

    async def incr(self, key: str, amount: int = 1) -> int:
        """Atomically increment an integer key.

        Args:
            key: Redis key.
            amount: Increment amount.

        Returns:
            New value after increment.
        """
        r = self._ensure_connected()
        return int(await cast(Awaitable[int], r.incr(key, amount=amount)))
