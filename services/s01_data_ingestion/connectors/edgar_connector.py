"""SEC EDGAR fundamentals connector.

Downloads company filings metadata and XBRL financial data from the SEC
EDGAR system. Uses the official JSON APIs (submissions + companyfacts)
with required User-Agent identification per SEC fair access policy.

References:
    SEC EDGAR API — https://www.sec.gov/edgar/sec-api-documentation
    Fama & French (1993) JFE — "Common risk factors in the returns
        on stocks and bonds"
    Novy-Marx (2013) JFE — "The other side of value: The gross
        profitability premium"
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx
import structlog

from core.config import get_settings
from core.models.data import CorporateEvent, FundamentalPoint
from services.s01_data_ingestion.connectors.fundamentals_base import (
    FundamentalsConnector,
)

logger = structlog.get_logger(__name__)

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_REQUEST_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BATCH_SIZE = 500

# US-GAAP concept → metric_name mapping
_GAAP_CONCEPT_MAP: dict[str, str] = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "NetIncomeLoss": "net_income",
    "Assets": "total_assets",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "stockholders_equity",
    "EarningsPerShareBasic": "eps_basic",
    "EarningsPerShareDiluted": "eps_diluted",
    "OperatingIncomeLoss": "operating_income",
    "GrossProfit": "gross_profit",
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "LongTermDebt": "long_term_debt",
    "CommonStockSharesOutstanding": "shares_outstanding",
}

# Filing type → period_type mapping
_FILING_PERIOD_MAP: dict[str, str] = {
    "10-K": "annual",
    "10-Q": "quarterly",
    "8-K": "current",
}


class EDGARFetchError(Exception):
    """Raised when SEC EDGAR fetch fails after retries."""


class EDGARConnector(FundamentalsConnector):
    """Downloads fundamentals from SEC EDGAR JSON APIs.

    Uses ``httpx.AsyncClient`` with required User-Agent header.
    Rate-limited via ``asyncio.Semaphore(10)`` + 0.1 s sleep between calls.
    Retry: exponential backoff (1 s, 2 s, 4 s), max 3 attempts.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        user_agent: str | None = None,
        concurrency: int = 10,
    ) -> None:
        if user_agent is None:
            user_agent = get_settings().edgar_user_agent
        self._user_agent = user_agent
        self._headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cik_cache: dict[str, int] | None = None

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "edgar"

    # ── Ticker → CIK resolution ──────────────────────────────────────────────

    async def _ensure_cik_cache(self) -> dict[str, int]:
        """Download and cache the SEC company_tickers.json mapping."""
        if self._cik_cache is not None:
            return self._cik_cache

        data = await self._get_json(_COMPANY_TICKERS_URL)
        mapping: dict[str, int] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = int(entry.get("cik_str", 0))
            if ticker and cik:
                mapping[ticker] = cik
        self._cik_cache = mapping
        logger.info("edgar_cik_cache_loaded", count=len(mapping))
        return mapping

    async def ticker_to_cik(self, ticker: str) -> int:
        """Resolve a ticker symbol to its SEC CIK number.

        Args:
            ticker: Equity ticker (e.g. ``AAPL``).

        Returns:
            CIK number as integer.

        Raises:
            EDGARFetchError: If ticker cannot be resolved.
        """
        cache = await self._ensure_cik_cache()
        cik = cache.get(ticker.upper())
        if cik is None:
            msg = f"Ticker {ticker!r} not found in SEC company_tickers.json"
            raise EDGARFetchError(msg)
        return cik

    # ── Filings list ─────────────────────────────────────────────────────────

    async def fetch_filings(
        self,
        ticker: str,
        filing_types: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, str]]:
        """Fetch filing metadata for a ticker.

        Args:
            ticker: Equity ticker.
            filing_types: Desired filing types (e.g. ``["10-K", "10-Q"]``).
            start: Inclusive start date.
            end: Exclusive end date.

        Returns:
            List of dicts with keys ``form``, ``filingDate``, ``accessionNumber``.
        """
        cik = await self.ticker_to_cik(ticker)
        cik_padded = f"{cik:010d}"
        url = _SUBMISSIONS_URL.format(cik=cik_padded)
        data = await self._get_json(url)

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])

        filing_types_set = {ft.upper() for ft in filing_types}
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        results: list[dict[str, str]] = []
        for form, filing_date_str, accession in zip(forms, dates, accessions, strict=False):
            if form.upper() not in filing_types_set:
                continue
            filing_date = date.fromisoformat(filing_date_str)
            if filing_date < start_date or filing_date >= end_date:
                continue
            results.append(
                {
                    "form": form,
                    "filingDate": filing_date_str,
                    "accessionNumber": accession,
                }
            )

        logger.info(
            "edgar_filings_fetched",
            ticker=ticker,
            count=len(results),
            filing_types=list(filing_types_set),
        )
        return results

    # ── XBRL companyfacts → FundamentalPoint ─────────────────────────────────

    async def _fetch_companyfacts(self, ticker: str) -> dict[str, Any]:
        """Download the full XBRL companyfacts JSON for a ticker."""
        cik = await self.ticker_to_cik(ticker)
        cik_padded = f"{cik:010d}"
        url = _COMPANYFACTS_URL.format(cik=cik_padded)
        return await self._get_json(url)

    def _parse_xbrl_concepts(
        self,
        facts: dict[str, Any],
        asset_id: uuid.UUID,
        filing_types: list[str],
        start: datetime,
        end: datetime,
    ) -> list[FundamentalPoint]:
        """Extract FundamentalPoint records from XBRL companyfacts JSON.

        Maps US-GAAP concepts to our metric names and filters by date range
        and filing type.
        """
        facts_inner: Any = facts.get("facts", {})
        if isinstance(facts_inner, dict):
            us_gaap: dict[str, Any] = facts_inner.get("us-gaap", {})
        else:
            return []

        filing_types_set = {ft.upper() for ft in filing_types}
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        points: list[FundamentalPoint] = []
        seen: set[tuple[str, str, str]] = set()

        for concept_name, metric_name in _GAAP_CONCEPT_MAP.items():
            concept_data: Any = us_gaap.get(concept_name)
            if not concept_data:
                continue

            units: dict[str, Any] = concept_data.get("units", {})
            for unit_key, entries in units.items():
                for entry in entries:
                    form = str(entry.get("form", "")).upper()
                    if form not in filing_types_set:
                        continue

                    filed_str = entry.get("filed", "")
                    if not filed_str:
                        continue

                    try:
                        filed_date = date.fromisoformat(str(filed_str))
                    except ValueError:
                        continue

                    if filed_date < start_date or filed_date >= end_date:
                        continue

                    # Determine period type from form
                    period_type = _FILING_PERIOD_MAP.get(form, "other")

                    # Dedup key: (metric, date, period)
                    dedup_key = (metric_name, str(filed_date), period_type)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    val = entry.get("val")
                    currency = "USD" if unit_key == "USD" else unit_key

                    points.append(
                        FundamentalPoint(
                            asset_id=asset_id,
                            report_date=filed_date,
                            period_type=period_type,
                            metric_name=metric_name,
                            value=float(val) if val is not None else None,
                            currency=currency if unit_key != "shares" else None,
                        )
                    )

        logger.info("edgar_xbrl_parsed", point_count=len(points))
        return points

    # ── FundamentalsConnector interface ───────────────────────────────────────

    async def fetch_fundamentals(
        self,
        ticker: str,
        filing_types: list[str],
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[FundamentalPoint]]:
        """Yield batches of fundamental data from SEC EDGAR XBRL.

        Uses the companyfacts endpoint which returns all historical data
        for a company in a single JSON response.

        Args:
            ticker: Equity ticker (e.g. ``AAPL``).
            filing_types: Filing types to include (e.g. ``["10-K", "10-Q"]``).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of :class:`FundamentalPoint` up to 500 per batch.
        """
        # Use a deterministic UUID based on ticker for consistency
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"edgar.{ticker.upper()}")

        facts = await self._fetch_companyfacts(ticker)
        points = self._parse_xbrl_concepts(facts, asset_id, filing_types, start, end)

        for i in range(0, len(points), _BATCH_SIZE):
            yield points[i : i + _BATCH_SIZE]

    async def fetch_corporate_events(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[CorporateEvent]]:
        """Yield corporate events from EDGAR 8-K filings.

        Extracts 8-K filing dates as corporate events of type ``filing_8k``.

        Args:
            ticker: Equity ticker.
            start: Inclusive start datetime.
            end: Exclusive end datetime.

        Yields:
            Lists of :class:`CorporateEvent`.
        """
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"edgar.{ticker.upper()}")
        filings = await self.fetch_filings(ticker, ["8-K"], start, end)

        events: list[CorporateEvent] = []
        for filing in filings:
            filing_date = date.fromisoformat(filing["filingDate"])
            events.append(
                CorporateEvent(
                    asset_id=asset_id,
                    event_date=filing_date,
                    event_type="filing_8k",
                    details_json={
                        "form": filing["form"],
                        "accession_number": filing["accessionNumber"],
                        "source": "edgar",
                    },
                )
            )

        if events:
            yield events

    # ── HTTP helper ──────────────────────────────────────────────────────────

    async def _get_json(self, url: str) -> dict[str, Any]:
        """GET a JSON endpoint with retry, rate limiting, and User-Agent.

        Args:
            url: Full URL to fetch.

        Returns:
            Parsed JSON as a dict.

        Raises:
            EDGARFetchError: After all retries exhausted.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    if self._client is not None:
                        resp = await self._client.get(
                            url,
                            headers=self._headers,
                            timeout=_REQUEST_TIMEOUT,
                        )
                    else:
                        async with httpx.AsyncClient(
                            follow_redirects=True,
                        ) as client:
                            resp = await client.get(
                                url,
                                headers=self._headers,
                                timeout=_REQUEST_TIMEOUT,
                            )
                    await asyncio.sleep(0.1)

                if resp.status_code == 404:
                    msg = f"EDGAR 404: {url}"
                    raise EDGARFetchError(msg)
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
            except EDGARFetchError:
                raise
            except Exception as exc:
                logger.warning(
                    "edgar_fetch_retry",
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise EDGARFetchError(f"Failed to fetch {url}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))

        msg = f"Unreachable for {url}"
        raise EDGARFetchError(msg)
