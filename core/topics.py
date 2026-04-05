"""Centralized ZeroMQ topic constants for the APEX Trading System.

ALL ZMQ topics must be defined here.
Services must import from this module — never hardcode topic strings.

Topic convention: {category}.{subcategory}.{identifier}
"""

from __future__ import annotations


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

    # ── Service health (all services → supervisor) ────────────────────────────
    SERVICE_HEALTH: str = "service.health"  # e.g. service.health.s01_data_ingestion

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
        """Build a signal topic string.

        Args:
            symbol: Trading symbol (will be uppercased).

        Returns:
            Full ZMQ topic string, e.g. ``'signal.technical.BTCUSDT'``.
        """
        return f"signal.technical.{symbol.upper()}"

    @staticmethod
    def health(service_id: str) -> str:
        """Build a service health topic string.

        Args:
            service_id: Service identifier, e.g. ``'s01_data_ingestion'``.

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
