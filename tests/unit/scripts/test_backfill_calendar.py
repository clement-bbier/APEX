"""Unit tests for backfill_calendar.py CLI helpers.

Tests the argument parsing, provider dispatch, and dry-run mode
without requiring a database or network access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.backfill_calendar import _ALL_PROVIDERS, _build_connector, run_backfill
from services.s01_data_ingestion.connectors.boj_calendar_scraper import BoJCalendarScraper
from services.s01_data_ingestion.connectors.ecb_scraper import ECBScraper
from services.s01_data_ingestion.connectors.fomc_scraper import FOMCScraper


class TestBuildConnector:
    """Tests for provider → connector dispatch."""

    def test_provider_dispatch_fomc(self) -> None:
        conn = _build_connector("fomc")
        assert isinstance(conn, FOMCScraper)

    def test_provider_dispatch_ecb(self) -> None:
        conn = _build_connector("ecb")
        assert isinstance(conn, ECBScraper)

    def test_provider_dispatch_boj(self) -> None:
        conn = _build_connector("boj")
        assert isinstance(conn, BoJCalendarScraper)

    def test_provider_dispatch_fred_releases(self) -> None:
        with (
            patch("services.s01_data_ingestion.connectors.fred_releases.Fred"),
            patch(
                "services.s01_data_ingestion.connectors.fred_releases.get_settings",
            ) as mock_settings,
        ):
            mock_secret = MagicMock()
            mock_secret.get_secret_value.return_value = "test-key"
            mock_settings.return_value.fred_api_key = mock_secret

            from services.s01_data_ingestion.connectors.fred_releases import (
                FREDReleasesConnector,
            )

            conn = _build_connector("fred_releases")
            assert isinstance(conn, FREDReleasesConnector)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            _build_connector("bloomberg")


class TestArgparseChoices:
    """Verify CLI --provider choices match _ALL_PROVIDERS."""

    def test_argparse_choices(self) -> None:
        assert "fomc" in _ALL_PROVIDERS
        assert "ecb" in _ALL_PROVIDERS
        assert "boj" in _ALL_PROVIDERS
        assert "fred_releases" in _ALL_PROVIDERS
        assert len(_ALL_PROVIDERS) == 4


class TestDryRun:
    """Test dry-run mode skips DB writes entirely."""

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(self) -> None:
        """Dry-run mode should not create any DB connections."""
        with patch("scripts.backfill_calendar._build_connector") as mock_build:
            mock_connector = MagicMock()
            mock_connector.connector_name = "fomc_scraper"

            # Empty async generator for testing
            async def _empty_gen(
                start: datetime,
                end: datetime,
            ) -> None:
                return
                yield  # pragma: no cover

            mock_connector.fetch_events = _empty_gen
            mock_build.return_value = mock_connector

            # Should complete without touching DB
            with patch("scripts.backfill_calendar.TimescaleRepository") as mock_repo_cls:
                await run_backfill(
                    providers=["fomc"],
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2024, 12, 31, tzinfo=UTC),
                    dry_run=True,
                )
                # DB should not be instantiated in dry-run mode
                mock_repo_cls.assert_not_called()


class TestDefaultDates:
    """Test default end date includes forward window."""

    def test_default_dates_includes_forward_window(self) -> None:
        """Verify that --end default is at least 1 year in the future."""
        from scripts.backfill_calendar import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--provider", "fomc"])

        now = datetime.now(UTC)
        delta = args.end - now
        assert delta.days > 365, (
            f"Default --end should be at least 1 year ahead, got {delta.days} days"
        )
