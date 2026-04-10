"""Unit tests for scripts/backfill_equities.py (Phase 2.5)."""

from __future__ import annotations

import uuid
from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

from core.models.data import Asset, AssetClass

_DUMMY_ASSET = Asset(
    asset_id=uuid.UUID(int=1),
    symbol="AAPL",
    exchange="ALPACA",
    asset_class=AssetClass.EQUITY,
    currency="USD",
)


class TestBackfillEquitiesScript:
    """Tests for the equities backfill CLI module."""

    def test_module_imports(self) -> None:
        import scripts.backfill_equities as mod

        assert hasattr(mod, "run_backfill")
        assert hasattr(mod, "main")
        assert hasattr(mod, "_create_connector")

    def test_create_connector_alpaca(self) -> None:
        with patch("scripts.backfill_equities.AlpacaHistoricalConnector") as mock_cls:
            from scripts.backfill_equities import _create_connector

            with patch("scripts.backfill_equities.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock()
                connector = _create_connector("alpaca")
            mock_cls.assert_called_once()

    def test_create_connector_massive(self) -> None:
        with patch("scripts.backfill_equities.MassiveHistoricalConnector") as mock_cls:
            from scripts.backfill_equities import _create_connector

            with patch("scripts.backfill_equities.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock()
                connector = _create_connector("massive")
            mock_cls.assert_called_once()

    def test_create_connector_invalid_raises(self) -> None:
        from scripts.backfill_equities import _create_connector

        with patch("scripts.backfill_equities.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            with pytest.raises(ValueError, match="Unknown provider"):
                _create_connector("unknown")

    def test_parse_utc_datetime_shared(self) -> None:
        from scripts._backfill_common import _parse_utc_datetime

        dt = _parse_utc_datetime("2024-01-02")
        assert dt.tzinfo is not None
        assert dt.tzinfo == UTC
