"""Byte-determinism regression for the backtest-gate fixture generator.

The CI backtest-gate relies on ``scripts/generate_test_fixtures.py`` producing
an identical parquet file on every run — otherwise Sharpe/DD thresholds would
drift between CI runs and could silently pass or fail for reasons unrelated
to code changes.

Fail-fast: any non-determinism in the OU process (missing seed, non-fixed RNG,
non-deterministic pandas operation) is caught here instead of on the nightly
CI.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.generate_test_fixtures import (
    _OU_MU,
    _OU_SIGMA,
    _OU_THETA,
    _SEED,
    _generate_ou_price_path,
)


def _path_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_price_path_is_deterministic_across_runs() -> None:
    """Two runs with the fixed seed yield bit-identical price arrays."""
    rng1 = np.random.default_rng(_SEED)
    rng2 = np.random.default_rng(_SEED)
    path1 = _generate_ou_price_path(1_000, rng1)
    path2 = _generate_ou_price_path(1_000, rng2)
    assert np.array_equal(path1, path2), (
        "OU price path diverged across two runs with the same seed — "
        "fixture is not byte-deterministic"
    )


def test_price_path_parameters_are_within_realistic_band() -> None:
    """Steady-state std implied by OU params stays within a realistic 1% band.

    Protects against future retuning that would silently expand or
    collapse the price band and invalidate the backtest thresholds.
    """
    rng = np.random.default_rng(_SEED)
    path = _generate_ou_price_path(43_200, rng)
    # With theta=0.001, sigma=15, steady-state std = sigma / sqrt(2*theta) ~ 335.
    # Observed std over 30 days should be O(hundreds), not O(thousands).
    observed_std = float(np.std(path))
    assert 100.0 < observed_std < 1_000.0, (
        f"OU steady-state std = {observed_std:.2f}; outside [100, 1000] "
        f"realistic band. Params may have drifted from "
        f"(theta={_OU_THETA}, mu={_OU_MU}, sigma={_OU_SIGMA})."
    )


def test_parquet_output_is_byte_deterministic(tmp_path: Path) -> None:
    """Writing the fixture twice with the fixed seed yields identical bytes."""
    rng_a = np.random.default_rng(_SEED)
    rng_b = np.random.default_rng(_SEED)
    n = 1_000
    price_a = _generate_ou_price_path(n, rng_a)
    price_b = _generate_ou_price_path(n, rng_b)

    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    timestamp_ms = start_ms + np.arange(n, dtype=np.int64) * 60_000

    def _write(path: Path, price: np.ndarray, rng: np.random.Generator) -> None:
        df = pd.DataFrame(
            {
                "symbol": "BTCUSDT",
                "market": "crypto",
                "timestamp_ms": timestamp_ms,
                "price": price,
                "volume": rng.uniform(0.5, 5.0, n),
                "side": "unknown",
                "bid": price * 0.9999,
                "ask": price * 1.0001,
                "spread_bps": np.full(n, 1.0, dtype=np.float64),
                "session": "after_hours",
            }
        )
        df.to_parquet(path, index=False)

    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    _write(a, price_a, np.random.default_rng(_SEED + 1))
    _write(b, price_b, np.random.default_rng(_SEED + 1))

    assert _path_hash(a) == _path_hash(b), (
        "Two parquet writes with identical inputs produced different bytes — "
        "pandas / pyarrow is introducing non-determinism"
    )
