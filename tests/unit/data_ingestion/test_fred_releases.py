"""Unit tests for FREDReleasesConnector.

Mock strategy: patch fredapi.Fred with MagicMock, return synthetic release data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.models.data import EconomicEvent

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_fred_releases_fixture() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "fred_releases_payems_2024.json").read_text(encoding="utf-8"),
    )


def _build_mock_releases_df(dates: list[str]) -> pd.DataFrame:
    """Build a DataFrame that mimics fredapi.Fred.get_series_all_releases.

    Returns a DataFrame with MultiIndex (realtime_start, date) and a 'value' column.
    """
    rows = []
    for d in dates:
        ts = pd.Timestamp(d)
        # Each release date shows multiple observation dates
        rows.append({"realtime_start": ts, "date": ts, "value": 150000.0})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index(["realtime_start", "date"])
    return df


# ── Tests ────────────────────────────────────────────────────────────────────


class TestFREDReleasesConnectorName:
    def test_connector_name(self) -> None:
        with patch("services.data_ingestion.connectors.fred_releases.Fred"):
            from services.data_ingestion.connectors.fred_releases import (
                FREDReleasesConnector,
            )

            conn = FREDReleasesConnector(api_key="test-key")
            assert conn.connector_name == "fred_releases"


class TestFREDReleasesInit:
    def test_init_raises_on_empty_key(self) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
            FREDReleasesFetchError,
        )

        with pytest.raises(FREDReleasesFetchError, match="FRED_API_KEY is required"):
            FREDReleasesConnector(api_key="")


class TestFREDReleasesFetch:
    @pytest.fixture
    def fixture_data(self) -> dict[str, object]:
        return _load_fred_releases_fixture()

    @pytest.fixture
    def connector(self) -> object:
        with patch("services.data_ingestion.connectors.fred_releases.Fred") as mock_cls:
            from services.data_ingestion.connectors.fred_releases import (
                FREDReleasesConnector,
            )

            mock_fred = MagicMock()
            mock_cls.return_value = mock_fred
            conn = FREDReleasesConnector(api_key="test-key")
            conn._fred = mock_fred
            return conn

    @pytest.mark.asyncio
    async def test_fetch_payems_releases(
        self, connector: object, fixture_data: dict[str, object]
    ) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        assert isinstance(connector, FREDReleasesConnector)
        dates = fixture_data["release_dates"]
        assert isinstance(dates, list)
        mock_df = _build_mock_releases_df(dates)
        connector._fred.get_series_all_releases = MagicMock(return_value=mock_df)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        all_events: list[EconomicEvent] = []
        async for batch in connector.fetch_events(start, end):
            all_events.extend(batch)

        # Should have events for NFP (PAYEMS) at minimum
        nfp_events = [e for e in all_events if e.event_type == "us_data_release_nfp"]
        assert len(nfp_events) > 0

    @pytest.mark.asyncio
    async def test_fetch_cpi_releases(self, connector: object) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        assert isinstance(connector, FREDReleasesConnector)
        dates = ["2024-01-11", "2024-02-13", "2024-03-12"]
        mock_df = _build_mock_releases_df(dates)
        connector._fred.get_series_all_releases = MagicMock(return_value=mock_df)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        all_events: list[EconomicEvent] = []
        async for batch in connector.fetch_events(start, end):
            all_events.extend(batch)

        cpi_events = [e for e in all_events if "cpi" in e.event_type]
        assert len(cpi_events) > 0

    @pytest.mark.asyncio
    async def test_release_dates_have_timezones(self, connector: object) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        assert isinstance(connector, FREDReleasesConnector)
        dates = ["2024-01-05", "2024-02-02"]
        mock_df = _build_mock_releases_df(dates)
        connector._fred.get_series_all_releases = MagicMock(return_value=mock_df)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        async for batch in connector.fetch_events(start, end):
            for event in batch:
                assert event.scheduled_time.tzinfo is not None

    @pytest.mark.asyncio
    async def test_event_importance_classification(self, connector: object) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        assert isinstance(connector, FREDReleasesConnector)
        dates = ["2024-01-05"]
        mock_df = _build_mock_releases_df(dates)
        connector._fred.get_series_all_releases = MagicMock(return_value=mock_df)

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        all_events: list[EconomicEvent] = []
        async for batch in connector.fetch_events(start, end):
            all_events.extend(batch)

        # High impact: NFP, CPI, core CPI, GDP
        high = [e for e in all_events if e.impact_score == 3]
        # Medium impact: retail, ISM, jobless, consumer sentiment
        medium = [e for e in all_events if e.impact_score == 2]
        assert len(high) > 0
        assert len(medium) > 0

    def test_settings_loaded(self) -> None:
        """Verify connector reads from Settings when no key is passed."""
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        with (
            patch("services.data_ingestion.connectors.fred_releases.Fred"),
            patch(
                "services.data_ingestion.connectors.fred_releases.get_settings"
            ) as mock_settings,
        ):
            mock_secret = MagicMock()
            mock_secret.get_secret_value.return_value = "settings-key-123"
            mock_settings.return_value.fred_api_key = mock_secret

            conn = FREDReleasesConnector()
            assert conn.connector_name == "fred_releases"

    @pytest.mark.asyncio
    async def test_date_range_filtering(self, connector: object) -> None:
        from services.data_ingestion.connectors.fred_releases import (
            FREDReleasesConnector,
        )

        assert isinstance(connector, FREDReleasesConnector)
        dates = ["2024-01-05", "2024-06-07", "2024-12-06"]
        mock_df = _build_mock_releases_df(dates)
        connector._fred.get_series_all_releases = MagicMock(return_value=mock_df)

        start = datetime(2024, 5, 1, tzinfo=UTC)
        end = datetime(2024, 7, 1, tzinfo=UTC)
        all_events: list[EconomicEvent] = []
        async for batch in connector.fetch_events(start, end):
            all_events.extend(batch)

        for e in all_events:
            assert start <= e.scheduled_time < end
