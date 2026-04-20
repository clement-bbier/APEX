"""Kelly criterion position sizer for APEX Trading System - S04 Fusion Engine.

Reads per-symbol win-rate and average risk/reward statistics from Redis,
computes the quarter-Kelly fraction, and converts it into a concrete
position size adjusted for regime, session, market-impact, and asset class.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from core.config import get_settings
from core.state import StateStore

_logger = structlog.get_logger(__name__)


class KellySizer:
    """Compute Kelly-optimal position sizes from live trade statistics.

    Statistics are stored in Redis as HASHES (written by S09 FeedbackLoop
    via :meth:`StateStore.hset`) under the per-strategy key
    ``kelly:{strategy_id}:{symbol}`` (primary) with a fallback read from the
    legacy single-strategy key ``kelly:{symbol}`` during the Phase A migration
    window (Roadmap v3.0 §2.2.5, ADR-0007 §D9). If neither key is present the
    safe defaults ``win_rate=0.5``, ``avg_rr=1.5`` are used.

    Storage shape: each key is a Redis HASH with fields ``win_rate`` and
    ``avg_rr`` (see ``services/s09_feedback_loop/service.py`` _fast_analysis).
    The reader therefore issues ``hgetall`` — issuing a plain ``GET`` against
    the same key would raise ``WRONGTYPE`` at runtime.

    The writer-side migration (S09 FeedbackLoop cutting over to the
    per-strategy primary key) lands in a follow-up ticket; this class is
    reader-side only.
    """

    # ── Statistics ────────────────────────────────────────────────────────────

    async def get_rolling_stats_from_redis(
        self,
        state: StateStore,
        strategy_key: str = "default",
    ) -> tuple[float, float]:
        """Fetch rolling win_rate and avg_rr from Redis.

        Written by S09 FeedbackLoop after every closed trade.

        Redis key: feedback:kelly_stats:{strategy_key}
        Expected: {"win_rate": 0.54, "avg_rr": 1.6, "n_trades": 47}

        Returns (win_rate, avg_rr) — defaults to conservative (0.50, 1.5) if no data.

        Args:
            state: Connected StateStore instance.
            strategy_key: Key suffix for multi-strategy isolation.

        Returns:
            (win_rate, avg_rr) with sanity-clamped values.
        """
        data: dict[str, Any] | None = await state.get(f"feedback:kelly_stats:{strategy_key}")

        if not isinstance(data, dict) or data.get("n_trades", 0) < 20:
            _logger.info(
                "kelly_using_defaults",
                reason="insufficient_trade_history",
                n_trades=data.get("n_trades", 0) if isinstance(data, dict) else 0,
            )
            return 0.50, 1.50

        win_rate = float(data["win_rate"])
        avg_rr = float(data["avg_rr"])

        # Sanity bounds — never trust extreme estimates
        win_rate = max(0.40, min(0.70, win_rate))
        avg_rr = max(1.0, min(4.0, avg_rr))

        return win_rate, avg_rr

    async def get_stats(
        self,
        state: StateStore,
        symbol: str,
        strategy_id: str = "default",
    ) -> tuple[float, float]:
        """Read win-rate and average risk/reward for ``symbol`` from Redis.

        Dual-read during Phase A migration (Roadmap v3.0 §2.2.5, ADR-0007 §D9):
        the per-strategy key ``kelly:{strategy_id}:{symbol}`` is tried first,
        and on empty-miss a fallback read against the legacy ``kelly:{symbol}``
        key is performed. Every legacy-path hit emits a structlog WARNING so
        the residual dependency on the legacy key is observable. When the S09
        writer migration lands and all legacy stats have aged out, the
        fallback branch (and this parameter) can be removed.

        Storage contract: S09 writes each key as a Redis HASH via
        :meth:`StateStore.hset`; the reader therefore uses
        :meth:`StateStore.hgetall` (which returns ``{}`` for a missing key),
        not ``get`` — the latter would raise ``WRONGTYPE`` against a hash.

        Fallback semantics: the legacy path is gated strictly on the primary
        HASH being empty (cache miss). A non-empty primary hash missing
        ``win_rate`` / ``avg_rr`` fields does **not** trigger fallback; the
        reader uses the in-dict values (or defaults) directly. Invalid
        values (non-numeric ``win_rate`` etc.) surface as ``ValueError`` via
        :func:`float` — fail-loud, mirroring :mod:`portfolio_tracker`.

        Args:
            state:       Connected :class:`~core.state.StateStore` instance.
            symbol:      Uppercase trading symbol.
            strategy_id: Per-strategy namespace; defaults to ``"default"`` to
                         preserve pre-migration behavior for existing callers.

        Returns:
            ``(win_rate, avg_rr)`` tuple.  Defaults: ``(0.5, 1.5)``.
        """
        new_key = f"kelly:{strategy_id}:{symbol}"
        legacy_key = f"kelly:{symbol}"

        primary: dict[str, Any] = await state.hgetall(new_key)

        if not primary:
            legacy: dict[str, Any] = await state.hgetall(legacy_key)
            if not legacy:
                return 0.5, 1.5
            _logger.warning(
                "kelly_sizer.legacy_key_fallback",
                strategy_id=strategy_id,
                symbol=symbol,
                legacy_key=legacy_key,
                new_key=new_key,
            )
            raw: dict[str, Any] = legacy
        else:
            raw = primary

        win_rate = float(raw.get("win_rate", 0.5))
        avg_rr = float(raw.get("avg_rr", 1.5))
        # Clamp to sensible ranges.
        win_rate = max(0.0, min(1.0, win_rate))
        avg_rr = max(0.01, avg_rr)
        return win_rate, avg_rr

    # ── Kelly formula ─────────────────────────────────────────────────────────

    def kelly_fraction(self, win_rate: float, avg_rr: float) -> float:
        """Compute the scaled Kelly fraction.

        Full Kelly formula:  f* = (p × b − q) / b
        where p = win_rate, b = avg_rr (reward-to-risk), q = 1 − p.

        The result is divided by ``settings.kelly_divisor`` (default 4) to
        produce a fractional-Kelly sizing, then capped at 0.25.

        Args:
            win_rate: Historical win probability in ``[0, 1]``.
            avg_rr:   Average reward-to-risk ratio.

        Returns:
            Scaled Kelly fraction in ``[0.0, 0.25]``.
        """
        settings = get_settings()
        p = win_rate
        q = 1.0 - p
        b = avg_rr
        full_kelly = (p * b - q) / b
        f_used = max(0.0, full_kelly) / settings.kelly_divisor
        return min(f_used, 0.25)

    # ── Position sizing ───────────────────────────────────────────────────────

    def position_size(
        self,
        capital: Decimal,
        kelly_f: float,
        regime_mult: float,
        session_mult: float,
        kyle_lambda: float,
        is_crypto: bool,
    ) -> Decimal:
        """Compute the final position size in quote-currency units.

        Adjustments applied (all multiplicative):
        - ``kelly_f``      : fraction of capital per Kelly sizing.
        - ``regime_mult``  : macro/vol regime factor.
        - ``session_mult`` : trading-session factor.
        - ``lambda_norm``  : market-impact penalty derived from Kyle lambda.
        - ``crypto_mult``  : 0.70 for crypto assets, 1.0 for equities.

        Hard cap: result is bounded at 10 % of ``capital``.

        Args:
            capital:      Total portfolio value in quote currency.
            kelly_f:      Quarter-Kelly fraction (output of :meth:`kelly_fraction`).
            regime_mult:  Regime multiplier in ``[0.0, 1.0]``.
            session_mult: Session multiplier.
            kyle_lambda:  Price-impact coefficient (higher → more illiquid).
            is_crypto:    ``True`` if the symbol is a crypto asset.

        Returns:
            Position size in quote-currency units, capped at 10 % of capital.
        """
        lambda_norm = max(0.1, min(1.0, 1.0 - kyle_lambda * 100.0))
        crypto_mult = Decimal("0.70") if is_crypto else Decimal("1.0")

        size = (
            capital
            * Decimal(str(kelly_f))
            * Decimal(str(regime_mult))
            * Decimal(str(session_mult))
            * Decimal(str(lambda_norm))
            * crypto_mult
        )

        max_size = capital * Decimal("0.10")
        return min(size, max_size)
