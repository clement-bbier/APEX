"""FastAPI dependency injection for the APEX Serving Layer.

Provides ``get_repo`` and ``get_settings`` callables for use with
FastAPI's ``Depends()`` mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from core.config import get_settings as _get_settings

if TYPE_CHECKING:
    from core.config import Settings
    from core.data.timescale_repository import TimescaleRepository


def get_repo(request: Request) -> TimescaleRepository:
    """Return the TimescaleRepository attached to app state during lifespan."""
    repo: TimescaleRepository = request.app.state.repo
    return repo


def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return _get_settings()
