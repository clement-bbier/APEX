"""Portfolio-capital reader with per-strategy dual-key Redis fallback.

Phase A.7 (issue #197, Roadmap v3.0 §2.2.4, ADR-0007 §D9).

Audit finding (2026-04-20)
--------------------------
Prior to this module, the S05 pre-trade context loader
(:mod:`services.s05_risk_manager.context_loader`) reads the
``portfolio:capital`` Redis key directly and **unscoped**. Per ADR-0007 §D9
the Phase B topology migrates every order-path writer to a per-strategy
key (``portfolio:{strategy_id}:capital``). Once Phase B writers cut over,
the legacy unscoped key stops being updated -- a reader that keeps
consulting it silently returns **stale data** (an "orphan read").

Fix
---
:class:`PortfolioTracker` performs a dual-key read:

1. **Primary**  -- ``portfolio:{strategy_id}:capital`` (Phase B target).
2. **Fallback** -- ``portfolio:capital`` (legacy, Phase A).

On fallback the tracker emits a :mod:`structlog` WARNING
(``portfolio_tracker.legacy_key_fallback``) to give operators an audit
trail of legacy hits throughout the Phase A -> Phase B migration. Once
Phase B writers populate the per-strategy key, fallback hits drop to zero
and the legacy branch dies naturally.

During Phase A, callers that omit ``strategy_id`` transparently keep
their current behavior (``strategy_id="default"``) because the fallback
preserves the pre-fix payload. No existing call site is broken by
wiring this tracker in (follow-up PR).

Compliance notes
----------------
- CLAUDE.md Section 2: :class:`Decimal` (never float) for money;
  :mod:`structlog` only; no ``threading.Thread`` / ``print`` /
  ``datetime.now()`` without UTC.
- CLAUDE.md Section 10: deserialization errors surface as
  :class:`RuntimeError` (fail-loud per ADR-0006 D4), not silently
  swallowed.

Wiring
------
This module is **new** and not yet consumed. The follow-up that replaces
the raw ``portfolio:capital`` read in
:class:`services.s05_risk_manager.context_loader.ContextLoader.load` with
a :class:`PortfolioTracker` call is tracked as a dedicated micro-PR -- or
naturally bundled into the Phase B ``LegacyConfluenceStrategy`` wrap.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from core.logger import get_logger

logger = get_logger("s05_risk_manager.portfolio_tracker")

LEGACY_CAPITAL_KEY = "portfolio:capital"
"""Legacy unscoped Redis key. Written by pre-Phase-B producers only."""

DEFAULT_STRATEGY_ID = "default"
"""Strategy scope used when callers haven't migrated to per-strategy calls."""


class _StateReader(Protocol):
    """Duck-type for the subset of :class:`core.state.StateStore` used here."""

    async def get(self, key: str) -> Any | None: ...  # noqa: ANN401


class PortfolioTracker:
    """Dual-key Redis reader for the ``portfolio:capital`` snapshot.

    Args:
        state: Any object exposing an awaitable ``get(key: str)`` method
            that returns the JSON-deserialized payload or ``None`` on
            miss. :class:`core.state.StateStore` satisfies this protocol
            in production; a ``fakeredis``-backed adapter satisfies it
            in unit tests (see ``tests/unit/s05/test_portfolio_tracker.py``).
    """

    def __init__(self, state: _StateReader) -> None:
        self._state = state

    @staticmethod
    def primary_key(strategy_id: str) -> str:
        """Return the per-strategy primary key for ``strategy_id``.

        Exposed so callers (and tests) can write the same key the tracker
        will read back -- single source of truth for the key format.
        """
        return f"portfolio:{strategy_id}:capital"

    async def read_raw(
        self,
        *,
        strategy_id: str = DEFAULT_STRATEGY_ID,
    ) -> Any | None:  # noqa: ANN401
        """Read the raw capital payload with dual-key fallback.

        Algorithm:
            1. Attempt the primary per-strategy key
               (``portfolio:{strategy_id}:capital``). On hit, return the
               payload immediately -- no fallback, no warning.
            2. On miss, attempt the legacy unscoped key
               (``portfolio:capital``). On hit, emit a structlog WARNING
               (``portfolio_tracker.legacy_key_fallback``) with both keys
               and ``strategy_id`` for the audit trail, then return the
               legacy payload.
            3. If both keys miss, return ``None`` so the caller's
               fail-loud contract (ADR-0006 D4) decides whether to
               raise.

        Args:
            strategy_id: Per-strategy scope. Defaults to ``"default"`` to
                preserve Phase A call-site behavior.

        Returns:
            The JSON-deserialized payload (typically a ``dict`` with an
            ``available`` key) or ``None`` if neither key resolves.
        """
        _, payload = await self._resolve(strategy_id=strategy_id)
        return payload

    async def _resolve(
        self,
        *,
        strategy_id: str,
    ) -> tuple[str | None, Any | None]:
        """Perform the dual-key read and report which key produced the payload.

        Returns:
            ``(resolved_key, payload)``. ``resolved_key`` is the primary key
            on a primary hit, the legacy key on fallback, and ``None`` when
            both keys miss (``payload`` is also ``None`` in that case).
        """
        primary = self.primary_key(strategy_id)
        primary_value = await self._state.get(primary)
        if primary_value is not None:
            return primary, primary_value

        legacy_value = await self._state.get(LEGACY_CAPITAL_KEY)
        if legacy_value is not None:
            logger.warning(
                "portfolio_tracker.legacy_key_fallback",
                strategy_id=strategy_id,
                legacy_key=LEGACY_CAPITAL_KEY,
                new_key=primary,
            )
            return LEGACY_CAPITAL_KEY, legacy_value

        return None, None

    async def get_capital(
        self,
        *,
        strategy_id: str = DEFAULT_STRATEGY_ID,
    ) -> Decimal | None:
        """Return the available capital as :class:`Decimal` (never float).

        Thin convenience wrapper around :meth:`read_raw`. Validates that
        the payload is a ``dict`` carrying an ``available`` entry and
        converts that entry to :class:`Decimal` via ``str(...)`` to avoid
        binary-float rounding, per CLAUDE.md Section 2.

        Args:
            strategy_id: Per-strategy scope (see :meth:`read_raw`).

        Returns:
            Available capital as :class:`Decimal`, or ``None`` if neither
            key resolved.

        Raises:
            RuntimeError: If a payload was returned but is malformed
                (not a ``dict`` / missing ``available`` / non-numeric).
                Fail-loud per ADR-0006 D4. The error message includes the
                resolved key (primary vs legacy) and ``strategy_id`` so
                post-Phase-B audits can locate the offending producer.
        """
        resolved_key, payload = await self._resolve(strategy_id=strategy_id)
        if payload is None:
            return None
        if not isinstance(payload, dict) or "available" not in payload:
            raise RuntimeError(
                f"portfolio capital malformed at key={resolved_key!r} "
                f"strategy_id={strategy_id!r}: {payload!r}"
            )
        try:
            return Decimal(str(payload["available"]))
        except (InvalidOperation, ValueError) as exc:
            raise RuntimeError(
                f"portfolio capital 'available' not numeric at "
                f"key={resolved_key!r} strategy_id={strategy_id!r}: "
                f"{payload['available']!r}"
            ) from exc
