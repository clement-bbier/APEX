"""Benchmark for features.calculators.cvd_kyle.CVDKyleCalculator (CVD part).

Module: features/calculators/cvd_kyle.py
Hot path role: signal_gen (cumulative volume delta, realization feature)
Current mean latency: 341 ms @ 1k ticks, 19.6 s @ 50k ticks (combined with Kyle)
Rust port feasibility: high (trivial cumulative sum + divergence scoring)
Estimated Rust speedup: 3x-8x on CVD alone; compounds with Kyle port
Recommendation: bundle with Kyle port -- same module, shared compute
                (Phase B Rust candidate #3, piggy-backs on #1)

Note: CVD and Kyle share the same calculator (CVDKyleCalculator). This
file exercises the full compute() (produces both blocks). The separate
bench_kyle_lambda.py parametrizes kyle_window sweeps to isolate the
rolling-OLS cost which is the dominant Kyle-specific cost.
"""

from __future__ import annotations

import pytest

from features.calculators.cvd_kyle import CVDKyleCalculator

from .conftest import TickFrameFactory


@pytest.mark.parametrize("n_ticks", [1000, 10_000, 50_000])
def test_bench_cvd_compute(
    benchmark: object,
    tick_frame_factory: TickFrameFactory,
    n_ticks: int,
) -> None:
    df = tick_frame_factory(n_ticks)
    calc = CVDKyleCalculator(
        cvd_window=20,
        kyle_window=100,
        kyle_zscore_lookback=252,
        cvd_divergence_k=3.0,
        liquidity_signal_k=3.0,
        combined_weights=(0.5, 0.5),
    )
    benchmark(calc.compute, df)  # type: ignore[operator]
