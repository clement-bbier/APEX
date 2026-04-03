"""Sector rotation analysis for APEX Trading System."""

from __future__ import annotations

import aiohttp


class SectorRotation:
    """Fetches sector ETF performance and classifies risk-on/off market environment."""

    SECTOR_ETFS: list[str] = [
        "XLK",
        "XLE",
        "XLF",
        "XLV",
        "XLU",
        "XLI",
        "XLB",
        "XLY",
        "XLP",
        "XLRE",
        "XLC",
    ]

    _YAHOO_QUOTE_URL = (
        "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    )

    async def fetch_performance(self) -> dict[str, float]:
        """Fetch the 1-day percentage change for each sector ETF from Yahoo Finance.

        Returns:
            Dict mapping ETF ticker to daily % change (e.g. 0.012 for +1.2%).
            Missing tickers are omitted from the result.
        """
        performance: dict[str, float] = {}

        async with aiohttp.ClientSession() as session:
            for symbol in self.SECTOR_ETFS:
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
                    if len(closes) >= 2 and closes[-2] and closes[-2] != 0:
                        pct = (closes[-1] - closes[-2]) / closes[-2]
                        performance[symbol] = float(pct)
                except Exception:
                    pass

        return performance

    def risk_on_off(self, performance: dict[str, float]) -> str:
        """Classify the market environment as risk-on, risk-off, or neutral.

        Compares the average performance of defensive sectors (XLU, XLP, XLV)
        against growth sectors (XLK, XLY, XLC).

        Args:
            performance: Dict of ETF ticker → daily % change.

        Returns:
            "risk_on" if growth outperforms defensive by > 0.5%.
            "risk_off" if defensive outperforms growth by > 0.5%.
            "neutral" otherwise.
        """
        defensive = [performance[s] for s in ("XLU", "XLP", "XLV") if s in performance]
        growth = [performance[s] for s in ("XLK", "XLY", "XLC") if s in performance]

        if not defensive or not growth:
            return "neutral"

        avg_defensive = sum(defensive) / len(defensive)
        avg_growth = sum(growth) / len(growth)
        diff = avg_growth - avg_defensive

        if diff > 0.005:
            return "risk_on"
        if diff < -0.005:
            return "risk_off"
        return "neutral"

    def sector_strength_matrix(self, performance: dict[str, float]) -> list[dict]:
        """Build a ranked sector strength matrix.

        Args:
            performance: Dict of ETF ticker → daily % change.

        Returns:
            List of dicts sorted by descending return, each with keys
            "sector", "return_pct", and "rank".
        """
        sorted_sectors = sorted(performance.items(), key=lambda x: x[1], reverse=True)
        return [
            {"sector": sector, "return_pct": ret, "rank": rank}
            for rank, (sector, ret) in enumerate(sorted_sectors, start=1)
        ]
