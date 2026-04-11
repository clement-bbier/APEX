"""Macro router — /v1/macro_series and /v1/macro_series/metadata endpoints.

Serves macroeconomic time series data (FRED, ECB, BoJ) from TimescaleDB.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from core.data.timescale_repository import TimescaleRepository

from ..deps import get_repo
from ..schemas import MacroMetadataResponse, MacroPointResponse

router = APIRouter(prefix="/v1", tags=["macro"])

_DEFAULT_LIMIT = 1000
_MAX_LIMIT = 10_000


@router.get("/macro_series", response_model=list[MacroPointResponse])
async def get_macro_series(
    series_id: str = Query(..., min_length=1, description="Series ID, e.g. VIXCLS"),
    start: datetime = Query(..., description="Inclusive start (UTC ISO-8601)"),
    end: datetime = Query(..., description="Exclusive end (UTC ISO-8601)"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[MacroPointResponse]:
    """Fetch macro time series data within a date range."""
    rows = await repo.get_macro_series(series_id, start, end, limit=limit)
    return [MacroPointResponse.from_point(p) for p in rows]


@router.get("/macro_series/metadata", response_model=MacroMetadataResponse)
async def get_macro_metadata(
    series_id: str = Query(..., min_length=1, description="Series ID"),
    repo: TimescaleRepository = Depends(get_repo),
) -> MacroMetadataResponse:
    """Fetch metadata for a macro series."""
    meta = await repo.get_macro_metadata(series_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")
    return MacroMetadataResponse.from_meta(meta)
