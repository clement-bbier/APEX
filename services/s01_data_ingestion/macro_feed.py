"""Macro data feed for the APEX Trading System.

Polls external HTTP APIs for macroeconomic indicators used in regime detection:

* **VIX**          - CBOE Volatility Index via FRED
* **DXY**          - US Dollar Index via Yahoo Finance
* **Yield Spread** - 10Y minus 2Y US Treasury yield via FRED

All fetches are performed asynchronously with :mod:`aiohttp` at a configurable
polling interval (default 60 seconds).
"""

from __future__ import annotations

import asyncio

import aiohttp

from core.logger import get_logger

logger = get_logger("s01_data_ingestion.macro_feed")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_YAHOO_DXY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=2d"
_POLL_INTERVAL_SECONDS: int = 60
_HTTP_TIMEOUT_SECONDS: int = 15


class MacroFeed:
    """Polls FRED and Yahoo Finance for key macroeconomic indicators.

    Latest values are exposed via :meth:`get_vix`, :meth:`get_dxy`, and
    :meth:`get_yield_spread`.  A background polling loop keeps the cache
    fresh; consumers read the cached value directly without waiting.

    Args:
        fred_api_key: API key for the Federal Reserve FRED data service.
    """

    def __init__(self, fred_api_key: str) -> None:
        """Initialise the macro feed.

        Args:
            fred_api_key: FRED API key used for all FRED requests.
        """
        self._fred_api_key = fred_api_key
        self._running = False
        self._poll_task: asyncio.Task | None = None

        # Cached latest values (None until first successful fetch).
        self._vix: float | None = None
        self._dxy: float | None = None
        self._yield_spread: float | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background polling loop.

        Returns immediately; polling runs in a background task.
        """
        self._running = True
        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info(
            "MacroFeed started",
            poll_interval_seconds=_POLL_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("MacroFeed stopped")

    # ── Public data accessors ─────────────────────────────────────────────────

    async def get_vix(self) -> float | None:
        """Fetch (or return cached) latest VIX value from FRED.

        Endpoint: ``VIXCLS`` series, most recent observation.

        Returns:
            Latest VIX closing value, or ``None`` on error.
        """
        value = await self._fetch_fred_latest("VIXCLS")
        if value is not None:
            self._vix = value
        return self._vix

    async def get_dxy(self) -> float | None:
        """Fetch (or return cached) latest US Dollar Index from Yahoo Finance.

        Returns:
            Latest DXY close price, or ``None`` on error.
        """
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    _YAHOO_DXY_URL,
                    timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
                    headers={"User-Agent": "apex-trading/1.0"},
                ) as resp:
                    resp.raise_for_status()
                    payload: dict = await resp.json(content_type=None)
                    result = (
                        payload.get("chart", {})
                        .get("result", [{}])[0]
                        .get("meta", {})
                        .get("regularMarketPrice")
                    )
                    if result is not None:
                        self._dxy = float(result)
                        logger.debug("DXY fetched", value=self._dxy)
                    return self._dxy
            except Exception as exc:
                logger.warning("DXY fetch failed", error=str(exc))
                return self._dxy

    async def get_yield_spread(self) -> float | None:
        """Fetch (or return cached) 10Y-2Y US Treasury yield spread from FRED.

        Fetches ``DGS10`` and ``DGS2`` series and returns their difference.

        Returns:
            10Y minus 2Y yield in percentage points, or ``None`` on error.
        """
        dgs10, dgs2 = await asyncio.gather(
            self._fetch_fred_latest("DGS10"),
            self._fetch_fred_latest("DGS2"),
            return_exceptions=True,
        )
        if isinstance(dgs10, float) and isinstance(dgs2, float):
            self._yield_spread = dgs10 - dgs2
            logger.debug(
                "Yield spread computed",
                dgs10=dgs10,
                dgs2=dgs2,
                spread=self._yield_spread,
            )
        return self._yield_spread

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _polling_loop(self) -> None:
        """Continuously refresh all macro indicators until stopped."""
        while self._running:
            try:
                await asyncio.gather(
                    self.get_vix(),
                    self.get_dxy(),
                    self.get_yield_spread(),
                    return_exceptions=True,
                )
                logger.debug(
                    "Macro poll complete",
                    vix=self._vix,
                    dxy=self._dxy,
                    yield_spread=self._yield_spread,
                )
            except Exception as exc:
                logger.error("Macro polling loop error", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _fetch_fred_latest(self, series_id: str) -> float | None:
        """Fetch the most recent observation for a FRED series.

        Args:
            series_id: FRED series identifier, e.g. ``"VIXCLS"`` or ``"DGS10"``.

        Returns:
            The latest non-null float observation value, or ``None`` on error.
        """
        url = (
            f"{_FRED_BASE}"
            f"?series_id={series_id}"
            f"&api_key={self._fred_api_key}"
            f"&file_type=json"
            f"&limit=1"
            f"&sort_order=desc"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
                ) as resp:
                    resp.raise_for_status()
                    payload: dict = await resp.json(content_type=None)
                    observations: list[dict] = payload.get("observations", [])
                    if not observations:
                        logger.warning("FRED returned no observations", series=series_id)
                        return None
                    raw_value: str = observations[0].get("value", ".")
                    if raw_value == ".":
                        # FRED uses "." to represent missing data.
                        logger.debug("FRED value is missing", series=series_id)
                        return None
                    value = float(raw_value)
                    logger.debug("FRED value fetched", series=series_id, value=value)
                    return value
            except Exception as exc:
                logger.warning("FRED fetch failed", series=series_id, error=str(exc))
                return None
