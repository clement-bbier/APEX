"""Gap detection check for bar time series.

Detects missing bars by comparing actual intervals against expected intervals
derived from bar_size. Weekend gaps are ignored for equities.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.logger import get_logger
from core.models.data import Asset, AssetClass, Bar, BarSize, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.gap_check")

# Expected interval in seconds for each bar size.
_BAR_INTERVAL: dict[BarSize, int] = {
    BarSize.M1: 60,
    BarSize.M5: 300,
    BarSize.M15: 900,
    BarSize.H1: 3600,
    BarSize.H4: 14400,
    BarSize.D1: 86400,
    BarSize.W1: 604800,
    BarSize.MO1: 2592000,
}


def _is_weekend_gap(ts_a: float, ts_b: float) -> bool:
    """Return True if the gap between ts_a and ts_b spans a weekend day."""
    dt_a = datetime.fromtimestamp(ts_a, tz=UTC)
    dt_b = datetime.fromtimestamp(ts_b, tz=UTC)
    # Gap traverses at least one Saturday or Sunday
    current = dt_a
    while current < dt_b:
        if current.weekday() >= 5:
            return True
        current += timedelta(days=1)
    return dt_b.weekday() >= 5


class GapCheck(QualityCheck):
    """Detect missing bars based on expected time intervals."""

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Check for gaps between consecutive bars."""
        if len(bars) < 2:
            return []

        issues: list[QualityIssue] = []
        expected = _BAR_INTERVAL.get(bars[0].bar_size)
        if expected is None:
            return []

        is_equity = asset.asset_class == AssetClass.EQUITY

        for i in range(len(bars) - 1):
            ts_a = bars[i].timestamp.timestamp()
            ts_b = bars[i + 1].timestamp.timestamp()
            actual_interval = ts_b - ts_a

            if actual_interval > expected * self._config.gap_tolerance_multiplier:
                if is_equity and _is_weekend_gap(ts_a, ts_b):
                    continue

                issue = QualityIssue(
                    check_type="gap",
                    severity=CheckResult.WARN,
                    asset_id=asset.asset_id,
                    timestamp=bars[i + 1].timestamp,
                    details={
                        "expected_seconds": expected,
                        "actual_seconds": actual_interval,
                        "bar_index": i + 1,
                    },
                )
                issues.append(issue)
                logger.warning(
                    "gap_detected",
                    asset=asset.symbol,
                    expected=expected,
                    actual=actual_interval,
                )

        return issues

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Ticks have no expected interval — always returns empty."""
        return []
