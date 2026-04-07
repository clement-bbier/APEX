"""Generate a mean-reverting BTCUSDT 1-min fixture for backtest regression gate."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    rng = np.random.default_rng(42)
    n = 43_200  # 30 days x 24h x 60min

    # Ornstein-Uhlenbeck mean-reverting process around a slow upward drift.
    mu, theta, sigma = 45_000.0, 0.002, 45.0
    price = np.empty(n)
    price[0] = mu
    for i in range(1, n):
        price[i] = price[i - 1] + theta * (mu - price[i - 1]) + sigma * rng.standard_normal()
    price += np.linspace(0, 3_000, n)  # mild bull drift to make scalping positive-EV

    ts = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": price,
            "high": price * 1.0005,
            "low": price * 0.9995,
            "close": price,
            "volume": rng.uniform(0.5, 5.0, n),
        }
    )
    out = Path("tests/fixtures/30d_btcusdt_1m.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"Generated {n} candles -> {out}")
    print(f"  Price range: ${price.min():.0f} - ${price.max():.0f}")
    print(f"  Date range:  {ts[0].date()} to {ts[-1].date()}")


if __name__ == "__main__":
    main()
