"""Unit tests for the SimFin fundamentals connector.

Tests authentication, financial statement parsing, ratio parsing,
error handling, and the async generator interface.
All network calls are mocked via httpx transport.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from services.s01_data_ingestion.connectors.simfin_connector import (
    SimFinConnector,
    SimFinFetchError,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_fixture(name: str) -> list | dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _mock_transport(responses: dict[str, tuple[int, list | dict | str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern, (status, body) in responses.items():
            if pattern in url:
                if isinstance(body, (dict, list)):
                    return httpx.Response(status, json=body)
                return httpx.Response(status, text=body)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


class TestAuth:
    """Tests for API key authentication."""

    def test_missing_api_key_raises(self) -> None:
        with patch(
            "services.s01_data_ingestion.connectors.simfin_connector.get_settings"
        ) as mock_settings:
            mock_secret = type("FakeSecret", (), {"get_secret_value": lambda self: ""})()
            mock_settings.return_value.simfin_api_key = mock_secret
            with pytest.raises(SimFinFetchError, match="required but empty"):
                SimFinConnector()

    def test_api_key_in_headers(self) -> None:
        conn = SimFinConnector(api_key="test_key_123", client=httpx.AsyncClient())
        assert conn._headers["X-API-KEY"] == "test_key_123"

    @pytest.mark.asyncio
    async def test_401_raises_simfin_error(self) -> None:
        transport = _mock_transport(
            {
                "statements": (401, {"error": "unauthorized"}),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = SimFinConnector(api_key="bad_key", client=client)
            with pytest.raises(SimFinFetchError, match="invalid or expired"):
                await conn.fetch_financials("AAPL", "PL", "fy")


class TestFetchFinancials:
    """Tests for financial statement fetching."""

    @pytest.mark.asyncio
    async def test_fetch_financials_returns_data(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        transport = _mock_transport({"statements": (200, financials)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = SimFinConnector(api_key="test_key", client=client)
            result = await conn.fetch_financials("AAPL", "PL", "fy")
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_financials_404(self) -> None:
        transport = _mock_transport({})  # No matching pattern → 404
        async with httpx.AsyncClient(transport=transport) as client:
            conn = SimFinConnector(api_key="test_key", client=client)
            with pytest.raises(SimFinFetchError, match="404"):
                await conn.fetch_financials("NOTEXIST", "PL", "fy")


class TestParseStatements:
    """Tests for statement → FundamentalPoint parsing."""

    def test_parse_statements_revenue(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "simfin.AAPL")
        points = conn._parse_statements(
            financials,
            asset_id,
            date(2023, 1, 1),
            date(2025, 1, 1),
        )
        revenues = [p for p in points if p.metric_name == "revenue"]
        assert len(revenues) >= 1
        assert revenues[0].value > 0

    def test_parse_statements_multiple_metrics(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "simfin.AAPL")
        points = conn._parse_statements(
            financials,
            asset_id,
            date(2023, 1, 1),
            date(2025, 1, 1),
        )
        metric_names = {p.metric_name for p in points}
        assert "revenue" in metric_names
        assert "net_income" in metric_names

    def test_parse_statements_date_filter(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "simfin.AAPL")
        # Narrow window: only 2024
        points = conn._parse_statements(
            financials,
            asset_id,
            date(2024, 1, 1),
            date(2025, 1, 1),
        )
        for p in points:
            assert p.report_date >= date(2024, 1, 1)
            assert p.report_date < date(2025, 1, 1)

    def test_parse_statements_period_type(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "simfin.AAPL")
        points = conn._parse_statements(
            financials,
            asset_id,
            date(2023, 1, 1),
            date(2025, 1, 1),
        )
        period_types = {p.period_type for p in points}
        assert "annual" in period_types or "quarterly" in period_types


class TestFetchRatios:
    """Tests for ratio fetching and parsing."""

    @pytest.mark.asyncio
    async def test_fetch_ratios_returns_data(self) -> None:
        ratio_data = [
            {
                "Report Date": "2023-09-30",
                "Period": "FY",
                "Return on Equity": 0.1712,
                "Return on Assets": 0.2712,
                "Gross Profit Margin": 0.4413,
                "Net Profit Margin": 0.2530,
                "Price / Earnings Ratio": 28.5,
            }
        ]
        transport = _mock_transport({"ratios": (200, ratio_data)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = SimFinConnector(api_key="test_key", client=client)
            result = await conn.fetch_ratios("AAPL")
            assert len(result) > 0

    def test_parse_ratios(self) -> None:
        ratio_data = [
            {
                "Report Date": "2023-09-30",
                "Period": "FY",
                "Return on Equity": 0.1712,
                "Gross Profit Margin": 0.4413,
                "Net Profit Margin": 0.2530,
            }
        ]
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "simfin.AAPL")
        points = conn._parse_ratios(
            ratio_data,
            asset_id,
            date(2023, 1, 1),
            date(2025, 1, 1),
        )
        metric_names = {p.metric_name for p in points}
        assert "roe" in metric_names
        assert "gross_margin" in metric_names


class TestConnectorInterface:
    """Tests for FundamentalsConnector interface compliance."""

    def test_connector_name(self) -> None:
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        assert conn.connector_name == "simfin"

    @pytest.mark.asyncio
    async def test_corporate_events_not_implemented(self) -> None:
        conn = SimFinConnector(api_key="test_key", client=httpx.AsyncClient())
        with pytest.raises(NotImplementedError):
            async for _ in conn.fetch_corporate_events(
                "AAPL",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            ):
                pass

    @pytest.mark.asyncio
    async def test_fetch_fundamentals_yields_batches(self) -> None:
        financials = _load_fixture("simfin_aapl_financials.json")
        ratio_data = [
            {
                "Report Date": "2023-09-30",
                "Period": "FY",
                "Return on Equity": 0.17,
            }
        ]
        transport = _mock_transport(
            {
                "statements": (200, financials),
                "ratios": (200, ratio_data),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = SimFinConnector(api_key="test_key", client=client)
            all_points = []
            async for batch in conn.fetch_fundamentals(
                "AAPL",
                ["10-K"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            ):
                all_points.extend(batch)
            assert len(all_points) > 0
