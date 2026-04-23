"""Session persistence shim — Phase A.10 (issue #200).

Resolves the orphan read of ``session:current`` by
:mod:`services.risk_manager.context_loader` (line 108).

Per ADR-0006 §D4 the S05 pre-trade context loader fail-loud-rejects every
order if ``session:current`` is missing or malformed. Without a writer
the live pipeline rejects 100% of orders. This module is the production
writer.

Why S01 (data_ingestion) and not S03 (regime_detector)
------------------------------------------------------
S05's :class:`core.models.tick.Session` enum (``us_prime`` / ``us_normal``
/ ``after_hours`` / ``london`` / ``asian`` / ``weekend`` / ``unknown``)
is **not** the same as the S03
:class:`services.regime_detector.session_tracker.Session` enum
(``us_open`` / ``us_morning`` / ``us_lunch`` / …). The canonical
classifier returning the S05-shape enum is
:class:`services.data_ingestion.normalizers.session_tagger.SessionTagger`,
which already lives in S01. Co-locating the writer with the classifier
keeps the producer/consumer enum contract intact.

See ``docs/audits/SESSION_MACRO_SHIMS_AUDIT_2026-04-21.md`` §3.4 + §5
for the full rationale.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol

from core.logger import get_logger
from services.data_ingestion.normalizers.session_tagger import SessionTagger

logger = get_logger("data_ingestion.session_persister")

SESSION_REDIS_KEY = "session:current"
"""Redis key consumed by ``services/risk_manager/context_loader.py:108``."""

DEFAULT_POLL_INTERVAL_SECONDS: float = 30.0
"""Default cadence — sub-minute granularity is sufficient since session
boundaries are minutes apart and session_mult [0.5, 1.5] is the only
sizing input that depends on this value."""


class _StateWriter(Protocol):
    """Duck-type for the subset of :class:`core.state.StateStore` used here."""

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...  # noqa: ANN401


class SessionPersister:
    """Periodically persists the current trading session to Redis.

    Args:
        state: Any object exposing an awaitable
            ``set(key: str, value, ttl: int | None = None)`` method.
            :class:`core.state.StateStore` satisfies this in production;
            ``fakeredis`` adapters satisfy it in tests.
        tagger: Injected :class:`SessionTagger`. Defaults to a fresh
            instance — exposed so tests can substitute a deterministic
            stub that maps any UTC timestamp to a known session.
        poll_interval_seconds: Cadence between persistence ticks.
            Defaults to 30 s (see :data:`DEFAULT_POLL_INTERVAL_SECONDS`).
    """

    def __init__(
        self,
        state: _StateWriter,
        *,
        tagger: SessionTagger | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._state = state
        self._tagger = tagger if tagger is not None else SessionTagger()
        self._poll_interval = poll_interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background persistence loop.

        Returns immediately; persistence runs in a background task.
        Persists once eagerly so the value is available to S05 on the
        next pre-trade context load (no first-tick blackout). Eager-tick
        errors are logged and the loop is started anyway — the loop
        will retry on its next cadence.
        """
        self._running = True
        try:
            await self.persist_once()
        except Exception as exc:
            logger.warning("session_persister.eager_tick_error", error=str(exc))
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "session_persister.started",
            poll_interval_seconds=self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the background persistence loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("session_persister.stopped")

    async def persist_once(self, *, now: datetime | None = None) -> str:
        """Compute and persist the current session.

        Args:
            now: Override for the reference time. Defaults to
                ``datetime.now(UTC)``. Exposed so tests can pin time
                to specific session-boundary cases (DST, weekend, midnight).

        Returns:
            The persisted session value (e.g. ``"us_prime"``). Returned
            for convenience in tests; not used by ``start()``.
        """
        ts = now if now is not None else datetime.now(UTC)
        session = self._tagger.tag(ts)
        await self._state.set(SESSION_REDIS_KEY, session.value)
        logger.debug(
            "session_persister.tick",
            session=session.value,
            timestamp=ts.isoformat(),
        )
        return session.value

    async def _loop(self) -> None:
        """Internal loop body — exception-safe, never propagates."""
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                if not self._running:
                    break
                await self.persist_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "session_persister.tick_error",
                    error=str(exc),
                )
