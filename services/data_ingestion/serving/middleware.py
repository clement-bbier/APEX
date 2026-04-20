"""Observability middleware for the APEX Serving Layer.

Automatically records Prometheus metrics for every HTTP request:
latency, request count, and response status codes.

References:
    Beyer et al. (2016) SRE Book Ch. 6 — latency, traffic, errors
    Starlette middleware docs — https://www.starlette.io/middleware/
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from services.s01_data_ingestion.observability.metrics import record_serving_request

# Paths excluded from metrics to avoid noise
_EXCLUDED_PATHS = frozenset({"/metrics", "/openapi.json", "/docs", "/redoc"})


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records request metrics.

    For every request (except excluded paths), records:
    - Request count by method + endpoint
    - Response count by method + endpoint + status code
    - Request duration histogram
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Intercept request, measure duration, record metrics."""
        path = request.url.path
        if path in _EXCLUDED_PATHS:
            return await call_next(request)

        method = request.method
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        record_serving_request(
            method=method,
            endpoint=path,
            status_code=response.status_code,
            duration_s=duration,
        )
        return response
