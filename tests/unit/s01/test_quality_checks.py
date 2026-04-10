"""Unit tests for the data quality pipeline checks and orchestrator.

Covers: GapCheck, OutlierCheck, TimestampCheck, VolumeCheck, PriceCheck,
StaleCheck, and DataQualityChecker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from core.models.data import Asset, AssetClass, Bar, BarSize, BarType, DbTick
from services.s01_data_ingestion.quality.base import CheckResult
from services.s01_data_ingestion.quality.checker import DataQualityChecker
from services.s01_data_ingestion.quality.config import QualityConfig
from services.s01_data_ingestion.quality.gap_check import GapCheck
from services.s01_data_ingestion.quality.outlier_check import OutlierCheck
from services.s01_data_ingestion.quality.price_check import PriceCheck
from services.s01_data_ingestion.quality.stale_check import StaleCheck
from services.s01_data_ingestion.quality.timestamp_check import TimestampCheck
from services.s01_data_ingestion.quality.volume_check import VolumeCheck

# ── Helpers ─────────────────────────────────────────────────────────────────

_ASSET_ID = uuid.uuid4()
_DEFAULT_CONFIG = QualityConfig()


def _make_asset(
    asset_class: AssetClass = AssetClass.CRYPTO,
    listing_date: date | None = None,
) -> Asset:
    return Asset(
        asset_id=_ASSET_ID,
        symbol="BTCUSDT",
        exchange="BINANCE",
        asset_class=asset_class,
        currency="USD",
        listing_date=listing_date,
    )


def _make_bar(
    timestamp: datetime,
    close: float = 50000.0,
    volume: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
    bar_size: BarSize = BarSize.M1,
) -> Bar:
    c = Decimal(str(close))
    h = Decimal(str(high)) if high is not None else c + Decimal("10")
    lo = Decimal(str(low)) if low is not None else c - Decimal("10")
    o = Decimal(str(open_)) if open_ is not None else c
    return Bar(
        asset_id=_ASSET_ID,
        bar_type=BarType.TIME,
        bar_size=bar_size,
        timestamp=timestamp,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=Decimal(str(volume)),
    )


def _make_bars(
    count: int,
    start_timestamp: datetime,
    interval_seconds: int = 60,
    close: float = 50000.0,
    bar_size: BarSize = BarSize.M1,
) -> list[Bar]:
    return [
        _make_bar(
            timestamp=start_timestamp + timedelta(seconds=i * interval_seconds),
            close=close,
            bar_size=bar_size,
        )
        for i in range(count)
    ]


def _make_tick(
    timestamp: datetime,
    price: float = 50000.0,
    quantity: float = 1.0,
) -> DbTick:
    return DbTick(
        asset_id=_ASSET_ID,
        timestamp=timestamp,
        price=Decimal(str(price)),
        quantity=Decimal(str(quantity)),
    )


# ── TestGapCheck ────────────────────────────────────────────────────────────


class TestGapCheck:
    def setup_method(self) -> None:
        self.check = GapCheck(_DEFAULT_CONFIG)
        self.asset = _make_asset()

    def test_no_gaps_consecutive(self) -> None:
        bars = _make_bars(5, datetime(2025, 1, 6, 10, 0, tzinfo=UTC))
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_gap_detected(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = _make_bars(3, start)
        # Insert a gap: skip 2 minutes
        bars.append(_make_bar(start + timedelta(minutes=5)))
        bars.append(_make_bar(start + timedelta(minutes=6)))
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) >= 1
        assert all(i.severity == CheckResult.WARN for i in issues)

    def test_weekend_gap_equity_ignored(self) -> None:
        asset = _make_asset(AssetClass.EQUITY)
        # Friday 16:00 -> Monday 09:30
        friday = datetime(2025, 1, 3, 16, 0, tzinfo=UTC)  # Friday
        monday = datetime(2025, 1, 6, 9, 30, tzinfo=UTC)  # Monday
        bars = [
            _make_bar(friday),
            _make_bar(monday),
        ]
        issues = self.check.check_bars(bars, asset)
        assert len(issues) == 0

    def test_weekend_gap_crypto_detected(self) -> None:
        # Crypto trades 24/7 — weekend gaps are flagged
        friday = datetime(2025, 1, 3, 16, 0, tzinfo=UTC)
        monday = datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
        bars = [
            _make_bar(friday),
            _make_bar(monday),
        ]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) >= 1

    def test_hourly_gap(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = [
            _make_bar(start, bar_size=BarSize.H1),
            _make_bar(start + timedelta(hours=1), bar_size=BarSize.H1),
            _make_bar(start + timedelta(hours=4), bar_size=BarSize.H1),  # 2h gap
        ]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) >= 1

    def test_empty_bars(self) -> None:
        issues = self.check.check_bars([], self.asset)
        assert len(issues) == 0


# ── TestOutlierCheck ────────────────────────────────────────────────────────


class TestOutlierCheck:
    def setup_method(self) -> None:
        self.check = OutlierCheck(_DEFAULT_CONFIG)
        self.asset = _make_asset()

    def test_normal_prices(self) -> None:
        # 110 bars with slight variation — no outliers expected
        import random as _random

        _random.seed(42)
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = [
            _make_bar(
                start + timedelta(minutes=i),
                close=50000.0 + _random.uniform(-100, 100),
            )
            for i in range(110)
        ]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_extreme_outlier_fail(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = _make_bars(110, start, close=50000.0)
        # Inject extreme outlier at position 105
        bars[105] = _make_bar(bars[105].timestamp, close=100000.0)
        issues = self.check.check_bars(bars, self.asset)
        fails = [i for i in issues if i.severity == CheckResult.FAIL]
        assert len(fails) >= 1

    def test_moderate_outlier_warn(self) -> None:
        import random as _random

        _random.seed(99)
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        # Bars with natural variance so std > 0
        config = QualityConfig(outlier_warn_sigma=2.0, outlier_fail_sigma=100.0)
        check = OutlierCheck(config)
        bars = [
            _make_bar(start + timedelta(minutes=i), close=50000.0 + _random.uniform(-50, 50))
            for i in range(110)
        ]
        # Inject moderate outlier (~5 sigma from mean with std ~30)
        bars[105] = _make_bar(bars[105].timestamp, close=50300.0)
        issues = check.check_bars(bars, self.asset)
        warns = [i for i in issues if i.severity == CheckResult.WARN]
        assert len(warns) >= 1

    def test_insufficient_window(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = _make_bars(10, start)  # Less than default window of 100
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_custom_config(self) -> None:
        import random as _random

        _random.seed(77)
        config = QualityConfig(outlier_warn_sigma=2.0, outlier_window=5)
        check = OutlierCheck(config)
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = [
            _make_bar(start + timedelta(minutes=i), close=100.0 + _random.uniform(-2, 2))
            for i in range(20)
        ]
        bars[15] = _make_bar(bars[15].timestamp, close=200.0)
        issues = check.check_bars(bars, self.asset)
        assert len(issues) >= 1


# ── TestTimestampCheck ──────────────────────────────────────────────────────


class TestTimestampCheck:
    def setup_method(self) -> None:
        self.check = TimestampCheck(_DEFAULT_CONFIG)
        self.asset = _make_asset()

    def test_normal_timestamp(self) -> None:
        bars = [_make_bar(datetime.now(UTC) - timedelta(minutes=5))]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_future_timestamp_fail(self) -> None:
        future = datetime.now(UTC) + timedelta(days=1)
        bars = [_make_bar(future)]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 1
        assert issues[0].severity == CheckResult.FAIL

    def test_epoch_zero_fail(self) -> None:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        bars = [_make_bar(epoch)]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 1
        assert issues[0].severity == CheckResult.FAIL

    def test_before_listing_date_fail(self) -> None:
        asset = _make_asset(listing_date=date(2020, 1, 1))
        bars = [_make_bar(datetime(2019, 6, 1, tzinfo=UTC))]
        issues = self.check.check_bars(bars, asset)
        assert len(issues) == 1
        assert issues[0].severity == CheckResult.FAIL

    def test_future_within_tolerance(self) -> None:
        # 30 seconds into the future is within the default 60s tolerance
        near_future = datetime.now(UTC) + timedelta(seconds=30)
        bars = [_make_bar(near_future)]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0


# ── TestVolumeCheck ─────────────────────────────────────────────────────────


class TestVolumeCheck:
    def setup_method(self) -> None:
        self.check = VolumeCheck(_DEFAULT_CONFIG)
        self.asset = _make_asset()

    def test_normal_volume(self) -> None:
        bars = _make_bars(5, datetime(2025, 1, 6, 10, 0, tzinfo=UTC))
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_zero_volume_warn(self) -> None:
        bars = [_make_bar(datetime(2025, 1, 6, 10, 0, tzinfo=UTC), volume=0.0)]
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 1
        assert issues[0].severity == CheckResult.WARN

    def test_negative_volume_fail(self) -> None:
        # Use model_construct to bypass Pydantic ge=0 validation
        bar = Bar.model_construct(
            asset_id=_ASSET_ID,
            bar_type=BarType.TIME,
            bar_size=BarSize.M1,
            timestamp=datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            open=Decimal("50000"),
            high=Decimal("50010"),
            low=Decimal("49990"),
            close=Decimal("50000"),
            volume=Decimal("-10"),
            trade_count=None,
            vwap=None,
            adj_close=None,
        )
        issues = self.check.check_bars([bar], self.asset)
        assert len(issues) == 1
        assert issues[0].severity == CheckResult.FAIL

    def test_volume_spike_warn(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
        bars = _make_bars(10, start, close=50000.0)
        # Append a bar with volume 100x the average (100 * 10 = 1000x)
        bars.append(_make_bar(start + timedelta(minutes=10), volume=100000.0))
        issues = self.check.check_bars(bars, self.asset)
        spikes = [i for i in issues if i.check_type == "volume_spike"]
        assert len(spikes) >= 1
        assert spikes[0].severity == CheckResult.WARN


# ── TestPriceCheck ──────────────────────────────────────────────────────────


class TestPriceCheck:
    def setup_method(self) -> None:
        self.check = PriceCheck(_DEFAULT_CONFIG)
        self.asset = _make_asset(AssetClass.EQUITY)

    def test_normal_price(self) -> None:
        bars = _make_bars(5, datetime(2025, 1, 6, 10, 0, tzinfo=UTC))
        issues = self.check.check_bars(bars, self.asset)
        assert len(issues) == 0

    def test_negative_price_equity_fail(self) -> None:
        bar = Bar.model_construct(
            asset_id=_ASSET_ID,
            bar_type=BarType.TIME,
            bar_size=BarSize.M1,
            timestamp=datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            open=Decimal("-5"),
            high=Decimal("-1"),
            low=Decimal("-10"),
            close=Decimal("-5"),
            volume=Decimal("100"),
            trade_count=None,
            vwap=None,
            adj_close=None,
        )
        issues = self.check.check_bars([bar], self.asset)
        price_issues = [i for i in issues if i.check_type == "price_non_positive"]
        assert len(price_issues) >= 1
        assert price_issues[0].severity == CheckResult.FAIL

    def test_high_less_than_low_warn(self) -> None:
        bar = _make_bar(
            datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            close=100.0,
            high=90.0,
            low=110.0,
        )
        issues = self.check.check_bars([bar], self.asset)
        hl = [i for i in issues if i.check_type == "price_high_lt_low"]
        assert len(hl) >= 1
        assert hl[0].severity == CheckResult.WARN

    def test_close_outside_range_warn(self) -> None:
        bar = _make_bar(
            datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            close=200.0,
            high=150.0,
            low=100.0,
        )
        issues = self.check.check_bars([bar], self.asset)
        outside = [i for i in issues if i.check_type == "price_close_outside_range"]
        assert len(outside) >= 1
        assert outside[0].severity == CheckResult.WARN

    def test_excessive_spread_warn(self) -> None:
        # Spread > 50%: high=200, low=50 -> spread = 150/125 = 1.2 > 0.50
        bar = _make_bar(
            datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            close=125.0,
            high=200.0,
            low=50.0,
        )
        issues = self.check.check_bars([bar], self.asset)
        spreads = [i for i in issues if i.check_type == "price_excessive_spread"]
        assert len(spreads) >= 1
        assert spreads[0].severity == CheckResult.WARN


# ── TestStaleCheck ──────────────────────────────────────────────────────────


class TestStaleCheck:
    def setup_method(self) -> None:
        self.check = StaleCheck(_DEFAULT_CONFIG)

    def test_not_stale(self) -> None:
        asset = _make_asset(AssetClass.CRYPTO)
        now = datetime.now(UTC)
        last = now - timedelta(minutes=2)
        issue = self.check.check_staleness(asset, last, now)
        assert issue is None

    def test_stale_crypto(self) -> None:
        asset = _make_asset(AssetClass.CRYPTO)
        now = datetime.now(UTC)
        last = now - timedelta(minutes=10)  # 600s > 300s threshold
        issue = self.check.check_staleness(asset, last, now)
        assert issue is not None
        assert issue.severity == CheckResult.WARN

    def test_stale_equity(self) -> None:
        asset = _make_asset(AssetClass.EQUITY)
        now = datetime.now(UTC)
        last = now - timedelta(minutes=20)  # 1200s > 900s threshold
        issue = self.check.check_staleness(asset, last, now)
        assert issue is not None
        assert issue.severity == CheckResult.WARN


# ── TestDataQualityChecker ──────────────────────────────────────────────────


class TestDataQualityChecker:
    def setup_method(self) -> None:
        self.asset = _make_asset()

    def test_all_clean(self) -> None:
        checker = DataQualityChecker()
        start = datetime.now(UTC) - timedelta(hours=2)
        bars = _make_bars(50, start)
        report = checker.validate_bars(bars, self.asset)
        assert report.pass_rate == 1.0
        assert report.is_acceptable is True
        assert len(report.clean_bars) == 50
        assert len(report.rejected_bars) == 0

    def test_mixed_issues(self) -> None:
        checker = DataQualityChecker()
        start = datetime.now(UTC) - timedelta(hours=2)
        bars = _make_bars(50, start)
        # Add a bar with future timestamp (FAIL)
        future_bar = _make_bar(datetime.now(UTC) + timedelta(days=1))
        bars.append(future_bar)
        report = checker.validate_bars(bars, self.asset)
        assert report.failures >= 1
        assert len(report.rejected_bars) >= 1
        assert report.is_acceptable is False

    def test_custom_config(self) -> None:
        config = QualityConfig(future_tolerance_seconds=0)
        checker = DataQualityChecker(config=config)
        # A bar 30s in the future should now fail (tolerance=0)
        bar = _make_bar(datetime.now(UTC) + timedelta(seconds=30))
        report = checker.validate_bars([bar], self.asset)
        assert report.failures >= 1

    def test_validate_ticks(self) -> None:
        checker = DataQualityChecker()
        now = datetime.now(UTC)
        ticks = [_make_tick(now - timedelta(seconds=i), price=50000.0) for i in range(10)]
        report = checker.validate_ticks(ticks, self.asset)
        assert report.total_records == 10
        assert report.is_acceptable is True
        assert len(report.clean_ticks) == 10
