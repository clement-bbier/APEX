"""Geopolitical and energy market analyzer for APEX Trading System."""

from __future__ import annotations

import aiohttp


class GeopoliticalAnalyzer:
    """Analyzes energy prices and their geopolitical market impact."""

    _YAHOO_QUOTE_URL = (
        "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    )

    async def get_energy_prices(self) -> dict[str, float | None]:
        """Fetch WTI and Brent crude oil prices from Yahoo Finance.

        Returns:
            Dict with keys "wti" (CL=F) and "brent" (BZ=F) as Optional floats.
        """
        result: dict[str, float | None] = {"wti": None, "brent": None}
        symbols = {"wti": "CL=F", "brent": "BZ=F"}

        async with aiohttp.ClientSession() as session:
            for key, symbol in symbols.items():
                try:
                    url = self._YAHOO_QUOTE_URL.format(symbol=symbol)
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        data = await resp.json()
                    closes = (
                        data.get("chart", {})
                        .get("result", [{}])[0]
                        .get("indicators", {})
                        .get("quote", [{}])[0]
                        .get("close", [])
                    )
                    if closes:
                        result[key] = float(closes[-1])
                except Exception:
                    pass

        return result

    def energy_impact_score(self, wti_change_pct: float, brent_change_pct: float) -> float:
        """Compute a normalised energy impact score from price changes.

        Impact score = average change × 2, capped to [0, 1].

        Args:
            wti_change_pct: WTI crude % change (e.g. 0.03 for 3%).
            brent_change_pct: Brent crude % change.

        Returns:
            Impact score in [0.0, 1.0].
        """
        avg_change = (abs(wti_change_pct) + abs(brent_change_pct)) / 2.0
        score = avg_change * 2.0
        return min(max(score, 0.0), 1.0)

    def affected_sectors(self, energy_impact: float) -> list[str]:
        """Return a list of affected sector tickers based on energy impact score.

        Args:
            energy_impact: Impact score from energy_impact_score().

        Returns:
            List of sector ETF tickers most affected by the energy move.
        """
        sectors: list[str] = []
        if energy_impact > 0.02:
            sectors.extend(["XLE", "XOM"])
        if energy_impact > 0.05:
            sectors.extend(["XLB", "airlines_negative"])
        return sectors
