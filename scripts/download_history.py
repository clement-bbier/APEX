#!/usr/bin/env python3
"""Download historical data for APEX backtesting.

Downloads:
- Binance: BTC/USDT and ETH/USDT 1-minute klines (2 years)
- Alpaca:  Top 20 S&P500 equities 1-minute bars (2 years)

Data is saved to ``data/historical/*.parquet``.

Usage::

    python scripts/download_history.py --years 2 --output-dir data/historical
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


async def download_binance(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    output_dir: Path,
) -> None:
    """Download Binance klines and save as Parquet.

    Args:
        symbol:     Binance pair, e.g. ``"BTCUSDT"``.
        start_dt:   Start datetime (UTC).
        end_dt:     End datetime (UTC).
        output_dir: Directory to write the Parquet file.
    """
    from backtesting.data_loader import BinanceHistoricalLoader, save_parquet

    print(f"  Downloading Binance {symbol} …")
    loader = BinanceHistoricalLoader(symbol=symbol)
    ticks = await loader.load_klines(start_dt, end_dt)
    fname = output_dir / f"{symbol.lower()}_1m.parquet"
    save_parquet(ticks, fname)
    print(f"    ✓ {len(ticks)} bars → {fname}")


def download_alpaca(
    symbol: str,
    api_key: str,
    secret_key: str,
    start_dt: datetime,
    end_dt: datetime,
    output_dir: Path,
) -> None:
    """Download Alpaca equity bars and save as Parquet.

    Uses the ``alpaca-py`` SDK - NOT the deprecated ``alpaca-trade-api``.

    Args:
        symbol:     Equity ticker, e.g. ``"AAPL"``.
        api_key:    Alpaca API key.
        secret_key: Alpaca secret key.
        start_dt:   Start datetime (UTC).
        end_dt:     End datetime (UTC).
        output_dir: Directory to write the Parquet file.
    """
    from backtesting.data_loader import AlpacaHistoricalLoader, save_parquet

    print(f"  Downloading Alpaca {symbol} …")
    loader = AlpacaHistoricalLoader(api_key=api_key, secret_key=secret_key)
    ticks = loader.load_bars(symbol, start_dt, end_dt)
    fname = output_dir / f"{symbol.lower()}_1m.parquet"
    save_parquet(ticks, fname)
    print(f"    ✓ {len(ticks)} bars → {fname}")


async def main(
    years: int,
    days: int,
    symbol: str,
    output_dir: str,
    alpaca_key: str,
    alpaca_secret: str,
) -> None:
    """Entry point for the download script.

    Args:
        years:        Number of years of history to download.
        days:         Number of days of history to download.
        symbol:       Specific symbol to download.
        output_dir:   Output directory path.
        alpaca_key:   Alpaca API key (may be empty).
        alpaca_secret: Alpaca secret key (may be empty).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.now(UTC)
    if years > 0:
        start_dt = end_dt - timedelta(days=365 * years)
    else:
        start_dt = end_dt - timedelta(days=days)

    print("\n─── APEX Historical Data Downloader ───")
    print(f"  period  : {start_dt.date()} → {end_dt.date()}")
    print(f"  output  : {out.resolve()}\n")

    # Binance crypto
    pairs = [symbol.upper()] if symbol else ["BTCUSDT", "ETHUSDT"]
    for pair in pairs:
        try:
            await download_binance(pair, start_dt, end_dt, out)
        except Exception as exc:
            print(f"  ✗ Binance {pair} failed: {exc}", file=sys.stderr)

    # Alpaca equities
    if alpaca_key and alpaca_secret and not symbol:
        sp500_top20 = [
            "AAPL",
            "MSFT",
            "AMZN",
            "NVDA",
            "GOOGL",
            "META",
            "TSLA",
            "AVGO",
            "GOOG",
            "BRK.B",
            "JPM",
            "LLY",
            "XOM",
            "UNH",
            "V",
            "MA",
            "HD",
            "PG",
            "COST",
            "ABBV",
        ]
        for ticker in sp500_top20:
            try:
                download_alpaca(ticker, alpaca_key, alpaca_secret, start_dt, end_dt, out)
            except Exception as exc:
                print(f"  ✗ Alpaca {ticker} failed: {exc}", file=sys.stderr)
    else:
        print("  ⚠ Alpaca keys not set - skipping equity download")

    print("\n─── Done ───")


def cli() -> None:
    """Parse CLI arguments and run."""
    import os

    parser = argparse.ArgumentParser(description="Download APEX historical data")
    parser.add_argument("--years", type=int, default=0, help="Years of history (default 0)")
    parser.add_argument("--days", type=int, default=7, help="Days of history (default 7)")
    parser.add_argument("--symbol", type=str, default="", help="Symbol to download (default: all)")
    parser.add_argument("--output-dir", default="data/historical", help="Output directory")
    args = parser.parse_args()

    alpaca_key = os.environ.get("ALPACA_API_KEY", "")
    alpaca_secret = os.environ.get("ALPACA_API_SECRET", "")

    asyncio.run(
        main(args.years, args.days, args.symbol, args.output_dir, alpaca_key, alpaca_secret)
    )


if __name__ == "__main__":
    cli()
