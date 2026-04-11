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
from services.s01_data_ingestion.observability.healthcheck import (
    DatabaseCheck,
    HealthChecker,
)
from services.s01_data_ingestion.observability.metrics import record_db_insert
from services.s01_data_ingestion.observability.metrics_server import (
    mount_metrics_endpoint,
)
from services.s01_data_ingestion.observability.tracing import init_tracing

from .deps import get_repo
from .middleware import ObservabilityMiddleware
from .routers import assets, calendar, fundamentals, macro, microstructure
from .schemas import HealthResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_API_TITLE = "APEX Data Serving Layer"
_API_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage TimescaleRepository connection pool lifecycle."""
    settings = get_settings()
    init_tracing(otel_endpoint=settings.otel_endpoint)

    def _on_insert(table: str, rows: int, duration_s: float) -> None:
        record_db_insert(table=table, rows=rows, duration_s=duration_s)

    repo = TimescaleRepository(
        dsn=settings.timescale_dsn,
        pool_min=settings.timescale_pool_min,
        pool_max=settings.timescale_pool_max,
        on_insert=_on_insert,
    )
    await repo.connect()
    application.state.repo = repo
    application.state.health_checker = HealthChecker(
        dependency_checks=[DatabaseCheck(repo)],
    )
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

# ── Observability ───────────────────────────────────────────────────────────

app.add_middleware(ObservabilityMiddleware)
mount_metrics_endpoint(app)


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
    request: Request,
    repo: TimescaleRepository = Depends(get_repo),  # noqa: B008
) -> HealthResponse:
    """Health check — verifies database connectivity via HealthChecker."""
    checker: HealthChecker = request.app.state.health_checker
    report = await checker.readiness()
    database_check = next(
        (c for c in report.checks if c.name == "database"),
        None,
    )
    db_ok = database_check is not None and database_check.status.value == "healthy"
    return HealthResponse(status=report.status.value, database=db_ok)
