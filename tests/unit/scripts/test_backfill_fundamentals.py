"""Unit tests for backfill_fundamentals.py CLI helpers.

Tests the argument parsing, provider dispatch, ticker loading,
and dry-run mode without requiring a database or network access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.backfill_fundamentals import (
    _ALL_PROVIDERS,
    _build_arg_parser,
    _build_connector,
    _load_tickers,
    run_backfill,
)


class TestBuildConnector:
    """Tests for provider → connector dispatch."""

    def test_provider_dispatch_edgar(self) -> None:
        with patch(
            "services.s01_data_ingestion.connectors.edgar_connector.get_settings"
        ) as mock_settings:
            mock_settings.return_value.edgar_user_agent = "Test test@test.com"
            from services.s01_data_ingestion.connectors.edgar_connector import EDGARConnector

            conn = _build_connector("edgar")
            assert isinstance(conn, EDGARConnector)

    def test_provider_dispatch_simfin(self) -> None:
        with patch(
            "services.s01_data_ingestion.connectors.simfin_connector.get_settings"
        ) as mock_settings:
            mock_secret = MagicMock()
            mock_secret.get_secret_value.return_value = "test_key"
            mock_settings.return_value.simfin_api_key = mock_secret

            from services.s01_data_ingestion.connectors.simfin_connector import SimFinConnector

            conn = _build_connector("simfin")
            assert isinstance(conn, SimFinConnector)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            _build_connector("bloomberg")


class TestLoadTickers:
    """Tests for ticker loading from CLI arguments."""

    def test_load_from_csv(self) -> None:
        tickers = _load_tickers("AAPL,MSFT,NVDA", None)
        assert tickers == ["AAPL", "MSFT", "NVDA"]

    def test_load_deduplicates(self) -> None:
        tickers = _load_tickers("AAPL,MSFT,AAPL", None)
        assert tickers == ["AAPL", "MSFT"]

    def test_load_uppercases(self) -> None:
        tickers = _load_tickers("aapl,msft", None)
        assert tickers == ["AAPL", "MSFT"]

    def test_load_from_file(self, tmp_path) -> None:
        f = tmp_path / "tickers.txt"
        f.write_text("AAPL\n# comment\nMSFT\n\nNVDA\n", encoding="utf-8")
        tickers = _load_tickers(None, str(f))
        assert tickers == ["AAPL", "MSFT", "NVDA"]

    def test_load_empty(self) -> None:
        tickers = _load_tickers(None, None)
        assert tickers == []


class TestArgparser:
    """Tests for argument parser configuration."""

    def test_all_providers_tuple(self) -> None:
        assert "edgar" in _ALL_PROVIDERS
        assert "simfin" in _ALL_PROVIDERS
        assert len(_ALL_PROVIDERS) == 2

    def test_default_filings(self) -> None:
        parser = _build_arg_parser()
        args = parser.parse_args(["--provider", "edgar", "--tickers", "AAPL"])
        assert args.filings == "10-K,10-Q"


class TestDryRun:
    """Test dry-run mode skips DB writes entirely."""

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(self) -> None:
        with patch("scripts.backfill_fundamentals._build_connector") as mock_build:
            mock_connector = MagicMock()
            mock_connector.connector_name = "edgar"

            async def _empty_gen(ticker, filing_types, start, end):
                return
                yield  # pragma: no cover

            mock_connector.fetch_fundamentals = _empty_gen
            mock_build.return_value = mock_connector

            with patch("scripts.backfill_fundamentals.TimescaleRepository") as mock_repo_cls:
                await run_backfill(
                    providers=["edgar"],
                    tickers=["AAPL"],
                    filing_types=["10-K"],
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2024, 12, 31, tzinfo=UTC),
                    dry_run=True,
                )
                mock_repo_cls.assert_not_called()
