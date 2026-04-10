"""Data quality orchestrator.

Runs all registered QualityChecks against bars/ticks and produces
a QualityReport that separates clean from rejected records.

References:
    Breck et al. (2017) — "Data Validation for Machine Learning"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.logger import get_logger
from core.models.data import Asset, Bar, DbTick

from .base import CheckResult, QualityCheck, QualityIssue
from .config import QualityConfig
from .gap_check import GapCheck
from .outlier_check import OutlierCheck
from .price_check import PriceCheck
from .timestamp_check import TimestampCheck
from .volume_check import VolumeCheck

logger = get_logger("quality.checker")


def _default_checks(config: QualityConfig) -> list[QualityCheck]:
    """Instantiate the standard suite of quality checks.

    Note: StaleCheck is intentionally excluded — it is a no-op in the
    pipeline (check_bars/check_ticks return []).  Use it explicitly via
    StaleCheck.check_staleness() from monitoring code.
    """
    return [
        GapCheck(config),
        OutlierCheck(config),
        TimestampCheck(config),
        VolumeCheck(config),
        PriceCheck(config),
    ]


@dataclass
class BarQualityReport:
    """Report from validating a list of bars."""

    total_records: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    clean_bars: list[Bar] = field(default_factory=list)
    rejected_bars: list[Bar] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Fraction of records that passed (no FAIL)."""
        if self.total_records == 0:
            return 1.0
        return (self.total_records - self.failures) / self.total_records

    @property
    def is_acceptable(self) -> bool:
        """True if zero FAILs were detected."""
        return self.failures == 0


@dataclass
class TickQualityReport:
    """Report from validating a list of ticks."""

    total_records: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    clean_ticks: list[DbTick] = field(default_factory=list)
    rejected_ticks: list[DbTick] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Fraction of records that passed (no FAIL)."""
        if self.total_records == 0:
            return 1.0
        return (self.total_records - self.failures) / self.total_records

    @property
    def is_acceptable(self) -> bool:
        """True if zero FAILs were detected."""
        return self.failures == 0


# Backward-compatible alias
QualityReport = BarQualityReport


class DataQualityChecker:
    """Orchestrates all quality checks and produces reports."""

    def __init__(
        self,
        config: QualityConfig | None = None,
        checks: list[QualityCheck] | None = None,
    ) -> None:
        self._config = config or QualityConfig()
        self._checks = checks if checks is not None else _default_checks(self._config)

    def validate_bars(self, bars: list[Bar], asset: Asset) -> BarQualityReport:
        """Run all checks on bars and classify each bar."""
        all_issues: list[QualityIssue] = []
        for check in self._checks:
            all_issues.extend(check.check_bars(bars, asset))

        # Build per-bar severity map: timestamp -> max severity
        fail_timestamps: set[float] = set()
        warn_timestamps: set[float] = set()

        for issue in all_issues:
            if issue.timestamp is not None:
                ts = issue.timestamp.timestamp()
                if issue.severity == CheckResult.FAIL:
                    fail_timestamps.add(ts)
                elif issue.severity == CheckResult.WARN:
                    warn_timestamps.add(ts)

        clean: list[Bar] = []
        rejected: list[Bar] = []
        passed = 0
        warnings = 0
        failures = 0

        for bar in bars:
            ts = bar.timestamp.timestamp()
            if ts in fail_timestamps:
                rejected.append(bar)
                failures += 1
            elif ts in warn_timestamps:
                clean.append(bar)
                warnings += 1
            else:
                clean.append(bar)
                passed += 1

        report = BarQualityReport(
            total_records=len(bars),
            passed=passed,
            warnings=warnings,
            failures=failures,
            issues=all_issues,
            clean_bars=clean,
            rejected_bars=rejected,
        )

        logger.info(
            "bar_quality_report",
            total=report.total_records,
            passed=report.passed,
            warnings=report.warnings,
            failures=report.failures,
            pass_rate=round(report.pass_rate, 4),
        )

        return report

    def validate_ticks(self, ticks: list[DbTick], asset: Asset) -> TickQualityReport:
        """Run all checks on ticks and classify each tick.

        Uses index-based classification to avoid timestamp collision bugs
        when multiple ticks share the same timestamp.
        """
        all_issues: list[QualityIssue] = []
        for check in self._checks:
            all_issues.extend(check.check_ticks(ticks, asset))

        # Map timestamps to tick indices for issue → tick matching
        ts_to_indices: dict[float, list[int]] = {}
        for idx, tick in enumerate(ticks):
            ts_to_indices.setdefault(tick.timestamp.timestamp(), []).append(idx)

        fail_indices: set[int] = set()
        warn_indices: set[int] = set()

        for issue in all_issues:
            if issue.timestamp is None:
                continue
            indices = ts_to_indices.get(issue.timestamp.timestamp(), [])
            for idx in indices:
                if issue.severity == CheckResult.FAIL:
                    fail_indices.add(idx)
                elif issue.severity == CheckResult.WARN:
                    warn_indices.add(idx)

        clean: list[DbTick] = []
        rejected: list[DbTick] = []
        passed = 0
        warnings = 0
        failures = 0

        for idx, tick in enumerate(ticks):
            if idx in fail_indices:
                rejected.append(tick)
                failures += 1
            elif idx in warn_indices:
                clean.append(tick)
                warnings += 1
            else:
                clean.append(tick)
                passed += 1

        report = TickQualityReport(
            total_records=len(ticks),
            passed=passed,
            warnings=warnings,
            failures=failures,
            issues=all_issues,
            clean_ticks=clean,
            rejected_ticks=rejected,
        )

        logger.info(
            "tick_quality_report",
            total=report.total_records,
            passed=report.passed,
            warnings=report.warnings,
            failures=report.failures,
        )

        return report
