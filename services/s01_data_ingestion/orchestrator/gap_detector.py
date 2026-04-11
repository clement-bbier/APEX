"""Gap detector for the Backfill Orchestrator.

Scans time-series data (bars or macro points) for gaps — intervals where
no data exists but is expected. Used for silent gap recovery.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_GAP_TOLERANCE_FACTOR: float = 1.5


# ── Models ───────────────────────────────────────────────────────────────────


class Gap(BaseModel):
    """A detected gap in time-series data."""

    model_config = ConfigDict(frozen=True)

    start: datetime = Field(description="Start of the gap (last known point).")
    end: datetime = Field(description="End of the gap (next known point).")
    expected_interval: timedelta = Field(description="Expected interval between points.")

    @property
    def duration(self) -> timedelta:
        """Duration of the gap."""
        return self.end - self.start


def detect_gaps(
    timestamps: list[datetime],
    expected_interval: timedelta,
    start: datetime,
    end: datetime,
) -> list[Gap]:
    """Detect gaps in a sorted list of timestamps.

    A gap is an interval between consecutive timestamps that exceeds
    ``expected_interval * _GAP_TOLERANCE_FACTOR``.

    Args:
        timestamps: Sorted list of UTC-aware timestamps.
        expected_interval: Expected spacing between consecutive points.
        start: Start of the expected coverage window.
        end: End of the expected coverage window.

    Returns:
        List of detected :class:`Gap` instances.
    """
    if not timestamps:
        if end - start > expected_interval:
            return [Gap(start=start, end=end, expected_interval=expected_interval)]
        return []

    threshold = expected_interval * _GAP_TOLERANCE_FACTOR
    gaps: list[Gap] = []

    # Check gap at the beginning
    if timestamps[0] - start > threshold:
        gaps.append(Gap(start=start, end=timestamps[0], expected_interval=expected_interval))

    # Check gaps between consecutive timestamps
    for i in range(len(timestamps) - 1):
        delta = timestamps[i + 1] - timestamps[i]
        if delta > threshold:
            gaps.append(
                Gap(
                    start=timestamps[i],
                    end=timestamps[i + 1],
                    expected_interval=expected_interval,
                )
            )

    # Check gap at the end
    if end - timestamps[-1] > threshold:
        gaps.append(Gap(start=timestamps[-1], end=end, expected_interval=expected_interval))

    if gaps:
        logger.info("gap_detector.found", count=len(gaps))

    return gaps
