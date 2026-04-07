"""
Meta-Label Gate -- Confidence-Weighted Kelly Modulation (Phase 6).

Integrates the MetaLabeler output into the risk chain as:
    1. A hard gate: if meta_confidence < MIN_META_CONFIDENCE_TO_TRADE (0.52) -> block
    2. A Kelly modulator: kelly_final = kelly_raw x confidence_weight(confidence)

Reads MetaLabeler confidence from Redis key meta_label:latest:{symbol}.
Key is written by S04 Fusion Engine after each MetaLabeler.predict() call.

If no meta-label data is available (system just started, < 100 ticks seen),
falls through with conservative confidence=0.52 (just above threshold).

Kelly modulation formula:
    weight(c) = max(0.0, (c - 0.5) / 0.5)

    c = 0.50 -> weight = 0.00 -> Kelly zeroed  (random performance = no bet)
    c = 0.75 -> weight = 0.50 -> Kelly halved  (moderate certainty)
    c = 1.00 -> weight = 1.00 -> full Kelly    (full confidence)

This implements linear shrinkage from full Kelly at c=1.0 to zero at c=0.5.
Equivalent to Bayesian update: uniform prior (bet=0) -> concentrated (full bet).

Reference:
    Lopez de Prado, M. (2018). AFML, Ch. 10: Bet Sizing.
    James, W. & Stein, C. (1961). Berkeley Symposium on Math Statistics, 1, 361-379.
    Bailey, D.H. & Lopez de Prado, M. (2012). Sharpe Ratio Efficient Frontier.
    Journal of Risk, 15(2), 3-44.
"""

from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis

from services.s05_risk_manager.models import (
    MIN_KELLY_FRACTION,
    MIN_META_CONFIDENCE_TO_TRADE,
    BlockReason,
    RuleResult,
)

_STARTUP_FALLBACK_CONFIDENCE: float = 0.52  # Conservative startup default
_META_LABEL_KEY_PREFIX: str = "meta_label:latest:"
_MAX_VALID_CONFIDENCE: float = 1.0
_MIN_VALID_CONFIDENCE: float = 0.0

logger = structlog.get_logger(__name__)


class MetaLabelGate:
    """Gate and Kelly modulator based on MetaLabeler confidence.

    Args:
        redis: Async Redis client instance.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(self, symbol: str, kelly_raw: float) -> tuple[RuleResult, float, float]:
        """Evaluate meta-label confidence and modulate Kelly fraction.

        Args:
            symbol:    Trading symbol (used to build Redis key).
            kelly_raw: Raw Kelly fraction from S04 sizing (before modulation).

        Returns:
            Tuple of (rule_result, meta_confidence, kelly_final).
            If rule_result.passed is False, kelly_final = 0.0.
        """
        meta_confidence = await self._get_meta_confidence(symbol)

        # Gate 1: Hard confidence threshold
        if meta_confidence < MIN_META_CONFIDENCE_TO_TRADE:
            return (
                RuleResult.fail(
                    rule_name="meta_label_gate",
                    block_reason=BlockReason.META_LABEL_CONFIDENCE_TOO_LOW,
                    reason=(
                        f"meta_confidence {meta_confidence:.3f} < "
                        f"threshold {MIN_META_CONFIDENCE_TO_TRADE}"
                    ),
                    meta_confidence=meta_confidence,
                ),
                meta_confidence,
                0.0,
            )

        # Kelly modulation: weight = max(0, (c - 0.5) / 0.5)
        weight = self._confidence_weight(meta_confidence)
        kelly_final = kelly_raw * weight

        # Gate 2: Minimum Kelly fraction after modulation
        if kelly_final < MIN_KELLY_FRACTION:
            return (
                RuleResult.fail(
                    rule_name="meta_label_gate",
                    block_reason=BlockReason.KELLY_FRACTION_TOO_SMALL,
                    reason=(
                        f"kelly_final {kelly_final:.4f} < min {MIN_KELLY_FRACTION} "
                        f"(kelly_raw={kelly_raw:.4f}, weight={weight:.3f})"
                    ),
                    kelly_final=kelly_final,
                    kelly_raw=kelly_raw,
                    weight=weight,
                ),
                meta_confidence,
                kelly_final,
            )

        return (
            RuleResult.ok(
                rule_name="meta_label_gate",
                reason=(
                    f"kelly {kelly_raw:.4f} x weight({meta_confidence:.3f}={weight:.3f}) "
                    f"= {kelly_final:.4f}"
                ),
            ),
            meta_confidence,
            kelly_final,
        )

    @staticmethod
    def _confidence_weight(confidence: float) -> float:
        """Linear shrinkage weight from Kelly towards zero.

        weight(c) = max(0.0, (c - 0.5) / 0.5)

        Properties:
            c = 0.50 -> weight = 0.00
            c = 0.75 -> weight = 0.50
            c = 1.00 -> weight = 1.00

        Args:
            confidence: MetaLabeler confidence in [0, 1].

        Returns:
            Shrinkage weight in [0.0, 1.0].
        """
        return max(0.0, (confidence - 0.5) / 0.5)

    async def _get_meta_confidence(self, symbol: str) -> float:
        """Retrieve MetaLabeler confidence from Redis.

        Returns _STARTUP_FALLBACK_CONFIDENCE (0.52) if key is not found
        or if data is corrupted -- prevents startup deadlock.

        Args:
            symbol: Trading symbol.

        Returns:
            Float confidence in [0.0, 1.0], clamped.
        """
        key = f"{_META_LABEL_KEY_PREFIX}{symbol}"
        try:
            raw = await self._redis.get(key)
            if raw is None:
                logger.debug(
                    "meta_label_not_found",
                    symbol=symbol,
                    fallback=_STARTUP_FALLBACK_CONFIDENCE,
                )
                return _STARTUP_FALLBACK_CONFIDENCE
            if isinstance(raw, (int, float)):
                confidence = float(raw)
            elif isinstance(raw, bytes):
                confidence = float(raw.decode())
            elif isinstance(raw, str):
                confidence = float(raw)
            else:
                data = json.loads(str(raw))
                if isinstance(data, dict):
                    confidence = float(data.get("confidence", _STARTUP_FALLBACK_CONFIDENCE))
                else:
                    confidence = float(data)
            # Clamp to [0, 1]
            return max(_MIN_VALID_CONFIDENCE, min(_MAX_VALID_CONFIDENCE, confidence))
        except Exception as exc:
            logger.warning("meta_label_parse_error", symbol=symbol, error=str(exc))
            return _STARTUP_FALLBACK_CONFIDENCE
