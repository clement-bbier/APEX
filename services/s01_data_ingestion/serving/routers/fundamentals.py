"""Fundamentals router — /v1/fundamentals endpoint.

Serves fundamental metrics (revenue, EPS, etc.) from SEC EDGAR / SimFin.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from core.data.timescale_repository import TimescaleRepository

from ..deps import get_repo
from ..schemas import FundamentalResponse

router = APIRouter(prefix="/v1", tags=["fundamentals"])

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000
_VALID_PERIOD_TYPES = frozenset({"quarterly", "annual"})


@router.get("/fundamentals", response_model=list[FundamentalResponse])
async def get_fundamentals(
    symbol: str = Query(..., min_length=1, description="Trading symbol, e.g. AAPL"),
    exchange: str = Query(..., min_length=1, description="Exchange name, e.g. NYSE"),
    start: date = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end: date = Query(..., description="Exclusive end date (YYYY-MM-DD)"),
    period_type: str | None = Query(default=None, description="quarterly or annual"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[FundamentalResponse]:
    """Fetch fundamental metrics for a symbol within a date range."""
    if period_type is not None and period_type not in _VALID_PERIOD_TYPES:
        msg = f"Invalid period_type '{period_type}', must be one of {sorted(_VALID_PERIOD_TYPES)}"
        raise ValueError(msg)
    asset = await repo.get_asset(symbol, exchange)
    if asset is None:
        return []
    rows = await repo.get_fundamentals(
        asset_id=asset.asset_id,
        start=start,
        end=end,
        period_type=period_type,
        limit=limit,
    )
    return [FundamentalResponse.from_point(p) for p in rows]
