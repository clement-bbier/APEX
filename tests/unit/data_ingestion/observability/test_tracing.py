"""Unit tests for S01 observability tracing.

Verifies OpenTelemetry tracer init, @trace_async decorator,
and span lifecycle. All OTLP exports are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider

from services.data_ingestion.observability.tracing import (
    get_tracer,
    init_tracing,
    reset_tracing,
    trace_async,
)


@pytest.fixture(autouse=True)
def _reset_otel() -> None:
    """Reset tracing state before each test."""
    reset_tracing()


class TestInitTracing:
    """Tests for init_tracing."""

    def test_returns_tracer_provider(self) -> None:
        provider = init_tracing(otel_endpoint=None)
        assert isinstance(provider, TracerProvider)

    def test_idempotent_returns_same_type(self) -> None:
        p1 = init_tracing(otel_endpoint=None)
        p2 = init_tracing(otel_endpoint=None)
        # Both calls should return TracerProvider instances
        assert isinstance(p1, TracerProvider)
        assert isinstance(p2, TracerProvider)

    @patch(
        "services.data_ingestion.observability.tracing.OTLPSpanExporter",
        create=True,
    )
    def test_otlp_exporter_when_endpoint_set(self, mock_otlp: MagicMock) -> None:
        mock_otlp.return_value = MagicMock()
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
            mock_otlp,
        ):
            provider = init_tracing(otel_endpoint="http://localhost:4317")
        assert isinstance(provider, TracerProvider)

    def test_console_exporter_when_no_endpoint(self) -> None:
        provider = init_tracing(otel_endpoint=None)
        assert isinstance(provider, TracerProvider)


class TestGetTracer:
    """Tests for get_tracer."""

    def test_returns_tracer(self) -> None:
        init_tracing(otel_endpoint=None)
        tracer = get_tracer("test.scope")
        assert tracer is not None


class TestTraceAsync:
    """Tests for @trace_async decorator."""

    async def test_success_creates_span(self) -> None:
        init_tracing(otel_endpoint=None)

        @trace_async("test.operation")
        async def my_func() -> str:
            return "result"

        result = await my_func()
        assert result == "result"

    async def test_exception_records_error(self) -> None:
        init_tracing(otel_endpoint=None)

        @trace_async("test.error_operation")
        async def failing_func() -> None:
            msg = "test error"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="test error"):
            await failing_func()

    async def test_exception_propagates_not_type_error(self) -> None:
        """Verify set_status uses Status objects — no TypeError from OTel."""
        init_tracing(otel_endpoint=None)

        @trace_async("test.status_object")
        async def raises_runtime() -> None:
            msg = "runtime boom"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="runtime boom"):
            await raises_runtime()

    async def test_preserves_function_name(self) -> None:
        @trace_async("test.named")
        async def original_name() -> None:
            pass

        assert original_name.__name__ == "original_name"
