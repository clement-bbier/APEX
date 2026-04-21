"""Unit tests for ECBConnector.

Mock strategy: patch httpx.AsyncClient with mock JSON SDMX responses.
Fixture data from tests/fixtures/ecb_eurusd_2024.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.data import MacroPoint, MacroSeriesMeta
from services.data_ingestion.connectors.ecb_connector import (
    ECBConnector,
    ECBFetchError,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_ecb_fixture() -> dict:
    return json.loads((FIXTURES / "ecb_eurusd_2024.json").read_text(encoding="utf-8"))


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────


class TestECBConnectorInit:
    """Tests for ECBConnector basics."""

    def test_connector_name(self):
        conn = ECBConnector()
        assert conn.connector_name == "ecb_sdw"

    def test_parse_series_id_valid(self):
        flow, key = ECBConnector._parse_series_id("EXR/D.USD.EUR.SP00.A")
        assert flow == "EXR"
        assert key == "D.USD.EUR.SP00.A"

    def test_parse_series_id_invalid(self):
        with pytest.raises(ECBFetchError, match="Invalid ECB series_id"):
            ECBConnector._parse_series_id("NO_SLASH_HERE")


class TestECBFetchSeries:
    """Tests for ECBConnector.fetch_series."""

    @pytest.mark.asyncio
    async def test_fetch_series_returns_points(self):
        fixture = _load_ecb_fixture()
        conn = ECBConnector()

        mock_resp = _mock_response(fixture)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.data_ingestion.connectors.ecb_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 12, 31, tzinfo=UTC)

            all_points = []
            async for batch in conn.fetch_series("EXR/D.USD.EUR.SP00.A", start, end):
                all_points.extend(batch)

        assert len(all_points) == 10
        assert all(isinstance(p, MacroPoint) for p in all_points)
        assert all_points[0].value == pytest.approx(1.0842)

    @pytest.mark.asyncio
    async def test_fetch_series_filters_by_date_range(self):
        fixture = _load_ecb_fixture()
        conn = ECBConnector()

        mock_resp = _mock_response(fixture)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.data_ingestion.connectors.ecb_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            # Only request first week of January
            start = datetime(2024, 1, 2, tzinfo=UTC)
            end = datetime(2024, 1, 6, tzinfo=UTC)

            all_points = []
            async for batch in conn.fetch_series("EXR/D.USD.EUR.SP00.A", start, end):
                all_points.extend(batch)

        # Should include Jan 2, 3, 4, 5 (not Jan 6 which is exclusive)
        assert len(all_points) == 4

    @pytest.mark.asyncio
    async def test_fetch_series_sorted_by_timestamp(self):
        fixture = _load_ecb_fixture()
        conn = ECBConnector()

        mock_resp = _mock_response(fixture)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.data_ingestion.connectors.ecb_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 12, 31, tzinfo=UTC)

            all_points = []
            async for batch in conn.fetch_series("EXR/D.USD.EUR.SP00.A", start, end):
                all_points.extend(batch)

        timestamps = [p.timestamp for p in all_points]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_fetch_series_404_raises(self):
        conn = ECBConnector()

        mock_resp = _mock_response({}, status_code=404)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.data_ingestion.connectors.ecb_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 12, 31, tzinfo=UTC)

            with pytest.raises(ECBFetchError, match="series not found"):
                async for _ in conn.fetch_series("EXR/D.USD.EUR.SP00.A", start, end):
                    pass


class TestECBParseSdmxJson:
    """Tests for the SDMX-JSON parser."""

    def test_parse_valid_fixture(self):
        fixture = _load_ecb_fixture()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        points = ECBConnector._parse_sdmx_json(fixture, "EXR/D.USD.EUR.SP00.A", start, end)
        assert len(points) == 10
        assert points[0].series_id == "EXR/D.USD.EUR.SP00.A"

    def test_parse_empty_datasets(self):
        data = {"dataSets": [], "structure": {"dimensions": {"observation": []}}}
        points = ECBConnector._parse_sdmx_json(
            data, "TEST/X", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)
        )
        assert points == []

    def test_parse_bad_structure_raises(self):
        with pytest.raises(ECBFetchError, match="unexpected SDMX-JSON"):
            ECBConnector._parse_sdmx_json(
                {"dataSets": [{"series": {}}]},
                "TEST/X",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            )

    def test_parse_monthly_dates(self):
        """ECB monthly series use dates like '2024-01' without day."""
        data = {
            "dataSets": [{"series": {"0": {"observations": {"0": [2.5], "1": [2.6]}}}}],
            "structure": {
                "dimensions": {
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "values": [
                                {"id": "2024-01"},
                                {"id": "2024-02"},
                            ],
                        }
                    ]
                }
            },
        }
        points = ECBConnector._parse_sdmx_json(
            data,
            "IRS/M.X",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(points) == 2
        assert points[0].timestamp.day == 1


class TestECBFetchMetadata:
    """Tests for ECBConnector.fetch_metadata."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_returns_meta(self):
        fixture = _load_ecb_fixture()
        conn = ECBConnector()

        mock_resp = _mock_response(fixture)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.data_ingestion.connectors.ecb_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            meta = await conn.fetch_metadata("EXR/D.USD.EUR.SP00.A")

        assert isinstance(meta, MacroSeriesMeta)
        assert meta.source == "ECB"
        assert meta.series_id == "EXR/D.USD.EUR.SP00.A"
        assert meta.frequency == "daily"
