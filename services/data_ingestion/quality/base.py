"""Abstract base classes for composable data quality checks.

Defines the QualityCheck ABC and supporting types (CheckResult, QualityIssue)
used by all concrete check implementations.

References:
    Breck et al. (2017) — "Data Validation for Machine Learning"
    Kleppmann (2017) — "Designing Data-Intensive Applications", Ch. 11
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from core.models.data import Asset, Bar, DbTick


class CheckResult(StrEnum):
    """Outcome severity of a single quality check."""

    PASS = "pass"  # noqa: S105
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class QualityIssue:
    """A single data quality issue detected by a check."""

    check_type: str
    severity: CheckResult
    asset_id: uuid.UUID | None = None
    timestamp: datetime | None = None
    details: dict[str, object] = field(default_factory=dict)


class QualityCheck(ABC):
    """Abstract base class for all data quality checks.

    Each concrete check implements validation logic for bars and/or ticks.
    Checks are purely functional — no DB access, no side effects.
    """

    @abstractmethod
    def check_bars(self, bars: list[Bar], asset: Asset) -> list[QualityIssue]:
        """Validate a list of bars and return any issues found."""

    @abstractmethod
    def check_ticks(self, ticks: list[DbTick], asset: Asset) -> list[QualityIssue]:
        """Validate a list of ticks and return any issues found."""
