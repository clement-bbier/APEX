"""Price sanity check.

Validates OHLC consistency, detects non-positive prices, and flags
excessive intra-bar spreads.
"""

from __future__ import annotations

from decimal import Decimal

from core.logger import get_logger
from core.models.data import Asset, AssetClass, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.price_check")


class PriceCheck(QualityCheck):
    """Validate price fields for bars and ticks."""

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Check price sanity across a list of bars."""
        issues: list[QualityIssue] = []

        for bar in bars:
            # Non-positive close (allowed for futures if configured)
            if bar.close <= Decimal("0"):
                if asset.asset_class != AssetClass.FUTURE and not self._config.allow_negative_price:
                    issues.append(
                        QualityIssue(
                            check_type="price_non_positive",
                            severity=CheckResult.FAIL,
                            asset_id=asset.asset_id,
                            timestamp=bar.timestamp,
                            details={"close": str(bar.close)},
                        )
                    )
                    logger.warning("non_positive_price", asset=asset.symbol, close=str(bar.close))

            # High < Low
            if bar.high < bar.low:
                issues.append(
                    QualityIssue(
                        check_type="price_high_lt_low",
                        severity=CheckResult.WARN,
                        asset_id=asset.asset_id,
                        timestamp=bar.timestamp,
                        details={"high": str(bar.high), "low": str(bar.low)},
                    )
                )

            # Close outside [low, high] range
            if bar.close > bar.high or bar.close < bar.low:
                issues.append(
                    QualityIssue(
                        check_type="price_close_outside_range",
                        severity=CheckResult.WARN,
                        asset_id=asset.asset_id,
                        timestamp=bar.timestamp,
                        details={
                            "close": str(bar.close),
                            "high": str(bar.high),
                            "low": str(bar.low),
                        },
                    )
                )

            # Excessive spread
            mid = (bar.high + bar.low) / Decimal("2")
            if mid > Decimal("0"):
                spread_pct = float((bar.high - bar.low) / mid)
                if spread_pct > self._config.price_spread_max_pct:
                    issues.append(
                        QualityIssue(
                            check_type="price_excessive_spread",
                            severity=CheckResult.WARN,
                            asset_id=asset.asset_id,
                            timestamp=bar.timestamp,
                            details={
                                "spread_pct": round(spread_pct, 4),
                                "threshold": self._config.price_spread_max_pct,
                            },
                        )
                    )

        return issues

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Check tick price sanity."""
        issues: list[QualityIssue] = []
        for tick in ticks:
            if tick.price <= Decimal("0"):
                if asset.asset_class != AssetClass.FUTURE and not self._config.allow_negative_price:
                    issues.append(
                        QualityIssue(
                            check_type="price_non_positive",
                            severity=CheckResult.FAIL,
                            asset_id=asset.asset_id,
                            timestamp=tick.timestamp,
                            details={"price": str(tick.price)},
                        )
                    )
        return issues
