"""Persistence layer for data quality issues.

Maps QualityIssue instances to DataQualityEntry models and persists
them via TimescaleRepository.log_quality_check().
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.data.timescale_repository import TimescaleRepository
from core.logger import get_logger
from core.models.data import DataQualityEntry, Severity

from .base import CheckResult, QualityIssue
from .checker import BarQualityReport, TickQualityReport

logger = get_logger("quality.db_logger")

_SEVERITY_MAP: dict[CheckResult, Severity] = {
    CheckResult.PASS: Severity.INFO,
    CheckResult.WARN: Severity.WARNING,
    CheckResult.FAIL: Severity.ERROR,
}


class QualityDbLogger:
    """Persists quality issues to the data_quality_log table."""

    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    async def log_issues(self, issues: list[QualityIssue]) -> None:
        """Persist a list of quality issues to the database."""
        for issue in issues:
            entry = DataQualityEntry(
                check_type=issue.check_type,
                asset_id=issue.asset_id,
                severity=_SEVERITY_MAP.get(issue.severity, Severity.WARNING),
                timestamp=issue.timestamp or datetime.now(UTC),
                details_json=dict(issue.details),
            )
            await self._repo.log_quality_check(entry)

        if issues:
            logger.info("quality_issues_logged", count=len(issues))

    async def log_report(
        self, report: BarQualityReport | TickQualityReport, connector: str
    ) -> None:
        """Persist all issues from a quality report."""
        _ = connector  # Available for future metadata enrichment
        await self.log_issues(report.issues)
