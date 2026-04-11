"""Microstructure router — /v1/bars and /v1/trades endpoints.

Serves OHLCV bars and tick-level trade data from TimescaleDB.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from core.data.timescale_repository import TimescaleRepository

from ..deps import get_repo
from ..schemas import BarResponse, TickResponse

router = APIRouter(prefix="/v1", tags=["microstructure"])

_DEFAULT_LIMIT = 1000
_MAX_LIMIT = 10_000


@router.get("/bars", response_model=list[BarResponse])
async def get_bars(
    symbol: str = Query(..., min_length=1, description="Trading symbol, e.g. BTCUSDT"),
    exchange: str = Query(..., min_length=1, description="Exchange name, e.g. BINANCE"),
    bar_size: str = Query(..., description="Bar size, e.g. 1m, 5m, 1h, 1d"),
    start: datetime = Query(..., description="Inclusive start (UTC ISO-8601)"),
    end: datetime = Query(..., description="Exclusive end (UTC ISO-8601)"),
    bar_type: str = Query(default="time", description="Bar type: time, tick, volume, dollar"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[BarResponse]:
    """Fetch OHLCV bars for a symbol within a time range."""
    asset = await repo.get_asset(symbol, exchange)
    if asset is None:
        return []
    rows = await repo.get_bars(asset.asset_id, bar_type, bar_size, start, end)
    return [BarResponse.from_bar(b) for b in rows[:limit]]


@router.get("/trades", response_model=list[TickResponse])
async def get_trades(
    symbol: str = Query(..., min_length=1, description="Trading symbol"),
    exchange: str = Query(..., min_length=1, description="Exchange name"),
    start: datetime = Query(..., description="Inclusive start (UTC ISO-8601)"),
    end: datetime = Query(..., description="Exclusive end (UTC ISO-8601)"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: TimescaleRepository = Depends(get_repo),
) -> list[TickResponse]:
    """Fetch tick-level trades for a symbol within a time range."""
    asset = await repo.get_asset(symbol, exchange)
    if asset is None:
        return []
    rows = await repo.get_ticks(asset.asset_id, start, end)
    return [TickResponse.from_tick(t) for t in rows[:limit]]
