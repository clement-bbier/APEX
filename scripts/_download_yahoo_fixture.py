"""One-shot fixture downloader for Yahoo Finance tests."""

from __future__ import annotations

import yfinance as yf


def main() -> None:
    """Download ^GSPC Q1 2024 daily bars and save as JSON fixture."""
    df = yf.Ticker("^GSPC").history(
        start="2024-01-01",
        end="2024-04-01",
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    df.to_json(
        "tests/fixtures/yahoo_spx_1d_2024-q1.json",
        orient="table",
        date_format="iso",
    )
    print(f"Saved {len(df)} bars")


if __name__ == "__main__":
    main()
