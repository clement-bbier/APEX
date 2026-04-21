"""
Latency tests: verify signal pipeline processes ticks in < 50ms.

Per DEVELOPMENT_PLAN.md Phase 3 DoD:
  "Latency: tick -> signal < 50ms (measured)"

These tests do NOT require Redis or ZMQ - they measure pure computation latency.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np

from services.signal_engine.signal_scorer import SignalComponent, SignalScorer
from services.regime_detector.regime_engine import RegimeEngine
from services.regime_detector.session_tracker import SessionTracker


class TestComputationLatency:
    LATENCY_BUDGET_MS = 50.0  # 50ms budget per tick

    def test_signal_scorer_latency(self) -> None:
        """SignalScorer.compute() must run in < 5ms p99 (it's in the hot path)."""
        scorer = SignalScorer()
        components = [
            SignalComponent("microstructure", 0.8, 0.35, True),
            SignalComponent("bollinger", 0.7, 0.25, True),
            SignalComponent("ema_mtf", 0.6, 0.20, True),
            SignalComponent("rsi_divergence", 0.5, 0.15, True),
            SignalComponent("vwap", 0.3, 0.05, True),
        ]

        # Warm up
        for _ in range(10):
            scorer.compute(components)

        times = []
        for _ in range(1000):
            t0 = time.perf_counter()
            scorer.compute(components)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = float(np.percentile(times, 99))
        assert p99_ms < 5.0, f"SignalScorer p99 latency = {p99_ms:.2f}ms (budget: 5ms)"

    def test_regime_engine_latency(self) -> None:
        """RegimeEngine.compute() must run in < 2ms p99."""
        engine = RegimeEngine()

        # Warm up
        for _ in range(10):
            engine.compute(vix=18.0, dxy_1h_change_pct=0.1, yield_10y=4.5, yield_2y=4.3)

        times = []
        for _ in range(1000):
            t0 = time.perf_counter()
            engine.compute(vix=18.0, dxy_1h_change_pct=0.1, yield_10y=4.5, yield_2y=4.3)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = float(np.percentile(times, 99))
        assert p99_ms < 2.0, f"RegimeEngine p99 latency = {p99_ms:.2f}ms (budget: 2ms)"

    def test_session_tracker_latency(self) -> None:
        """SessionTracker.get_session() must run in < 1ms p99."""
        tracker = SessionTracker()
        now = datetime.now(UTC)

        # Warm up
        for _ in range(100):
            tracker.get_session(now)

        times = []
        for _ in range(10000):
            t0 = time.perf_counter()
            tracker.get_session(now)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = float(np.percentile(times, 99))
        assert p99_ms < 1.0, f"SessionTracker p99 latency = {p99_ms:.2f}ms (budget: 1ms)"
