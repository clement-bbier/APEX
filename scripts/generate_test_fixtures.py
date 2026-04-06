#!/usr/bin/env python3
"""Generate synthetic test fixtures for APEX CI pipeline.

Creates ``tests/fixtures/30d_btcusdt_1m.parquet`` containing 30 days of
synthetic BTC/USDT 1-minute OHLCV data using a regime-aware price path
that produces trending, ranging, and high-volatility periods.

The regime structure ensures RSI reaches extremes and OFI signals emerge,
allowing the backtest engine to generate demonstrable trades.

Usage::

    python scripts/generate_test_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def generate_btcusdt_fixture(n_candles: int = 43_200) -> None:
    """Generate synthetic BTC/USDT 1-minute OHLCV data with regime structure.

    Price path alternates across three regimes every n_candles//10 bars:
    - Trending (drift=+0.0003, σ=0.0006) — produces RSI extremes
    - Ranging  (mean-reverting, σ=0.0004) — produces OFI signals
    - High-vol (drift=0, σ=0.0020)        — stress tests risk rules

    Args:
        n_candles: Number of 1-minute candles (default: 43200 = 30 days).
    """
    Path("tests/fixtures").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)

    # Timestamps: 30 days starting 2024-01-01 UTC
    timestamps = pd.date_range("2024-01-01", periods=n_candles, freq="1min", tz="UTC")

    # Regime-aware price path with symmetric up/down trends
    # Regimes cycle (length = n_candles//12 each):
    #   trending-up → ranging → trending-down → ranging → high-vol → ranging → ...
    # Drift is kept modest so price doesn't explode in one direction.
    regime_length = n_candles // 12
    prices = [42_000.0]
    base_price = 42_000.0
    directions = [1, 0, -1, 0, 0, 0]  # up, range, down, range, highvol, range

    for i in range(n_candles - 1):
        regime_slot = (i // regime_length) % len(directions)
        # Reset base_price at each regime boundary so ranging reverts to the
        # current price level, not back to the original $42 000 start.
        if i % regime_length == 0 and i > 0:
            base_price = prices[-1]
        d = directions[regime_slot]
        if d == 1:  # trending up — low vol so RSI stays moderate (40-60)
            drift = 0.00003
            vol = 0.0003
        elif d == -1:  # trending down — same
            drift = -0.00003
            vol = 0.0003
        elif d == 0 and (i // regime_length) % len(directions) == 4:  # high-vol
            drift = 0.0
            vol = 0.002
        else:
            # Ranging: strong OU mean-reversion so RSI reliably reaches
            # extremes and quickly reverts — this gives RSI signals clear edge.
            deviation = (prices[-1] - base_price) / base_price
            drift = -0.05 * deviation  # k=0.05 → ~20-min reversion time constant
            vol = 0.0012              # higher vol → RSI hits extremes regularly

        ret = rng.normal(drift, vol)
        prices.append(prices[-1] * (1.0 + ret))

    close = np.array(prices)

    # open/high/low not stored in fixture -- only close/bid/ask are used

    # Spread: ~2 bps
    spread = close * 0.0002
    bid = close - spread / 2.0
    ask = close + spread / 2.0

    # Volume: log-normal ~ realistic exchange volume
    volume = rng.lognormal(mean=8.0, sigma=1.0, size=n_candles)

    df = pd.DataFrame(
        {
            "symbol": "BTC/USDT",
            "market": "crypto",
            "timestamp_ms": (timestamps.view("int64") // 10**6).astype("int64"),
            "price": close,
            "volume": volume,
            "side": "unknown",
            "bid": bid,
            "ask": ask,
            "spread_bps": 2.0,
            "session": "after_hours",
        }
    )

    out_path = "tests/fixtures/30d_btcusdt_1m.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Generated {n_candles} candles -> {out_path}")
    print(f"  Price range: ${close.min():.0f} - ${close.max():.0f}")
    print(f"  Date range:  {timestamps[0].date()} to {timestamps[-1].date()}")


if __name__ == "__main__":
    generate_btcusdt_fixture()
