"""One-shot script to download/refresh fundamentals test fixtures.

Generates fixture files for fundamentals connectors:
- tests/fixtures/edgar_company_tickers.json
- tests/fixtures/edgar_aapl_submissions.json
- tests/fixtures/edgar_aapl_companyfacts.json
- tests/fixtures/simfin_aapl_financials.json

If network downloads fail or SIMFIN_API_KEY is absent, the script falls
back to the existing synthetic fixtures that ship with the repo.

Usage:
    python -m scripts._download_fundamentals_fixtures
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

_TICKERS_OF_INTEREST = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA", "META", "AMZN", "AMD"]
_AAPL_CIK = 320193


def download_company_tickers() -> None:
    """Download SEC company_tickers.json and extract a reduced subset."""
    try:
        import httpx

        resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "APEX fixtures@example.com"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        full = resp.json()

        # Filter to tickers of interest + SPY/QQQ
        wanted = {t.upper() for t in _TICKERS_OF_INTEREST} | {"SPY", "QQQ"}
        reduced: dict[str, dict[str, object]] = {}
        idx = 0
        for entry in full.values():
            if str(entry.get("ticker", "")).upper() in wanted:
                reduced[str(idx)] = entry
                idx += 1

        out = FIXTURES / "edgar_company_tickers.json"
        out.write_text(json.dumps(reduced, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out} ({len(reduced)} tickers)")
    except Exception as exc:
        print(f"Company tickers download failed: {exc} — keeping existing fixture")


def download_aapl_submissions() -> None:
    """Download AAPL submissions from SEC EDGAR."""
    try:
        import httpx

        cik_padded = f"{_AAPL_CIK:010d}"
        resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers={"User-Agent": "APEX fixtures@example.com"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()

        # Keep only recent filings (first 20 entries)
        recent = data.get("filings", {}).get("recent", {})
        trimmed_recent: dict[str, list[object]] = {}
        for key, values in recent.items():
            if isinstance(values, list):
                trimmed_recent[key] = values[:20]
            else:
                trimmed_recent[key] = values

        trimmed = {
            "cik": data.get("cik"),
            "entityType": data.get("entityType"),
            "sic": data.get("sic"),
            "sicDescription": data.get("sicDescription"),
            "name": data.get("name"),
            "tickers": data.get("tickers"),
            "exchanges": data.get("exchanges"),
            "filings": {"recent": trimmed_recent, "files": []},
        }

        out = FIXTURES / "edgar_aapl_submissions.json"
        out.write_text(json.dumps(trimmed, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    except Exception as exc:
        print(f"AAPL submissions download failed: {exc} — keeping existing fixture")


def download_aapl_companyfacts() -> None:
    """Download AAPL companyfacts from SEC EDGAR XBRL API."""
    try:
        import httpx

        cik_padded = f"{_AAPL_CIK:010d}"
        resp = httpx.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json",
            headers={"User-Agent": "APEX fixtures@example.com"},
            timeout=60.0,
            follow_redirects=True,
        )
        resp.raise_for_status()

        out = FIXTURES / "edgar_aapl_companyfacts.json"
        out.write_text(resp.text, encoding="utf-8")
        size_kb = len(resp.text) / 1024
        print(f"Wrote {out} ({size_kb:.0f} KB)")
    except Exception as exc:
        print(f"AAPL companyfacts download failed: {exc} — keeping existing fixture")


def download_simfin_aapl() -> None:
    """Download AAPL financials from SimFin API."""
    try:
        from core.config import get_settings

        key = get_settings().simfin_api_key.get_secret_value()
        if not key:
            print("SIMFIN_API_KEY not set — keeping existing fixture")
            return

        import httpx

        headers = {"X-API-KEY": key, "Accept": "application/json"}
        resp = httpx.get(
            "https://backend.simfin.com/api/v3/companies/AAPL/statements/PL",
            headers=headers,
            params={"period": "fy"},
            timeout=30.0,
        )
        resp.raise_for_status()

        out = FIXTURES / "simfin_aapl_financials.json"
        out.write_text(json.dumps(resp.json(), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    except Exception as exc:
        print(f"SimFin AAPL download failed: {exc} — keeping existing fixture")


def main() -> None:
    """Download all fundamentals fixtures, falling back on failure."""
    print(f"Fixture dir: {FIXTURES}")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    download_company_tickers()
    download_aapl_submissions()
    download_aapl_companyfacts()
    download_simfin_aapl()
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)
