"""Centralized ZeroMQ topic constants for the APEX Trading System.

ALL ZMQ topics must be defined here.
Services must import from this module — never hardcode topic strings.

Topic convention: hierarchical, dot-delimited segments. The leading two
segments identify the channel family (``{category}.{subcategory}``), and
the number of trailing segments varies per channel. Examples:

- 3 segments: ``tick.crypto.BTCUSDT``, ``service.health.data_ingestion``,
  ``macro.catalyst.FOMC``.
- 3 segments (legacy, single-strategy): ``signal.technical.BTCUSDT`` —
  emitted by the deprecated :meth:`Topics.signal` helper.
- 4 segments (per-strategy, Phase A onwards): ``signal.technical.<strategy_id>.<symbol>``
  — emitted by :meth:`Topics.signal_for` per Charter §5.5 and ADR-0007 §D7.
"""

from __future__ import annotations

import warnings

_STRATEGY_ID_FORBIDDEN_CHARS: tuple[str, ...] = ("/", "\\", "'", '"')
_STRATEGY_ID_MAX_LEN: int = 64


class Topics:
    """ZeroMQ topic string constants. Import this class; never use string literals."""

    # ── Data ingestion (S01) ─────────────────────────────────────────────────
    TICK_CRYPTO: str = "tick.crypto"  # e.g. tick.crypto.BTCUSDT
    TICK_EQUITY: str = "tick.us_equity"  # e.g. tick.us_equity.AAPL
    TICK_FUTURES: str = "tick.futures"
    MACRO_UPDATE: str = "macro.update"

    # ── Signal engine (S02) ──────────────────────────────────────────────────
    SIGNAL_TECHNICAL: str = "signal.technical"  # e.g. signal.technical.BTCUSDT
    SIGNAL_VALIDATED: str = "signal.validated"

    # ── Regime detector (S03) ────────────────────────────────────────────────
    REGIME_UPDATE: str = "regime.update"
    MACRO_CATALYST: str = "macro.catalyst"  # e.g. macro.catalyst.FOMC
    SESSION_PATTERN: str = "session.pattern"  # e.g. session.pattern.US_OPEN

    # ── Order lifecycle (S04 → S05 → S06) ────────────────────────────────────
    ORDER_CANDIDATE: str = "order.candidate"
    ORDER_APPROVED: str = "order.approved"
    ORDER_BLOCKED: str = "order.blocked"
    ORDER_SUBMITTED: str = "order.submitted"
    ORDER_FILLED: str = "order.filled"
    ORDER_CANCELLED: str = "order.cancelled"
    ORDER_PARTIAL: str = "order.partial"

    # ── Risk (S05) ───────────────────────────────────────────────────────────
    RISK_BREACH: str = "risk.breach"
    CIRCUIT_OPEN: str = "risk.circuit_open"
    CIRCUIT_CLOSED: str = "risk.circuit_closed"
    RISK_APPROVED: str = "risk.approved"  # RiskDecision published (approved=True)
    RISK_BLOCKED: str = "risk.blocked"  # RiskDecision published (approved=False)
    RISK_CB_TRIPPED: str = "risk.cb.tripped"  # Circuit breaker state change notification
    RISK_AUDIT: str = "risk.audit"  # Full audit stream (all decisions)
    # Fail-closed guard transitions (ADR-0006)
    RISK_SYSTEM_STATE_CHANGE: str = "risk.system.state_change"

    # ── Service health (all services → supervisor) ────────────────────────────
    SERVICE_HEALTH: str = "service.health"  # e.g. service.health.data_ingestion

    # ── Analytics (S07, S04) ─────────────────────────────────────────────────
    ANALYTICS_UPDATE: str = "analytics.update"
    ANALYTICS_META_FEATURES: str = "analytics.meta_features"  # MetaLabeler decisions (S04)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def tick(market: str, symbol: str) -> str:
        """Build a tick topic string.

        Example::

            Topics.tick('crypto', 'BTCUSDT') == 'tick.crypto.BTCUSDT'

        Args:
            market: Market identifier, e.g. ``'crypto'`` or ``'us_equity'``.
            symbol: Trading symbol (will be uppercased).

        Returns:
            Full ZMQ topic string.
        """
        return f"tick.{market}.{symbol.upper()}"

    @staticmethod
    def signal(symbol: str) -> str:
        """Build a legacy single-strategy signal topic string.

        Deprecated since Phase A (Roadmap §2.2.2): use
        :meth:`Topics.signal_for` so consumers can route per ``strategy_id``.
        Retained for backward compatibility with the LegacyConfluenceStrategy
        path until Phase B migrates it to ``signal_for("default", symbol)``.

        Args:
            symbol: Trading symbol (will be uppercased).

        Returns:
            Full ZMQ topic string, e.g. ``'signal.technical.BTCUSDT'``.
        """
        warnings.warn(
            "Topics.signal(symbol) is deprecated; migrate callers to "
            "Topics.signal_for('default', symbol) for the legacy "
            "single-strategy path. Scheduled for removal once Phase B "
            "wraps the legacy flow as LegacyConfluenceStrategy.",
            DeprecationWarning,
            stacklevel=2,
        )
        return f"signal.technical.{symbol.upper()}"

    @staticmethod
    def signal_for(strategy_id: str, symbol: str) -> str:
        """Build a per-strategy signal topic string.

        Per Charter §5.5 and ADR-0007 §D7, every strategy publishes its
        Signals on a dedicated ZMQ topic so downstream consumers can subscribe
        per-strategy or broadly via the ``signal.technical.`` prefix.

        Example::

            Topics.signal_for('crypto_momentum', 'BTCUSDT')
                == 'signal.technical.crypto_momentum.BTCUSDT'

        Sanitization mirrors the ``Signal`` Pydantic model validator
        (Roadmap §2.2.2): empty/whitespace identifiers, identifiers
        containing path or quote characters, and identifiers exceeding
        64 characters are rejected. Symbols must be non-empty and free
        of whitespace.

        Args:
            strategy_id: Snake_case strategy identifier matching the folder
                ``services/strategies/<strategy_id>/``. Use ``'default'`` for
                the LegacyConfluenceStrategy path.
            symbol: Trading symbol (will be uppercased).

        Returns:
            Full ZMQ topic string, e.g.
            ``'signal.technical.crypto_momentum.BTCUSDT'``.

        Raises:
            ValueError: If ``strategy_id`` or ``symbol`` fails validation.
        """
        if not isinstance(strategy_id, str) or not strategy_id or not strategy_id.strip():
            raise ValueError(
                f"strategy_id must be a non-empty, non-whitespace string; got {strategy_id!r}"
            )
        if any(c.isspace() for c in strategy_id):
            raise ValueError(f"strategy_id must not contain whitespace; got {strategy_id!r}")
        for forbidden in _STRATEGY_ID_FORBIDDEN_CHARS:
            if forbidden in strategy_id:
                raise ValueError(f"strategy_id must not contain {forbidden!r}; got {strategy_id!r}")
        if len(strategy_id) > _STRATEGY_ID_MAX_LEN:
            raise ValueError(
                f"strategy_id length {len(strategy_id)} exceeds max "
                f"{_STRATEGY_ID_MAX_LEN}; got {strategy_id!r}"
            )
        if not isinstance(symbol, str) or not symbol or not symbol.strip():
            raise ValueError(f"symbol must be a non-empty, non-whitespace string; got {symbol!r}")
        if any(c.isspace() for c in symbol):
            raise ValueError(f"symbol must not contain whitespace; got {symbol!r}")
        return f"signal.technical.{strategy_id}.{symbol.upper()}"

    @staticmethod
    def health(service_id: str) -> str:
        """Build a service health topic string.

        Args:
            service_id: Service identifier, e.g. ``'data_ingestion'``.

        Returns:
            Full ZMQ topic string.
        """
        return f"service.health.{service_id}"

    @staticmethod
    def catalyst(event_type: str) -> str:
        """Build a macro catalyst topic string.

        Args:
            event_type: Event type identifier (will be uppercased), e.g. ``'FOMC'``.

        Returns:
            Full ZMQ topic string.
        """
        return f"macro.catalyst.{event_type.upper()}"
