"""Generate a mean-reverting BTCUSDT 1-min fixture for backtest regression gate.

Schema is aligned with backtesting.data_loader.load_parquet():
    symbol       : str
    market       : str        ("crypto")
    timestamp_ms : int64      (epoch milliseconds)
    price        : float64
    volume       : float64
    side         : str        ("unknown")
    bid / ask    : float64
    spread_bps   : float64
    session      : str        ("after_hours")

The price path is a discrete Ornstein-Uhlenbeck process:

    X_{t+1} = X_t + theta * (mu - X_t) * dt + sigma * sqrt(dt) * Z_t

with ``Z_t ~ N(0, 1)``, ``dt = 1`` minute. Parameters (see
``_OU_THETA``, ``_OU_MU``, ``_OU_SIGMA``) produce a price that oscillates
inside a plausible band around ``mu`` with a half-life of ~11.5 hours,
creating mean-reversion opportunities the Phase 3/4 signal suite can
exercise. The RNG seed is fixed so the fixture is byte-deterministic
across runs (tests/unit/scripts/test_fixture_determinism.py enforces).

Why this fixture replaced the previous constant-price one: the old
generator emitted ``np.full(43_200, 45_000.0)`` so the BacktestEngine
produced zero trades and ``scripts/backtest_regression.py`` short-
circuited with exit 0 without ever running ``full_report()``. That made
the CI backtest-gate structurally vacuous — passing regardless of
Sharpe/DD correctness. See issue #102 + STRATEGIC_AUDIT_2026-04-17
Tech Finding 3.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Ornstein-Uhlenbeck parameters. Tuned so that (a) the process stays
# inside a realistic ~1% band around mu, (b) minute-scale volatility is
# large enough to trigger the microstructure signal suite.
_OU_THETA: float = 0.001  # mean-reversion speed per minute (half-life ~11.5h)
_OU_MU: float = 45_000.0  # long-term mean in USD
_OU_SIGMA: float = 15.0  # diffusion term per sqrt(minute)
_SEED: int = 42  # fixed for byte-deterministic fixture output


def _generate_ou_price_path(n: int, rng: np.random.Generator) -> np.ndarray:
    """Simulate n minutes of a discrete OU process starting at mu.

    Uses the Euler-Maruyama discretisation with dt=1 (minute). Clamps the
    output at a 1.0 floor as a defensive guard — with the chosen params
    the steady-state std is ~335, so the floor never activates in
    practice but we want to fail loudly if the params are ever retuned
    to something unrealistic.
    """
    price = np.empty(n, dtype=np.float64)
    price[0] = _OU_MU
    noise = rng.standard_normal(n)
    for i in range(1, n):
        drift = _OU_THETA * (_OU_MU - price[i - 1])
        price[i] = price[i - 1] + drift + _OU_SIGMA * noise[i]
    return np.maximum(price, 1.0)


def main() -> None:
    rng = np.random.default_rng(_SEED)
    n = 43_200  # 30 days × 24h × 60min

    price = _generate_ou_price_path(n, rng)

    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    timestamp_ms = start_ms + np.arange(n, dtype=np.int64) * 60_000  # 1-min cadence

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
    out = Path("tests/fixtures/30d_btcusdt_1m.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"Generated {n} candles -> {out}")
    print(f"  Price range: ${price.min():.2f} - ${price.max():.2f}")
    print(f"  Price mean / std: ${price.mean():.2f} / ${price.std():.2f}")
    print(f"  Time range:  {timestamp_ms[0]} -> {timestamp_ms[-1]} (ms epoch)")


if __name__ == "__main__":
    main()
