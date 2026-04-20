"""Outlier detection using rolling z-score.

Flags bars/ticks whose close/price deviates significantly from the
rolling mean over a configurable window.

References:
    Huber (1981) — "Robust Statistics"
"""

from __future__ import annotations

from decimal import Decimal

from core.logger import get_logger
from core.models.data import Asset, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig

logger = get_logger("quality.outlier_check")


def _rolling_zscore(values: list[Decimal], index: int, window: int) -> float | None:
    """Compute z-score of values[index] against the preceding window."""
    start = max(0, index - window)
    window_vals = [float(v) for v in values[start:index]]
    if len(window_vals) < 2:
        return None
    mean = sum(window_vals) / len(window_vals)
    variance = sum((x - mean) ** 2 for x in window_vals) / len(window_vals)
    std = variance**0.5
    if std == 0.0:
        # If std is zero but value differs from mean, treat as extreme outlier.
        return float("inf") if float(values[index]) != mean else 0.0
    return float(abs(float(values[index]) - mean) / std)


class OutlierCheck(QualityCheck):
    """Detect price outliers using rolling z-score."""

    def __init__(self, config: QualityConfig) -> None:
        self._config = config

    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Flag bars whose close price is a statistical outlier."""
        if len(bars) < self._config.outlier_window:
            return []

        issues: list[QualityIssue] = []
        closes = [b.close for b in bars]

        for i in range(self._config.outlier_window, len(bars)):
            z = _rolling_zscore(closes, i, self._config.outlier_window)
            if z is None:
                continue

            severity: CheckResult | None = None
            if z > self._config.outlier_fail_sigma:
                severity = CheckResult.FAIL
            elif z > self._config.outlier_warn_sigma:
                severity = CheckResult.WARN

            if severity is not None:
                issue = QualityIssue(
                    check_type="outlier",
                    severity=severity,
                    asset_id=asset.asset_id,
                    timestamp=bars[i].timestamp,
                    details={"z_score": round(z, 4), "close": str(bars[i].close)},
                )
                issues.append(issue)
                logger.warning(
                    "outlier_detected",
                    asset=asset.symbol,
                    z_score=round(z, 4),
                    severity=severity.value,
                )

        return issues

    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Flag ticks whose price is a statistical outlier."""
        if len(ticks) < self._config.outlier_window:
            return []

        issues: list[QualityIssue] = []
        prices = [t.price for t in ticks]

        for i in range(self._config.outlier_window, len(ticks)):
            z = _rolling_zscore(prices, i, self._config.outlier_window)
            if z is None:
                continue

            severity: CheckResult | None = None
            if z > self._config.outlier_fail_sigma:
                severity = CheckResult.FAIL
            elif z > self._config.outlier_warn_sigma:
                severity = CheckResult.WARN

            if severity is not None:
                issue = QualityIssue(
                    check_type="outlier",
                    severity=severity,
                    asset_id=asset.asset_id,
                    timestamp=ticks[i].timestamp,
                    details={"z_score": round(z, 4), "price": str(ticks[i].price)},
                )
                issues.append(issue)

        return issues
