"""Benchmark for features.calculators.ofi.OFICalculator.compute.

Module: features/calculators/ofi.py
Hot path role: signal_gen (order-flow imbalance, rolling windows)
Current mean latency: 97 ms @ 1k ticks, 11.5 s @ 100k ticks (trade-mode)
                      129 ms @ 1k ticks, 11.2 s @ 100k ticks (book-mode)
Rust port feasibility: high (tight numeric loop over ticks, no Python branching)
Estimated Rust speedup: 5x-15x
Recommendation: port -- tick-path feature, Phase B Rust candidate #2.
"""

from __future__ import annotations

import pytest

from features.calculators.ofi import OFICalculator

from .conftest import TickFrameFactory


@pytest.mark.parametrize("n_ticks", [1000, 10_000, 100_000])
@pytest.mark.parametrize("with_book", [False, True])
def test_bench_ofi_compute(
    benchmark: object,
    tick_frame_factory: TickFrameFactory,
    n_ticks: int,
    with_book: bool,
) -> None:
    df = tick_frame_factory(n_ticks, with_book=with_book)
    calc = OFICalculator(windows=(10, 50, 100), signal_k=3.0, weights=(0.5, 0.3, 0.2))
    benchmark(calc.compute, df)  # type: ignore[operator]
