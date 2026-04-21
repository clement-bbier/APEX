"""MetaFeatureLogger — Persists every MetaLabelDecision for future ML training.

Each decision (TRADE or NO-TRADE) is logged with its full feature vector.
After 3 months of paper trading, this creates a ~5,000-15,000 row training
dataset for a supervised binary classifier (MetaLabeler v2).

Dual persistence strategy:
    1. ZMQ topic ``analytics.meta_features`` (Topics.ANALYTICS_META_FEATURES)
       → real-time consumers (S09 FeedbackLoop, S10 Dashboard)
    2. Redis LPUSH ``meta_label_history`` (capped at 500 entries)
       → sliding window for Dashboard queries

TimescaleDB schema (created by migration, filled async by S09):
    CREATE TABLE IF NOT EXISTS meta_label_log (
        ts_utc               TIMESTAMPTZ NOT NULL,
        symbol               TEXT NOT NULL,
        signal_strength      REAL,
        n_triggers           INT,
        hurst_exponent       REAL,
        vpin                 REAL,
        har_rv_vol           REAL,
        spread_bps           REAL,
        session_mult         REAL,
        macro_mult           REAL,
        kyle_lambda          REAL,
        meta_decision        BOOLEAN,
        meta_score           REAL,
        confidence           REAL,
        blocking_reason      TEXT,
        triple_barrier_label SMALLINT DEFAULT NULL  -- filled later by S09
    );
    SELECT create_hypertable('meta_label_log', 'ts_utc', if_not_exists => TRUE);

Design constraints:
    - Fire-and-forget: exceptions NEVER propagate into S04's hot path.
    - All I/O is async; no blocking calls.
    - Latency budget: << 1 ms (ZMQ + Redis are non-blocking by design).

References:
    López de Prado, M. (2018). Advances in Financial Machine Learning.
        Wiley. Chapter 3, Section 3.6 (Meta-Labeling). Cornell → AQR.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from core.bus import MessageBus
from core.state import StateStore
from core.topics import Topics
from services.fusion_engine.meta_labeler import MetaFeatures, MetaLabelDecision

logger = structlog.get_logger(__name__)


class MetaFeatureLogger:
    """Log every MetaLabelDecision for offline ML training.

    Publishes on ZMQ and pushes to Redis — both fire-and-forget.
    Failures at either layer are logged at WARNING but never raised.

    Attributes:
        REDIS_KEY:     Redis list key for sliding history window.
        REDIS_MAX_LEN: Maximum number of entries kept in Redis.
    """

    REDIS_KEY: str = "meta_label_history"
    REDIS_MAX_LEN: int = 500

    def __init__(self, bus: MessageBus, state: StateStore) -> None:
        """Initialize the logger.

        Args:
            bus:   ZMQ MessageBus (must have publisher initialized).
            state: Redis StateStore (must be connected).
        """
        self._bus = bus
        self._state = state

    async def log(
        self,
        symbol: str,
        features: MetaFeatures,
        decision: MetaLabelDecision,
        ts: datetime | None = None,
    ) -> None:
        """Publish and persist one meta-label decision.

        Both the ZMQ publish and Redis push are wrapped in try/except so
        that a failure in logging NEVER blocks S04's hot path.

        Args:
            symbol:   Trading symbol, e.g. ``'BTCUSDT'``.
            features: Feature vector that produced the decision.
            decision: MetaLabeler output (TRADE or NO-TRADE).
            ts:       Decision timestamp; defaults to ``datetime.now(UTC)``.
        """
        ts = ts or datetime.now(UTC)

        payload: dict[str, Any] = {
            "ts_utc": ts.isoformat(),
            "symbol": symbol,
            "features": {
                "signal_strength": features.signal_strength,
                "n_triggers": features.n_triggers,
                "hurst_exponent": features.hurst_exponent,
                "vpin": features.vpin,
                "har_rv_forecast_vol": features.har_rv_forecast_vol,
                "spread_bps": features.spread_bps,
                "session_mult": features.session_mult,
                "macro_mult": features.macro_mult,
                "kyle_lambda": features.kyle_lambda,
            },
            "meta_decision": decision.should_trade,
            "meta_score": decision.meta_score,
            "confidence": decision.confidence,
            "blocking_reason": decision.blocking_reason,
            # filled later by S09 after trade resolution via Triple Barrier
            "triple_barrier_label": None,
        }

        # ZMQ publish — fire-and-forget
        try:
            await self._bus.publish(Topics.ANALYTICS_META_FEATURES, payload)
        except Exception as exc:
            logger.warning("meta_zmq_failed", symbol=symbol, error=str(exc))

        # Redis push — fire-and-forget; cap at REDIS_MAX_LEN
        try:
            await self._state.lpush(self.REDIS_KEY, payload)
            await self._state.ltrim(self.REDIS_KEY, 0, self.REDIS_MAX_LEN - 1)
        except Exception as exc:
            logger.warning("meta_redis_failed", symbol=symbol, error=str(exc))
