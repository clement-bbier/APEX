"""OpenTelemetry tracing setup and decorators for S01.

Initializes the OTel tracer provider as an immutable singleton.
If ``otel_endpoint`` is configured, exports via OTLP/gRPC;
otherwise falls back to ``ConsoleSpanExporter`` for local dev.

References:
    Majors & Fong-Jones (2022) — "Observability Engineering" Ch. 5-7
    OpenTelemetry Python docs — https://opentelemetry.io/docs/languages/python/
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, cast

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.trace import Status, StatusCode

_SERVICE_NAME = "apex-s01-data-ingestion"
_RESOURCE_ATTRIBUTES_KEY = "service.name"

_F = TypeVar("_F", bound=Callable[..., Coroutine[Any, Any, Any]])

# Module-level flag to prevent double-init
_initialized: bool = False


def init_tracing(otel_endpoint: str | None = None) -> TracerProvider:
    """Initialize the OpenTelemetry tracer provider.

    Idempotent — calling multiple times returns the existing provider.

    Args:
        otel_endpoint: OTLP gRPC endpoint (e.g. ``http://localhost:4317``).
            If ``None``, uses ``ConsoleSpanExporter``.

    Returns:
        The configured ``TracerProvider``.
    """
    global _initialized

    if _initialized:
        existing = trace.get_tracer_provider()
        if isinstance(existing, TracerProvider):
            return existing

    resource = Resource.create({_RESOURCE_ATTRIBUTES_KEY: _SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    exporter: SpanExporter
    if otel_endpoint:
        # Import here to avoid hard dependency when not using OTLP
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=otel_endpoint)
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _initialized = True
    return provider


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer instance for the given instrumentation scope.

    Args:
        name: Instrumentation scope name (e.g. ``connector.alpaca``).

    Returns:
        An OpenTelemetry ``Tracer``.
    """
    return trace.get_tracer(name)


def trace_async(span_name: str) -> Callable[[_F], _F]:
    """Decorator that wraps an async function in an OpenTelemetry span.

    Usage::

        @trace_async("connector.alpaca.fetch_bars")
        async def fetch_bars(self, ...) -> ...:
            ...

    Args:
        span_name: Name for the created span.

    Returns:
        Decorated async function.
    """

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        async def wrapper(
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            tracer = get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                    span.record_exception(exc)
                    raise

        return cast(_F, wrapper)

    return decorator


def reset_tracing() -> None:
    """Reset the tracing state. Only for use in tests."""
    global _initialized
    _initialized = False
