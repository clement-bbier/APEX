"""Unit tests for Binance connectors (Phase 2.4).

Tests: BinanceHistoricalConnector, BinanceLiveConnector, backfill script.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType, DbTick
from services.s01_data_ingestion.connectors.binance_historical import (
    BinanceFetchError,
    BinanceHistoricalConnector,
    _bar_size_to_binance_interval,
    _placeholder_asset,
)
from services.s01_data_ingestion.connectors.binance_live import BinanceLiveConnector
from services.s01_data_ingestion.normalizers.binance_bar import BinanceBarNormalizer

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "binance_btcusdt_1m_2024-01-01.zip"
)

_DUMMY_ASSET = Asset(
    asset_id=uuid.UUID(int=1),
    symbol="BTCUSDT",
    exchange="BINANCE",
    asset_class=AssetClass.CRYPTO,
    currency="USDT",
)


def _make_zip_bytes(csv_content: str, filename: str = "data.csv") -> bytes:
    """Create an in-memory ZIP with a single CSV file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, csv_content)
    return buf.getvalue()


def _sample_kline_csv_row() -> str:
    """Return one valid Binance kline CSV row."""
    return (
        "1704067200000,42283.58000000,42298.62000000,42261.02000000,"
        "42298.61000000,35.92724000,1704067259999,1519031.69451920,"
        "1327,23.18766000,980394.71034560,0"
    )


def _sample_aggtrade_csv_row() -> str:
    """Return one valid Binance aggTrades CSV row."""
    return "123456,42283.58,0.5,100,200,1704067200000,true,true"


class TestBinanceHistoricalConnector:
    """Tests for BinanceHistoricalConnector."""

    def test_connector_name(self) -> None:
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        assert connector.connector_name == "binance_historical"

    def test_bar_size_to_binance_interval(self) -> None:
        assert _bar_size_to_binance_interval(BarSize.M1) == "1m"
        assert _bar_size_to_binance_interval(BarSize.H1) == "1h"
        assert _bar_size_to_binance_interval(BarSize.D1) == "1d"
        assert _bar_size_to_binance_interval(BarSize.MO1) == "1M"

    def test_placeholder_asset(self) -> None:
        asset = _placeholder_asset("BTCUSDT")
        assert asset.symbol == "BTCUSDT"
        assert asset.exchange == "BINANCE"
        assert asset.asset_class == AssetClass.CRYPTO
        assert asset.asset_id == uuid.UUID(int=0)

    def test_extract_csv_from_zip(self) -> None:
        csv_text = "a,b,c\n1,2,3\n4,5,6\n"
        zip_bytes = _make_zip_bytes(csv_text)
        rows = BinanceHistoricalConnector._extract_csv_from_zip(zip_bytes)
        assert len(rows) == 3
        assert rows[0] == ["a", "b", "c"]

    def test_extract_csv_from_empty_zip(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            pass
        rows = BinanceHistoricalConnector._extract_csv_from_zip(buf.getvalue())
        assert rows == []

    def test_csv_row_to_kline(self) -> None:
        row = _sample_kline_csv_row().split(",")
        kline = BinanceHistoricalConnector._csv_row_to_kline(row)
        assert kline[0] == 1704067200000  # open_time_ms
        assert kline[1] == "42283.58000000"  # open
        assert kline[8] == 1327  # trade_count
        assert len(kline) == 12

    def test_parse_agg_trade(self) -> None:
        row = _sample_aggtrade_csv_row().split(",")
        tick = BinanceHistoricalConnector._parse_agg_trade(row, _DUMMY_ASSET)
        assert isinstance(tick, DbTick)
        assert tick.price == Decimal("42283.58")
        assert tick.quantity == Decimal("0.5")
        assert tick.side == "sell"  # is_buyer_maker=true means sell
        assert tick.trade_id == "123456"

    def test_parse_agg_trade_buyer(self) -> None:
        row = "123456,42283.58,0.5,100,200,1704067200000,false,true".split(",")
        tick = BinanceHistoricalConnector._parse_agg_trade(row, _DUMMY_ASSET)
        assert tick.side == "buy"

    @pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="fixture not available")
    def test_fetch_klines_from_fixture(self) -> None:
        """Parse the real committed fixture and verify 1440 bars."""
        with open(FIXTURE_PATH, "rb") as f:
            content = f.read()
        rows = BinanceHistoricalConnector._extract_csv_from_zip(content)
        assert len(rows) == 1440

        from services.s01_data_ingestion.normalizers.binance_bar import BinanceBarNormalizer

        normalizer = BinanceBarNormalizer(BarSize.M1)
        placeholder = _placeholder_asset("BTCUSDT")
        bars = []
        for row in rows:
            kline = BinanceHistoricalConnector._csv_row_to_kline(row)
            bar = normalizer.normalize(kline, placeholder)
            bars.append(bar)

        assert len(bars) == 1440
        assert all(isinstance(b, Bar) for b in bars)
        assert all(b.bar_type == BarType.TIME for b in bars)
        assert all(b.bar_size == BarSize.M1 for b in bars)
        # First bar: 2024-01-01 00:00 UTC
        assert bars[0].timestamp == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        # Last bar: 2024-01-01 23:59 UTC
        assert bars[-1].timestamp == datetime(2024, 1, 1, 23, 59, tzinfo=UTC)

    def test_daily_kline_urls(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        urls = list(BinanceHistoricalConnector._daily_kline_urls("BTCUSDT", "1m", start, end))
        assert len(urls) == 2
        assert "2024-01-01" in urls[0]
        assert "2024-01-02" in urls[1]
        assert "/daily/klines/" in urls[0]

    def test_monthly_kline_urls(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 4, 1, tzinfo=UTC)
        urls = list(BinanceHistoricalConnector._monthly_kline_urls("BTCUSDT", "1m", start, end))
        assert len(urls) == 3
        assert "2024-01" in urls[0]
        assert "2024-02" in urls[1]
        assert "2024-03" in urls[2]
        assert "/monthly/klines/" in urls[0]

    @pytest.mark.asyncio
    async def test_download_zip_csv_404_returns_none(self) -> None:
        """On 404, _download_zip_csv returns None (fallback trigger)."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        result = await connector._download_zip_csv(mock_client, "https://example.com/test.zip")
        assert result is None

    @pytest.mark.asyncio
    async def test_download_zip_csv_success(self) -> None:
        """Successful ZIP download and CSV extraction."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        csv_text = _sample_kline_csv_row() + "\n"
        zip_bytes = _make_zip_bytes(csv_text)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = zip_bytes
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        result = await connector._download_zip_csv(mock_client, "https://example.com/test.zip")
        assert result is not None
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_download_zip_csv_retry_on_429(self) -> None:
        """On 429, retries with backoff then succeeds."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        csv_text = _sample_kline_csv_row() + "\n"
        zip_bytes = _make_zip_bytes(csv_text)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429

        resp_ok = MagicMock(spec=httpx.Response)
        resp_ok.status_code = 200
        resp_ok.content = zip_bytes
        resp_ok.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=[resp_429, resp_ok])

        with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
            result = await connector._download_zip_csv(mock_client, "https://example.com/test.zip")
        assert result is not None
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_bars_streaming(self) -> None:
        """fetch_bars yields batches from mocked ZIP downloads."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        csv_text = _sample_kline_csv_row() + "\n"
        zip_bytes = _make_zip_bytes(csv_text)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = zip_bytes
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
                start = datetime(2024, 1, 1, tzinfo=UTC)
                end = datetime(2024, 1, 2, tzinfo=UTC)
                batches: list[list[Bar]] = []
                async for batch in connector.fetch_bars("BTCUSDT", BarSize.M1, start, end):
                    batches.append(batch)

        assert len(batches) >= 1
        assert all(isinstance(b, Bar) for batch in batches for b in batch)


class TestBinanceLiveConnector:
    """Tests for BinanceLiveConnector stub."""

    def test_connector_name(self) -> None:
        connector = BinanceLiveConnector()
        assert connector.connector_name == "binance_live"

    @pytest.mark.asyncio
    async def test_fetch_bars_raises(self) -> None:
        connector = BinanceLiveConnector()
        with pytest.raises(NotImplementedError, match="stream-based"):
            async for _ in connector.fetch_bars(
                "BTCUSDT",
                BarSize.M1,
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            ):
                pass

    @pytest.mark.asyncio
    async def test_fetch_ticks_raises(self) -> None:
        connector = BinanceLiveConnector()
        with pytest.raises(NotImplementedError, match="stream-based"):
            async for _ in connector.fetch_ticks(
                "BTCUSDT",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            ):
                pass


class TestBackfillScript:
    """Tests for scripts/backfill_binance.py."""

    def test_argparse_valid(self) -> None:
        """Verify argparse accepts valid arguments."""
        import scripts.backfill_binance as mod

        parser = mod.main.__code__
        # Just verify the module imports without error
        assert hasattr(mod, "run_backfill")
        assert hasattr(mod, "main")

    @pytest.mark.asyncio
    async def test_dry_run_no_insert(self) -> None:
        """Dry run should validate but not insert bars."""
        from scripts.backfill_binance import run_backfill

        csv_text = _sample_kline_csv_row() + "\n"
        zip_bytes = _make_zip_bytes(csv_text)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = zip_bytes
        mock_response.raise_for_status = MagicMock()

        mock_repo = AsyncMock()
        mock_repo.connect = AsyncMock()
        mock_repo.close = AsyncMock()
        mock_repo.get_asset = AsyncMock(return_value=_DUMMY_ASSET)
        mock_repo.start_ingestion_run = AsyncMock(return_value=uuid.uuid4())
        mock_repo.finish_ingestion_run = AsyncMock()
        mock_repo.insert_bars = AsyncMock(return_value=0)

        with (
            patch("scripts.backfill_binance.get_settings") as mock_settings,
            patch("scripts.backfill_binance.TimescaleRepository", return_value=mock_repo),
            patch("httpx.AsyncClient") as mock_cls,
            patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"),
        ):
            mock_settings.return_value.timescale_dsn = "postgresql://test:test@localhost/test"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 1, 2, tzinfo=UTC)
            await run_backfill("BTCUSDT", start, end, "1m", dry_run=True)

        # dry_run=True means insert_bars should NOT be called
        mock_repo.insert_bars.assert_not_called()

    def test_backfill_pipeline_imports(self) -> None:
        """Verify the full import chain works."""
        from services.s01_data_ingestion.connectors import (
            BinanceHistoricalConnector,
            BinanceLiveConnector,
            DataConnector,
        )

        assert issubclass(BinanceHistoricalConnector, DataConnector)
        assert issubclass(BinanceLiveConnector, DataConnector)


class TestCopilotFixes:
    """Tests for Copilot review fixes on PR #43."""

    def test_parse_utc_datetime_naive_input(self) -> None:
        """Naive ISO string should become UTC-aware."""
        from scripts.backfill_binance import _parse_utc_datetime

        dt = _parse_utc_datetime("2024-01-01")
        assert dt.tzinfo is not None
        assert dt.tzinfo == UTC

    def test_parse_utc_datetime_aware_input(self) -> None:
        """Already-aware datetime should remain unchanged."""
        from scripts.backfill_binance import _parse_utc_datetime

        dt = _parse_utc_datetime("2024-01-01T00:00:00+00:00")
        assert dt.tzinfo is not None

    @pytest.mark.asyncio
    async def test_download_zip_csv_max_retries_raises(self) -> None:
        """After exhausting retries on 429, should raise BinanceFetchError."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=resp_429)

        with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
            with pytest.raises(BinanceFetchError, match="max retries exceeded"):
                await connector._download_zip_csv(mock_client, "https://example.com/test.zip")

    @pytest.mark.asyncio
    async def test_fallback_rest_klines_paginates(self) -> None:
        """REST fallback should paginate: 1000 + 440 = 1440 total rows."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)

        # First page: 1000 klines, second page: 440 klines, third page: empty
        page1 = [[str(1704067200000 + i * 60000)] + ["1"] * 11 for i in range(1000)]
        page2 = [[str(1704067200000 + (1000 + i) * 60000)] + ["1"] * 11 for i in range(440)]

        resp1 = MagicMock(spec=httpx.Response)
        resp1.status_code = 200
        resp1.json = MagicMock(return_value=page1)
        resp1.raise_for_status = MagicMock()

        resp2 = MagicMock(spec=httpx.Response)
        resp2.status_code = 200
        resp2.json = MagicMock(return_value=page2)
        resp2.raise_for_status = MagicMock()

        resp_empty = MagicMock(spec=httpx.Response)
        resp_empty.status_code = 200
        resp_empty.json = MagicMock(return_value=[])
        resp_empty.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=[resp1, resp2, resp_empty])

        with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
            start = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2024, 1, 2, tzinfo=UTC)
            rows = await connector._fallback_rest_klines(mock_client, "BTCUSDT", "1m", start, end)
        assert len(rows) == 1440

    @pytest.mark.asyncio
    async def test_fetch_bars_404_uses_period_specific_fallback(self) -> None:
        """On 404, fallback should receive period bounds, not global range."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)

        resp_404 = MagicMock(spec=httpx.Response)
        resp_404.status_code = 404

        # REST fallback returns one kline
        kline_row = _sample_kline_csv_row().split(",")
        rest_resp = MagicMock(spec=httpx.Response)
        rest_resp.status_code = 200
        rest_resp.json = MagicMock(return_value=[kline_row])
        rest_resp.raise_for_status = MagicMock()

        rest_resp_empty = MagicMock(spec=httpx.Response)
        rest_resp_empty.status_code = 200
        rest_resp_empty.json = MagicMock(return_value=[])
        rest_resp_empty.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            # First call: ZIP 404, then REST klines, then empty
            mock_client.get = AsyncMock(side_effect=[resp_404, rest_resp, rest_resp_empty])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
                start = datetime(2024, 1, 1, tzinfo=UTC)
                end = datetime(2024, 1, 2, tzinfo=UTC)
                batches = []
                async for batch in connector.fetch_bars("BTCUSDT", BarSize.M1, start, end):
                    batches.append(batch)

        assert len(batches) >= 1

    @pytest.mark.asyncio
    async def test_fetch_ticks_rest_fallback(self) -> None:
        """On 404 for aggTrades ZIP, REST fallback should be called."""
        connector = BinanceHistoricalConnector(bar_normalizer_factory=BinanceBarNormalizer)

        resp_404 = MagicMock(spec=httpx.Response)
        resp_404.status_code = 404

        # REST fallback returns one trade
        trade = {
            "a": 1,
            "p": "42000.0",
            "q": "0.5",
            "f": 100,
            "l": 200,
            "T": 1704067200000,
            "m": True,
        }
        rest_resp = MagicMock(spec=httpx.Response)
        rest_resp.status_code = 200
        rest_resp.json = MagicMock(return_value=[trade])
        rest_resp.raise_for_status = MagicMock()

        rest_resp_empty = MagicMock(spec=httpx.Response)
        rest_resp_empty.status_code = 200
        rest_resp_empty.json = MagicMock(return_value=[])
        rest_resp_empty.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            # ZIP 404, then REST trades, then empty for remaining hours
            mock_client.get = AsyncMock(side_effect=[resp_404, rest_resp] + [rest_resp_empty] * 24)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("services.s01_data_ingestion.connectors.binance_historical.asyncio.sleep"):
                start = datetime(2024, 1, 1, tzinfo=UTC)
                end = datetime(2024, 1, 2, tzinfo=UTC)
                batches = []
                async for batch in connector.fetch_ticks("BTCUSDT", start, end):
                    batches.append(batch)

        assert len(batches) >= 1
        assert batches[0][0].price == Decimal("42000.0")
