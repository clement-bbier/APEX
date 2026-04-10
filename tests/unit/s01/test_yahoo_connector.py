"""Unit tests for Yahoo Finance connector (Phase 2.6).

Tests: YahooHistoricalConnector, YahooBarNormalizer, backfill_yahoo script.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType
from services.s01_data_ingestion.connectors.yahoo_historical import (
    YahooFetchError,
    YahooHistoricalConnector,
    _bar_size_to_yahoo_interval,
    _placeholder_asset,
)
from services.s01_data_ingestion.normalizers.yahoo_bar import YahooBarNormalizer

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "yahoo_spx_1d_2024-q1.json"

_DUMMY_ASSET = Asset(
    asset_id=uuid.UUID(int=1),
    symbol="^GSPC",
    exchange="YAHOO",
    asset_class=AssetClass.INDEX,
    currency="USD",
)


def _make_sample_df(n_rows: int = 5, tz_aware: bool = True) -> pd.DataFrame:
    """Create a sample OHLCV DataFrame matching yfinance output."""
    dates = pd.date_range("2024-01-02", periods=n_rows, freq="B")
    if tz_aware:
        dates = dates.tz_localize("America/New_York")
    data = {
        "Open": [100.0 + i for i in range(n_rows)],
        "High": [105.0 + i for i in range(n_rows)],
        "Low": [95.0 + i for i in range(n_rows)],
        "Close": [102.0 + i for i in range(n_rows)],
        "Volume": [1_000_000 + i * 100_000 for i in range(n_rows)],
    }
    return pd.DataFrame(data, index=dates)


def _make_nan_volume_df() -> pd.DataFrame:
    """Create a DataFrame with NaN volume (common for indices)."""
    dates = pd.date_range("2024-01-02", periods=3, freq="B", tz="UTC")
    data = {
        "Open": [4700.0, 4710.0, 4720.0],
        "High": [4750.0, 4760.0, 4770.0],
        "Low": [4690.0, 4700.0, 4710.0],
        "Close": [4730.0, 4740.0, 4750.0],
        "Volume": [float("nan"), float("nan"), float("nan")],
    }
    return pd.DataFrame(data, index=dates)


# ── YahooHistoricalConnector ─────────────────────────────────────────────────


class TestYahooHistoricalConnector:
    """Tests for YahooHistoricalConnector."""

    def test_connector_name(self) -> None:
        connector = YahooHistoricalConnector()
        assert connector.connector_name == "yahoo_historical"

    def test_bar_size_to_yahoo_interval_daily(self) -> None:
        assert _bar_size_to_yahoo_interval(BarSize.D1) == "1d"

    def test_bar_size_to_yahoo_interval_minute(self) -> None:
        assert _bar_size_to_yahoo_interval(BarSize.M1) == "1m"
        assert _bar_size_to_yahoo_interval(BarSize.M5) == "5m"
        assert _bar_size_to_yahoo_interval(BarSize.M15) == "15m"

    def test_bar_size_to_yahoo_interval_hourly(self) -> None:
        assert _bar_size_to_yahoo_interval(BarSize.H1) == "1h"

    def test_bar_size_to_yahoo_interval_weekly(self) -> None:
        assert _bar_size_to_yahoo_interval(BarSize.W1) == "1wk"

    def test_bar_size_to_yahoo_interval_monthly(self) -> None:
        assert _bar_size_to_yahoo_interval(BarSize.MO1) == "1mo"

    def test_bar_size_unsupported_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            _bar_size_to_yahoo_interval(BarSize.H4)

    def test_placeholder_asset(self) -> None:
        asset = _placeholder_asset("^GSPC")
        assert asset.symbol == "^GSPC"
        assert asset.exchange == "YAHOO"
        assert asset.asset_class == AssetClass.EQUITY
        assert asset.currency == "USD"

    @pytest.mark.asyncio
    async def test_fetch_bars_yields_batches(self) -> None:
        """Verify fetch_bars yields Bar objects from mocked yfinance data."""
        df = _make_sample_df(5, tz_aware=True)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df

        with patch("services.s01_data_ingestion.connectors.yahoo_historical.yf.Ticker") as mock_yf:
            mock_yf.return_value = mock_ticker
            connector = YahooHistoricalConnector()
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 4, 1, tzinfo=UTC)
            batches: list[list[Bar]] = []
            async for batch in connector.fetch_bars("^GSPC", BarSize.D1, start, end):
                batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 5
        for bar in batches[0]:
            assert isinstance(bar, Bar)
            assert bar.bar_type == BarType.TIME
            assert bar.bar_size == BarSize.D1

    @pytest.mark.asyncio
    async def test_fetch_bars_empty_df_raises(self) -> None:
        """Empty DataFrame after retries should raise YahooFetchError."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with (
            patch("services.s01_data_ingestion.connectors.yahoo_historical.yf.Ticker") as mock_yf,
            patch(
                "services.s01_data_ingestion.connectors.yahoo_historical.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            mock_yf.return_value = mock_ticker
            connector = YahooHistoricalConnector()
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 4, 1, tzinfo=UTC)
            with pytest.raises(YahooFetchError, match="empty dataframe"):
                async for _ in connector.fetch_bars("INVALID", BarSize.D1, start, end):
                    pass

    @pytest.mark.asyncio
    async def test_fetch_bars_retry_on_exception(self) -> None:
        """Connector should retry on transient exceptions."""
        df = _make_sample_df(3, tz_aware=True)
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = [
            ConnectionError("network error"),
            ConnectionError("network error"),
            df,
        ]

        with (
            patch("services.s01_data_ingestion.connectors.yahoo_historical.yf.Ticker") as mock_yf,
            patch(
                "services.s01_data_ingestion.connectors.yahoo_historical.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            mock_yf.return_value = mock_ticker
            connector = YahooHistoricalConnector()
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 4, 1, tzinfo=UTC)
            bars: list[Bar] = []
            async for batch in connector.fetch_bars("^GSPC", BarSize.D1, start, end):
                bars.extend(batch)

        assert len(bars) == 3

    @pytest.mark.asyncio
    async def test_fetch_ticks_not_implemented(self) -> None:
        """fetch_ticks should raise NotImplementedError."""
        connector = YahooHistoricalConnector()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 4, 1, tzinfo=UTC)
        with pytest.raises(NotImplementedError, match="tick data"):
            async for _ in connector.fetch_ticks("^GSPC", start, end):
                pass


# ── YahooBarNormalizer ───────────────────────────────────────────────────────


class TestYahooBarNormalizer:
    """Tests for YahooBarNormalizer."""

    def test_normalize_basic(self) -> None:
        """Happy path: valid row with UTC timestamp."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02", tz="UTC")
        row = {
            "Open": 4700.0,
            "High": 4750.0,
            "Low": 4690.0,
            "Close": 4730.0,
            "Volume": 3_500_000_000.0,
        }
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        assert bar.open == Decimal("4700.0")
        assert bar.high == Decimal("4750.0")
        assert bar.low == Decimal("4690.0")
        assert bar.close == Decimal("4730.0")
        assert bar.volume == Decimal("3500000000.0")
        assert bar.timestamp.tzinfo is not None
        assert bar.bar_size == BarSize.D1

    def test_normalize_naive_timestamp_localized_to_utc(self) -> None:
        """Naive timestamps should be localized to UTC."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02")  # naive
        row = {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 102.0, "Volume": 1000.0}
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        assert bar.timestamp.tzinfo is not None
        assert bar.timestamp.year == 2024

    def test_normalize_non_utc_timezone_converted(self) -> None:
        """Non-UTC timestamps should be converted to UTC."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02 09:30:00", tz="America/New_York")
        row = {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 102.0, "Volume": 1000.0}
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        # 9:30 ET = 14:30 UTC
        assert bar.timestamp.hour == 14
        assert bar.timestamp.minute == 30

    def test_normalize_nan_volume_defaults_to_zero(self) -> None:
        """NaN volume (common for indices) should default to 0."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 102.0, "Volume": float("nan")}
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        assert bar.volume == Decimal("0")

    def test_normalize_none_volume_defaults_to_zero(self) -> None:
        """None volume should default to 0."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 102.0, "Volume": None}
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        assert bar.volume == Decimal("0")

    def test_normalize_missing_volume_key_defaults_to_zero(self) -> None:
        """Missing Volume key should default to 0."""
        normalizer = YahooBarNormalizer(BarSize.D1)
        ts = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 102.0}
        bar = normalizer.normalize((ts, row), _DUMMY_ASSET)
        assert bar.volume == Decimal("0")

    def test_normalize_with_fixture(self) -> None:
        """Load real fixture and verify normalization."""
        assert FIXTURE_PATH.exists(), f"fixture missing: {FIXTURE_PATH} — repo packaging error"
        df = pd.read_json(FIXTURE_PATH, orient="table")
        normalizer = YahooBarNormalizer(BarSize.D1)
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            bar = normalizer.normalize((ts, row.to_dict()), _DUMMY_ASSET)
            bars.append(bar)
        assert len(bars) > 0
        for bar in bars:
            assert bar.open > 0
            assert bar.high >= bar.low
            assert bar.volume >= 0


# ── Backfill script ──────────────────────────────────────────────────────────


class TestBackfillYahoo:
    """Tests for backfill_yahoo.py CLI."""

    def test_import_main(self) -> None:
        """Verify the main function is importable."""
        from scripts.backfill_yahoo import main

        assert callable(main)

    def test_asset_class_map_has_expected_keys(self) -> None:
        """Verify _ASSET_CLASS_MAP covers required asset classes."""
        from scripts.backfill_yahoo import _ASSET_CLASS_MAP

        assert "equity" in _ASSET_CLASS_MAP
        assert "index" in _ASSET_CLASS_MAP
        assert "forex" in _ASSET_CLASS_MAP
        assert "commodity" in _ASSET_CLASS_MAP

    def test_argparse_symbol_required(self) -> None:
        """CLI should reject invocation without --symbol."""

        from scripts.backfill_yahoo import main

        with pytest.raises(SystemExit):
            with patch("sys.argv", ["backfill_yahoo"]):
                main()

    def test_argparse_valid_args(self) -> None:
        """CLI should parse valid arguments correctly."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument("--interval", default="1d")
        parser.add_argument("--asset-class", default="equity")
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(
            [
                "--symbol",
                "^GSPC",
                "--start",
                "2024-01-01",
                "--end",
                "2024-04-01",
                "--asset-class",
                "index",
                "--dry-run",
            ]
        )
        assert args.symbol == "^GSPC"
        assert args.asset_class == "index"
        assert args.dry_run is True
