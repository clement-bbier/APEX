"""Integration tests: end-to-end on synthetic bar data."""

from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from core.math.labeling import TripleBarrierConfig
from features.labeling import (
    build_events_from_signals,
    compute_label_diagnostics,
    label_events_binary,
)


def _ts(minute: int) -> datetime:
    return datetime(2024, 6, 1, 9, 30, tzinfo=UTC) + timedelta(minutes=minute)


def _synthetic_gbm(n: int, mu: float, sigma: float, seed: int) -> list[float]:
    """Deterministic geometric-Brownian-motion closes."""
    rng = _LCG(seed)
    dt = 1.0 / 252.0 / (6.5 * 60)  # per-minute fraction of trading year
    closes: list[float] = [100.0]
    for _ in range(n - 1):
        z = rng.normal()
        drift = (mu - 0.5 * sigma * sigma) * dt
        shock = sigma * math.sqrt(dt) * z
        closes.append(closes[-1] * math.exp(drift + shock))
    return closes


class _LCG:
    """Deterministic box-muller normal sampler on a linear-congruential RNG."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF
        self._spare: float | None = None

    def _uniform(self) -> float:
        self._state = (1103515245 * self._state + 12345) & 0x7FFFFFFF
        return self._state / 0x7FFFFFFF

    def normal(self) -> float:
        if self._spare is not None:
            v = self._spare
            self._spare = None
            return v
        u1 = max(self._uniform(), 1e-12)
        u2 = self._uniform()
        mag = math.sqrt(-2.0 * math.log(u1))
        self._spare = mag * math.sin(2 * math.pi * u2)
        return mag * math.cos(2 * math.pi * u2)


class TestIntegrationWithBarData:
    def test_full_pipeline_on_100_events(self) -> None:
        """Build signals -> events -> labels -> diagnostics."""
        seed = int(os.environ.get("APEX_SEED", "42"))
        n_bars = 500
        closes = _synthetic_gbm(n_bars, mu=0.10, sigma=0.25, seed=seed)

        # Signal: simple momentum over 5 bars.
        signal = [0.0, 0.0, 0.0, 0.0, 0.0] + [
            (closes[i] - closes[i - 5]) / closes[i - 5] for i in range(5, n_bars)
        ]
        timestamps = [_ts(i) for i in range(n_bars)]
        signals = pl.DataFrame({"timestamp": timestamps, "signal": signal})
        bars = pl.DataFrame({"timestamp": timestamps, "close": closes})

        events = build_events_from_signals(
            signals, signal_col="signal", threshold=0.001, symbol="SYN"
        )
        # Drop the first events that fall inside the vol warmup window.
        events = events.filter(pl.col("timestamp") >= timestamps[25])
        assert len(events) > 0

        cfg = TripleBarrierConfig(
            pt_multiplier=2.0, sl_multiplier=1.0, max_holding_periods=30, vol_lookback=20
        )
        labels = label_events_binary(events, bars, cfg)
        assert len(labels) == len(events)

        diag = compute_label_diagnostics(labels)
        assert diag.n_events == len(events)
        assert 0.0 <= diag.binary_pct_one <= 1.0

    def test_reproducible_with_seed(self) -> None:
        """Two runs with APEX_SEED=42 produce bit-identical labels."""
        os.environ["APEX_SEED"] = "42"
        n_bars = 300
        closes = _synthetic_gbm(n_bars, mu=0.08, sigma=0.20, seed=42)
        timestamps = [_ts(i) for i in range(n_bars)]
        bars = pl.DataFrame({"timestamp": timestamps, "close": closes})
        events = pl.DataFrame(
            {
                "timestamp": [timestamps[50], timestamps[100], timestamps[150]],
                "symbol": ["X", "X", "X"],
                "direction": [1, 1, 1],
            },
            schema={
                "timestamp": pl.Datetime("us", "UTC"),
                "symbol": pl.Utf8,
                "direction": pl.Int8,
            },
        )
        cfg = TripleBarrierConfig()
        out1 = label_events_binary(events, bars, cfg)
        out2 = label_events_binary(events, bars, cfg)
        assert out1.equals(out2)

    @pytest.mark.timeout(10)
    def test_performance_smoke(self) -> None:
        """Smoke: 500 events over 2000 bars completes quickly."""
        n_bars = 2000
        closes = _synthetic_gbm(n_bars, mu=0.05, sigma=0.15, seed=42)
        timestamps = [_ts(i) for i in range(n_bars)]
        bars = pl.DataFrame({"timestamp": timestamps, "close": closes})
        event_ts = [timestamps[i] for i in range(25, n_bars - 50, 3)][:500]
        events = pl.DataFrame(
            {
                "timestamp": event_ts,
                "symbol": ["Z"] * len(event_ts),
                "direction": [1] * len(event_ts),
            },
            schema={
                "timestamp": pl.Datetime("us", "UTC"),
                "symbol": pl.Utf8,
                "direction": pl.Int8,
            },
        )
        start = time.perf_counter()
        labels = label_events_binary(events, bars)
        elapsed = time.perf_counter() - start
        assert len(labels) == len(event_ts)
        assert elapsed < 10.0, f"labeling took {elapsed:.2f}s"
