"""FRED releases connector — fetches US economic data release schedules.

Uses the ``fredapi`` SDK to retrieve release dates for major US economic
indicators (NFP, CPI, GDP, ISM, etc.) via the FRED releases endpoint.

References:
    Savor & Wilson (2013) RFS — "How Much Do Investors Care About
        Macroeconomic Risk?"
    Lucca & Moench (2015) JF — "The Pre-FOMC Announcement Drift"
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from fredapi import Fred

from core.config import get_settings
from core.models.data import EconomicEvent
from services.s01_data_ingestion.connectors.calendar_base import CalendarConnector

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0

# Priority US economic releases and their metadata.
# impact_score: 3=high (NFP, CPI, GDP, FOMC), 2=medium (retail, ISM, claims)
_PRIORITY_RELEASES: dict[str, dict[str, str | int]] = {
    "PAYEMS": {"event_type": "us_data_release_nfp", "impact_score": 3},
    "CPIAUCSL": {"event_type": "us_data_release_cpi", "impact_score": 3},
    "CPILFESL": {"event_type": "us_data_release_core_cpi", "impact_score": 3},
    "GDP": {"event_type": "us_data_release_gdp", "impact_score": 3},
    "RSAFS": {"event_type": "us_data_release_retail_sales", "impact_score": 2},
    "NAPM": {"event_type": "us_data_release_ism_pmi", "impact_score": 2},
    "ICSA": {"event_type": "us_data_release_jobless_claims", "impact_score": 2},
    "UMCSENT": {"event_type": "us_data_release_consumer_sentiment", "impact_score": 2},
}

# Typical release times (UTC) — most US data releases are at 12:30 or 14:00 UTC
_DEFAULT_RELEASE_HOUR = 12
_DEFAULT_RELEASE_MINUTE = 30

# Some releases have specific times
_RELEASE_TIMES: dict[str, tuple[int, int]] = {
    "PAYEMS": (12, 30),  # 08:30 ET
    "CPIAUCSL": (12, 30),  # 08:30 ET
    "CPILFESL": (12, 30),  # 08:30 ET
    "GDP": (12, 30),  # 08:30 ET
    "RSAFS": (12, 30),  # 08:30 ET
    "NAPM": (14, 0),  # 10:00 ET (ISM)
    "ICSA": (12, 30),  # 08:30 ET
    "UMCSENT": (14, 0),  # 10:00 ET
}


class FREDReleasesFetchError(Exception):
    """Raised when FRED releases fetch fails after retries."""


class FREDReleasesConnector(CalendarConnector):
    """Fetches US economic data release schedules from FRED.

    Uses ``fredapi.Fred`` (synchronous) wrapped in ``asyncio.to_thread``.
    Queries ``get_series_all_releases`` or the search endpoint to find
    release dates for each priority series.
    """

    def __init__(
        self,
        api_key: str | None = None,
        concurrency: int = 5,
    ) -> None:
        if api_key is None:
            api_key = get_settings().fred_api_key.get_secret_value()
        if not api_key:
            msg = "FRED_API_KEY is required but empty"
            raise FREDReleasesFetchError(msg)
        self._fred = Fred(api_key=api_key)
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "fred_releases"

    async def fetch_events(
        self,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[EconomicEvent]]:
        """Yield batches of US economic release events.

        Iterates over all priority series, fetching release dates for each.

        Args:
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`EconomicEvent` per series.
        """
        for series_id, meta in _PRIORITY_RELEASES.items():
            try:
                events = await self._fetch_release_dates(series_id, meta, start, end)
                if events:
                    yield events
            except FREDReleasesFetchError:
                logger.error(
                    "fred_releases_series_failed",
                    series_id=series_id,
                )
                # Continue with other series
            except Exception as exc:
                logger.error(
                    "fred_releases_series_error",
                    series_id=series_id,
                    error=str(exc),
                )

    async def _fetch_release_dates(
        self,
        series_id: str,
        meta: dict[str, str | int],
        start: datetime,
        end: datetime,
    ) -> list[EconomicEvent]:
        """Fetch release dates for a single series."""
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    # get_series_all_releases returns a DataFrame with
                    # 'date' and 'value' columns, indexed by realtime_start.
                    # We extract unique release dates from the realtime_start index.
                    releases_df = await asyncio.to_thread(
                        self._fred.get_series_all_releases,
                        series_id,
                    )
                    await asyncio.sleep(0.5)
                break
            except FREDReleasesFetchError:
                raise
            except Exception as exc:
                logger.warning(
                    "fred_releases_retry",
                    series_id=series_id,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise FREDReleasesFetchError(
                        f"failed to fetch releases for {series_id}: {exc}"
                    ) from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        else:
            raise FREDReleasesFetchError(f"unreachable for {series_id}")

        event_type = str(meta["event_type"])
        impact_score = int(meta["impact_score"])
        hour, minute = _RELEASE_TIMES.get(
            series_id, (_DEFAULT_RELEASE_HOUR, _DEFAULT_RELEASE_MINUTE)
        )

        # Extract unique release dates from the DataFrame index (realtime_start)
        events: list[EconomicEvent] = []
        seen_dates: set[str] = set()

        if releases_df is None or (hasattr(releases_df, "empty") and releases_df.empty):
            logger.warning("fred_releases_empty", series_id=series_id)
            return events

        for idx_val in releases_df.index:
            # The index may be a MultiIndex (realtime_start, date) or just date
            if hasattr(idx_val, "__iter__") and not isinstance(idx_val, str):
                # MultiIndex: first element is realtime_start (release date)
                release_date_raw = idx_val[0]
            else:
                release_date_raw = idx_val

            # Convert to string for dedup
            date_str = str(release_date_raw)[:10]
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)

            # Parse the release date
            try:
                if hasattr(release_date_raw, "to_pydatetime"):
                    dt = release_date_raw.to_pydatetime()
                else:
                    dt = datetime.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)

            # Set the typical release time
            release_time = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if not (start <= release_time < end):
                continue

            events.append(
                EconomicEvent(
                    event_type=event_type,
                    scheduled_time=release_time,
                    impact_score=impact_score,
                    source="fred_releases",
                )
            )

        logger.info(
            "fred_releases_parsed",
            series_id=series_id,
            event_type=event_type,
            count=len(events),
        )
        return events
