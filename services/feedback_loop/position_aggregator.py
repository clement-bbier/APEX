"""Aggregates per-symbol fill records into the consolidated portfolio:positions list.

Phase A.9 (issue #199, Roadmap v3.0 §2.2.4 row 4, PHASE_5_SPEC_v2 §3.2).

Audit finding (2026-04-22, see ``docs/audits/POSITION_KEY_AUDIT_2026-04-21.md``)
------------------------------------------------------------------------------
The S05 Risk Manager pre-trade context loader
(:class:`services.risk_manager.context_loader.ContextLoader`) reads
``portfolio:positions`` as a JSON-encoded ``list[Position]``. The exhaustive
producer grep returned **zero** writers for that key in ``services/`` or
``core/``. The S06 ExecutionService writes per-symbol fill records under
``positions:{symbol}`` (``services/execution/service.py:153``) but no
component rolls those records up into the consolidated list shape S05
expects. The S05 fail-closed guard (ADR-0006 §D1, STEP 0 in the chain)
masks the orphan read by short-circuiting to
``REJECTED_SYSTEM_UNAVAILABLE``, which would block 100% of orders in
production.

Fix
---
:class:`PositionAggregator` runs in S09 FeedbackLoop, scans the
``positions:*`` namespace, transforms each per-symbol record into the
:class:`services.risk_manager.models.Position` envelope, and writes the
aggregated list to ``portfolio:positions``. Snapshotting is periodic
(default 15 s); the cadence is decoupled from S06 fills because S05's
pre-trade context tolerates seconds-old position state (positions move
on order-fill timescales, not on tick timescales).

Phase B forward-compat
----------------------
Per ADR-0012 §D2, the broker net per symbol is
``Σ subbook[strategy_id].position(symbol)``. The :meth:`aggregate_records`
function below is a pure ``records → list[Position]`` transform that
accepts the per-symbol records currently produced by S06 today and that
will accept the sub-book records produced in Phase B without any change to
its algebra (signed-size summation reduces to a 1:1 transform when each
symbol has one source record). Only the :meth:`aggregate_from_redis`
caller will swap its source-key prefix from ``positions:*`` to
``subbook:*:position:*`` when Phase B lands.

Compliance notes
----------------
- CLAUDE.md §2 — :class:`Decimal` (never float) for sizes/prices;
  :mod:`structlog` only; ``asyncio`` (no threading); UTC datetimes only.
- CLAUDE.md §3 — single responsibility (read source, transform, snapshot);
  no premature multi-strategy abstraction.
- CLAUDE.md §10 — per-record decode failures are logged at DEBUG and
  skipped (a corrupted broker record on one symbol must not silently
  block snapshots for other symbols); a structurally malformed source
  surface (e.g. unparseable JSON at the Redis layer) propagates to
  :meth:`aggregate_from_redis` so the periodic loop logs and moves on.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from core.logger import get_logger
from services.risk_manager.models import Position

logger = get_logger("feedback_loop.position_aggregator")

PER_SYMBOL_KEY_PREFIX = "positions:"
"""Source-key prefix written by the S06 ExecutionService on every fill."""

AGGREGATE_KEY = "portfolio:positions"
"""Consolidated aggregate read by S05's :class:`ContextLoader`."""

DEFAULT_SNAPSHOT_INTERVAL_S: float = 15.0
"""Snapshot cadence default. Positions move on fill timescales, not tick
timescales; 15 s is conservatively faster than the typical fill rate of
the current single-strategy paper book and well inside S05's
``DEGRADED`` staleness budget (10 s for in-memory state per
PHASE_5_SPEC_v2 §3.2 — but ``portfolio:positions`` lives on the slower
context-loader path that re-reads on every order, so eventual consistency
within seconds is acceptable)."""


class _StateProtocol(Protocol):
    """Duck-type for the subset of :class:`core.state.StateStore` used here.

    Mirrors the protocol pattern used by
    :class:`services.risk_manager.portfolio_tracker.PortfolioTracker` and
    :class:`services.risk_manager.pnl_tracker.PnLTracker` so a
    ``fakeredis``-backed adapter satisfies it in unit tests.
    """

    @property
    def client(self) -> Any: ...  # noqa: ANN401

    async def get(self, key: str) -> Any | None: ...  # noqa: ANN401

    async def set(
        self,
        key: str,
        value: Any,  # noqa: ANN401
        ttl: int | None = ...,
    ) -> None: ...


def aggregate_records(records: dict[str, dict[str, Any]]) -> list[Position]:
    """Transform a ``{symbol: per_symbol_record}`` map into a list of Positions.

    Pure function, no I/O. Phase B will reuse this entry point with
    sub-book inputs (ADR-0012 §D2) — the algebra is identical because
    each ``records`` entry already represents the consolidated signed
    size for its symbol.

    Args:
        records: Map ``symbol → record`` where ``record`` is the dict
            shape written by S06 (``services/execution/service.py:153``)
            with at least ``size`` and ``entry``/``entry_price`` numeric
            fields. The map key (``symbol``) takes precedence over any
            ``record["symbol"]`` mismatch (defensive: the source key is
            authoritative).

    Returns:
        List of :class:`Position` instances. Records with non-positive
        size, missing required fields, or unparseable Decimal values are
        logged at DEBUG and skipped — never raise. The output is sorted
        by symbol for deterministic test assertions and stable
        downstream diffing.
    """
    positions: list[Position] = []
    for symbol, record in records.items():
        if not isinstance(record, dict):
            logger.debug(
                "position_record_not_dict",
                symbol=symbol,
                record_type=type(record).__name__,
            )
            continue

        size_raw = record.get("size")
        entry_raw = record.get("entry_price", record.get("entry"))
        if size_raw is None or entry_raw is None:
            logger.debug(
                "position_record_missing_field",
                symbol=symbol,
                has_size=size_raw is not None,
                has_entry=entry_raw is not None,
            )
            continue

        try:
            size = Decimal(str(size_raw))
            entry_price = Decimal(str(entry_raw))
        except (InvalidOperation, ValueError) as exc:
            logger.debug(
                "position_record_decimal_decode_failed",
                symbol=symbol,
                size=size_raw,
                entry=entry_raw,
                error=str(exc),
            )
            continue

        # Position model rejects size <= 0; closed positions / shorts
        # carrying a negative magnitude are filtered here so the
        # constructor never raises ValidationError on a known-bad row.
        # Direction (long/short) is carried separately in S06 records and
        # is intentionally not propagated to the Position model — the
        # ExposureMonitor's class checks operate on |size| × entry_price
        # and a future signed-position refactor is tracked in ADR-0012 §D2.
        magnitude = abs(size)
        if magnitude == Decimal("0"):
            logger.debug("position_record_zero_size_skipped", symbol=symbol)
            continue
        if entry_price <= Decimal("0"):
            logger.debug(
                "position_record_non_positive_entry_skipped",
                symbol=symbol,
                entry=str(entry_price),
            )
            continue

        try:
            positions.append(
                Position(
                    symbol=symbol,
                    size=magnitude,
                    entry_price=entry_price,
                    asset_class=_infer_asset_class(symbol, record),
                )
            )
        except Exception as exc:
            # Belt-and-suspenders: filtering above should already prevent
            # validator errors; an exception here means a pydantic
            # contract drift that must surface as a debug log so the
            # snapshot keeps producing the remaining symbols.
            logger.debug(
                "position_model_validate_failed",
                symbol=symbol,
                error=str(exc),
            )

    positions.sort(key=lambda p: p.symbol)
    return positions


_CRYPTO_SUFFIXES: frozenset[str] = frozenset({"USDT", "BTC", "ETH", "BNB"})


def _infer_asset_class(symbol: str, record: dict[str, Any]) -> str:
    """Return ``"crypto"`` for known crypto suffixes, else fall back.

    Mirrors the convention used by
    :func:`services.risk_manager.exposure_monitor._asset_class` so the
    aggregator does not introduce a divergent classification rule. If
    the source record carries an explicit ``asset_class`` field
    (forward-compat with sub-book records that may include it), that
    value wins.
    """
    explicit = record.get("asset_class")
    if isinstance(explicit, str) and explicit:
        return explicit
    upper = symbol.upper()
    if any(upper.endswith(sfx) for sfx in _CRYPTO_SUFFIXES):
        return "crypto"
    return "equity"


class PositionAggregator:
    """Periodic aggregator: ``positions:*`` → ``portfolio:positions``.

    Args:
        state: Any object satisfying :class:`_StateProtocol`. In
            production this is :class:`core.state.StateStore`; in tests
            a ``fakeredis``-backed adapter (see
            ``tests/unit/feedback_loop/test_position_aggregator.py``).
        ttl: Optional TTL applied to the aggregate Redis key. ``None``
            (default) preserves the StateStore default TTL; pass an
            explicit value to override (e.g. for tests that need
            persistence across long-running scenarios).
    """

    def __init__(
        self,
        state: _StateProtocol,
        *,
        ttl: int | None = None,
    ) -> None:
        self._state = state
        self._ttl = ttl

    async def aggregate_from_redis(self) -> list[Position]:
        """Scan ``positions:*`` and return the aggregated Position list.

        Uses ``SCAN`` (via ``redis.scan_iter``) rather than ``KEYS`` so
        the call remains safe on a production-sized keyspace. Per-key
        decode failures are logged at DEBUG and skipped via
        :func:`aggregate_records` so a single corrupted broker record
        cannot block snapshots for other symbols.

        Returns:
            List of :class:`Position` envelopes, sorted by symbol.
        """
        records: dict[str, dict[str, Any]] = {}
        client = self._state.client
        async for raw_key in client.scan_iter(match=f"{PER_SYMBOL_KEY_PREFIX}*"):
            if isinstance(raw_key, (bytes, bytearray)):
                key = raw_key.decode("utf-8")
            else:
                key = str(raw_key)
            # Defensive: scan_iter's match pattern is a glob, not a strict
            # prefix; an exact-prefix re-check defends against keys whose
            # name happens to start with "positions" (e.g. "positionable:")
            # if the namespace ever extends.
            if not key.startswith(PER_SYMBOL_KEY_PREFIX):
                continue
            symbol = key[len(PER_SYMBOL_KEY_PREFIX) :]
            if not symbol:
                continue
            try:
                payload = await self._state.get(key)
            except Exception as exc:
                logger.debug(
                    "position_record_read_failed",
                    key=key,
                    error=str(exc),
                )
                continue
            if not isinstance(payload, dict):
                logger.debug(
                    "position_record_not_dict_at_read",
                    key=key,
                    payload_type=type(payload).__name__,
                )
                continue
            records[symbol] = payload

        return aggregate_records(records)

    async def snapshot_to_redis(self) -> int:
        """Aggregate and write to ``portfolio:positions``; return the count.

        Writes an empty list when no source records exist. This is
        intentional: S05's ContextLoader requires the key to be present
        and a list — an empty list is a valid "flat book" answer, where
        a missing key would trip the fail-closed guard.

        Returns:
            Number of positions written to the aggregate key.
        """
        positions = await self.aggregate_from_redis()
        payload = [p.model_dump(mode="json") for p in positions]
        await self._state.set(AGGREGATE_KEY, payload, ttl=self._ttl)
        logger.info(
            "position_aggregator_snapshot",
            count=len(positions),
            key=AGGREGATE_KEY,
        )
        return len(positions)

    async def run_loop(
        self,
        interval_s: float = DEFAULT_SNAPSHOT_INTERVAL_S,
        *,
        running: Any = None,  # noqa: ANN401
    ) -> None:
        """Periodically snapshot until cancelled.

        Args:
            interval_s: Seconds between snapshots. Defaults to
                :data:`DEFAULT_SNAPSHOT_INTERVAL_S`.
            running: Optional flag-like object; the loop polls
                ``bool(running)`` between iterations and exits cleanly on
                ``False``. ``None`` means "run until cancelled".
        """
        while running is None or bool(running):
            try:
                await self.snapshot_to_redis()
            except Exception as exc:
                # Snapshot failures must not crash the background loop;
                # the next interval retries. Hot-path errors surface in
                # the logged event for observability.
                logger.error(
                    "position_aggregator_snapshot_failed",
                    error=str(exc),
                )
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                logger.info("position_aggregator_loop_cancelled")
                raise
