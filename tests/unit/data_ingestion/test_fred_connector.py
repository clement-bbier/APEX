"""Unit tests for FREDConnector.

Mock strategy: patch ``fredapi.Fred`` with MagicMock to avoid real API calls.
Fixture data from tests/fixtures/fred_fedfunds_2024.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.models.data import MacroPoint, MacroSeriesMeta

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_fred_fixture() -> dict:
    return json.loads((FIXTURES / "fred_fedfunds_2024.json").read_text(encoding="utf-8"))


def _fixture_to_pandas_series(fixture: dict) -> pd.Series:
    """Convert fixture JSON observations to a pandas Series (like fredapi)."""
    dates = [pd.Timestamp(o["date"]) for o in fixture["observations"]]
    values = [o["value"] for o in fixture["observations"]]
    return pd.Series(values, index=dates)


def _fixture_to_info(fixture: dict) -> pd.Series:
    """Convert fixture metadata to pandas Series (like fredapi.get_series_info)."""
    return pd.Series(
        {
            "title": fixture["title"],
            "frequency_short": fixture["frequency_short"],
            "units_short": fixture["units_short"],
            "notes": fixture["notes"],
        }
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestFREDConnectorInit:
    """Tests for FREDConnector initialization."""

    def test_init_with_explicit_key(self):
        with patch("services.s01_data_ingestion.connectors.fred_connector.Fred"):
            from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

            conn = FREDConnector(api_key="test-key-123")
            assert conn.connector_name == "fred"

    def test_init_raises_on_empty_key(self):
        from services.s01_data_ingestion.connectors.fred_connector import (
            FREDConnector,
            FREDFetchError,
        )

        with pytest.raises(FREDFetchError, match="FRED_API_KEY is required"):
            FREDConnector(api_key="")


class TestFREDFetchSeries:
    """Tests for FREDConnector.fetch_series."""

    @pytest.fixture
    def fixture_data(self):
        return _load_fred_fixture()

    @pytest.fixture
    def connector(self):
        with patch("services.s01_data_ingestion.connectors.fred_connector.Fred") as mock_fred_cls:
            from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

            mock_fred = MagicMock()
            mock_fred_cls.return_value = mock_fred
            conn = FREDConnector(api_key="test-key")
            conn._fred = mock_fred
            yield conn, mock_fred

    @pytest.mark.asyncio
    async def test_fetch_series_returns_macro_points(self, connector, fixture_data):
        conn, mock_fred = connector
        mock_fred.get_series.return_value = _fixture_to_pandas_series(fixture_data)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        batches = []
        async for batch in conn.fetch_series("FEDFUNDS", start, end):
            batches.append(batch)

        assert len(batches) >= 1
        all_points = [p for b in batches for p in b]
        assert len(all_points) == 10
        assert all(isinstance(p, MacroPoint) for p in all_points)

    @pytest.mark.asyncio
    async def test_fetch_series_filters_nan(self, connector, fixture_data):
        conn, mock_fred = connector
        series = _fixture_to_pandas_series(fixture_data)
        series.iloc[2] = float("nan")
        mock_fred.get_series.return_value = series

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points = []
        async for batch in conn.fetch_series("FEDFUNDS", start, end):
            all_points.extend(batch)

        assert len(all_points) == 9  # One NaN filtered

    @pytest.mark.asyncio
    async def test_fetch_series_correct_values(self, connector, fixture_data):
        conn, mock_fred = connector
        mock_fred.get_series.return_value = _fixture_to_pandas_series(fixture_data)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points = []
        async for batch in conn.fetch_series("FEDFUNDS", start, end):
            all_points.extend(batch)

        first = all_points[0]
        assert first.series_id == "FEDFUNDS"
        assert first.value == pytest.approx(5.33)
        assert first.timestamp.year == 2024
        assert first.timestamp.month == 1

    @pytest.mark.asyncio
    async def test_fetch_series_retry_on_exception(self, connector):
        conn, mock_fred = connector
        mock_fred.get_series.side_effect = [
            ConnectionError("network fail"),
            ConnectionError("network fail again"),
            _fixture_to_pandas_series(_load_fred_fixture()),
        ]

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points = []
        async for batch in conn.fetch_series("FEDFUNDS", start, end):
            all_points.extend(batch)

        assert len(all_points) == 10
        assert mock_fred.get_series.call_count == 3

    @pytest.mark.asyncio
    async def test_fetch_series_raises_after_max_retries(self, connector):
        conn, mock_fred = connector
        mock_fred.get_series.side_effect = ConnectionError("persistent failure")

        from services.s01_data_ingestion.connectors.fred_connector import FREDFetchError

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        with pytest.raises(FREDFetchError, match="failed to fetch"):
            async for _ in conn.fetch_series("FEDFUNDS", start, end):
                pass

    @pytest.mark.asyncio
    async def test_fetch_series_empty(self, connector):
        conn, mock_fred = connector
        mock_fred.get_series.return_value = pd.Series(dtype=float)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)

        all_points = []
        async for batch in conn.fetch_series("EMPTY", start, end):
            all_points.extend(batch)

        assert len(all_points) == 0


class TestFREDFetchMetadata:
    """Tests for FREDConnector.fetch_metadata."""

    @pytest.fixture
    def connector(self):
        with patch("services.s01_data_ingestion.connectors.fred_connector.Fred") as mock_fred_cls:
            from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

            mock_fred = MagicMock()
            mock_fred_cls.return_value = mock_fred
            conn = FREDConnector(api_key="test-key")
            conn._fred = mock_fred
            yield conn, mock_fred

    @pytest.mark.asyncio
    async def test_fetch_metadata_returns_macro_series_meta(self, connector):
        conn, mock_fred = connector
        fixture = _load_fred_fixture()
        mock_fred.get_series_info.return_value = _fixture_to_info(fixture)

        meta = await conn.fetch_metadata("FEDFUNDS")

        assert isinstance(meta, MacroSeriesMeta)
        assert meta.series_id == "FEDFUNDS"
        assert meta.source == "FRED"
        assert meta.name == "Federal Funds Effective Rate"
        assert meta.frequency == "M"
        assert meta.unit == "Percent"

    @pytest.mark.asyncio
    async def test_fetch_metadata_retry_on_error(self, connector):
        conn, mock_fred = connector
        fixture = _load_fred_fixture()
        mock_fred.get_series_info.side_effect = [
            ConnectionError("fail"),
            _fixture_to_info(fixture),
        ]

        meta = await conn.fetch_metadata("FEDFUNDS")
        assert meta.name == "Federal Funds Effective Rate"
        assert mock_fred.get_series_info.call_count == 2
