"""One-shot script to download/refresh calendar event test fixtures.

Generates fixture files for calendar connectors:
- tests/fixtures/fomc_calendar_2024.html
- tests/fixtures/ecb_calendar_2024.html
- tests/fixtures/boj_calendar_2024.html
- tests/fixtures/fred_releases_payems_2024.json

If network downloads fail, the script falls back to synthetic fixtures
that contain representative data for deterministic unit tests.

Usage:
    python -m scripts._download_calendar_fixtures
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def download_fomc_fixture() -> None:
    """Download FOMC calendar page and save as HTML fixture."""
    try:
        import httpx

        resp = httpx.get(
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        out = FIXTURES / "fomc_calendar_2024.html"
        out.write_text(resp.text, encoding="utf-8")
        print(f"Wrote {out} ({len(resp.text)} chars)")
    except Exception as exc:
        print(f"FOMC download failed: {exc} — writing synthetic fixture")
        _write_synthetic_fomc()


def download_ecb_fixture() -> None:
    """Download ECB calendar page and save as HTML fixture."""
    try:
        import httpx

        resp = httpx.get(
            "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        out = FIXTURES / "ecb_calendar_2024.html"
        out.write_text(resp.text, encoding="utf-8")
        print(f"Wrote {out} ({len(resp.text)} chars)")
    except Exception as exc:
        print(f"ECB download failed: {exc} — writing synthetic fixture")
        _write_synthetic_ecb()


def download_boj_fixture() -> None:
    """Download BoJ MPM schedule page and save as HTML fixture."""
    try:
        import httpx

        resp = httpx.get(
            "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        out = FIXTURES / "boj_calendar_2024.html"
        out.write_text(resp.text, encoding="utf-8")
        print(f"Wrote {out} ({len(resp.text)} chars)")
    except Exception as exc:
        print(f"BoJ download failed: {exc} — writing synthetic fixture")
        _write_synthetic_boj()


def download_fred_releases_fixture() -> None:
    """Download FRED PAYEMS release dates and save as JSON fixture."""
    try:
        from fredapi import Fred

        from core.config import get_settings

        key = get_settings().fred_api_key.get_secret_value()
        if not key:
            print("FRED_API_KEY not set — writing synthetic fixture")
            _write_synthetic_fred_releases()
            return

        fred = Fred(api_key=key)
        df = fred.get_series_all_releases("PAYEMS")

        # Extract unique release dates (realtime_start from MultiIndex)
        dates: list[str] = []
        seen: set[str] = set()
        for idx_val in df.index:
            date_str = str(idx_val[0] if hasattr(idx_val, "__iter__") else idx_val)[:10]
            if date_str not in seen:
                seen.add(date_str)
                dates.append(date_str)

        # Keep only 2024 dates
        dates_2024 = [d for d in dates if d.startswith("2024")][:12]

        data = {
            "series_id": "PAYEMS",
            "release_dates": dates_2024,
        }
        out = FIXTURES / "fred_releases_payems_2024.json"
        out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out} ({len(dates_2024)} release dates)")
    except Exception as exc:
        print(f"FRED releases download failed: {exc} — writing synthetic fixture")
        _write_synthetic_fred_releases()


# ── Synthetic fallbacks ──────────────────────────────────────────────────


def _write_synthetic_fomc() -> None:
    """Write a minimal synthetic FOMC calendar HTML fixture."""
    html = """\
<!DOCTYPE html>
<html>
<head><title>FOMC Calendars</title></head>
<body>
<div class="panel panel-default">
  <div class="panel-heading"><h4>2024</h4></div>
  <div class="panel-body">
    <div class="fomc-meeting">January 30-31* (Released February 21, 2024)</div>
    <div class="fomc-meeting">March 19-20* (Released April 10, 2024)</div>
    <div class="fomc-meeting">April 30 - May 1 (Released May 22, 2024)</div>
    <div class="fomc-meeting">June 11-12* (Released July 3, 2024)</div>
    <div class="fomc-meeting">July 30-31 (Released August 21, 2024)</div>
    <div class="fomc-meeting">September 17-18* (Released October 9, 2024)</div>
    <div class="fomc-meeting">November 6-7* (Released November 26, 2024)</div>
    <div class="fomc-meeting">December 17-18* (Released January 8, 2025)</div>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h4>2025</h4></div>
  <div class="panel-body">
    <div class="fomc-meeting">January 28-29* (Released February 19, 2025)</div>
    <div class="fomc-meeting">March 18-19* (Released April 9, 2025)</div>
  </div>
</div>
</body>
</html>
"""
    out = FIXTURES / "fomc_calendar_2024.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote synthetic {out}")


def _write_synthetic_ecb() -> None:
    """Write a minimal synthetic ECB calendar HTML fixture."""
    html = """\
<!DOCTYPE html>
<html>
<head><title>ECB Governing Council Calendar</title></head>
<body>
<table>
  <tr><td>Monetary policy meeting</td><td>25 January 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>7 March 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>11 April 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>6 June 2024</td></tr>
  <tr><td>Governing Council (non-monetary)</td><td>17 July 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>12 September 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>17 October 2024</td></tr>
  <tr><td>Monetary policy meeting</td><td>12 December 2024</td></tr>
</table>
</body>
</html>
"""
    out = FIXTURES / "ecb_calendar_2024.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote synthetic {out}")


def _write_synthetic_boj() -> None:
    """Write a minimal synthetic BoJ MPM schedule HTML fixture."""
    html = """\
<!DOCTYPE html>
<html>
<head><title>Schedule of Monetary Policy Meetings</title></head>
<body>
<h3>2024</h3>
<table>
  <tr><td>January 22, 23</td></tr>
  <tr><td>March 18, 19</td></tr>
  <tr><td>April 25, 26</td></tr>
  <tr><td>June 13, 14</td></tr>
  <tr><td>July 30, 31</td></tr>
  <tr><td>September 19, 20</td></tr>
  <tr><td>October 30, 31</td></tr>
  <tr><td>December 18, 19</td></tr>
</table>
</body>
</html>
"""
    out = FIXTURES / "boj_calendar_2024.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote synthetic {out}")


def _write_synthetic_fred_releases() -> None:
    """Write a minimal synthetic FRED PAYEMS release dates fixture."""
    data = {
        "series_id": "PAYEMS",
        "release_dates": [
            "2024-01-05",
            "2024-02-02",
            "2024-03-08",
            "2024-04-05",
            "2024-05-03",
            "2024-06-07",
            "2024-07-05",
            "2024-08-02",
            "2024-09-06",
            "2024-10-04",
            "2024-11-01",
            "2024-12-06",
        ],
    }
    out = FIXTURES / "fred_releases_payems_2024.json"
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote synthetic {out}")


def main() -> None:
    """Download all calendar fixtures, falling back to synthetic on failure."""
    print(f"Fixture dir: {FIXTURES}")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    download_fomc_fixture()
    download_ecb_fixture()
    download_boj_fixture()
    download_fred_releases_fixture()
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)
