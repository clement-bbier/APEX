"""Shared fixtures for features/ unit tests.

Provides a synthetic 100-bar OHLCV DataFrame (BTC, UTC timestamps,
Decimal-compatible prices) used across all test modules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest


@pytest.fixture
def synthetic_bars() -> pl.DataFrame:
    """100-bar synthetic BTC 5m OHLCV DataFrame.

    Prices are float-typed (as Polars would load from a DB) around
    ~30,000 with small random-walk increments.  Timestamps are UTC.
    """
    import hashlib

    n = 100
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    base_price = 30_000.0

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    price = base_price
    for i in range(n):
        ts = base_time + timedelta(minutes=5 * i)
        # Deterministic pseudo-random step from hash
        h = int(hashlib.sha256(str(i).encode()).hexdigest()[:8], 16)
        step = ((h % 200) - 100) / 10.0  # [-10.0, +10.0]

        o = price
        c = price + step
        hi = max(o, c) + abs(step) * 0.5
        lo = min(o, c) - abs(step) * 0.5
        vol = 1_000.0 + (h % 500)

        timestamps.append(ts)
        opens.append(round(o, 2))
        highs.append(round(hi, 2))
        lows.append(round(lo, 2))
        closes.append(round(c, 2))
        volumes.append(round(vol, 2))

        price = c

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


@pytest.fixture
def synthetic_bars_decimal() -> pl.DataFrame:
    """100-bar DataFrame with string-encoded Decimal prices."""
    import hashlib

    n = 100
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    base_price = Decimal("30000.00")

    timestamps: list[datetime] = []
    closes: list[str] = []

    price = base_price
    for i in range(n):
        ts = base_time + timedelta(minutes=5 * i)
        h = int(hashlib.sha256(str(i).encode()).hexdigest()[:8], 16)
        step = Decimal(str(((h % 200) - 100) / 10.0))
        price = price + step
        timestamps.append(ts)
        closes.append(str(price))

    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "close": [float(c) for c in closes],
        }
    )
