"""Redis async state wrapper for APEX Trading System.

Provides get/set/delete/hget/hset/publish/stream operations with TTL support.
All operations are async using redis[asyncio].
"""

from __future__ import annotations

import asyncio
import importlib
import json
import math
import types
from collections.abc import Awaitable
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field

aioredis: types.ModuleType | None
_redis_exceptions: types.ModuleType | None
try:
    aioredis = importlib.import_module("redis.asyncio")
    _redis_exceptions = importlib.import_module("redis.exceptions")
except ModuleNotFoundError:
    aioredis = None
    _redis_exceptions = None

from core.config import get_settings  # noqa: E402
from core.logger import get_logger  # noqa: E402
from core.topics import Topics  # noqa: E402

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.bus import MessageBus

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

    @property
    def client(self) -> Any:  # noqa: ANN401
        """Return the underlying Redis client.

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

    def _ensure_connected(self) -> Any:  # noqa: ANN401
        """Return the Redis client or raise if not connected.

        .. deprecated::
            Use :attr:`client` property instead.

        Returns:
            Active Redis client.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        return self.client

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


# ── Fail-Closed Pre-Trade Risk Controls (ADR-0006) ────────────────────────────

REDIS_HEARTBEAT_KEY: Final[str] = "risk:heartbeat"
REDIS_SYSTEM_STATE_KEY: Final[str] = "risk:system:state"
HEARTBEAT_TTL_SECONDS: Final[int] = 5
HEARTBEAT_REFRESH_SECONDS: Final[float] = 2.0


class SystemRiskState(StrEnum):
    """System-wide risk state driving S05's fail-closed pre-trade guard.

    See ADR-0006 §D1. The three states differ only in observability; both
    non-HEALTHY states reject 100 % of orders. There is no partial-trading
    middle ground (ADR-0006 §D7).
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SystemRiskStateCause(StrEnum):
    """Short machine-readable cause codes for SystemRiskState transitions.

    See ADR-0006 §D8. Emitted on the ``risk.system.state_change`` ZMQ
    topic and in the ``structlog.critical`` transition event.
    """

    HEARTBEAT_STALE = "heartbeat_stale"
    REDIS_CONNECTION_ERROR = "redis_connection_error"
    REDIS_TIMEOUT = "redis_timeout"
    RECOVERY = "recovery"


class SystemRiskStateChange(BaseModel):
    """Frozen envelope for a SystemRiskState transition.

    Published on ``Topics.RISK_SYSTEM_STATE_CHANGE`` by
    :class:`SystemRiskMonitor` whenever the observed state changes.
    See ADR-0006 §D5 and §D8 for the field contract.
    """

    model_config = ConfigDict(frozen=True)

    previous_state: SystemRiskState
    new_state: SystemRiskState
    redis_reachable: bool
    heartbeat_age_seconds: float = Field(
        ...,
        description="Wall-clock age of last observed heartbeat; -1.0 if never written",
    )
    cause: SystemRiskStateCause
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SystemRiskMonitor:
    """Owns the SystemRiskState machine for S05's fail-closed guard.

    Two paths (ADR-0006 §D2):

    - :meth:`write_heartbeat` is called periodically (2 s) by S05's
      background task (:meth:`run_heartbeat_loop`). It refreshes
      ``risk:heartbeat`` with TTL 5 s.
    - :meth:`current_state` is called synchronously by
      :class:`services.s05_risk_manager.fail_closed.FailClosedGuard` on
      every ``OrderCandidate``. It reads the heartbeat directly, maps the
      result to a :class:`SystemRiskState`, and publishes a transition
      event on :attr:`Topics.RISK_SYSTEM_STATE_CHANGE` if the state has
      changed since the previous observation.

    See ADR-0006 for the full contract. The monitor owns no background
    tasks itself — the caller (S05 service) is expected to spawn
    :meth:`run_heartbeat_loop` as a task and cancel it at shutdown.

    Args:
        redis: Async Redis client (``redis.asyncio.Redis``).
        bus: Message bus used to publish state-change events.
    """

    def __init__(self, redis: Redis, bus: MessageBus) -> None:
        self._redis = redis
        self._bus = bus
        self._last_observed: SystemRiskState | None = None

    async def write_heartbeat(self) -> None:
        """Refresh ``risk:heartbeat`` with TTL 5 s.

        Called eagerly once at startup (before S05 subscribes to
        ``ORDER_CANDIDATE``) and then periodically by
        :meth:`run_heartbeat_loop`. Exceptions are logged but do not
        propagate: if Redis is unreachable the key simply expires and the
        next foreground :meth:`current_state` observes ``UNAVAILABLE``.
        """
        try:
            now_iso = datetime.now(UTC).isoformat()
            await self._redis.set(REDIS_HEARTBEAT_KEY, now_iso, ex=HEARTBEAT_TTL_SECONDS)
        except Exception as exc:
            # Broad catch is intentional: the fail-closed contract requires that
            # heartbeat failure propagates to the foreground reader via key
            # expiry, not via a raised exception on the background task.
            logger.warning("heartbeat_write_failed", error=str(exc))

    async def run_heartbeat_loop(self, interval: float = HEARTBEAT_REFRESH_SECONDS) -> None:
        """Periodically refresh the heartbeat.

        Runs until cancelled. Exceptions from
        :meth:`write_heartbeat` are already logged and swallowed there;
        the loop itself only propagates :class:`asyncio.CancelledError`.

        Args:
            interval: Seconds between heartbeat refreshes. Must be shorter
                than :data:`HEARTBEAT_TTL_SECONDS`. Default: 2 s.
        """
        while True:
            await self.write_heartbeat()
            await asyncio.sleep(interval)

    async def current_state(self) -> tuple[SystemRiskState, float, bool]:
        """Synchronous per-order check. Publishes transitions on state change.

        Latency budget: < 1 ms (single Redis ``GET``). See ADR-0006 §D3.

        Returns:
            ``(state, heartbeat_age_seconds, redis_reachable)``.
            ``heartbeat_age_seconds`` is ``math.inf`` if the key is
            absent or the payload is unparseable; always finite when the
            state is ``HEALTHY``.
        """
        redis_reachable = True
        heartbeat_age = math.inf
        cause = SystemRiskStateCause.HEARTBEAT_STALE

        try:
            raw = await self._redis.get(REDIS_HEARTBEAT_KEY)
        except Exception as exc:
            # Broad catch is intentional: any failure to read the heartbeat
            # (ConnectionError, TimeoutError, or unknown) → UNAVAILABLE + reject.
            redis_reachable = False
            new_state = SystemRiskState.UNAVAILABLE
            # _redis_exceptions is typed as ModuleType | None — use getattr+cast so
            # mypy --strict accepts the dynamic isinstance-target lookup.
            redis_timeout_error = cast(
                "type[BaseException] | None",
                getattr(_redis_exceptions, "TimeoutError", None)
                if _redis_exceptions is not None
                else None,
            )
            if redis_timeout_error is not None and isinstance(exc, redis_timeout_error):
                cause = SystemRiskStateCause.REDIS_TIMEOUT
            else:
                cause = SystemRiskStateCause.REDIS_CONNECTION_ERROR
        else:
            if raw is None:
                new_state = SystemRiskState.DEGRADED
                cause = SystemRiskStateCause.HEARTBEAT_STALE
            else:
                payload = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
                try:
                    written_at = datetime.fromisoformat(payload)
                except ValueError:
                    new_state = SystemRiskState.DEGRADED
                    cause = SystemRiskStateCause.HEARTBEAT_STALE
                else:
                    if written_at.tzinfo is None:
                        # Fail-closed on tz-naive heartbeats: the age computation
                        # below would raise, and silently treating a naive local
                        # time as UTC is an attack surface (clock skew).
                        new_state = SystemRiskState.DEGRADED
                        cause = SystemRiskStateCause.HEARTBEAT_STALE
                    else:
                        heartbeat_age = (datetime.now(UTC) - written_at).total_seconds()
                        # Fail-closed at the boundary (>=) and on negative ages.
                        # Negative age = future-dated heartbeat (clock skew or
                        # adversarial write) → treat as stale, not fresh.
                        if heartbeat_age < 0 or heartbeat_age >= HEARTBEAT_TTL_SECONDS:
                            new_state = SystemRiskState.DEGRADED
                            cause = SystemRiskStateCause.HEARTBEAT_STALE
                        else:
                            new_state = SystemRiskState.HEALTHY
                            cause = SystemRiskStateCause.RECOVERY

        previous = self._last_observed
        self._last_observed = new_state

        if previous is not None and previous != new_state:
            await self._publish_transition(
                previous=previous,
                new_state=new_state,
                redis_reachable=redis_reachable,
                heartbeat_age_seconds=heartbeat_age,
                cause=cause,
            )

        if redis_reachable:
            try:
                await self._redis.set(
                    REDIS_SYSTEM_STATE_KEY,
                    new_state.value,
                    ex=HEARTBEAT_TTL_SECONDS,
                )
            except Exception as exc:
                # Best-effort observability persistence — the foreground read
                # is authoritative; a write failure here is debug-level noise.
                logger.debug("system_state_persist_failed", error=str(exc))

        return new_state, heartbeat_age, redis_reachable

    async def _publish_transition(
        self,
        *,
        previous: SystemRiskState,
        new_state: SystemRiskState,
        redis_reachable: bool,
        heartbeat_age_seconds: float,
        cause: SystemRiskStateCause,
    ) -> None:
        """Emit the critical log + publish the ZMQ envelope for a transition."""
        age_for_model = heartbeat_age_seconds if math.isfinite(heartbeat_age_seconds) else -1.0
        event = SystemRiskStateChange(
            previous_state=previous,
            new_state=new_state,
            redis_reachable=redis_reachable,
            heartbeat_age_seconds=age_for_model,
            cause=cause,
        )
        logger.critical(
            "risk_system_state_change",
            previous_state=previous.value,
            new_state=new_state.value,
            redis_reachable=redis_reachable,
            heartbeat_age_seconds=age_for_model,
            cause=cause.value,
            timestamp_utc=event.timestamp_utc.isoformat(),
        )
        try:
            await self._bus.publish(
                Topics.RISK_SYSTEM_STATE_CHANGE,
                event.model_dump(mode="json"),
            )
        except Exception as exc:
            # Publish failure must not block rejection — the authoritative
            # rejection path is the critical structlog above; the ZMQ
            # envelope is a dashboard observability channel.
            logger.error("state_change_publish_failed", error=str(exc))
