"""Volume sanity check.

Flags negative volume (FAIL), zero volume (WARN), and volume spikes
exceeding a configurable multiplier of the rolling average (WARN).
"""

from __future__ import annotations

from decimal import Decimal

from core.logger import get_logger
from core.models.data import Asset, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.volume_check")


class VolumeCheck(QualityCheck):
    """Validate volume fields for bars and ticks."""

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Check volume sanity across a list of bars."""
        issues: list[QualityIssue] = []

        for i, bar in enumerate(bars):
            if bar.volume < Decimal("0"):
                issues.append(
                    QualityIssue(
                        check_type="volume_negative",
                        severity=CheckResult.FAIL,
                        asset_id=asset.asset_id,
                        timestamp=bar.timestamp,
                        details={"volume": str(bar.volume)},
                    )
                )
                logger.warning("negative_volume", asset=asset.symbol, volume=str(bar.volume))
                continue

            if bar.volume == Decimal("0"):
                issues.append(
                    QualityIssue(
                        check_type="volume_zero",
                        severity=CheckResult.WARN,
                        asset_id=asset.asset_id,
                        timestamp=bar.timestamp,
                        details={"volume": "0"},
                    )
                )
                continue

            # Volume spike detection
            if i > 0:
                prev_volumes = [
                    float(bars[j].volume)
                    for j in range(max(0, i - self._config.volume_spike_lookback), i)
                ]
                if prev_volumes:
                    avg = sum(prev_volumes) / len(prev_volumes)
                    if avg > 0 and float(bar.volume) > avg * self._config.volume_spike_multiplier:
                        issues.append(
                            QualityIssue(
                                check_type="volume_spike",
                                severity=CheckResult.WARN,
                                asset_id=asset.asset_id,
                                timestamp=bar.timestamp,
                                details={
                                    "volume": str(bar.volume),
                                    "average": round(avg, 2),
                                    "multiplier": round(float(bar.volume) / avg, 2),
                                },
                            )
                        )
                        logger.warning(
                            "volume_spike",
                            asset=asset.symbol,
                            volume=str(bar.volume),
                            avg=round(avg, 2),
                        )

        return issues

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Check tick quantity sanity."""
        issues: list[QualityIssue] = []
        for tick in ticks:
            if tick.quantity < Decimal("0"):
                issues.append(
                    QualityIssue(
                        check_type="quantity_negative",
                        severity=CheckResult.FAIL,
                        asset_id=asset.asset_id,
                        timestamp=tick.timestamp,
                        details={"quantity": str(tick.quantity)},
                    )
                )
        return issues
