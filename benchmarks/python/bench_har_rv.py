"""Benchmark for features.calculators.har_rv.HARRVCalculator.compute.

Module: features/calculators/har_rv.py
Hot path role: signal_gen (volatility forecasting, batch per-day refit)
Current mean latency: 324 ms @ 100 bars, 30.7 s @ 1000 bars (p99: 464 ms / 35.6 s)
Rust port feasibility: low (O(n^2) expanding-window OLS by design)
Estimated Rust speedup: ~2x (numpy already dominant; loop overhead is small)
Recommendation: do not port -- daily refresh cadence means the 30s/1000d
                cost is amortized across an 8-hour trading session.
"""

from __future__ import annotations

import pytest

from features.calculators.har_rv import HARRVCalculator

from .conftest import DailyBarsFactory


@pytest.mark.parametrize("n_days", [100, 500, 1000])
def test_bench_har_rv_compute(
    benchmark: object,
    daily_bars_factory: DailyBarsFactory,
    n_days: int,
) -> None:
    df = daily_bars_factory(n_days)
    calc = HARRVCalculator(bar_frequency="1d", warm_up_periods=30)
    benchmark(calc.compute, df)  # type: ignore[operator]
