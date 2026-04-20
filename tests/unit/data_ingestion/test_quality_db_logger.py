"""Unit tests for QualityDbLogger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.data import DataQualityEntry
from services.s01_data_ingestion.quality.base import CheckResult, QualityIssue
from services.s01_data_ingestion.quality.checker import BarQualityReport
from services.s01_data_ingestion.quality.db_logger import QualityDbLogger


def _make_issue(check_type: str = "test", severity: CheckResult = CheckResult.WARN) -> QualityIssue:
    return QualityIssue(
        check_type=check_type,
        severity=severity,
        asset_id=uuid.uuid4(),
        timestamp=datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
        details={"key": "value"},
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.log_quality_check = AsyncMock()
    return repo


class TestQualityDbLogger:
    @pytest.mark.asyncio
    async def test_log_issues(self, mock_repo: MagicMock) -> None:
        logger = QualityDbLogger(mock_repo)
        issues = [_make_issue(), _make_issue(severity=CheckResult.FAIL)]
        await logger.log_issues(issues)
        assert mock_repo.log_quality_check.call_count == 2
        # Verify the entries are DataQualityEntry instances
        for call in mock_repo.log_quality_check.call_args_list:
            entry = call[0][0]
            assert isinstance(entry, DataQualityEntry)

    @pytest.mark.asyncio
    async def test_log_report(self, mock_repo: MagicMock) -> None:
        logger = QualityDbLogger(mock_repo)
        report = BarQualityReport(
            total_records=5,
            passed=3,
            warnings=1,
            failures=1,
            issues=[_make_issue(), _make_issue(severity=CheckResult.FAIL)],
        )
        await logger.log_report(report, connector="test")
        assert mock_repo.log_quality_check.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_issues(self, mock_repo: MagicMock) -> None:
        logger = QualityDbLogger(mock_repo)
        await logger.log_issues([])
        mock_repo.log_quality_check.assert_not_called()
