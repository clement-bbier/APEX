"""Prometheus metrics endpoint for the serving layer.

Provides a helper to mount the ``/metrics`` endpoint on an existing
FastAPI app, returning Prometheus exposition format. This avoids
a separate process — metrics are served alongside the API.

References:
    Prometheus exposition formats —
        https://prometheus.io/docs/instrumenting/exposition_formats/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

_METRICS_PATH = "/metrics"
_METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST


def mount_metrics_endpoint(
    app: FastAPI,
    path: str = _METRICS_PATH,
    registry: CollectorRegistry | None = None,
) -> None:
    """Add a ``/metrics`` GET endpoint to the FastAPI application.

    Args:
        app: The FastAPI application instance.
        path: URL path for the metrics endpoint.
        registry: Optional custom Prometheus registry (for testing).
    """

    @app.get(path, include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Return Prometheus metrics in exposition format."""
        data = generate_latest(registry) if registry else generate_latest()
        return Response(content=data, media_type=_METRICS_CONTENT_TYPE)
