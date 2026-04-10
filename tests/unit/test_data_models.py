"""Unit tests for core/models/data.py — universal data schema models.

Tests creation, frozen immutability, StrEnum values, Decimal coercion,
and edge cases for all Pydantic v2 models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    CorporateEvent,
    DataQualityEntry,
    DbTick,
    EconomicEvent,
    EventImpact,
    FundamentalPoint,
    IngestionRun,
    IngestionStatus,
    MacroPoint,
    MacroSeriesMeta,
    OrderBookLevel,
    Severity,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

NOW = datetime.now(UTC)
ASSET_ID = uuid.uuid4()


def _make_asset(**overrides):
    defaults = {
        "symbol": "BTCUSDT",
        "exchange": "BINANCE",
        "asset_class": AssetClass.CRYPTO,
        "currency": "USD",
    }
    defaults.update(overrides)
    return Asset(**defaults)


def _make_bar(**overrides):
    defaults = {
        "asset_id": ASSET_ID,
        "bar_type": BarType.TIME,
        "bar_size": BarSize.M1,
        "timestamp": NOW,
        "open": Decimal("100.5"),
        "high": Decimal("101.0"),
        "low": Decimal("99.5"),
        "close": Decimal("100.8"),
        "volume": Decimal("1234.56"),
    }
    defaults.update(overrides)
    return Bar(**defaults)


def _make_tick(**overrides):
    defaults = {
        "asset_id": ASSET_ID,
        "timestamp": NOW,
        "price": Decimal("100.0"),
        "quantity": Decimal("1.5"),
    }
    defaults.update(overrides)
    return DbTick(**defaults)


# ── StrEnum tests ─────────────────────────────────────────────────────────────


class TestStrEnums:
    def test_asset_class_values(self):
        assert AssetClass.CRYPTO.value == "crypto"
        assert AssetClass.EQUITY.value == "equity"
        assert AssetClass.FOREX.value == "forex"
        assert AssetClass.COMMODITY.value == "commodity"
        assert AssetClass.BOND.value == "bond"
        assert AssetClass.OPTION.value == "option"
        assert AssetClass.FUTURE.value == "future"
        assert AssetClass.INDEX.value == "index"
        assert AssetClass.MACRO.value == "macro"

    def test_bar_type_values(self):
        assert BarType.TIME.value == "time"
        assert BarType.TICK.value == "tick"
        assert BarType.VOLUME.value == "volume"
        assert BarType.DOLLAR.value == "dollar"

    def test_bar_size_values(self):
        assert BarSize.M1.value == "1m"
        assert BarSize.M5.value == "5m"
        assert BarSize.M15.value == "15m"
        assert BarSize.H1.value == "1h"
        assert BarSize.H4.value == "4h"
        assert BarSize.D1.value == "1d"
        assert BarSize.W1.value == "1w"
        assert BarSize.MO1.value == "1M"

    def test_event_impact_values(self):
        assert EventImpact.LOW.value == "low"
        assert EventImpact.MEDIUM.value == "medium"
        assert EventImpact.HIGH.value == "high"

    def test_severity_values(self):
        assert Severity.INFO.value == "info"
        assert Severity.WARNING.value == "warning"
        assert Severity.ERROR.value == "error"
        assert Severity.CRITICAL.value == "critical"

    def test_ingestion_status_values(self):
        assert IngestionStatus.RUNNING.value == "running"
        assert IngestionStatus.SUCCESS.value == "success"
        assert IngestionStatus.FAILED.value == "failed"
        assert IngestionStatus.PARTIAL.value == "partial"


# ── Asset tests ───────────────────────────────────────────────────────────────


class TestAsset:
    def test_create_asset(self):
        asset = _make_asset()
        assert asset.symbol == "BTCUSDT"
        assert asset.exchange == "BINANCE"
        assert asset.asset_class == AssetClass.CRYPTO
        assert asset.currency == "USD"
        assert asset.is_active is True
        assert asset.timezone == "UTC"

    def test_frozen(self):
        asset = _make_asset()
        with pytest.raises(ValidationError):
            asset.symbol = "ETHUSDT"

    def test_symbol_uppercase(self):
        asset = _make_asset(symbol="btcusdt")
        assert asset.symbol == "BTCUSDT"

    def test_exchange_uppercase(self):
        asset = _make_asset(exchange="binance")
        assert asset.exchange == "BINANCE"

    def test_decimal_coercion_tick_size(self):
        asset = _make_asset(tick_size="0.01")
        assert asset.tick_size == Decimal("0.01")
        assert isinstance(asset.tick_size, Decimal)

    def test_decimal_coercion_lot_size_float(self):
        asset = _make_asset(lot_size=0.001)
        assert isinstance(asset.lot_size, Decimal)

    def test_asset_id_auto_generated(self):
        asset = _make_asset()
        assert isinstance(asset.asset_id, uuid.UUID)

    def test_empty_symbol_rejected(self):
        with pytest.raises(ValidationError):
            _make_asset(symbol="")

    def test_metadata_json_default(self):
        asset = _make_asset()
        assert asset.metadata_json == {}

    def test_with_all_optional_fields(self):
        asset = _make_asset(
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.001"),
            listing_date=date(2020, 1, 1),
            delisting_date=date(2025, 1, 1),
            metadata_json={"sector": "tech"},
            created_at=NOW,
            updated_at=NOW,
        )
        assert asset.listing_date == date(2020, 1, 1)
        assert asset.metadata_json["sector"] == "tech"


# ── Bar tests ─────────────────────────────────────────────────────────────────


class TestBar:
    def test_create_bar(self):
        bar = _make_bar()
        assert bar.open == Decimal("100.5")
        assert bar.bar_type == BarType.TIME
        assert bar.bar_size == BarSize.M1

    def test_frozen(self):
        bar = _make_bar()
        with pytest.raises(ValidationError):
            bar.close = Decimal("200")

    def test_decimal_coercion_from_string(self):
        bar = _make_bar(open="50.25", high="51.0", low="49.5", close="50.75")
        assert bar.open == Decimal("50.25")
        assert isinstance(bar.open, Decimal)

    def test_decimal_coercion_from_float(self):
        bar = _make_bar(open=50.25, high=51.0, low=49.5, close=50.75)
        assert isinstance(bar.open, Decimal)

    def test_zero_price_rejected(self):
        with pytest.raises(ValidationError):
            _make_bar(open=Decimal("0"))

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            _make_bar(high=Decimal("-1"))

    def test_zero_volume_accepted(self):
        bar = _make_bar(volume=Decimal("0"))
        assert bar.volume == Decimal("0")

    def test_optional_fields_none(self):
        bar = _make_bar()
        assert bar.trade_count is None
        assert bar.vwap is None
        assert bar.adj_close is None

    def test_with_optional_fields(self):
        bar = _make_bar(trade_count=42, vwap="100.6", adj_close="100.8")
        assert bar.trade_count == 42
        assert bar.vwap == Decimal("100.6")


# ── DbTick tests ─────────────────────────────────────────────────────────────


class TestDbTick:
    def test_create_tick(self):
        tick = _make_tick()
        assert tick.price == Decimal("100.0")
        assert tick.side == "unknown"
        assert tick.trade_id == ""

    def test_frozen(self):
        tick = _make_tick()
        with pytest.raises(ValidationError):
            tick.price = Decimal("200")

    def test_decimal_coercion(self):
        tick = _make_tick(price="55.5", quantity="10")
        assert tick.price == Decimal("55.5")
        assert isinstance(tick.quantity, Decimal)

    def test_zero_price_rejected(self):
        with pytest.raises(ValidationError):
            _make_tick(price=Decimal("0"))

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            _make_tick(quantity=Decimal("0"))

    def test_with_trade_id_and_side(self):
        tick = _make_tick(trade_id="12345", side="buy")
        assert tick.trade_id == "12345"
        assert tick.side == "buy"


# ── OrderBookLevel tests ─────────────────────────────────────────────────────


class TestOrderBookLevel:
    def test_create(self):
        ob = OrderBookLevel(
            asset_id=ASSET_ID,
            timestamp=NOW,
            depth_level=1,
            bid_price=Decimal("100.0"),
            bid_size=Decimal("5.0"),
            ask_price=Decimal("100.1"),
            ask_size=Decimal("3.0"),
        )
        assert ob.depth_level == 1
        assert ob.bid_price == Decimal("100.0")

    def test_frozen(self):
        ob = OrderBookLevel(asset_id=ASSET_ID, timestamp=NOW, depth_level=1)
        with pytest.raises(ValidationError):
            ob.depth_level = 2

    def test_depth_level_min(self):
        with pytest.raises(ValidationError):
            OrderBookLevel(asset_id=ASSET_ID, timestamp=NOW, depth_level=0)

    def test_decimal_coercion(self):
        ob = OrderBookLevel(
            asset_id=ASSET_ID,
            timestamp=NOW,
            depth_level=1,
            bid_price="99.5",
            ask_price=100.5,
        )
        assert isinstance(ob.bid_price, Decimal)
        assert isinstance(ob.ask_price, Decimal)


# ── MacroPoint tests ─────────────────────────────────────────────────────────


class TestMacroPoint:
    def test_create(self):
        mp = MacroPoint(series_id="VIXCLS", timestamp=NOW, value=18.5)
        assert mp.series_id == "VIXCLS"
        assert mp.value == 18.5

    def test_frozen(self):
        mp = MacroPoint(series_id="VIXCLS", timestamp=NOW, value=18.5)
        with pytest.raises(ValidationError):
            mp.value = 20.0

    def test_empty_series_id_rejected(self):
        with pytest.raises(ValidationError):
            MacroPoint(series_id="", timestamp=NOW, value=1.0)


# ── MacroSeriesMeta tests ────────────────────────────────────────────────────


class TestMacroSeriesMeta:
    def test_create(self):
        meta = MacroSeriesMeta(series_id="VIXCLS", source="FRED", name="VIX Close")
        assert meta.series_id == "VIXCLS"
        assert meta.frequency is None

    def test_frozen(self):
        meta = MacroSeriesMeta(series_id="VIXCLS", source="FRED", name="VIX Close")
        with pytest.raises(ValidationError):
            meta.source = "ECB"

    def test_with_all_fields(self):
        meta = MacroSeriesMeta(
            series_id="DGS10",
            source="FRED",
            name="10-Year Treasury",
            frequency="daily",
            unit="percent",
            description="Market yield on US 10Y",
        )
        assert meta.unit == "percent"


# ── FundamentalPoint tests ───────────────────────────────────────────────────


class TestFundamentalPoint:
    def test_create(self):
        fp = FundamentalPoint(
            asset_id=ASSET_ID,
            report_date=date(2024, 3, 31),
            period_type="quarterly",
            metric_name="revenue",
            value=1_000_000.0,
            currency="USD",
        )
        assert fp.metric_name == "revenue"
        assert fp.value == 1_000_000.0

    def test_frozen(self):
        fp = FundamentalPoint(
            asset_id=ASSET_ID,
            report_date=date(2024, 3, 31),
            period_type="quarterly",
            metric_name="eps",
        )
        with pytest.raises(ValidationError):
            fp.metric_name = "revenue"


# ── CorporateEvent tests ─────────────────────────────────────────────────────


class TestCorporateEvent:
    def test_create(self):
        ce = CorporateEvent(
            asset_id=ASSET_ID,
            event_date=date(2024, 6, 15),
            event_type="split",
            details_json={"ratio": "4:1"},
        )
        assert ce.event_type == "split"
        assert ce.details_json["ratio"] == "4:1"
        assert isinstance(ce.event_id, uuid.UUID)

    def test_frozen(self):
        ce = CorporateEvent(
            asset_id=ASSET_ID,
            event_date=date(2024, 6, 15),
            event_type="dividend",
        )
        with pytest.raises(ValidationError):
            ce.event_type = "split"


# ── EconomicEvent tests ──────────────────────────────────────────────────────


class TestEconomicEvent:
    def test_create(self):
        ee = EconomicEvent(
            event_type="FOMC",
            scheduled_time=NOW,
            actual=5.25,
            consensus=5.25,
            prior=5.0,
            impact_score=3,
        )
        assert ee.event_type == "FOMC"
        assert ee.impact_score == 3

    def test_frozen(self):
        ee = EconomicEvent(event_type="US_CPI", scheduled_time=NOW)
        with pytest.raises(ValidationError):
            ee.actual = 3.5

    def test_impact_score_bounds(self):
        with pytest.raises(ValidationError):
            EconomicEvent(event_type="FOMC", scheduled_time=NOW, impact_score=0)
        with pytest.raises(ValidationError):
            EconomicEvent(event_type="FOMC", scheduled_time=NOW, impact_score=4)

    def test_defaults(self):
        ee = EconomicEvent(event_type="ECB_RATE", scheduled_time=NOW)
        assert ee.actual is None
        assert ee.consensus is None
        assert ee.prior is None
        assert ee.impact_score == 1
        assert ee.related_asset_id is None
        assert ee.source is None


# ── DataQualityEntry tests ───────────────────────────────────────────────────


class TestDataQualityEntry:
    def test_create(self):
        dq = DataQualityEntry(
            check_type="gap",
            severity=Severity.WARNING,
            asset_id=ASSET_ID,
        )
        assert dq.check_type == "gap"
        assert dq.severity == Severity.WARNING
        assert dq.resolved is False

    def test_frozen(self):
        dq = DataQualityEntry(check_type="outlier", severity=Severity.ERROR)
        with pytest.raises(ValidationError):
            dq.resolved = True


# ── IngestionRun tests ───────────────────────────────────────────────────────


class TestIngestionRun:
    def test_create(self):
        ir = IngestionRun(
            connector="binance",
            started_at=NOW,
        )
        assert ir.connector == "binance"
        assert ir.status == IngestionStatus.RUNNING
        assert ir.rows_inserted == 0

    def test_frozen(self):
        ir = IngestionRun(connector="alpaca", started_at=NOW)
        with pytest.raises(ValidationError):
            ir.status = IngestionStatus.SUCCESS

    def test_with_all_fields(self):
        ir = IngestionRun(
            connector="polygon",
            asset_id=ASSET_ID,
            started_at=NOW,
            finished_at=NOW,
            status=IngestionStatus.SUCCESS,
            rows_inserted=5000,
            metadata_json={"date_range": "2024-01-01/2024-06-30"},
        )
        assert ir.rows_inserted == 5000
        assert ir.status == IngestionStatus.SUCCESS
