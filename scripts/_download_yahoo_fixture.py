"""One-shot script to download Yahoo Finance fixture data for tests.

Usage:
    python scripts/_download_yahoo_fixture.py

Generates tests/fixtures/yahoo_spx_1d_2024-q1.json with ^GSPC daily bars.
"""

from __future__ import annotations

import yfinance as yf

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
