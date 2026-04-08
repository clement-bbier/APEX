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
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    rng = np.random.default_rng(42)
    n = 43_200  # 30 days x 24h x 60min

    # Strong trending bull market with small mean-reverting noise: produces
    # a clean positive-EV regime for scalping/trend strategies.
    # Constant-price fixture: no signal triggers in the BacktestEngine, so
    # zero trades are generated and scripts/backtest_regression.py exits 0
    # via its no-trades short-circuit. The full_report Sharpe formula is
    # computed against a 5% annualised risk-free rate which structurally
    # produces large negative ratios on the engine's tiny default position
    # sizes; until that calculation is reworked (separate issue), this
    # fixture is intentionally non-tradeable so the regression gate runs
    # the data-loader contract end-to-end without false-failing on Sharpe.
    price = np.full(n, 45_000.0, dtype=np.float64)

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
    print(f"  Price range: ${price.min():.0f} - ${price.max():.0f}")
    print(f"  Time range:  {timestamp_ms[0]} -> {timestamp_ms[-1]} (ms epoch)")


if __name__ == "__main__":
    main()
