"""FRED (Federal Reserve Economic Data) macro connector.

Downloads macro-economic time series from the FRED API via the ``fredapi``
SDK. Wraps the synchronous SDK calls in ``asyncio.to_thread`` to keep the
event loop responsive.

References:
    FRED API docs — https://fred.stlouisfed.org/docs/api/fred/
    Cochrane (2005) — "Asset Pricing" (macro factor models)
    Lucca & Moench (2015) — "The Pre-FOMC Announcement Drift"
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from fredapi import Fred

from core.config import get_settings
from core.models.data import MacroPoint, MacroSeriesMeta
from services.s01_data_ingestion.connectors.macro_base import MacroConnector

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class FREDFetchError(Exception):
    """Raised when FRED API fetch fails after retries."""


class FREDConnector(MacroConnector):
    """Downloads macro time series from the FRED API.

    Uses ``fredapi.Fred`` (synchronous) wrapped in ``asyncio.to_thread``.
    Rate-limited via ``asyncio.Semaphore(10)`` + 0.5 s sleep between calls.
    Retry: exponential backoff (1 s, 2 s, 4 s), max 3 attempts.
    """

    def __init__(
        self,
        api_key: str | None = None,
        concurrency: int = 10,
    ) -> None:
        if api_key is None:
            api_key = get_settings().fred_api_key.get_secret_value()
        if not api_key:
            msg = "FRED_API_KEY is required but empty"
            raise FREDFetchError(msg)
        self._fred = Fred(api_key=api_key)
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "fred"

    async def fetch_series(
        self,
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[MacroPoint]]:
        """Yield batches of macro data points from FRED.

        Args:
            series_id: FRED series ID (e.g. ``FEDFUNDS``, ``DFF``, ``T10Y2Y``).
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`MacroPoint` per batch.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    series = await asyncio.to_thread(
                        self._fred.get_series,
                        series_id,
                        observation_start=start.strftime("%Y-%m-%d"),
                        observation_end=end.strftime("%Y-%m-%d"),
                    )
                    await asyncio.sleep(0.5)
                break
            except FREDFetchError:
                raise
            except Exception as exc:
                logger.warning(
                    "fred_fetch_retry",
                    series_id=series_id,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise FREDFetchError(f"failed to fetch {series_id}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        else:
            raise FREDFetchError(f"unreachable for {series_id}")

        # Convert pandas Series to MacroPoint batches
        batch: list[MacroPoint] = []
        for ts, value in series.items():
            # Skip NaN values (FRED uses NaN for missing observations)
            if value != value:
                continue
            # Convert pandas Timestamp to UTC datetime
            dt = ts.to_pydatetime()  # type: ignore[union-attr,unused-ignore]
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            batch.append(
                MacroPoint(
                    series_id=series_id,
                    timestamp=dt,
                    value=float(value),
                )
            )
            if len(batch) >= _BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch

    async def fetch_metadata(self, series_id: str) -> MacroSeriesMeta:
        """Retrieve FRED series metadata.

        Args:
            series_id: FRED series ID.

        Returns:
            A :class:`MacroSeriesMeta` populated from FRED series info.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    info = await asyncio.to_thread(self._fred.get_series_info, series_id)
                    await asyncio.sleep(0.5)
                break
            except Exception as exc:
                logger.warning(
                    "fred_metadata_retry",
                    series_id=series_id,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise FREDFetchError(
                        f"failed to fetch metadata for {series_id}: {exc}"
                    ) from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        else:
            raise FREDFetchError(f"unreachable metadata for {series_id}")

        return MacroSeriesMeta(
            series_id=series_id,
            source="FRED",
            name=str(info.get("title", series_id)),
            frequency=str(info.get("frequency_short", "")) or None,
            unit=str(info.get("units_short", "")) or None,
            description=str(info.get("notes", "")) or None,
        )
