"""Minimal asyncpg connection pool wrapper for APEX.

This module is the foundation of the Phase B persistence layer. It is
deliberately small: no ORM, no query builder, no row mapping — just a
typed async context manager around ``asyncpg.create_pool`` plus a
``get_connection`` context manager that services use to run raw SQL.

Higher-level repositories (the domain-specific ``TimescaleRepository``
in ``core/data/timescale_repository.py`` being the first example) layer
on top of this primitive. Keeping the primitive small means every
service that needs persistence has a single, unambiguous place to ask
for a connection without dragging in code it does not need.

Usage
-----

    from core.db import DBPool, DBSettings

    async with DBPool(DBSettings.from_env()) as pool:
        async with pool.get_connection() as conn:
            row = await conn.fetchrow('SELECT 1 AS ok')
            assert row['ok'] == 1

References
----------
- Charter §5.5 (per-strategy persistence)
- ADR-0014 (TimescaleDB schema v2)
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import asyncpg


@dataclass(frozen=True)
class DBSettings:
    """Connection settings resolved from environment variables.

    All fields have safe local-dev defaults that match
    ``docker/docker-compose.yml``. Callers should override via environment
    for any non-dev deployment.
    """

    host: str = "localhost"
    port: int = 5432
    user: str = "apex"
    # Dev-only default matching docker/docker-compose.yml. Real deployments
    # MUST override via the DB_PASSWORD environment variable.
    password: str = "apex_secret"  # noqa: S105
    database: str = "apex"
    pool_min: int = 2
    pool_max: int = 10
    command_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> Self:
        """Build settings from ``DB_*`` environment variables."""
        return cls(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            user=os.environ.get("DB_USER", "apex"),
            password=os.environ.get("DB_PASSWORD", "apex_secret"),
            database=os.environ.get("DB_NAME", "apex"),
            pool_min=int(os.environ.get("DB_POOL_MIN", "2")),
            pool_max=int(os.environ.get("DB_POOL_MAX", "10")),
            command_timeout=float(os.environ.get("DB_COMMAND_TIMEOUT", "30")),
        )

    @property
    def dsn(self) -> str:
        """Build a ``postgresql://`` DSN from the component fields."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class DBPool:
    """Async context manager around an ``asyncpg`` connection pool.

    The pool is created on ``__aenter__`` and closed on ``__aexit__``.
    Use ``get_connection()`` inside the ``async with`` to acquire a
    connection for the duration of a scope.
    """

    def __init__(self, settings: DBSettings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None

    async def __aenter__(self) -> Self:
        self._pool = await asyncpg.create_pool(
            dsn=self._settings.dsn,
            min_size=self._settings.pool_min,
            max_size=self._settings.pool_max,
            command_timeout=self._settings.command_timeout,
            init=self._init_connection,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    async def _init_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
        """Register JSON/JSONB codecs so dict values round-trip cleanly."""
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "json",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Acquire a pooled connection for the duration of the ``async with``.

        Raises:
            RuntimeError: if the pool has not been entered yet.
        """
        if self._pool is None:
            raise RuntimeError("DBPool is not active — call `async with DBPool(settings):` first.")
        async with self._pool.acquire() as conn:
            yield conn

    @property
    def is_open(self) -> bool:
        """True if the pool is currently open."""
        return self._pool is not None
