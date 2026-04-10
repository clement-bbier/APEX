"""One-shot script to download/refresh macro test fixtures.

Generates fixture files for FRED, ECB, and BoJ connectors:
- tests/fixtures/fred_fedfunds_2024.json
- tests/fixtures/ecb_eurusd_2024.json
- tests/fixtures/boj_policy_rate_2024.csv

If network downloads fail (no API key, offline, etc.), the script
prints a warning and keeps the existing synthetic fixtures.

Usage:
    python -m scripts._download_macro_fixtures
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def download_fred_fixture() -> None:
    """Download FEDFUNDS 2024 from FRED and save as JSON fixture."""
    try:
        from fredapi import Fred

        from core.config import get_settings

        key = get_settings().fred_api_key.get_secret_value()
        if not key:
            print("FRED_API_KEY not set — keeping synthetic fixture")
            return
        fred = Fred(api_key=key)
        series = fred.get_series(
            "FEDFUNDS",
            observation_start="2024-01-01",
            observation_end="2024-12-31",
        )
        info = fred.get_series_info("FEDFUNDS")

        observations = []
        for ts, val in series.items():
            if val == val:  # skip NaN
                observations.append(
                    {
                        "date": ts.strftime("%Y-%m-%d"),
                        "value": round(float(val), 4),
                    }
                )

        data = {
            "series_id": "FEDFUNDS",
            "source": "FRED",
            "title": str(info.get("title", "Federal Funds Effective Rate")),
            "frequency_short": str(info.get("frequency_short", "M")),
            "units_short": str(info.get("units_short", "Percent")),
            "notes": str(info.get("notes", "")),
            "observations": observations[:10],
        }
        out = FIXTURES / "fred_fedfunds_2024.json"
        out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out} ({len(observations)} obs, truncated to 10)")
    except Exception as exc:
        print(f"FRED download failed: {exc} — keeping synthetic fixture")


def download_ecb_fixture() -> None:
    """Download EUR/USD daily 2024 from ECB and save as JSON fixture."""
    try:
        import httpx

        url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
        params = {
            "format": "jsondata",
            "startPeriod": "2024-01-01",
            "endPeriod": "2024-01-31",
            "lastNObservations": "10",
        }
        resp = httpx.get(url, params=params, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        out = FIXTURES / "ecb_eurusd_2024.json"
        out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    except Exception as exc:
        print(f"ECB download failed: {exc} — keeping synthetic fixture")


def download_boj_fixture() -> None:
    """Download BoJ policy rate CSV and save as fixture."""
    try:
        import httpx

        url = "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm02_m_1.csv"
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        out = FIXTURES / "boj_policy_rate_2024.csv"
        out.write_bytes(resp.content)
        print(f"Wrote {out} ({len(resp.content)} bytes)")
    except Exception as exc:
        print(f"BoJ download failed: {exc} — keeping synthetic fixture")


def main() -> None:
    """Download all fixtures, falling back to synthetic on failure."""
    print(f"Fixture dir: {FIXTURES}")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    download_fred_fixture()
    download_ecb_fixture()
    download_boj_fixture()
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)
