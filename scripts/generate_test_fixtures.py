#!/usr/bin/env python3
"""Generate synthetic test fixtures for APEX CI pipeline.

Creates ``tests/fixtures/30d_btcusdt_1m.parquet`` containing 30 days of
realistic synthetic BTC/USDT 1-minute OHLCV data using Geometric Brownian
Motion for price simulation.

Usage::

    python scripts/generate_test_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def generate_btcusdt_fixture(n_candles: int = 43_200) -> None:
    """Generate synthetic BTC/USDT 1-minute OHLCV data.

    Price follows Geometric Brownian Motion:
        S(t+dt) = S(t) × exp((μ - σ²/2)dt + σ√dt × Z)
    where μ ≈ 0.00002 per minute and σ ≈ 0.001 per minute.

    Args:
        n_candles: Number of 1-minute candles to generate (default: 43200 = 30 days).
    """
    Path("tests/fixtures").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)

    # Timestamps: 30 days starting 2024-01-01 UTC
    timestamps = pd.date_range("2024-01-01", periods=n_candles, freq="1min", tz="UTC")

    # GBM parameters
    mu = 0.00002  # drift per minute
    sigma = 0.001  # volatility per minute

    # Generate log-normal returns
    dt = 1.0
    log_returns = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), n_candles)
    close = 42000.0 * np.cumprod(np.exp(log_returns))

    # Intrabar noise: open/high/low from close
    intra_noise = rng.normal(0, sigma * 0.5, n_candles)
    open_ = close * np.exp(intra_noise)
    high_extra = np.abs(rng.normal(0, sigma, n_candles))
    low_extra = np.abs(rng.normal(0, sigma, n_candles))
    high = np.maximum(close, open_) * np.exp(high_extra)
    low = np.minimum(close, open_) * np.exp(-low_extra)

    # Spread: ~2 bps
    spread = close * 0.0002
    bid = close - spread / 2.0
    ask = close + spread / 2.0

    # Volume: log-normal ~ realistic exchange volume
    volume = rng.lognormal(mean=8.0, sigma=1.0, size=n_candles)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "bid": bid,
            "ask": ask,
        }
    )

    out_path = "tests/fixtures/30d_btcusdt_1m.parquet"
    df.to_parquet(out_path, index=False)
    print(f"✓ Generated {n_candles} candles → {out_path}")
    print(f"  Price range: ${close.min():.0f} – ${close.max():.0f}")
    print(f"  Date range:  {timestamps[0].date()} → {timestamps[-1].date()}")


if __name__ == "__main__":
    generate_btcusdt_fixture()
