"""Benchmark for Kyle lambda rolling regression in CVDKyleCalculator.

Module: features/calculators/cvd_kyle.py
Hot path role: signal_gen (liquidity regression, rolling OLS per tick)
Current mean latency: 1.56 s @ 5k ticks (w=50), 7.86 s @ 20k ticks (w=50)
Rust port feasibility: high (rolling OLS is trivial in Rust with ndarray)
Estimated Rust speedup: 10x-20x (rolling regression is the hottest loop)
Recommendation: port -- Phase B Rust candidate #1 (top of list).

The kyle_window parametrization isolates how rolling-OLS cost scales with
window size; this is the bottleneck Rust would replace.

kyle_zscore_lookback is set to max(252, 2 * kyle_window) so the production
default (252) is preserved for w in {50, 100} while the w=250 sweep uses
the minimum valid lookback of 500 (per calculator invariant lookback >=
2 * kyle_window; see #239).
"""

from __future__ import annotations

import pytest

from features.calculators.cvd_kyle import CVDKyleCalculator

from .conftest import TickFrameFactory


@pytest.mark.parametrize("kyle_window", [50, 100, 250])
@pytest.mark.parametrize("n_ticks", [5_000, 20_000])
def test_bench_kyle_lambda(
    benchmark: object,
    tick_frame_factory: TickFrameFactory,
    n_ticks: int,
    kyle_window: int,
) -> None:
    df = tick_frame_factory(n_ticks)
    calc = CVDKyleCalculator(
        cvd_window=20,
        kyle_window=kyle_window,
        kyle_zscore_lookback=max(252, kyle_window * 2),
    )
    benchmark(calc.compute, df)  # type: ignore[operator]
