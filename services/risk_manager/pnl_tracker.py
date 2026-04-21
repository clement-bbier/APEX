"""Pre-trade PnL reader with per-strategy dual-key Redis fallback.

Phase A.8 (issue #198, Roadmap v3.0 §2.2.4, ADR-0007 §D9).

Design rationale
----------------
This is the **pre-trade** PnL reader, consumed by the S05 Risk Manager
gate chain. It is strictly separate from
:mod:`services.command_center.pnl_tracker` (reporting tracker feeding the
dashboard). Separation follows the Millennium / Citadel pod pattern:
pre-trade risk paths never share code with reporting paths so a bug in
one cannot block or corrupt the other.

**SLA distinction**

- Pre-trade path (this module): millisecond-scale reads, **fail-loud**
  on malformed data (ADR-0006 §D4). A corrupted payload MUST surface as
  :class:`RuntimeError` so the fail-closed guard rejects the order
  rather than sizing on garbage.
- Reporting path (``command_center.pnl_tracker``): seconds-scale SLA,
  eventual consistency tolerated, aggregates from ``trades:all`` list.

Audit finding (2026-04-20)
--------------------------
Grep of the repo for ``pnl:daily`` / ``pnl:24h``:

- **Writer of ``pnl:daily``**: **no production writer exists yet**.
  The key is an "orphan read" consumed by
  :class:`services.risk_manager.context_loader.ContextLoader` (line 74)
  and seeded only by test fixtures
  (``tests/unit/risk_manager/test_service_no_fallbacks.py:82`` and
  ``tests/unit/risk_manager/test_risk_chain.py:95``) which use
  ``redis.set("pnl:daily", "0")``. The S05 Fail-Closed guard
  (ADR-0006 §D1) currently shields production from the missing writer;
  the real writer lands in Phase B (S09 FeedbackLoop aggregation).
- **Writer of ``pnl:24h``**: **does not exist anywhere in the codebase
  today**. Introduced here as a reserved key so the Phase B writer can
  target the per-strategy primary directly.
- **Storage API**: :meth:`core.state.StateStore.set` is the only write
  primitive on the pre-trade path. It encodes the payload via
  ``json.dumps(value, default=str)`` under a Redis ``STRING`` (not a
  ``HASH``). :meth:`core.state.StateStore.get` mirrors it with
  ``json.loads`` on the raw value. See ``core/state.py:121`` +
  ``core/state.py:136``.
- **Payload shape**: unlike ``portfolio:capital`` (which is a dict
  ``{"available": <amount>}``), the PnL keys are encoded as **scalars**
  — a JSON number or numeric string. ``ContextLoader`` consumes them as
  ``Decimal(str(results[1]))`` directly (line 74), confirming the
  scalar contract.

Reader API decision
-------------------
Given the writer uses ``state.set(...)`` (STRING-with-JSON), this
tracker reads via ``state.get(key)`` and expects a **scalar numeric**
payload (JSON number, numeric string, or any value accepted by
``Decimal(str(...))``). Malformed payloads surface as
:class:`RuntimeError` with the resolved key + ``strategy_id`` embedded,
so post-Phase-B audits can locate the offending producer.

Fix
---
Dual-key read mirrors :class:`services.risk_manager.portfolio_tracker.PortfolioTracker`
(PR #210, ``92cf12a`` + fix ``e5eba7c``):

1. **Primary**  -- ``pnl:{strategy_id}:daily`` (or ``:24h``).
2. **Fallback** -- ``pnl:daily`` (or ``pnl:24h``) -- legacy unscoped.

On fallback the tracker emits a :mod:`structlog` WARNING
(``pnl_tracker.legacy_key_fallback``) carrying both keys and
``strategy_id`` so operators can audit the Phase-A → Phase-B cutover.
Once the Phase B writer populates the per-strategy key, fallback hits
drop to zero and the legacy branch dies naturally.

Wiring
------
This module is **new** and not wired into any consumer. ContextLoader
still reads ``pnl:daily`` directly; swapping it to this tracker is a
Phase B follow-up tracked alongside the S09 writer introduction.

Shared helper
-------------
A grep across ``core/`` and ``services/`` confirms no reusable dual-read
helper exists today (``portfolio_tracker`` and ``kelly_sizer`` each
open-code the pattern). Extraction is intentionally deferred: with a
third inline instance, a refactor to ``core/redis_dual_read.py`` becomes
economically justified, but this sprint preserves the proven pattern.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from core.logger import get_logger

logger = get_logger("risk_manager.pnl_tracker")

LEGACY_DAILY_KEY = "pnl:daily"
"""Legacy unscoped Redis key for daily PnL. Written by pre-Phase-B producers only."""

LEGACY_24H_KEY = "pnl:24h"
"""Legacy unscoped Redis key for trailing 24h PnL. Written by pre-Phase-B producers only."""

DEFAULT_STRATEGY_ID = "default"
"""Strategy scope used when callers haven't migrated to per-strategy calls."""


class _StateReader(Protocol):
    """Duck-type for the subset of :class:`core.state.StateStore` used here."""

    async def get(self, key: str) -> Any | None: ...  # noqa: ANN401


class PnLTracker:
    """Dual-key Redis reader for pre-trade PnL (daily + trailing 24h).

    Args:
        state: Any object exposing an awaitable ``get(key: str)`` method
            that returns the JSON-deserialized scalar payload or
            ``None`` on miss. :class:`core.state.StateStore` satisfies
            this protocol in production; a ``fakeredis``-backed adapter
            satisfies it in unit tests.
    """

    # TODO(Phase B): Add staleness check once the S09 FeedbackLoop writer
    # defines its cadence. The reader will verify Redis TTL or a sidecar
    # timestamp key (pnl:{strategy_id}:daily:ts) and raise PnLStale if
    # data is older than the writer's expected refresh interval.

    def __init__(self, state: _StateReader) -> None:
        self._state = state

    @staticmethod
    def primary_daily_key(strategy_id: str) -> str:
        """Return the per-strategy primary key for daily PnL.

        Exposed so callers (and tests) can write the same key the
        tracker will read back -- single source of truth for the key
        format.
        """
        return f"pnl:{strategy_id}:daily"

    @staticmethod
    def primary_24h_key(strategy_id: str) -> str:
        """Return the per-strategy primary key for trailing 24h PnL."""
        return f"pnl:{strategy_id}:24h"

    async def _resolve(
        self,
        *,
        primary_key: str,
        legacy_key: str,
        strategy_id: str,
    ) -> tuple[str | None, Any | None]:
        """Perform the dual-key read and report which key produced the payload.

        Returns:
            ``(resolved_key, payload)``. ``resolved_key`` is the primary
            key on a primary hit, the legacy key on fallback, and
            ``None`` when both keys miss (``payload`` is also ``None``).
        """
        primary_value = await self._state.get(primary_key)
        if primary_value is not None:
            return primary_key, primary_value

        legacy_value = await self._state.get(legacy_key)
        if legacy_value is not None:
            logger.warning(
                "pnl_tracker.legacy_key_fallback",
                strategy_id=strategy_id,
                legacy_key=legacy_key,
                new_key=primary_key,
            )
            return legacy_key, legacy_value

        return None, None

    async def get_daily_pnl(
        self,
        *,
        strategy_id: str = DEFAULT_STRATEGY_ID,
    ) -> Decimal | None:
        """Return current daily PnL as :class:`Decimal` (never float).

        Dual-key read: primary ``pnl:{strategy_id}:daily`` then legacy
        ``pnl:daily`` fallback with structlog WARNING on fallback.

        Args:
            strategy_id: Per-strategy scope. Defaults to ``"default"``
                to preserve Phase A call-site behavior.

        Returns:
            Daily PnL as :class:`Decimal`, or ``None`` if neither key
            resolved.

        Raises:
            RuntimeError: If a payload was returned but cannot be
                converted to :class:`Decimal` (fail-loud per
                ADR-0006 §D4). The message embeds the resolved key
                (primary vs legacy) and ``strategy_id`` so post-Phase-B
                audits can locate the offending producer.
        """
        return await self._read_scalar(
            primary_key=self.primary_daily_key(strategy_id),
            legacy_key=LEGACY_DAILY_KEY,
            strategy_id=strategy_id,
            field="daily",
        )

    async def get_24h_pnl(
        self,
        *,
        strategy_id: str = DEFAULT_STRATEGY_ID,
    ) -> Decimal | None:
        """Return trailing 24h PnL as :class:`Decimal` (never float).

        Same dual-read + fail-loud contract as :meth:`get_daily_pnl`
        but for the ``:24h`` key family.
        """
        return await self._read_scalar(
            primary_key=self.primary_24h_key(strategy_id),
            legacy_key=LEGACY_24H_KEY,
            strategy_id=strategy_id,
            field="24h",
        )

    async def _read_scalar(
        self,
        *,
        primary_key: str,
        legacy_key: str,
        strategy_id: str,
        field: str,
    ) -> Decimal | None:
        """Shared scalar-Decimal conversion used by the daily + 24h getters."""
        resolved_key, payload = await self._resolve(
            primary_key=primary_key,
            legacy_key=legacy_key,
            strategy_id=strategy_id,
        )
        if payload is None:
            return None
        if isinstance(payload, bool):
            # Guard against ``True``/``False`` being silently coerced to
            # ``Decimal("1")`` / ``Decimal("0")``: booleans are never a
            # valid PnL payload; fail loud.
            raise RuntimeError(
                f"pnl {field} payload non-numeric at key={resolved_key!r} "
                f"strategy_id={strategy_id!r}: {payload!r}"
            )
        try:
            return Decimal(str(payload))
        except (InvalidOperation, ValueError) as exc:
            raise RuntimeError(
                f"pnl {field} payload non-numeric at key={resolved_key!r} "
                f"strategy_id={strategy_id!r}: {payload!r}"
            ) from exc
