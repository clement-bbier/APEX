"""Benchmark for services.fusion_engine.kelly_sizer.KellySizer.

Module: services/fusion_engine/kelly_sizer.py
Hot path role: sizing (position sizing per order candidate)
Current mean latency: 3.17 us (kelly_fraction), 19.6 us (position_size),
                      24.7 us (full pipeline, equity path)
Rust port feasibility: low (arithmetic is O(1); Decimal overhead dominant)
Estimated Rust speedup: negligible (<1.5x once Decimal boundary crossed)
Recommendation: do not port -- already sub-microsecond, not a bottleneck
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.fusion_engine.kelly_sizer import KellySizer


@pytest.fixture(scope="module")
def kelly_sizer() -> KellySizer:
    return KellySizer()


def test_bench_kelly_fraction(benchmark: object, kelly_sizer: KellySizer) -> None:
    benchmark(kelly_sizer.kelly_fraction, 0.54, 1.6)  # type: ignore[operator]


def test_bench_kelly_position_size(benchmark: object, kelly_sizer: KellySizer) -> None:
    capital = Decimal("100000")

    def _call() -> Decimal:
        return kelly_sizer.position_size(
            capital=capital,
            kelly_f=0.15,
            regime_mult=0.8,
            session_mult=1.0,
            kyle_lambda=0.005,
            is_crypto=False,
        )

    benchmark(_call)  # type: ignore[operator]


@pytest.mark.parametrize("is_crypto", [False, True])
def test_bench_kelly_full_pipeline(
    benchmark: object, kelly_sizer: KellySizer, is_crypto: bool
) -> None:
    """Combined fraction + position_size, i.e. the sequence S04 runs per order."""
    capital = Decimal("100000")

    def _call() -> Decimal:
        f = kelly_sizer.kelly_fraction(0.54, 1.6)
        return kelly_sizer.position_size(
            capital=capital,
            kelly_f=f,
            regime_mult=0.8,
            session_mult=1.0,
            kyle_lambda=0.005,
            is_crypto=is_crypto,
        )

    benchmark(_call)  # type: ignore[operator]
