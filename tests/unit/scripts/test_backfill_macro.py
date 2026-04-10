"""Unit tests for backfill_macro.py CLI helpers.

Tests the argument parsing, provider dispatch, and series list loading
without requiring a database or network access.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.backfill_macro import _build_connector, _load_series_list


class TestBuildConnector:
    """Tests for provider → connector dispatch."""

    def test_fred_provider(self):
        with patch("services.s01_data_ingestion.connectors.fred_connector.Fred"):
            from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

            conn = _build_connector("fred")
            assert isinstance(conn, FREDConnector)

    def test_ecb_provider(self):
        from services.s01_data_ingestion.connectors.ecb_connector import ECBConnector

        conn = _build_connector("ecb")
        assert isinstance(conn, ECBConnector)

    def test_boj_provider(self):
        from services.s01_data_ingestion.connectors.boj_connector import BoJConnector

        conn = _build_connector("boj")
        assert isinstance(conn, BoJConnector)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            _build_connector("bloomberg")


class TestLoadSeriesList:
    """Tests for series list parsing."""

    def test_csv_parsing(self):
        result = _load_series_list("FEDFUNDS,DFF,T10Y2Y", None)
        assert result == ["FEDFUNDS", "DFF", "T10Y2Y"]

    def test_deduplication(self):
        result = _load_series_list("A,B,A,C,B", None)
        assert result == ["A", "B", "C"]

    def test_file_loading(self, tmp_path):
        f = tmp_path / "series.txt"
        f.write_text("# comment\nFEDFUNDS\nDFF\n\nT10Y2Y\n", encoding="utf-8")
        result = _load_series_list(None, str(f))
        assert result == ["FEDFUNDS", "DFF", "T10Y2Y"]

    def test_combined_csv_and_file(self, tmp_path):
        f = tmp_path / "extra.txt"
        f.write_text("T10Y2Y\nVIXCLS\n", encoding="utf-8")
        result = _load_series_list("FEDFUNDS,DFF", str(f))
        assert result == ["FEDFUNDS", "DFF", "T10Y2Y", "VIXCLS"]

    def test_empty_returns_empty(self):
        result = _load_series_list(None, None)
        assert result == []
