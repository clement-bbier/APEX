"""Macro persistence shim — Phase A.10 (issue #200).

Resolves the orphan reads of ``macro:vix_current`` and ``macro:vix_1h_ago``
by :mod:`services.risk_manager.context_loader` (lines 76-77).

Per ADR-0006 §D4 the S05 pre-trade context loader fail-loud-rejects
every order if either key is missing or malformed. Without a writer the
live pipeline rejects 100% of orders. This module is the production
writer.

Design notes
------------
- The :class:`services.data_ingestion.macro_feed.MacroFeed` already polls
  VIX/DXY/yield-spread from FRED + Yahoo on a 60 s cadence and caches
  them in instance attributes. The persister tails that cache and
  publishes the values to Redis.
- ``macro:vix_1h_ago`` is the VIX value of the **oldest snapshot ≥
  60 min old**. A bounded deque (capacity ≥ 90 entries at 60 s cadence)
  keeps the rolling window. Until 60 min of history has accumulated,
  the persister writes the oldest available snapshot — graceful
  degradation per CLAUDE.md §3 ("degrades gracefully if upstream data
  is stale").
- ``macro:vix``, ``macro:dxy``, ``macro:yield_spread`` are *also* orphan
  reads (S03 ``services/regime_detector/service.py:93-95``). Persisting
  them here is a zero-extra-cost bonus that closes the collateral
  finding flagged in ``REDIS_KEYS_WRITER_AUDIT_2026-04-17.md`` §4 — the
  values are already in the same cache snapshot the persister consumes.

See ``docs/audits/SESSION_MACRO_SHIMS_AUDIT_2026-04-21.md`` §6.2 for the
full specification.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from core.logger import get_logger

logger = get_logger("data_ingestion.macro_persister")

VIX_CURRENT_KEY = "macro:vix_current"
VIX_1H_AGO_KEY = "macro:vix_1h_ago"
VIX_KEY = "macro:vix"
DXY_KEY = "macro:dxy"
YIELD_SPREAD_KEY = "macro:yield_spread"

DEFAULT_POLL_INTERVAL_SECONDS: float = 60.0
"""Default cadence — matches ``MacroFeed._POLL_INTERVAL_SECONDS``."""

VIX_HISTORY_WINDOW_SECONDS: int = 60 * 60
"""1 hour rolling window for ``macro:vix_1h_ago`` resolution."""

VIX_HISTORY_MAX_ENTRIES: int = 120
"""Cap the deque to bound memory; at 60 s cadence this is ≈ 2 h of buffer."""


class _StateWriter(Protocol):
    """Duck-type for the subset of :class:`core.state.StateStore` used here."""

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...  # noqa: ANN401


class _MacroSnapshotSource(Protocol):
    """Duck-type matching the cached-getter subset of :class:`MacroFeed`."""

    async def get_vix(self) -> float | None: ...
    async def get_dxy(self) -> float | None: ...
    async def get_yield_spread(self) -> float | None: ...


class MacroPersister:
    """Tails :class:`MacroFeed` and persists macro context to Redis.

    Args:
        state: Any object exposing an awaitable
            ``set(key: str, value, ttl: int | None = None)`` method.
        feed: Any object exposing the cached
            ``get_vix() / get_dxy() / get_yield_spread()`` accessors.
            :class:`MacroFeed` satisfies this in production; tests pass
            a deterministic stub.
        poll_interval_seconds: Cadence between persistence ticks.
            Defaults to 60 s.
        clock: Injected wall-clock function returning a UTC-aware
            ``datetime``. Defaults to ``lambda: datetime.now(UTC)``.
            Exposed so tests can deterministically advance time across
            the 1 h boundary without sleeping.
    """

    def __init__(
        self,
        state: _StateWriter,
        feed: _MacroSnapshotSource,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        clock: Any = None,  # noqa: ANN401
    ) -> None:
        self._state = state
        self._feed = feed
        self._poll_interval = poll_interval_seconds
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._vix_history: deque[tuple[datetime, float]] = deque(maxlen=VIX_HISTORY_MAX_ENTRIES)

    async def start(self) -> None:
        """Start the background persistence loop.

        Persists once eagerly so the values are available on the next
        S05 pre-trade context load (no first-tick blackout). Eager-tick
        errors are logged and the loop is started anyway — the loop
        will retry on its next cadence.
        """
        self._running = True
        try:
            await self.persist_once()
        except Exception as exc:
            logger.warning("macro_persister.eager_tick_error", error=str(exc))
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "macro_persister.started",
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
        logger.info("macro_persister.stopped")

    async def persist_once(self) -> dict[str, float | None]:
        """Persist one snapshot of macro context.

        Returns:
            A dict mapping each persisted key to the value written
            (``None`` if the underlying feed has no value yet, in which
            case the key is *not* written — a missing key surfaces as
            fail-loud at the S05 reader, which is the intended behavior
            per ADR-0006 §D4).
        """
        vix, dxy, spread = await asyncio.gather(
            self._feed.get_vix(),
            self._feed.get_dxy(),
            self._feed.get_yield_spread(),
        )

        now = self._clock()
        written: dict[str, float | None] = {
            VIX_CURRENT_KEY: None,
            VIX_1H_AGO_KEY: None,
            VIX_KEY: None,
            DXY_KEY: None,
            YIELD_SPREAD_KEY: None,
        }

        if vix is not None:
            self._record_vix_snapshot(now, vix)
            await self._state.set(VIX_CURRENT_KEY, vix)
            await self._state.set(VIX_KEY, vix)
            written[VIX_CURRENT_KEY] = vix
            written[VIX_KEY] = vix

            vix_1h = self._resolve_vix_1h_ago(now)
            if vix_1h is not None:
                await self._state.set(VIX_1H_AGO_KEY, vix_1h)
                written[VIX_1H_AGO_KEY] = vix_1h

        if dxy is not None:
            await self._state.set(DXY_KEY, dxy)
            written[DXY_KEY] = dxy

        if spread is not None:
            await self._state.set(YIELD_SPREAD_KEY, spread)
            written[YIELD_SPREAD_KEY] = spread

        logger.debug(
            "macro_persister.tick",
            vix=vix,
            dxy=dxy,
            yield_spread=spread,
            vix_1h_ago=written[VIX_1H_AGO_KEY],
            history_depth=len(self._vix_history),
        )
        return written

    def _record_vix_snapshot(self, now: datetime, vix: float) -> None:
        """Append ``(now, vix)`` and evict snapshots older than the window."""
        self._vix_history.append((now, vix))
        cutoff = now - timedelta(seconds=VIX_HISTORY_WINDOW_SECONDS + self._poll_interval)
        while self._vix_history and self._vix_history[0][0] < cutoff:
            self._vix_history.popleft()

    def _resolve_vix_1h_ago(self, now: datetime) -> float | None:
        """Return the VIX value of the oldest snapshot ≥ 60 min old.

        Falls back to the oldest available snapshot when the deque
        does not yet span a full hour — graceful-degradation contract
        per CLAUDE.md §3. Returns ``None`` only when the deque is empty
        (i.e. the very first call before any snapshot was recorded).
        """
        if not self._vix_history:
            return None

        target = now - timedelta(seconds=VIX_HISTORY_WINDOW_SECONDS)
        # The deque is appended in order, so it is monotonically
        # increasing in timestamp. Scan from the left for the youngest
        # snapshot still ≤ target — that is the value "≥ 60 min old".
        chosen: float | None = None
        for ts, vix in self._vix_history:
            if ts <= target:
                chosen = vix
            else:
                break

        if chosen is not None:
            return chosen

        # Less than an hour of history yet — degrade to oldest available.
        return self._vix_history[0][1]

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
                    "macro_persister.tick_error",
                    error=str(exc),
                )
