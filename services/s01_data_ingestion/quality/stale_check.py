"""Staleness detection check.

Detects when the most recent data for an asset is older than expected,
with thresholds varying by asset class.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.logger import get_logger
from core.models.data import Asset, AssetClass, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.stale_check")


class StaleCheck(QualityCheck):
    """Detect stale data based on last-seen timestamp.

    Not included in the default pipeline checks (check_bars/check_ticks
    are no-ops).  Use check_staleness() directly from monitoring code.
    """

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def _get_threshold(self, asset: Asset) -> int:
        """Return staleness threshold in seconds for the given asset class."""
        if asset.asset_class == AssetClass.CRYPTO:
            return self._config.stale_crypto_seconds
        if asset.asset_class == AssetClass.EQUITY:
            return self._config.stale_equity_seconds
        return self._config.stale_daily_seconds

    def check_staleness(
        self,
        asset: Asset,
        last_timestamp: datetime,
        now: datetime | None = None,
    ) -> QualityIssue | None:
        """Check if the asset's data is stale.

        Args:
            asset: The asset to check.
            last_timestamp: Most recent data timestamp.
            now: Current time (defaults to UTC now).

        Returns:
            A QualityIssue if stale, else None.
        """
        if now is None:
            now = datetime.now(UTC)

        threshold = self._get_threshold(asset)
        age_seconds = (now - last_timestamp).total_seconds()

        if age_seconds > threshold:
            issue = QualityIssue(
                check_type="stale_data",
                severity=CheckResult.WARN,
                asset_id=asset.asset_id,
                timestamp=last_timestamp,
                details={
                    "age_seconds": round(age_seconds, 1),
                    "threshold_seconds": threshold,
                    "asset_class": asset.asset_class.value,
                },
            )
            logger.warning(
                "stale_data",
                asset=asset.symbol,
                age_seconds=round(age_seconds, 1),
                threshold=threshold,
            )
            return issue

        return None

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Staleness is checked via check_staleness() — returns empty."""
        return []

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Staleness is checked via check_staleness() — returns empty."""
        return []
