"""Unit tests for Massive connectors and normalizers (Phase 2.5).

Tests: MassiveHistoricalConnector, MassiveBarNormalizer.
"""

from __future__ import annotations

import csv
import gzip
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from botocore.exceptions import ClientError

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType
from services.data_ingestion.connectors.massive_historical import (
    MassiveFetchError,
    MassiveHistoricalConnector,
    _placeholder_asset,
)
from services.data_ingestion.normalizers.massive_bar import MassiveBarNormalizer

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "massive_aapl_minute_2024-01-02.csv.gz"
)

_DUMMY_ASSET = Asset(
    asset_id=uuid.UUID(int=1),
    symbol="AAPL",
    exchange="MASSIVE",
    asset_class=AssetClass.EQUITY,
    currency="USD",
)


def _make_csv_row(
    ticker: str = "AAPL",
    volume: str = "10000",
    open_: str = "185.50",
    close: str = "185.55",
    high: str = "185.75",
    low: str = "185.35",
    window_start_ns: str | None = None,
    transactions: str = "100",
) -> list[str]:
    """Create a Massive CSV row."""
    if window_start_ns is None:
        ts = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        window_start_ns = str(int(ts.timestamp() * 1_000_000_000))
    return [ticker, volume, open_, close, high, low, window_start_ns, transactions]


def _make_csv_gz_bytes(rows: list[list[str]], include_header: bool = True) -> bytes:
    """Create a gzipped CSV from rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    if include_header:
        writer.writerow(
            ["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"]
        )
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buf.getvalue().encode("utf-8"))


def _make_s3_body(csv_gz_bytes: bytes) -> io.BytesIO:
    """Create a file-like S3 Body from gzipped CSV bytes."""
    return io.BytesIO(csv_gz_bytes)


class TestMassiveBarNormalizer:
    """Tests for MassiveBarNormalizer."""

    def test_normalize_basic(self) -> None:
        normalizer = MassiveBarNormalizer(BarSize.M1)
        row = _make_csv_row()
        bar = normalizer.normalize(row, _DUMMY_ASSET)
        assert isinstance(bar, Bar)
        assert bar.bar_type == BarType.TIME
        assert bar.bar_size == BarSize.M1
        assert bar.open == Decimal("185.50")
        assert bar.high == Decimal("185.75")
        assert bar.low == Decimal("185.35")
        assert bar.close == Decimal("185.55")
        assert bar.volume == Decimal("10000")
        assert bar.trade_count == 100
        assert bar.vwap is None
        assert bar.asset_id == _DUMMY_ASSET.asset_id

    def test_normalize_timestamp_from_nanoseconds(self) -> None:
        normalizer = MassiveBarNormalizer()
        ts = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        ns = str(int(ts.timestamp() * 1_000_000_000))
        row = _make_csv_row(window_start_ns=ns)
        bar = normalizer.normalize(row, _DUMMY_ASSET)
        assert bar.timestamp == ts

    def test_normalize_batch(self) -> None:
        normalizer = MassiveBarNormalizer()
        rows = [_make_csv_row() for _ in range(5)]
        bars = normalizer.normalize_batch(rows, _DUMMY_ASSET)
        assert len(bars) == 5

    @pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="fixture not available")
    def test_fixture_parsing(self) -> None:
        with gzip.open(FIXTURE_PATH, "rt") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = [r for r in reader if r[0] == "AAPL"]
        normalizer = MassiveBarNormalizer(BarSize.M1)
        bars = [normalizer.normalize(row, _DUMMY_ASSET) for row in rows]
        assert len(bars) == 10
        assert bars[0].timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


class TestMassiveHistoricalConnector:
    """Tests for MassiveHistoricalConnector."""

    def _make_connector(self):
        """Create a MassiveHistoricalConnector with mocked deps."""
        from pydantic import SecretStr

        mock_settings = MagicMock()
        mock_settings.massive_s3_endpoint = "https://files.massive.com"
        mock_settings.massive_s3_access_key = SecretStr("test_access")
        mock_settings.massive_s3_secret_key = SecretStr("test_secret")
        mock_settings.massive_s3_bucket = "flatfiles"
        mock_settings.massive_api_key = SecretStr("test_api_key")

        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            import boto3

            boto3.client.return_value = MagicMock()  # type: ignore[attr-defined]
            connector = MassiveHistoricalConnector(
                mock_settings, bar_normalizer_factory=MassiveBarNormalizer
            )
        return connector

    def test_connector_name(self) -> None:
        connector = self._make_connector()
        assert connector.connector_name == "massive_historical"

    def test_placeholder_asset(self) -> None:
        asset = _placeholder_asset("AAPL")
        assert asset.symbol == "AAPL"
        assert asset.exchange == "MASSIVE"
        assert asset.asset_class == AssetClass.EQUITY

    @pytest.mark.asyncio
    async def test_fetch_bars_from_s3(self) -> None:
        connector = self._make_connector()
        rows = [_make_csv_row()]
        csv_gz = _make_csv_gz_bytes(rows)

        connector._s3_client.get_object = MagicMock(return_value={"Body": _make_s3_body(csv_gz)})

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        batches = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            batches.append(batch)

        assert len(batches) == 1
        assert isinstance(batches[0][0], Bar)

    @pytest.mark.asyncio
    async def test_fetch_bars_s3_not_found_falls_back_to_rest(self) -> None:
        connector = self._make_connector()

        connector._s3_client.get_object = MagicMock(
            side_effect=ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        )

        rest_data = {
            "results": [
                {
                    "t": int(datetime(2024, 1, 2, 14, 30, tzinfo=UTC).timestamp() * 1000),
                    "o": 185.50,
                    "h": 185.75,
                    "l": 185.35,
                    "c": 185.55,
                    "v": 10000,
                    "n": 100,
                }
            ]
        }
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=rest_data)
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            start = datetime(2024, 1, 2, tzinfo=UTC)
            end = datetime(2024, 1, 3, tzinfo=UTC)
            batches = []
            async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
                batches.append(batch)

        assert len(batches) == 1

    @pytest.mark.asyncio
    async def test_fetch_bars_filters_by_symbol(self) -> None:
        """Streaming filter returns only AAPL rows from mixed-ticker file."""
        connector = self._make_connector()
        rows = [
            _make_csv_row(ticker="AAPL"),
            _make_csv_row(ticker="MSFT"),
            _make_csv_row(ticker="AAPL"),
        ]
        csv_gz = _make_csv_gz_bytes(rows)

        connector._s3_client.get_object = MagicMock(return_value={"Body": _make_s3_body(csv_gz)})

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        all_bars = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            all_bars.extend(batch)

        assert len(all_bars) == 2

    @pytest.mark.asyncio
    async def test_fetch_ticks_raises_not_implemented(self) -> None:
        connector = self._make_connector()
        with pytest.raises(NotImplementedError, match=r"Phase 2\.6"):
            async for _ in connector.fetch_ticks(
                "AAPL",
                datetime(2024, 1, 2, tzinfo=UTC),
                datetime(2024, 1, 3, tzinfo=UTC),
            ):
                pass

    @pytest.mark.asyncio
    async def test_fetch_bars_empty_s3_file(self) -> None:
        connector = self._make_connector()
        csv_gz = _make_csv_gz_bytes([], include_header=True)

        connector._s3_client.get_object = MagicMock(return_value={"Body": _make_s3_body(csv_gz)})

        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        batches = []
        async for batch in connector.fetch_bars("AAPL", BarSize.M1, start, end):
            batches.append(batch)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_s3_download_filters_by_symbol(self) -> None:
        """_download_s3_csv_gz_filtered returns only target symbol rows."""
        connector = self._make_connector()
        rows = [
            _make_csv_row(ticker="AAPL"),
            _make_csv_row(ticker="MSFT"),
            _make_csv_row(ticker="GOOGL"),
            _make_csv_row(ticker="AAPL"),
            _make_csv_row(ticker="MSFT"),
        ]
        csv_gz = _make_csv_gz_bytes(rows)

        connector._s3_client.get_object = MagicMock(return_value={"Body": _make_s3_body(csv_gz)})

        result = await connector._download_s3_csv_gz_filtered(
            "us_stocks_sip/minute_aggs_v1/2024/01/2024-01-02.csv.gz", "AAPL"
        )
        assert result is not None
        assert len(result) == 2
        assert all(row[0] == "AAPL" for row in result)

    @pytest.mark.asyncio
    async def test_s3_client_error_non_nosuchkey_raises(self) -> None:
        """ClientError with code != NoSuchKey should raise MassiveFetchError."""
        connector = self._make_connector()

        connector._s3_client.get_object = MagicMock(
            side_effect=ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        )

        with pytest.raises(MassiveFetchError, match="S3 error AccessDenied"):
            await connector._download_s3_csv_gz_filtered(
                "us_stocks_sip/minute_aggs_v1/2024/01/2024-01-02.csv.gz", "AAPL"
            )
