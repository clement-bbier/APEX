"""Timestamp validity check.

Flags records with timestamps in the future, before the asset listing date,
or before the year 2000 (likely epoch-zero or corrupt data).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.logger import get_logger
from core.models.data import Asset, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.timestamp_check")

_MIN_YEAR = 2000


class TimestampCheck(QualityCheck):
    """Validate timestamp sanity for bars and ticks."""

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def _check_timestamp(self, ts: datetime, asset: Asset) -> QualityIssue | None:
        """Return an issue if the timestamp is invalid, else None."""
        now = datetime.now(UTC)

        if ts.timestamp() > now.timestamp() + self._config.future_tolerance_seconds:
            return QualityIssue(
                check_type="timestamp_future",
                severity=CheckResult.FAIL,
                asset_id=asset.asset_id,
                timestamp=ts,
                details={"reason": "future_timestamp", "now": str(now)},
            )

        if ts.year < _MIN_YEAR:
            return QualityIssue(
                check_type="timestamp_epoch",
                severity=CheckResult.FAIL,
                asset_id=asset.asset_id,
                timestamp=ts,
                details={"reason": "pre_2000", "year": ts.year},
            )

        if asset.listing_date is not None and ts.date() < asset.listing_date:
            return QualityIssue(
                check_type="timestamp_pre_listing",
                severity=CheckResult.FAIL,
                asset_id=asset.asset_id,
                timestamp=ts,
                details={
                    "reason": "before_listing_date",
                    "listing_date": str(asset.listing_date),
                },
            )

        return None

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Validate timestamps for a list of bars."""
        issues: list[QualityIssue] = []
        for bar in bars:
            issue = self._check_timestamp(bar.timestamp, asset)
            if issue is not None:
                issues.append(issue)
                logger.warning(
                    "timestamp_issue",
                    asset=asset.symbol,
                    reason=issue.details.get("reason"),
                    ts=str(bar.timestamp),
                )
        return issues

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Validate timestamps for a list of ticks."""
        issues: list[QualityIssue] = []
        for tick in ticks:
            issue = self._check_timestamp(tick.timestamp, asset)
            if issue is not None:
                issues.append(issue)
        return issues
