"""ECB (European Central Bank) Statistical Data Warehouse connector.

Downloads macro-economic time series from the ECB SDMX REST API
(``data-api.ecb.europa.eu``). Parses the SDMX-JSON format (``jsondata``).

References:
    ECB SDW docs — https://data.ecb.europa.eu/help/api/overview
    SDMX JSON format — https://sdmx.org/?page_id=5008

SDMX JSON structure (simplified)::

    {
      "dataSets": [{
        "series": {
          "0:0:0:0:0": {              # dimension key
            "observations": {
              "0": [1.0842],           # obs index → [value, ...]
              "1": [1.0850],
              ...
            }
          }
        }
      }],
      "structure": {
        "dimensions": {
          "observation": [{
            "id": "TIME_PERIOD",
            "values": [
              {"id": "2024-01-02"},   # index 0
              {"id": "2024-01-03"},   # index 1
              ...
            ]
          }]
        }
      }
    }

The observation indices in ``series["0:0:0:0:0"].observations`` map to
the ``values`` list in ``structure.dimensions.observation[0]`` to get
the actual dates.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog

from core.models.data import MacroPoint, MacroSeriesMeta
from services.s01_data_ingestion.connectors.macro_base import MacroConnector

logger = structlog.get_logger(__name__)

_ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
_BATCH_SIZE = 1000
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class ECBFetchError(Exception):
    """Raised when ECB API fetch fails after retries."""


class ECBConnector(MacroConnector):
    """Downloads macro time series from the ECB SDMX REST API.

    Uses ``httpx.AsyncClient`` with ``format=jsondata`` for JSON output.
    Rate-limited via ``asyncio.Semaphore(5)`` + 0.5 s sleep between calls.
    """

    def __init__(self, concurrency: int = 5) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def connector_name(self) -> str:
        """Return connector identifier."""
        return "ecb_sdw"

    async def fetch_series(
        self,
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[MacroPoint]]:
        """Yield batches of macro data points from ECB.

        Args:
            series_id: ECB dataflow/key string, e.g. ``EXR/D.USD.EUR.SP00.A``.
                       The part before ``/`` is the dataflow, the rest is the key.
            start: Inclusive start datetime (UTC).
            end: Exclusive end datetime (UTC).

        Yields:
            Lists of up to 1000 :class:`MacroPoint` per batch.
        """
        flow, key = self._parse_series_id(series_id)
        url = f"{_ECB_BASE}/{flow}/{key}"
        params: dict[str, str] = {
            "format": "jsondata",
            "startPeriod": start.strftime("%Y-%m-%d"),
            "endPeriod": end.strftime("%Y-%m-%d"),
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            data = await self._fetch_json(client, url, params)

        points = self._parse_sdmx_json(data, series_id, start, end)

        # Yield in batches
        for i in range(0, len(points), _BATCH_SIZE):
            yield points[i : i + _BATCH_SIZE]

    async def fetch_metadata(self, series_id: str) -> MacroSeriesMeta:
        """Retrieve ECB series metadata.

        Args:
            series_id: ECB dataflow/key string.

        Returns:
            A :class:`MacroSeriesMeta` populated from the SDMX structure.
        """
        flow, key = self._parse_series_id(series_id)
        url = f"{_ECB_BASE}/{flow}/{key}"
        params: dict[str, str] = {
            "format": "jsondata",
            "lastNObservations": "1",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            data = await self._fetch_json(client, url, params)

        # Extract name from structure
        name = series_id
        try:
            structure_raw: object = data["structure"]
            if isinstance(structure_raw, dict):
                dims_raw: object = structure_raw.get("dimensions", {})
                if isinstance(dims_raw, dict):
                    series_dims: object = dims_raw.get("series", [])
                    if isinstance(series_dims, list) and series_dims:
                        first_dim = series_dims[0]
                        if isinstance(first_dim, dict) and first_dim.get("values"):
                            vals = first_dim["values"]
                            if isinstance(vals, list) and vals:
                                v0 = vals[0]
                                if isinstance(v0, dict):
                                    name = str(v0.get("name", series_id))
        except (KeyError, IndexError, TypeError):
            pass

        # Extract frequency from key
        key_parts = key.split(".")
        freq = key_parts[0] if key_parts else None
        freq_map: dict[str, str] = {
            "D": "daily",
            "M": "monthly",
            "Q": "quarterly",
            "A": "annual",
        }

        return MacroSeriesMeta(
            series_id=series_id,
            source="ECB",
            name=str(name),
            frequency=freq_map.get(freq or "", freq),
            unit=None,
            description=f"ECB {flow} series: {key}",
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_series_id(series_id: str) -> tuple[str, str]:
        """Split ``flow/key`` into (flow, key).

        Raises:
            ECBFetchError: If the series_id format is invalid.
        """
        parts = series_id.split("/", maxsplit=1)
        if len(parts) != 2:
            msg = (
                f"Invalid ECB series_id '{series_id}': "
                "expected format 'DATAFLOW/KEY' (e.g. 'EXR/D.USD.EUR.SP00.A')"
            )
            raise ECBFetchError(msg)
        return parts[0], parts[1]

    async def _fetch_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> dict[str, object]:
        """Fetch JSON from ECB with retry and backoff.

        Returns:
            Parsed JSON response as a dict.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    resp = await client.get(url, params=params)
                    await asyncio.sleep(0.5)
                if resp.status_code == 404:
                    raise ECBFetchError(f"series not found: {url}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "ecb_retry",
                        url=url,
                        status=resp.status_code,
                        wait=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                result: dict[str, object] = resp.json()
                return result
            except ECBFetchError:
                raise
            except httpx.HTTPStatusError:
                raise
            except Exception as exc:
                logger.warning(
                    "ecb_fetch_error",
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == _MAX_RETRIES - 1:
                    raise ECBFetchError(f"failed to fetch {url}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        raise ECBFetchError(f"max retries exceeded: {url}")

    @staticmethod
    def _parse_sdmx_json(
        data: dict[str, object],
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> list[MacroPoint]:
        """Parse ECB SDMX-JSON response into MacroPoint list.

        See module docstring for the JSON structure explanation.
        """
        points: list[MacroPoint] = []

        try:
            data_sets: list[object] = data["dataSets"]  # type: ignore[assignment]
            if not data_sets:
                return points
            first_ds: dict[str, object] = data_sets[0]  # type: ignore[assignment]
            all_series: dict[str, object] = first_ds["series"]  # type: ignore[assignment]

            # Get time dimension values
            structure: dict[str, object] = data["structure"]  # type: ignore[assignment]
            dims: dict[str, object] = structure["dimensions"]  # type: ignore[assignment]
            obs_dims: list[object] = dims["observation"]  # type: ignore[assignment]
            time_dim: dict[str, object] = obs_dims[0]  # type: ignore[assignment]
            time_values: list[dict[str, str]] = time_dim["values"]  # type: ignore[assignment]
        except (KeyError, IndexError, TypeError) as exc:
            raise ECBFetchError(f"unexpected SDMX-JSON structure for {series_id}: {exc}") from exc

        for _series_key, series_data in all_series.items():
            if not isinstance(series_data, dict):
                continue
            obs_raw: object = series_data["observations"]
            observations: dict[str, list[float | None]] = obs_raw  # type: ignore[assignment]
            for obs_idx_str, obs_values in observations.items():
                obs_idx = int(obs_idx_str)
                if obs_idx >= len(time_values):
                    continue
                value = obs_values[0] if obs_values else None
                if value is None:
                    continue

                date_str = time_values[obs_idx]["id"]
                try:
                    dt = datetime.fromisoformat(date_str)
                except ValueError:
                    # Handle partial dates like "2024-01" or "2024"
                    if len(date_str) == 7:
                        dt = datetime.fromisoformat(f"{date_str}-01")
                    elif len(date_str) == 4:
                        dt = datetime.fromisoformat(f"{date_str}-01-01")
                    else:
                        logger.warning("ecb_unparseable_date", date=date_str)
                        continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)

                # Filter to [start, end)
                if dt < start or dt >= end:
                    continue

                points.append(
                    MacroPoint(
                        series_id=series_id,
                        timestamp=dt,
                        value=float(value),
                    )
                )

        # Sort by timestamp
        points.sort(key=lambda p: p.timestamp)
        return points
