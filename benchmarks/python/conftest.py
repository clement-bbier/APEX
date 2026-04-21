"""pytest-benchmark shared fixtures and configuration.

These benchmarks are intentionally kept outside the main ``tests/`` tree
so that normal CI (unit + integration) does not pay their cost. Run them
explicitly via:

    pytest benchmarks/python/ --benchmark-only

Or, to emit a machine-readable baseline file::

    pytest benchmarks/python/bench_har_rv.py \\
        --benchmark-only \\
        --benchmark-json=/tmp/har_rv.json
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

type DailyBarsFactory = Callable[[int], pl.DataFrame]
type TickFrameFactory = Callable[..., pl.DataFrame]

_RNG = np.random.default_rng(seed=20260421)


def _daily_bars(n_days: int) -> pl.DataFrame:
    """Generate a deterministic-noise daily OHLCV frame for HAR-RV benches."""
    start = datetime(2020, 1, 1, tzinfo=UTC)
    ts = [start + timedelta(days=i) for i in range(n_days)]
    log_ret = _RNG.normal(loc=0.0, scale=0.012, size=n_days)
    close = 100.0 * np.exp(np.cumsum(log_ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(_RNG.normal(0.0, 0.003, n_days)))
    low = np.minimum(open_, close) * (1.0 - np.abs(_RNG.normal(0.0, 0.003, n_days)))
    volume = np.abs(_RNG.normal(1_000_000, 100_000, n_days))
    return pl.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def _tick_frame(n_ticks: int, with_book: bool = False) -> pl.DataFrame:
    """Generate a deterministic-noise tick frame for OFI/CVD/Kyle benches."""
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    delta_p = _RNG.normal(0.0, 0.005, size=n_ticks)
    price = 100.0 + np.cumsum(delta_p)
    qty = np.abs(_RNG.lognormal(mean=4.0, sigma=0.5, size=n_ticks))
    sysrand = secrets.SystemRandom()
    side = [sysrand.choice(["BUY", "SELL"]) for _ in range(n_ticks)]
    ts = [start + timedelta(milliseconds=i * 50) for i in range(n_ticks)]
    data: dict[str, object] = {
        "timestamp": ts,
        "price": price,
        "quantity": qty,
        "side": side,
    }
    if with_book:
        data["bid_size"] = np.abs(_RNG.normal(100.0, 20.0, n_ticks))
        data["ask_size"] = np.abs(_RNG.normal(100.0, 20.0, n_ticks))
    return pl.DataFrame(data)


@pytest.fixture(scope="session")
def daily_bars_factory() -> DailyBarsFactory:
    """Factory producing N-day OHLCV frames on demand, cached per-session."""
    cache: dict[int, pl.DataFrame] = {}

    def _factory(n: int) -> pl.DataFrame:
        if n not in cache:
            cache[n] = _daily_bars(n)
        return cache[n]

    return _factory


@pytest.fixture(scope="session")
def tick_frame_factory() -> TickFrameFactory:
    """Factory producing N-tick frames on demand, cached per-session."""
    cache: dict[tuple[int, bool], pl.DataFrame] = {}

    def _factory(n: int, *, with_book: bool = False) -> pl.DataFrame:
        key = (n, with_book)
        if key not in cache:
            cache[key] = _tick_frame(n, with_book=with_book)
        return cache[key]

    return _factory
