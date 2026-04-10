"""Unit tests for BoJConnector.

Mock strategy: patch httpx with mock CSV bytes.
Fixture data from tests/fixtures/boj_policy_rate_2024.csv.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.data import MacroPoint, MacroSeriesMeta
from services.s01_data_ingestion.connectors.boj_connector import (
    BoJConnector,
    BoJFetchError,
    _first_numeric,
    _try_parse_date,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_boj_fixture() -> bytes:
    return (FIXTURES / "boj_policy_rate_2024.csv").read_bytes()


def _mock_csv_response(content: bytes, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────


class TestBoJConnectorBasics:
    """Tests for BoJConnector initialization and metadata."""

    def test_connector_name(self):
        conn = BoJConnector()
        assert conn.connector_name == "boj"

    def test_available_series(self):
        series = BoJConnector.available_series()
        assert "boj_policy_rate" in series
        assert len(series) >= 5

    @pytest.mark.asyncio
    async def test_fetch_metadata_known_series(self):
        conn = BoJConnector()
        meta = await conn.fetch_metadata("boj_policy_rate")

        assert isinstance(meta, MacroSeriesMeta)
        assert meta.source == "BOJ"
        assert meta.series_id == "boj_policy_rate"
        assert meta.frequency == "monthly"

    @pytest.mark.asyncio
    async def test_fetch_metadata_unknown_raises(self):
        conn = BoJConnector()
        with pytest.raises(BoJFetchError, match="Unknown BoJ series"):
            await conn.fetch_metadata("boj_nonexistent")


class TestBoJFetchSeries:
    """Tests for BoJConnector.fetch_series."""

    @pytest.mark.asyncio
    async def test_fetch_series_returns_points(self):
        conn = BoJConnector()
        csv_bytes = _load_boj_fixture()

        mock_resp = _mock_csv_response(csv_bytes)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.s01_data_ingestion.connectors.boj_connector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 12, 31, tzinfo=UTC)

            all_points = []
            async for batch in conn.fetch_series("boj_policy_rate", start, end):
                all_points.extend(batch)

        assert len(all_points) == 10
        assert all(isinstance(p, MacroPoint) for p in all_points)
        assert all_points[0].value == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_fetch_series_unknown_raises(self):
        conn = BoJConnector()
        with pytest.raises(BoJFetchError, match="Unknown BoJ series"):
            async for _ in conn.fetch_series(
                "boj_fake",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            ):
                pass


class TestBoJHelpers:
    """Tests for BoJ CSV parsing helpers."""

    def test_try_parse_date_slash_ym(self):
        dt = _try_parse_date("2024/03")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.tzinfo == UTC

    def test_try_parse_date_iso(self):
        dt = _try_parse_date("2024-06-15")
        assert dt is not None
        assert dt.day == 15

    def test_try_parse_date_invalid(self):
        assert _try_parse_date("not-a-date") is None
        assert _try_parse_date("") is None

    def test_first_numeric_valid(self):
        assert _first_numeric(["0.001", "100"]) == pytest.approx(0.001)

    def test_first_numeric_skips_na(self):
        assert _first_numeric(["n.a.", "-", "3.14"]) == pytest.approx(3.14)

    def test_first_numeric_all_empty(self):
        assert _first_numeric(["", "-", "..."]) is None

    def test_first_numeric_comma_thousands(self):
        assert _first_numeric(["1,234.56"]) == pytest.approx(1234.56)
