"""Assets router — /v1/assets endpoint.

Serves the asset registry (symbols, exchanges, asset classes).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.data.timescale_repository import TimescaleRepository
from core.models.data import AssetClass

from ..deps import get_repo
from ..schemas import AssetResponse

router = APIRouter(prefix="/v1", tags=["assets"])


@router.get("/assets", response_model=list[AssetResponse])
async def get_assets(
    asset_class: str | None = Query(default=None, description="Filter by asset class"),
    query: str | None = Query(default=None, description="Symbol prefix search"),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[AssetResponse]:
    """List assets, optionally filtered by class or symbol prefix."""
    ac = AssetClass(asset_class) if asset_class else None
    if query:
        rows = await repo.search_assets(query, asset_class=ac)
    else:
        rows = await repo.list_assets(asset_class=ac)
    return [AssetResponse.from_asset(a) for a in rows]
