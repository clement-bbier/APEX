"""Configurable thresholds for data quality checks.

All magic numbers are centralised here so that checks remain threshold-free.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityConfig:
    """Immutable configuration for all data quality thresholds."""

    # Outlier detection (z-score)
    outlier_warn_sigma: float = 4.0
    outlier_fail_sigma: float = 8.0
    outlier_window: int = 100

    # Staleness thresholds (seconds)
    stale_crypto_seconds: int = 300
    stale_equity_seconds: int = 900
    stale_daily_seconds: int = 93600

    # Volume
    volume_spike_multiplier: float = 10.0

    # Price spread
    price_spread_max_pct: float = 0.50

    # Negative prices (allowed for futures)
    allow_negative_price: bool = False

    # Timestamp tolerance (seconds into the future)
    future_tolerance_seconds: int = 60

    # Gap detection
    gap_tolerance_multiplier: float = 1.5

    # Volume spike lookback window
    volume_spike_lookback: int = 20
