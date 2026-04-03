"""S08 Macro Intelligence service for APEX Trading System."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core.base_service import BaseService
from services.s08_macro_intelligence.cb_watcher import CBWatcher
from services.s08_macro_intelligence.geopolitical import GeopoliticalAnalyzer
from services.s08_macro_intelligence.sector_rotation import SectorRotation


class MacroIntelligenceService(BaseService):
    """Service that monitors macro economic signals and publishes catalyst events."""

    service_id = "s08_macro_intelligence"

    def __init__(self) -> None:
        """Initialise macro sub-modules."""
        super().__init__()
        self._cb_watcher = CBWatcher()
        self._geo = GeopoliticalAnalyzer()
        self._sector_rotation = SectorRotation()

    async def on_message(self, topic: str, data: Any) -> None:
        """No-op message handler (service uses its own polling loops).

        Args:
            topic: ZMQ topic string.
            data: Deserialized message payload.
        """

    async def run(self) -> None:
        """Run 15-minute sector loop and 60-minute macro loop concurrently."""
        await asyncio.gather(
            self._sector_loop(),
            self._macro_loop(),
        )

    async def _sector_loop(self) -> None:
        """Every 15 minutes: fetch sector ETF performance and store in Redis."""
        while True:
            try:
                performance = await self._sector_rotation.fetch_performance()
                await self.state.set("macro:sectors", json.dumps(performance))

                regime = self._sector_rotation.risk_on_off(performance)
                await self.state.set("macro:risk_regime", regime)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("sector_loop error: %s", exc)
            await asyncio.sleep(900)

    async def _macro_loop(self) -> None:
        """Every 60 minutes: fetch energy prices, CB RSS, publish catalyst events."""
        while True:
            try:
                await self._run_macro_analytics()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("macro_loop error: %s", exc)
            await asyncio.sleep(3600)

    async def _run_macro_analytics(self) -> None:
        """Fetch energy and CB data, store in Redis, and publish ZMQ events."""
        energy = await self._geo.get_energy_prices()
        await self.state.set("macro:energy", json.dumps(energy))

        rss_items = await self._cb_watcher.fetch_fed_rss()
        if rss_items:
            latest = rss_items[0]
            statement = await self._cb_watcher.get_latest_statement()
            if statement:
                surprise = await self._cb_watcher.detect_surprise(statement)
                if surprise:
                    await self.publish(
                        f"macro.catalyst.{surprise}",
                        {"source": "fed", "title": latest.get("title", "")},
                    )

        wti = energy.get("wti")
        brent = energy.get("brent")
        if wti is not None and brent is not None:
            impact = self._geo.energy_impact_score(wti, brent)
            if impact > 0.02:
                await self.publish(
                    "macro.catalyst.energy",
                    {"wti": wti, "brent": brent, "impact": impact},
                )
