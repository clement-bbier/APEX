"""VPIN: Volume-Synchronized Probability of Informed Trading — Dynamic ADV-aware.

VPIN measures ORDER FLOW TOXICITY: the probability your counterparty has private
information. High VPIN preceded the May 2010 Flash Crash by several hours.

Key architectural improvement over static bucket_size:
    Dynamic calibration: bucket_size = ADV / n_buckets_per_day
    Updated every ~5 minutes from S07's Redis ADV estimate.
    EMA smoothing (α=0.1) prevents abrupt jumps in bucket_size.

This makes VPIN scale-invariant:
    BTC normal:    ADV=30,000 → bucket=600
    SPY:           ADV=80M    → bucket=1.6M shares
    BTC low-vol:   ADV=5,000  → bucket=100 (auto-adapted, not fixed 1000)
    BTC news pump: ADV=200k   → bucket=4,000 (auto-adapted)

References:
    Easley, D., López de Prado, M. & O'Hara, M. (2012).
        Flow Toxicity and Liquidity in a High-Frequency World.
        Review of Financial Studies, 25(5), 1457-1493.
    Easley, D., López de Prado, M. & O'Hara, M. (2011).
        The Microstructure of the Flash Crash: Flow Toxicity, Liquidity
        Crashes, and the Probability of Informed Trading.
        Journal of Portfolio Management, 37(2), 118-128.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import ClassVar

from core.models.tick import NormalizedTick, TradeSide


@dataclass
class VPINMetrics:
    """Complete VPIN output for one estimation window."""

    vpin: float
    toxicity_level: str  # "low"|"normal"|"elevated"|"high"|"extreme"
    size_multiplier: float  # Position size adjustment [0.0, 1.10]
    n_buckets_used: int
    effective_bucket_size: float  # Actual bucket size (ADV-calibrated)
    buy_volume_pct: float
    adv_source: str  # "live" (from S07) | "default" (fallback)


class VPINCalculator:
    """Real-time VPIN with dynamic ADV-calibrated bucket sizing.

    The bucket_size is updated via update_adv() each time S07 publishes
    a new ADV estimate to Redis (typically every 5 minutes).

    EMA smoothing on bucket_size prevents abrupt signal discontinuities
    when ADV changes (e.g. during news events or session transitions).

    Args:
        default_bucket_size: Fallback bucket size when ADV unavailable.
        n_window_buckets: Rolling window length in buckets (50 = standard).
        n_buckets_per_day: ADV divisor for bucket sizing (default 50).
    """

    THRESHOLDS: ClassVar[dict[str, float]] = {
        "low": 0.30,
        "normal": 0.50,
        "elevated": 0.70,
        "high": 0.85,
        "extreme": 0.95,
    }
    EMA_ALPHA: float = 0.10  # Smoothing factor for ADV updates

    def __init__(
        self,
        default_bucket_size: float = 1000.0,
        n_window_buckets: int = 50,
        n_buckets_per_day: int = 50,
    ) -> None:
        self._default_bucket_size = default_bucket_size
        self._bucket_size = default_bucket_size
        self._n_window = n_window_buckets
        self._n_buckets_per_day = n_buckets_per_day
        self._adv_source = "default"

        self._current_buy_vol: float = 0.0
        self._current_sell_vol: float = 0.0
        self._current_total_vol: float = 0.0
        self._buckets: deque[tuple[float, float]] = deque(maxlen=n_window_buckets)

    # ── Public interface ──────────────────────────────────────────────────────

    def update_adv(self, adv: float) -> None:
        """Update bucket_size from S07's ADV estimate with EMA smoothing.

        Called by S02 service every ADV_REFRESH_EVERY_N_TICKS ticks.
        EMA prevents abrupt bucket_size changes that would distort VPIN.

        Formula: new = (1-α)×old + α×(ADV/n_buckets_per_day)

        Args:
            adv: Average Daily Volume in native symbol units (e.g. BTC for BTCUSDT).
        """
        if adv <= 0:
            return
        target = adv / self._n_buckets_per_day
        # EMA smoothing: avoids discontinuities when ADV changes rapidly
        self._bucket_size = (
            (1.0 - self.EMA_ALPHA) * self._bucket_size + self.EMA_ALPHA * target
        )
        self._adv_source = "live"

    def update(self, tick: NormalizedTick) -> bool:
        """Process one tick. Returns True if a new bucket was completed.

        Uses Lee-Ready bulk classification for UNKNOWN-side ticks:
        if price >= midpoint → 60% buy; else 40% buy.

        Args:
            tick: Freshly normalized tick.

        Returns:
            True when a new volume bucket is sealed.
        """
        volume = float(tick.volume)

        if tick.side == TradeSide.BUY:
            buy_vol, sell_vol = volume, 0.0
        elif tick.side == TradeSide.SELL:
            buy_vol, sell_vol = 0.0, volume
        else:
            # Lee-Ready bulk classification for UNKNOWN side
            if tick.bid is not None and tick.ask is not None:
                mid = float(tick.bid + tick.ask) / 2.0
                ratio = 0.6 if float(tick.price) >= mid else 0.4
            else:
                ratio = 0.5
            buy_vol = volume * ratio
            sell_vol = volume * (1.0 - ratio)

        self._current_buy_vol += buy_vol
        self._current_sell_vol += sell_vol
        self._current_total_vol += volume

        if self._current_total_vol >= self._bucket_size:
            excess = (
                (self._current_total_vol - self._bucket_size)
                / self._current_total_vol
            )
            self._buckets.append((
                self._current_buy_vol * (1.0 - excess),
                self._current_sell_vol * (1.0 - excess),
            ))
            # Carry-forward excess volume into next bucket
            self._current_buy_vol *= excess
            self._current_sell_vol *= excess
            self._current_total_vol *= excess
            return True
        return False

    def compute(self) -> VPINMetrics:
        """Compute VPIN and toxicity classification over the rolling window.

        VPIN = Σ|V_B - V_S| / Σ(V_B + V_S)   over last n_window buckets

        Returns:
            VPINMetrics with toxicity level and position size multiplier.
        """
        if not self._buckets:
            return VPINMetrics(
                vpin=0.0,
                toxicity_level="normal",
                size_multiplier=1.0,
                n_buckets_used=0,
                effective_bucket_size=self._bucket_size,
                buy_volume_pct=0.5,
                adv_source=self._adv_source,
            )

        total = sum(b[0] + b[1] for b in self._buckets)
        imbalance = sum(abs(b[0] - b[1]) for b in self._buckets)
        vpin = max(0.0, min(1.0, imbalance / total)) if total > 0 else 0.0
        buy_pct = sum(b[0] for b in self._buckets) / total if total > 0 else 0.5

        if vpin >= self.THRESHOLDS["extreme"]:
            level, mult = "extreme", 0.0
        elif vpin >= self.THRESHOLDS["high"]:
            level, mult = "high", 0.25
        elif vpin >= self.THRESHOLDS["elevated"]:
            level, mult = "elevated", 0.50
        elif vpin >= self.THRESHOLDS["normal"]:
            level, mult = "normal", 1.0
        else:
            level, mult = "low", 1.10

        return VPINMetrics(
            vpin=vpin,
            toxicity_level=level,
            size_multiplier=mult,
            n_buckets_used=len(self._buckets),
            effective_bucket_size=self._bucket_size,
            buy_volume_pct=buy_pct,
            adv_source=self._adv_source,
        )
