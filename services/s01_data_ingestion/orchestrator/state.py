"""Redis-backed state management for the Backfill Orchestrator.

Persists job run state (distributed locks, last success timestamps,
run history) in Redis. All methods are async and fakeredis-compatible.

Lock safety: uses a unique UUID token per acquisition and a Lua
compare-and-delete script for release (prevents releasing another
worker's lock if TTL expired during a long run).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_KEY_PREFIX: str = "apex:orchestrator"
_LOCK_PREFIX: str = f"{_KEY_PREFIX}:lock"
_LAST_SUCCESS_PREFIX: str = f"{_KEY_PREFIX}:last_success"
_HISTORY_PREFIX: str = f"{_KEY_PREFIX}:history"
_HISTORY_MAX_LEN: int = 100
_HISTORY_DEFAULT_LIMIT: int = 10

# Lua script: compare token then delete — atomic on the Redis server.
_LOCK_RELEASE_LUA: str = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


# ── Models ───────────────────────────────────────────────────────────────────


class JobRunResult(BaseModel):
    """Result of a single job run, persisted in Redis streams."""

    model_config = ConfigDict(frozen=True)

    job_name: str
    status: str = Field(description="'success', 'failed', 'locked', or 'timeout'.")
    started_at: datetime
    finished_at: datetime
    rows_inserted: int = 0
    error_message: str | None = None


# ── State Manager ────────────────────────────────────────────────────────────


class JobStateManager:
    """Manages job run state in Redis.

    Responsibilities:
    - Distributed locks (SET NX EX + Lua CAS release) to prevent concurrent runs
    - Last-success timestamps per job
    - Capped run history via Redis streams (XADD / XRANGE)
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._lock_tokens: dict[str, str] = {}

    # ── Locking ──────────────────────────────────────────────────────────

    async def acquire_lock(self, job_name: str, ttl_seconds: int) -> bool:
        """Try to acquire a distributed lock for *job_name*.

        Uses ``SET NX EX`` with a unique UUID token. The token is stored
        in-memory so that only the owner can release the lock via Lua CAS.

        Returns:
            True if the lock was acquired, False if already held.
        """
        key = f"{_LOCK_PREFIX}:{job_name}"
        token = str(uuid.uuid4())
        acquired = await self._redis.set(key, token, nx=True, ex=ttl_seconds)
        if acquired:
            self._lock_tokens[job_name] = token
            logger.debug("state.lock_acquired", job=job_name, ttl=ttl_seconds)
            return True
        logger.debug("state.lock_already_held", job=job_name)
        return False

    async def release_lock(self, job_name: str) -> None:
        """Release the distributed lock for *job_name* via Lua CAS.

        Only deletes the key if the stored token matches the one from
        ``acquire_lock``. This prevents releasing another worker's lock
        if the TTL expired and the lock was re-acquired.
        """
        key = f"{_LOCK_PREFIX}:{job_name}"
        token = self._lock_tokens.pop(job_name, None)
        if token is None:
            logger.warning("state.lock_release_no_token", job=job_name)
            return
        result = await self._redis.eval(  # type: ignore[misc]
            _LOCK_RELEASE_LUA, 1, key, token
        )
        if result == 0:
            logger.warning("state.lock_release_token_mismatch", job=job_name)
        else:
            logger.debug("state.lock_released", job=job_name)

    # ── Last success ─────────────────────────────────────────────────────

    async def get_last_success(self, job_name: str) -> datetime | None:
        """Return the timestamp of the last successful run, or None."""
        key = f"{_LAST_SUCCESS_PREFIX}:{job_name}"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)

    async def set_last_success(self, job_name: str, ts: datetime) -> None:
        """Store the timestamp of a successful run."""
        key = f"{_LAST_SUCCESS_PREFIX}:{job_name}"
        await self._redis.set(key, ts.isoformat())
        logger.debug("state.last_success_updated", job=job_name, ts=ts.isoformat())

    # ── Run history ──────────────────────────────────────────────────────

    async def append_run_history(self, job_name: str, result: JobRunResult) -> None:
        """Append a run result to the capped Redis stream for *job_name*."""
        key = f"{_HISTORY_PREFIX}:{job_name}"
        fields: dict[str, str] = {
            "status": result.status,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "rows_inserted": str(result.rows_inserted),
        }
        if result.error_message:
            fields["error_message"] = result.error_message

        await self._redis.xadd(key, fields, maxlen=_HISTORY_MAX_LEN)  # type: ignore[arg-type]
        logger.debug("state.history_appended", job=job_name, status=result.status)

    async def get_run_history(
        self,
        job_name: str,
        limit: int = _HISTORY_DEFAULT_LIMIT,
    ) -> list[JobRunResult]:
        """Return the last *limit* run results for *job_name*."""
        key = f"{_HISTORY_PREFIX}:{job_name}"
        entries: list[Any] = await self._redis.xrevrange(key, count=limit)

        results: list[JobRunResult] = []
        for _entry_id, fields in entries:
            decoded = _decode_stream_fields(fields)
            results.append(
                JobRunResult(
                    job_name=job_name,
                    status=decoded["status"],
                    started_at=datetime.fromisoformat(decoded["started_at"]),
                    finished_at=datetime.fromisoformat(decoded["finished_at"]),
                    rows_inserted=int(decoded.get("rows_inserted", "0")),
                    error_message=decoded.get("error_message"),
                )
            )
        return results

    async def clear_state(self, job_name: str) -> None:
        """Purge all state for *job_name* (lock, last_success, history)."""
        self._lock_tokens.pop(job_name, None)
        keys = [
            f"{_LOCK_PREFIX}:{job_name}",
            f"{_LAST_SUCCESS_PREFIX}:{job_name}",
            f"{_HISTORY_PREFIX}:{job_name}",
        ]
        await self._redis.delete(*keys)
        logger.info("state.cleared", job=job_name)


def _decode_stream_fields(fields: dict[Any, Any]) -> dict[str, str]:
    """Decode Redis stream field bytes to str."""
    return {
        (k.decode() if isinstance(k, bytes) else str(k)): (
            v.decode() if isinstance(v, bytes) else str(v)
        )
        for k, v in fields.items()
    }


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)
