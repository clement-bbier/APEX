"""FastAPI application for the APEX Serving Layer.

Exposes Phase 2.4-2.9 ingested data to consumer services (S02-S10)
via an internal REST API. Uses async lifespan to manage the
TimescaleDB connection pool.

Reference: Kleppmann (2017) Ch. 1-4 — decoupling storage from serving.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.data.timescale_repository import TimescaleRepository

from .deps import get_repo
from .routers import assets, calendar, fundamentals, macro, microstructure
from .schemas import HealthResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_API_TITLE = "APEX Data Serving Layer"
_API_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage TimescaleRepository connection pool lifecycle."""
    settings = get_settings()
    repo = TimescaleRepository(
        dsn=settings.timescale_dsn,
        pool_min=settings.timescale_pool_min,
        pool_max=settings.timescale_pool_max,
    )
    await repo.connect()
    application.state.repo = repo
    logger.info("serving_layer.started", dsn_host=settings.timescale_host)
    try:
        yield
    finally:
        await repo.close()
        logger.info("serving_layer.stopped")


app = FastAPI(
    title=_API_TITLE,
    version=_API_VERSION,
    lifespan=lifespan,
)

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(microstructure.router)
app.include_router(macro.router)
app.include_router(calendar.router)
app.include_router(fundamentals.router)
app.include_router(assets.router)


# ── Error Handlers ───────────────────────────────────────────────────────────


@app.exception_handler(ValueError)
async def value_error_handler(
    request: Request,
    exc: ValueError,
) -> JSONResponse:
    """Return 400 for ValueError (bad query parameters, invalid enums, etc.)."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return 500 for unhandled exceptions — no stack trace leaks."""
    logger.error("serving_layer.unhandled_error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health(
    repo: TimescaleRepository = Depends(get_repo),  # noqa: B008
) -> HealthResponse:
    """Health check — verifies database connectivity."""
    db_ok = await repo.health_check()
    status = "ok" if db_ok else "degraded"
    return HealthResponse(status=status, database=db_ok)
