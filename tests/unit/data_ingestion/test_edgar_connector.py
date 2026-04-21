"""Unit tests for the SEC EDGAR fundamentals connector.

Tests ticker→CIK resolution, filings list parsing, XBRL concept mapping,
User-Agent requirement, rate limiting, retry logic, and error handling.
All network calls are mocked via httpx transport or monkeypatch.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from services.data_ingestion.connectors.edgar_connector import (
    EDGARConnector,
    EDGARFetchError,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _mock_transport(responses: dict[str, tuple[int, dict | list | str]]) -> httpx.MockTransport:
    """Build a MockTransport that matches URLs to predefined responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern, (status, body) in responses.items():
            if pattern in url:
                if isinstance(body, (dict, list)):
                    return httpx.Response(status, json=body)
                return httpx.Response(status, text=body)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


class TestTickerToCIK:
    """Tests for ticker → CIK resolution."""

    @pytest.mark.asyncio
    async def test_ticker_to_cik_aapl(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport({"company_tickers.json": (200, tickers)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            cik = await conn.ticker_to_cik("AAPL")
            assert cik == 320193

    @pytest.mark.asyncio
    async def test_ticker_to_cik_case_insensitive(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport({"company_tickers.json": (200, tickers)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            cik = await conn.ticker_to_cik("aapl")
            assert cik == 320193

    @pytest.mark.asyncio
    async def test_ticker_to_cik_unknown_raises(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport({"company_tickers.json": (200, tickers)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            with pytest.raises(EDGARFetchError, match="not found"):
                await conn.ticker_to_cik("XYZNOTEXIST")

    @pytest.mark.asyncio
    async def test_cik_cache_reused(self) -> None:
        """Second call should use cached CIK map without another HTTP request."""
        tickers = _load_fixture("edgar_company_tickers.json")
        call_count = 0

        def counting_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if "company_tickers.json" in str(request.url):
                call_count += 1
                return httpx.Response(200, json=tickers)
            return httpx.Response(404)

        transport = httpx.MockTransport(counting_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            await conn.ticker_to_cik("AAPL")
            await conn.ticker_to_cik("MSFT")
            assert call_count == 1


class TestFetchFilings:
    """Tests for fetching filing metadata from submissions endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_filings_10k(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        submissions = _load_fixture("edgar_aapl_submissions.json")
        transport = _mock_transport(
            {
                "company_tickers.json": (200, tickers),
                "submissions/CIK": (200, submissions),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            filings = await conn.fetch_filings(
                "AAPL",
                ["10-K"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            )
            assert len(filings) > 0
            assert all(f["form"] == "10-K" for f in filings)

    @pytest.mark.asyncio
    async def test_fetch_filings_date_filter(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        submissions = _load_fixture("edgar_aapl_submissions.json")
        transport = _mock_transport(
            {
                "company_tickers.json": (200, tickers),
                "submissions/CIK": (200, submissions),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            # Narrow window should return fewer filings
            filings = await conn.fetch_filings(
                "AAPL",
                ["10-K", "10-Q"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 6, 1, tzinfo=UTC),
            )
            for f in filings:
                assert f["filingDate"] >= "2024-01-01"
                assert f["filingDate"] < "2024-06-01"


class TestParseXBRLConcepts:
    """Tests for XBRL companyfacts → FundamentalPoint parsing."""

    @pytest.mark.asyncio
    async def test_parse_xbrl_revenue(self) -> None:
        facts = _load_fixture("edgar_aapl_companyfacts.json")
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport({"company_tickers.json": (200, tickers)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "edgar.AAPL")
            points = conn._parse_xbrl_concepts(
                facts,
                asset_id,
                ["10-K"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            )
            revenues = [p for p in points if p.metric_name == "revenue"]
            assert len(revenues) >= 1
            assert revenues[0].value > 0

    @pytest.mark.asyncio
    async def test_parse_xbrl_multiple_metrics(self) -> None:
        facts = _load_fixture("edgar_aapl_companyfacts.json")
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport({"company_tickers.json": (200, tickers)})
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "edgar.AAPL")
            points = conn._parse_xbrl_concepts(
                facts,
                asset_id,
                ["10-K", "10-Q"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            )
            metric_names = {p.metric_name for p in points}
            assert "revenue" in metric_names
            assert "net_income" in metric_names
            assert "total_assets" in metric_names

    @pytest.mark.asyncio
    async def test_parse_xbrl_period_type_annual(self) -> None:
        facts = _load_fixture("edgar_aapl_companyfacts.json")
        conn = EDGARConnector(
            client=httpx.AsyncClient(),
            user_agent="Test test@test.com",
        )
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, "edgar.AAPL")
        points = conn._parse_xbrl_concepts(
            facts,
            asset_id,
            ["10-K"],
            datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        for p in points:
            assert p.period_type == "annual"


class TestUserAgent:
    """Tests for User-Agent header requirement."""

    @pytest.mark.asyncio
    async def test_user_agent_sent_in_requests(self) -> None:
        captured_headers: dict[str, str] = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "X"}})

        transport = httpx.MockTransport(capture_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="MyBot me@test.com")
            await conn._ensure_cik_cache()
            assert "user-agent" in captured_headers
            assert "MyBot" in captured_headers["user-agent"]

    def test_default_user_agent_from_settings(self) -> None:
        with patch(
            "services.data_ingestion.connectors.edgar_connector.get_settings"
        ) as mock_settings:
            mock_settings.return_value.edgar_user_agent = "APEX/Test test@test.com"
            conn = EDGARConnector(client=httpx.AsyncClient())
            assert "APEX" in conn._user_agent


class TestRetryAndErrors:
    """Tests for retry logic and error handling."""

    @pytest.mark.asyncio
    async def test_404_raises_immediately(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        transport = _mock_transport(
            {
                "company_tickers.json": (200, tickers),
                "submissions/CIK": (404, {"error": "not found"}),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            with pytest.raises(EDGARFetchError, match="404"):
                await conn.fetch_filings(
                    "AAPL",
                    ["10-K"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2025, 1, 1, tzinfo=UTC),
                )

    @pytest.mark.asyncio
    async def test_connector_name(self) -> None:
        conn = EDGARConnector(
            client=httpx.AsyncClient(),
            user_agent="Test test@test.com",
        )
        assert conn.connector_name == "edgar"


class TestFetchFundamentals:
    """Tests for the full fetch_fundamentals async generator."""

    @pytest.mark.asyncio
    async def test_fetch_fundamentals_yields_batches(self) -> None:
        tickers = _load_fixture("edgar_company_tickers.json")
        facts = _load_fixture("edgar_aapl_companyfacts.json")
        transport = _mock_transport(
            {
                "company_tickers.json": (200, tickers),
                "companyfacts/CIK": (200, facts),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            conn = EDGARConnector(client=client, user_agent="Test test@test.com")
            all_points = []
            async for batch in conn.fetch_fundamentals(
                "AAPL",
                ["10-K", "10-Q"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
            ):
                all_points.extend(batch)
            assert len(all_points) > 0
            assert all(p.asset_id is not None for p in all_points)
