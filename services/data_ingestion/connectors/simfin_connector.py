"""SimFin fundamentals connector.

Downloads pre-computed financial statements and ratios from the SimFin
REST API v3. Requires a free or paid API key.

References:
    SimFin API docs — https://simfin.com/api/v3/documentation
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

_BASE_URL = "https://backend.simfin.com/api/v3"
_REQUEST_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BATCH_SIZE = 500

# SimFin statement field → metric_name mapping
_SIMFIN_FIELD_MAP: dict[str, str] = {
    "Revenue": "revenue",
    "Net Income": "net_income",
    "Total Assets": "total_assets",
    "Total Liabilities": "total_liabilities",
    "Total Equity": "stockholders_equity",
    "Earnings Per Share, Basic": "eps_basic",
    "Earnings Per Share, Diluted": "eps_diluted",
    "Operating Income (Loss)": "operating_income",
    "Gross Profit": "gross_profit",
    "Cash, Cash Equivalents & Short Term Investments": "cash_and_equivalents",
    "Long Term Debt": "long_term_debt",
    "Shares (Basic)": "shares_outstanding",
}

# SimFin ratio field → metric_name
_SIMFIN_RATIO_MAP: dict[str, str] = {
    "Return on Equity": "roe",
    "Return on Assets": "roa",
    "Gross Profit Margin": "gross_margin",
    "Operating Margin": "operating_margin",
    "Net Profit Margin": "net_margin",
    "Current Ratio": "current_ratio",
    "Debt / Equity": "debt_to_equity",
    "Price / Earnings Ratio": "pe_ratio",
    "Price / Book Value": "pb_ratio",
    "Dividend Yield": "dividend_yield",
}

# SimFin period → our period_type
_PERIOD_MAP: dict[str, str] = {
    "FY": "annual",
    "Q1": "quarterly",
    "Q2": "quarterly",
    "Q3": "quarterly",
    "Q4": "quarterly",
    "H1": "semi_annual",
    "H2": "semi_annual",
}


class SimFinFetchError(Exception):
    """Raised when SimFin API fetch fails after retries."""


class SimFinConnector(FundamentalsConnector):
    """Downloads fundamentals from the SimFin REST API v3.

    Uses ``httpx.AsyncClient`` with ``X-API-KEY`` header authentication.
    Rate-limited via ``asyncio.Semaphore(5)`` + 0.2 s sleep between calls.
    Retry: exponential backoff (1 s, 2 s, 4 s), max 3 attempts.
    """

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        concurrency: int = 5,
    ) -> None:
        if api_key is None:
            api_key = get_settings().simfin_api_key.get_secret_value()
        if not api_key:
            msg = "SIMFIN_API_KEY is required but empty"
            raise SimFinFetchError(msg)
        self._api_key = api_key
        self._headers = {"X-API-KEY": self._api_key, "Accept": "application/json"}
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "simfin"

    # ── Financials ───────────────────────────────────────────────────────────

    async def fetch_financials(
        self,
        ticker: str,
        statement_type: str = "PL",
        period: str = "fy",
    ) -> list[dict[str, Any]]:
        """Fetch financial statements from SimFin.

        Args:
            ticker: Equity ticker (e.g. ``AAPL``).
            statement_type: ``PL`` (profit & loss), ``BS`` (balance sheet),
                or ``CF`` (cash flow).
            period: ``fy`` (full year), ``q1``-``q4``, ``h1``-``h2``.

        Returns:
            Raw SimFin response as list of statement dicts.
        """
        url = f"{_BASE_URL}/companies/{ticker}/statements/{statement_type}"
        params = {"period": period}
        return await self._get_json_list(url, params)

    async def fetch_ratios(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch pre-computed financial ratios for a ticker.

        Args:
            ticker: Equity ticker.

        Returns:
            Raw SimFin ratios response.
        """
        url = f"{_BASE_URL}/companies/{ticker}/ratios"
        return await self._get_json_list(url)

    # ── FundamentalsConnector interface ───────────────────────────────────────

    async def fetch_fundamentals(
        self,
        ticker: str,
        filing_types: list[str],
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[FundamentalPoint]]:
        """Yield batches of fundamental data from SimFin.

        Downloads P&L, balance sheet, cash flow statements and ratios,
        then maps to :class:`FundamentalPoint`.

        Args:
            ticker: Equity ticker.
            filing_types: Filing types (mapped: ``10-K`` → ``fy``, ``10-Q`` → quarterly).
            start: Inclusive start datetime.
            end: Exclusive end datetime.

        Yields:
            Lists of :class:`FundamentalPoint` up to 500 per batch.
        """
        asset_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"simfin.{ticker.upper()}")
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        points: list[FundamentalPoint] = []

        # Determine periods to fetch based on filing_types
        periods: list[str] = []
        filing_upper = {ft.upper() for ft in filing_types}
        if "10-K" in filing_upper:
            periods.append("fy")
        if "10-Q" in filing_upper:
            periods.extend(["q1", "q2", "q3", "q4"])

        if not periods:
            periods = ["fy"]

        # Fetch statements (P&L, BS, CF) for each period
        for period in periods:
            for stmt_type in ("PL", "BS", "CF"):
                try:
                    statements = await self.fetch_financials(ticker, stmt_type, period)
                    points.extend(
                        self._parse_statements(statements, asset_id, start_date, end_date)
                    )
                except SimFinFetchError:
                    logger.warning(
                        "simfin_statement_unavailable",
                        ticker=ticker,
                        statement=stmt_type,
                        period=period,
                    )

        # Fetch ratios
        try:
            ratios = await self.fetch_ratios(ticker)
            points.extend(self._parse_ratios(ratios, asset_id, start_date, end_date))
        except SimFinFetchError:
            logger.warning("simfin_ratios_unavailable", ticker=ticker)

        for i in range(0, len(points), _BATCH_SIZE):
            yield points[i : i + _BATCH_SIZE]

    async def fetch_corporate_events(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[CorporateEvent]]:
        """Not implemented for SimFin — use EDGAR for corporate events.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("SimFin does not provide corporate events")
        yield  # pragma: no cover

    # ── Parsing helpers ──────────────────────────────────────────────────────

    def _parse_statements(
        self,
        statements: list[dict[str, Any]],
        asset_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[FundamentalPoint]:
        """Convert SimFin statement response to FundamentalPoint records."""
        points: list[FundamentalPoint] = []

        for stmt in statements:
            report_date_str = str(stmt.get("Report Date", stmt.get("reportDate", "")))
            period_str = str(stmt.get("Period", stmt.get("period", "FY")))

            if not report_date_str:
                continue

            try:
                report_date = date.fromisoformat(report_date_str)
            except ValueError:
                continue

            if report_date < start_date or report_date >= end_date:
                continue

            period_type = _PERIOD_MAP.get(period_str.upper(), "annual")

            for simfin_field, metric_name in _SIMFIN_FIELD_MAP.items():
                val = stmt.get(simfin_field)
                if val is None:
                    continue
                points.append(
                    FundamentalPoint(
                        asset_id=asset_id,
                        report_date=report_date,
                        period_type=period_type,
                        metric_name=metric_name,
                        value=float(val) if val is not None else None,
                        currency="USD",
                    )
                )

        return points

    def _parse_ratios(
        self,
        ratios: list[dict[str, Any]],
        asset_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[FundamentalPoint]:
        """Convert SimFin ratios response to FundamentalPoint records."""
        points: list[FundamentalPoint] = []

        for entry in ratios:
            report_date_str = str(entry.get("Report Date", entry.get("reportDate", "")))
            period_str = str(entry.get("Period", entry.get("period", "FY")))

            if not report_date_str:
                continue

            try:
                report_date = date.fromisoformat(report_date_str)
            except ValueError:
                continue

            if report_date < start_date or report_date >= end_date:
                continue

            period_type = _PERIOD_MAP.get(period_str.upper(), "annual")

            for simfin_field, metric_name in _SIMFIN_RATIO_MAP.items():
                val = entry.get(simfin_field)
                if val is None:
                    continue
                points.append(
                    FundamentalPoint(
                        asset_id=asset_id,
                        report_date=report_date,
                        period_type=period_type,
                        metric_name=metric_name,
                        value=float(val),
                        currency=None,
                    )
                )

        return points

    # ── HTTP helper ──────────────────────────────────────────────────────────

    async def _get_json_list(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """GET a JSON endpoint with retry and rate limiting.

        Args:
            url: Full URL to fetch.
            params: Optional query parameters.

        Returns:
            Parsed JSON as a list of dicts.

        Raises:
            SimFinFetchError: After all retries exhausted.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    if self._client is not None:
                        resp = await self._client.get(
                            url,
                            headers=self._headers,
                            params=params,
                            timeout=_REQUEST_TIMEOUT,
                        )
                    else:
                        async with httpx.AsyncClient(
                            follow_redirects=True,
                        ) as client:
                            resp = await client.get(
                                url,
                                headers=self._headers,
                                params=params,
                                timeout=_REQUEST_TIMEOUT,
                            )
                    await asyncio.sleep(0.2)

                if resp.status_code == 401:
                    msg = "SimFin API key is invalid or expired"
                    raise SimFinFetchError(msg)
                if resp.status_code == 404:
                    msg = f"SimFin 404: {url}"
                    raise SimFinFetchError(msg)
                resp.raise_for_status()
                data: Any = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return [data]
                return []
            except SimFinFetchError:
                raise
            except Exception as exc:
                logger.warning(
                    "simfin_fetch_retry",
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise SimFinFetchError(f"Failed to fetch {url}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))

        msg = f"Unreachable for {url}"
        raise SimFinFetchError(msg)
