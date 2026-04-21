"""Pre-trade context batch-loader for S05 Risk Manager.

Extracted from ``service.py`` as part of the Batch D SOLID-S decomposition
(STRATEGIC_AUDIT_2026-04-17 ACTION 25). Loads the eight pre-trade context
keys from Redis in parallel; raises :class:`RuntimeError` on any
missing / malformed key per ADR-0006 §D4 (fail-loud).

.. note::

   The eight Redis keys read here are currently orphan reads — no
   production writer exists (see
   ``docs/audits/REDIS_KEYS_WRITER_AUDIT_2026-04-17.md``). Phase 5.2
   (PHASE_5_SPEC_v2 §3.2) introduces the required producers and rewires
   this loader to read from an in-memory state machine. Until 5.2 ships,
   the 5.1 Fail-Closed guard (STEP 0 in the chain) shields production
   from those missing writers.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from core.logger import get_logger
from core.models.tick import Session
from services.risk_manager.models import Position

logger = get_logger("risk_manager.context_loader")

REQUIRED_KEYS: tuple[str, ...] = (
    "portfolio:capital",
    "pnl:daily",
    "pnl:intraday_30m",
    "macro:vix_current",
    "macro:vix_1h_ago",
    "portfolio:positions",
    "correlation:matrix",
    "session:current",
)


class ContextLoader:
    """Batches the eight pre-trade context Redis reads used by S05.

    The loader exposes a single :meth:`load` method that returns the same
    ``dict`` shape formerly produced by ``_load_context_parallel``. A future
    5.2 refactor replaces this class with an in-memory state reader; until
    then, the public API is preserved so existing tests keep passing.

    Args:
        state: Any object exposing an awaitable ``get(key: str) -> Any``
            method (the :class:`core.state.StateStore` in production).
    """

    def __init__(self, state: Any) -> None:  # noqa: ANN401
        self._state = state

    async def load(self, symbol: str) -> dict[str, Any]:
        """Load pre-trade context for ``symbol``.

        Raises:
            RuntimeError: If any required key is missing, None, or malformed
                (ADR-0006 §D4 fail-loud contract).
        """
        _ = symbol  # future-compat: symbol-scoped reads in 5.2
        results = await asyncio.gather(*(self._state.get(k) for k in REQUIRED_KEYS))

        cap_raw = self._require("portfolio:capital", results[0])
        if not isinstance(cap_raw, dict) or "available" not in cap_raw:
            raise RuntimeError(f"portfolio:capital malformed: {cap_raw!r}")
        capital = Decimal(str(cap_raw["available"]))

        daily_pnl = Decimal(str(self._require("pnl:daily", results[1])))
        intraday_30m = Decimal(str(self._require("pnl:intraday_30m", results[2])))
        vix_current = float(self._require("macro:vix_current", results[3]))
        vix_1h_ago = float(self._require("macro:vix_1h_ago", results[4]))

        raw_pos = self._require("portfolio:positions", results[5])
        if not isinstance(raw_pos, list):
            raise RuntimeError(
                f"portfolio:positions malformed: expected list, got {type(raw_pos).__name__}"
            )
        positions: list[Position] = []
        for p in raw_pos:
            try:
                positions.append(Position.model_validate(p))
            except Exception as exc:
                # Per-element parse failure is not fatal (broker feeds may
                # include unknown-type entries); log and skip.
                logger.debug("position_decode_failed", error=str(exc))

        corr_raw = self._require("correlation:matrix", results[6])
        if not isinstance(corr_raw, dict):
            raise RuntimeError(
                f"correlation:matrix malformed: expected dict, got {type(corr_raw).__name__}"
            )
        corr: dict[tuple[str, str], float] = {}
        for k, v in corr_raw.items():
            parts = str(k).split(":")
            if len(parts) != 2:
                continue
            try:
                corr[(parts[0], parts[1])] = float(v)
            except (ValueError, TypeError) as exc:
                logger.debug("correlation_decode_failed", key=str(k), error=str(exc))

        session_raw = self._require("session:current", results[7])
        try:
            session: Session = Session(str(session_raw))
        except ValueError as exc:
            raise RuntimeError(f"session:current invalid value: {session_raw!r}") from exc

        return {
            "capital": capital,
            "daily_pnl": daily_pnl,
            "intraday_loss_30m": intraday_30m,
            "vix_current": vix_current,
            "vix_1h_ago": vix_1h_ago,
            "service_last_seen": {},
            "positions": positions,
            "correlation_matrix": corr,
            "session": session,
        }

    @staticmethod
    def _require(name: str, value: Any) -> Any:  # noqa: ANN401
        if value is None:
            raise RuntimeError(f"required pre-trade context key missing or None: {name}")
        return value
