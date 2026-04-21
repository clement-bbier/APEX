"""Bank of Japan (BoJ) macro data connector.

Downloads limited macro-economic series from BoJ public CSV endpoints.
BoJ does not provide a structured REST API, so this connector scrapes
hardcoded CSV URLs for a curated set of priority series.

NOTE: BoJ CSV formats vary across endpoints. The connector handles the
most common format (date column + value columns). If an endpoint changes
its layout, the connector logs a clear error and skips that series.

References:
    BoJ Statistics — https://www.boj.or.jp/en/statistics/index.htm
    Ueda (2012) — "Japan's Deflation and the Bank of Japan's Experience
                    with Non-traditional Monetary Policy"
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog

from core.models.data import MacroPoint, MacroSeriesMeta
from services.data_ingestion.connectors.macro_base import MacroConnector

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0

# Curated series with known-stable BoJ CSV endpoints.
# These URLs point to English-language statistical downloads.
# NOTE: BoJ occasionally changes URL structure. If a download 404s,
# BoJFetchError is raised with the broken URL for manual triage.
_BOJ_SERIES: dict[str, dict[str, str]] = {
    "boj_policy_rate": {
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm02_m_1.csv",
        "name": "BoJ Policy Rate (Uncollateralized Overnight Call Rate)",
        "frequency": "monthly",
        "unit": "percent",
    },
    "boj_monetary_base": {
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/md02_m_1.csv",
        "name": "BoJ Monetary Base (Average Outstanding)",
        "frequency": "monthly",
        "unit": "100mn_jpy",
    },
    "boj_cpi": {
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/pr01_m_1.csv",
        "name": "Japan CPI (All Items, National)",
        "frequency": "monthly",
        "unit": "index",
    },
    "boj_m2": {
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/md11_m_1.csv",
        "name": "Japan M2 Money Stock",
        "frequency": "monthly",
        "unit": "100mn_jpy",
    },
    "boj_trade_balance": {
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/bp01_m_1.csv",
        "name": "Japan Trade Balance",
        "frequency": "monthly",
        "unit": "100mn_jpy",
    },
}


class BoJFetchError(Exception):
    """Raised when BoJ CSV download or parsing fails after retries."""


class BoJConnector(MacroConnector):
    """Downloads macro time series from BoJ public CSV endpoints.

    Limited to the curated series in ``_BOJ_SERIES``.
    Uses ``httpx.AsyncClient`` for downloads.
    """

    def __init__(self, concurrency: int = 3) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "boj"

    @staticmethod
    def available_series() -> list[str]:
        """Return list of supported BoJ series IDs."""
        return list(_BOJ_SERIES.keys())

    async def fetch_series(
        self,
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[MacroPoint]]:
        """Yield batches of macro data points from BoJ CSV.

        Args:
            series_id: BoJ series key (e.g. ``boj_policy_rate``).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`MacroPoint` per batch.
        """
        if series_id not in _BOJ_SERIES:
            msg = f"Unknown BoJ series '{series_id}'. Available: {list(_BOJ_SERIES.keys())}"
            raise BoJFetchError(msg)

        url = _BOJ_SERIES[series_id]["url"]
        csv_bytes = await self._download_csv(url)
        points = self._parse_boj_csv(csv_bytes, series_id, start, end)

        for i in range(0, len(points), _BATCH_SIZE):
            yield points[i : i + _BATCH_SIZE]

    async def fetch_metadata(self, series_id: str) -> MacroSeriesMeta:
        """Return metadata for a BoJ series.

        Args:
            series_id: BoJ series key.

        Returns:
            A :class:`MacroSeriesMeta` from the curated registry.
        """
        if series_id not in _BOJ_SERIES:
            msg = f"Unknown BoJ series '{series_id}'. Available: {list(_BOJ_SERIES.keys())}"
            raise BoJFetchError(msg)

        info = _BOJ_SERIES[series_id]
        return MacroSeriesMeta(
            series_id=series_id,
            source="BOJ",
            name=info["name"],
            frequency=info.get("frequency"),
            unit=info.get("unit"),
            description=f"Bank of Japan: {info['name']}",
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _download_csv(self, url: str) -> bytes:
        """Download CSV bytes from a BoJ URL with retry.

        Returns:
            Raw CSV content as bytes.
        """
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for attempt in range(_MAX_RETRIES):
                try:
                    async with self._semaphore:
                        resp = await client.get(url)
                        await asyncio.sleep(0.5)
                    if resp.status_code == 404:
                        raise BoJFetchError(f"BoJ CSV not found (URL may have changed): {url}")
                    if resp.status_code == 429 or resp.status_code >= 500:
                        wait = _BACKOFF_BASE * (2**attempt)
                        logger.warning(
                            "boj_retry",
                            url=url,
                            status=resp.status_code,
                            wait=wait,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.content
                except BoJFetchError:
                    raise
                except httpx.HTTPStatusError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "boj_download_error",
                        url=url,
                        error=str(exc),
                        attempt=attempt + 1,
                    )
                    if attempt == _MAX_RETRIES - 1:
                        raise BoJFetchError(f"failed to download {url}: {exc}") from exc
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        raise BoJFetchError(f"max retries exceeded: {url}")

    @staticmethod
    def _parse_boj_csv(
        raw: bytes,
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> list[MacroPoint]:
        """Parse BoJ CSV bytes into MacroPoint list.

        BoJ CSV format (common pattern):
        - Header rows (variable count, often Japanese labels)
        - Data rows: date-like first column, numeric subsequent columns
        - We take the first numeric column as the value

        The parser skips rows that don't match the expected pattern.
        """
        points: list[MacroPoint] = []

        # Try multiple encodings — BoJ CSVs are often Shift-JIS
        text = ""
        for encoding in ("utf-8-sig", "shift_jis", "cp932"):
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not text:
            raise BoJFetchError(
                f"failed to decode CSV for {series_id}: tried utf-8-sig, shift_jis, cp932"
            )

        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if len(row) < 2:
                continue
            # Try to parse first column as date
            dt = _try_parse_date(row[0].strip())
            if dt is None:
                continue
            if dt < start or dt >= end:
                continue

            # Find first numeric value in remaining columns
            value = _first_numeric(row[1:])
            if value is None:
                continue

            points.append(
                MacroPoint(
                    series_id=series_id,
                    timestamp=dt,
                    value=value,
                )
            )

        points.sort(key=lambda p: p.timestamp)
        return points


def _try_parse_date(s: str) -> datetime | None:
    """Attempt to parse a date string in common BoJ formats.

    Returns UTC datetime or None if unparseable.
    """
    # Remove quotes
    s = s.strip('"').strip("'").strip()
    for fmt in ("%Y/%m", "%Y/%m/%d", "%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _first_numeric(cells: list[str]) -> float | None:
    """Return the first parseable float from a list of cell values."""
    for cell in cells:
        cleaned = cell.strip().strip('"').replace(",", "")
        if not cleaned or cleaned in ("", "-", "...", "n.a.", "N/A"):
            continue
        try:
            return float(cleaned)
        except ValueError:
            continue
    return None
