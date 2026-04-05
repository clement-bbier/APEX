"""Unit tests for services/s02_signal_engine/vpin.py.

Covers: balanced/imbalanced flow, ADV EMA update, extreme hard-block,
bucket completion, property tests via Hypothesis.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.models.tick import Market, NormalizedTick, TradeSide
from services.s02_signal_engine.vpin import VPINCalculator, VPINMetrics

# ── Helpers ───────────────────────────────────────────────────────────────────


def _tick(
    volume: float,
    side: TradeSide = TradeSide.UNKNOWN,
    price: float = 100.0,
    bid: float | None = None,
    ask: float | None = None,
) -> NormalizedTick:
    """Build a minimal NormalizedTick for testing."""
    return NormalizedTick(
        symbol="BTCUSDT",
        market=Market.CRYPTO,
        timestamp_ms=1_700_000_000_000,
        price=Decimal(str(price)),
        volume=Decimal(str(volume)),
        side=side,
        bid=Decimal(str(bid)) if bid is not None else None,
        ask=Decimal(str(ask)) if ask is not None else None,
    )


def _feed(calc: VPINCalculator, n: int, side: TradeSide, vol: float = 100.0) -> None:
    """Feed n identical ticks into the calculator."""
    tick = _tick(vol, side)
    for _ in range(n):
        calc.update(tick)


# ── Bucket completion ─────────────────────────────────────────────────────────


class TestBucketCompletion:
    def test_bucket_sealed_when_volume_reaches_size(self) -> None:
        calc = VPINCalculator(default_bucket_size=500.0, n_window_buckets=50)
        completed = [calc.update(_tick(100.0, TradeSide.BUY)) for _ in range(10)]
        # At 100 vol/tick and bucket=500, bucket 1 completes on tick 5, bucket 2 on tick 10
        assert sum(completed) >= 1

    def test_no_bucket_before_threshold(self) -> None:
        calc = VPINCalculator(default_bucket_size=10_000.0)
        assert calc.update(_tick(1.0, TradeSide.BUY)) is False

    def test_multiple_buckets_accumulate_in_window(self) -> None:
        calc = VPINCalculator(default_bucket_size=100.0, n_window_buckets=5)
        _feed(calc, 20, TradeSide.BUY, vol=10.0)
        metrics = calc.compute()
        assert metrics.n_buckets_used >= 1


# ── VPIN values for balanced vs imbalanced flow ───────────────────────────────


class TestVPINFlow:
    def test_balanced_flow_low_vpin(self) -> None:
        """Alternating buy/sell of equal size → near-zero imbalance."""
        calc = VPINCalculator(default_bucket_size=100.0, n_window_buckets=50)
        for _ in range(200):
            calc.update(_tick(5.0, TradeSide.BUY))
            calc.update(_tick(5.0, TradeSide.SELL))
        m = calc.compute()
        assert m.vpin < 0.30, f"Expected low VPIN for balanced flow, got {m.vpin:.3f}"

    def test_one_sided_buy_high_vpin(self) -> None:
        """Pure buy flow → high imbalance → high VPIN."""
        calc = VPINCalculator(default_bucket_size=100.0, n_window_buckets=50)
        _feed(calc, 500, TradeSide.BUY, vol=10.0)
        m = calc.compute()
        assert m.vpin > 0.70, f"Expected high VPIN for pure buys, got {m.vpin:.3f}"

    def test_one_sided_sell_high_vpin(self) -> None:
        """Pure sell flow → high VPIN (symmetric to buy)."""
        calc = VPINCalculator(default_bucket_size=100.0, n_window_buckets=50)
        _feed(calc, 500, TradeSide.SELL, vol=10.0)
        m = calc.compute()
        assert m.vpin > 0.70, f"Expected high VPIN for pure sells, got {m.vpin:.3f}"

    def test_vpin_in_zero_one_range(self) -> None:
        calc = VPINCalculator(default_bucket_size=50.0)
        _feed(calc, 100, TradeSide.BUY)
        m = calc.compute()
        assert 0.0 <= m.vpin <= 1.0

    def test_empty_returns_normal_defaults(self) -> None:
        calc = VPINCalculator()
        m = calc.compute()
        assert m.vpin == 0.0
        assert m.toxicity_level == "normal"
        assert m.size_multiplier == 1.0
        assert m.n_buckets_used == 0


# ── Toxicity levels and size multipliers ─────────────────────────────────────


class TestToxicityClassification:
    """Verify that toxicity level and size_multiplier match VPIN thresholds."""

    def _calc_with_vpin(self, target_vpin: float) -> VPINMetrics:
        """Force a specific VPIN by injecting pre-built buckets directly."""
        calc = VPINCalculator(default_bucket_size=100.0, n_window_buckets=100)
        # Inject synthetic buckets: (buy_vol, sell_vol) calibrated to target_vpin
        buy = 50.0 + 50.0 * target_vpin
        sell = 50.0 - 50.0 * target_vpin
        from collections import deque
        calc._buckets = deque([(buy, sell)] * 10, maxlen=100)
        return calc.compute()

    def test_low_toxicity(self) -> None:
        m = self._calc_with_vpin(0.10)
        assert m.toxicity_level == "low"
        assert m.size_multiplier == 1.10

    def test_normal_toxicity(self) -> None:
        # normal: 0.50 <= VPIN < 0.70 → use target=0.55
        m = self._calc_with_vpin(0.55)
        assert m.toxicity_level == "normal"
        assert m.size_multiplier == 1.0

    def test_elevated_toxicity(self) -> None:
        # elevated: 0.70 <= VPIN < 0.85 → use target=0.75
        m = self._calc_with_vpin(0.75)
        assert m.toxicity_level == "elevated"
        assert m.size_multiplier == 0.50

    def test_high_toxicity(self) -> None:
        # high: 0.85 <= VPIN < 0.95 → use target=0.88
        m = self._calc_with_vpin(0.88)
        assert m.toxicity_level == "high"
        assert m.size_multiplier == 0.25

    def test_extreme_toxicity_zero_mult(self) -> None:
        m = self._calc_with_vpin(0.98)
        assert m.toxicity_level == "extreme"
        assert m.size_multiplier == 0.0


# ── ADV update EMA smoothing ─────────────────────────────────────────────────


class TestADVUpdate:
    def test_adv_source_starts_as_default(self) -> None:
        calc = VPINCalculator()
        assert calc._adv_source == "default"

    def test_adv_update_sets_live_source(self) -> None:
        calc = VPINCalculator()
        calc.update_adv(30_000.0)
        assert calc._adv_source == "live"

    def test_adv_update_ema_smoothing(self) -> None:
        """EMA(α=0.1): new = 0.9×old + 0.1×target. Verify single step."""
        calc = VPINCalculator(default_bucket_size=1000.0, n_buckets_per_day=50)
        target = 50_000.0 / 50  # = 1000.0
        expected = 0.9 * 1000.0 + 0.1 * target
        calc.update_adv(50_000.0)
        assert abs(calc._bucket_size - expected) < 1e-6

    def test_adv_zero_or_negative_ignored(self) -> None:
        calc = VPINCalculator(default_bucket_size=500.0)
        calc.update_adv(0.0)
        assert calc._bucket_size == 500.0
        assert calc._adv_source == "default"
        calc.update_adv(-100.0)
        assert calc._bucket_size == 500.0

    def test_adv_repeated_updates_converge(self) -> None:
        """After many updates, bucket_size should converge toward target."""
        calc = VPINCalculator(default_bucket_size=1000.0, n_buckets_per_day=50)
        adv = 100_000.0  # target bucket = 100_000/50 = 2000
        for _ in range(100):
            calc.update_adv(adv)
        assert abs(calc._bucket_size - 2000.0) < 1.0

    def test_adv_reflected_in_compute_effective_bucket_size(self) -> None:
        calc = VPINCalculator(default_bucket_size=500.0, n_buckets_per_day=50)
        calc.update_adv(100_000.0)  # target = 2000
        m = calc.compute()
        # After 1 EMA step: 0.9×500 + 0.1×2000 = 650
        assert abs(m.effective_bucket_size - 650.0) < 1.0


# ── Extreme hard-block ────────────────────────────────────────────────────────


class TestExtremeBlock:
    def test_extreme_returns_zero_size_multiplier(self) -> None:
        """When VPIN ≥ 0.95 the multiplier must be 0 — signal must be blocked."""
        calc = VPINCalculator(default_bucket_size=100.0)
        from collections import deque
        calc._buckets = deque([(99.0, 1.0)] * 50, maxlen=50)
        m = calc.compute()
        assert m.size_multiplier == 0.0
        assert m.toxicity_level == "extreme"

    def test_adv_source_in_metrics(self) -> None:
        calc = VPINCalculator(default_bucket_size=100.0)
        calc.update_adv(5000.0)
        m = calc.compute()
        assert m.adv_source == "live"


# ── Lee-Ready classification for UNKNOWN side ────────────────────────────────


class TestLeeReady:
    def test_unknown_with_bid_ask_above_mid_buy_classified(self) -> None:
        """Price at ask → classified as buy (ratio=0.6). Use large bucket_size
        so the single tick does NOT complete a bucket (carry-forward would zero out)."""
        calc = VPINCalculator(default_bucket_size=10_000.0)
        tick = _tick(100.0, TradeSide.UNKNOWN, price=100.5, bid=99.0, ask=101.0)
        calc.update(tick)
        # With ratio=0.6: buy_vol=60, sell_vol=40
        assert calc._current_buy_vol > calc._current_sell_vol

    def test_unknown_with_bid_ask_below_mid_sell_classified(self) -> None:
        """Price at bid → classified as sell (ratio=0.4)."""
        calc = VPINCalculator(default_bucket_size=10_000.0)
        tick = _tick(100.0, TradeSide.UNKNOWN, price=99.5, bid=99.0, ask=101.0)
        calc.update(tick)
        # With ratio=0.4: buy_vol=40, sell_vol=60
        assert calc._current_buy_vol < calc._current_sell_vol

    def test_unknown_without_bid_ask_split_evenly(self) -> None:
        calc = VPINCalculator(default_bucket_size=10_000.0)
        calc.update(_tick(100.0, TradeSide.UNKNOWN))
        assert calc._current_buy_vol == pytest.approx(50.0)
        assert calc._current_sell_vol == pytest.approx(50.0)


# ── Property tests ────────────────────────────────────────────────────────────


class TestProperties:
    @given(
        buy_frac=st.floats(0.0, 1.0, allow_nan=False),
        n_ticks=st.integers(5, 200),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_vpin_always_in_zero_one(self, buy_frac: float, n_ticks: int) -> None:
        calc = VPINCalculator(default_bucket_size=50.0, n_window_buckets=20)
        for i in range(n_ticks):
            side = TradeSide.BUY if (i / n_ticks) < buy_frac else TradeSide.SELL
            calc.update(_tick(10.0, side))
        m = calc.compute()
        assert 0.0 <= m.vpin <= 1.0

    @given(adv=st.floats(1.0, 1_000_000.0, allow_nan=False))
    @settings(max_examples=100)
    def test_adv_update_always_positive_bucket(self, adv: float) -> None:
        calc = VPINCalculator(default_bucket_size=500.0, n_buckets_per_day=50)
        calc.update_adv(adv)
        assert calc._bucket_size > 0.0

    @given(vol=st.floats(0.1, 1000.0, allow_nan=False))
    @settings(max_examples=50)
    def test_buy_volume_pct_in_range(self, vol: float) -> None:
        calc = VPINCalculator(default_bucket_size=100.0)
        for _ in range(50):
            calc.update(_tick(vol, TradeSide.BUY))
        m = calc.compute()
        assert 0.0 <= m.buy_volume_pct <= 1.0
