"""Calendar router — /v1/economic_events and /v1/economic_events/upcoming.

Serves scheduled economic events (FOMC, ECB, CPI, NFP, etc.).
The /upcoming endpoint is CRITICAL for Phase 6 Risk Manager pre-event blocking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from core.data.timescale_repository import TimescaleRepository

from ..deps import get_repo
from ..schemas import EconomicEventResponse

router = APIRouter(prefix="/v1", tags=["calendar"])

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


@router.get("/economic_events", response_model=list[EconomicEventResponse])
async def get_economic_events(
    start: datetime = Query(..., description="Inclusive start (UTC ISO-8601)"),
    end: datetime = Query(..., description="Exclusive end (UTC ISO-8601)"),
    event_type: str | None = Query(default=None, description="Filter by event type"),
    min_impact: int = Query(default=1, ge=1, le=3, description="Minimum impact score"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[EconomicEventResponse]:
    """Fetch economic events within a time range."""
    rows = await repo.get_economic_events(
        start=start,
        end=end,
        event_type=event_type,
        min_impact=min_impact,
    )
    return [EconomicEventResponse.from_event(e) for e in rows[:limit]]


@router.get("/economic_events/upcoming", response_model=list[EconomicEventResponse])
async def get_upcoming_events(
    within_minutes: int = Query(..., ge=1, le=1440, description="Look-ahead window in minutes"),
    min_impact: int = Query(default=1, ge=1, le=3, description="Minimum impact score"),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[EconomicEventResponse]:
    """Fetch economic events occurring within the next N minutes.

    Critical for Phase 6 Risk Manager — used to block new entries
    before high-impact events (FOMC, CPI, NFP, etc.).
    """
    now = datetime.now(UTC)
    end = now + timedelta(minutes=within_minutes)
    rows = await repo.get_upcoming_events(start=now, end=end, min_impact=min_impact)
    return [EconomicEventResponse.from_event(e) for e in rows]
