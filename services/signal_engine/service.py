"""Signal Engine Service (S02) for the APEX Trading System.

Subscribes to all normalized tick topics emitted by the data-ingestion
service, runs microstructure and technical analysis on each tick, and
publishes :class:`~core.models.signal.Signal` objects whenever one or more
trigger conditions fire.

Published topic: ``signal.technical.{SYMBOL}``
Redis cache key:  ``signal:{SYMBOL}``
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.base_service import BaseService
from core.logger import get_logger
from core.models.signal import Signal
from core.models.tick import NormalizedTick
from services.signal_engine.microstructure import MicrostructureAnalyzer
from services.signal_engine.mtf_aligner import MTFAligner
from services.signal_engine.pipeline import SignalPipeline
from services.signal_engine.signal_scorer import SignalScorer
from services.signal_engine.technical import TechnicalAnalyzer
from services.signal_engine.vpin import VPINCalculator

logger = get_logger("signal_engine.service")

# ZMQ topic prefix for all normalized ticks.
_TICK_TOPICS: list[str] = ["tick."]


class SignalEngineService(BaseService):
    """Generates technical trading signals from the live tick stream.

    For each incoming :class:`~core.models.tick.NormalizedTick` the service
    delegates to :class:`~.pipeline.SignalPipeline` which:

    1. Updates per-symbol analyzers (microstructure, technical, VPIN).
    2. Evaluates trigger conditions and builds scorer components.
    3. If a net directional consensus exists, builds a fully-populated
       :class:`~core.models.signal.Signal` with ATR-based price levels.
    4. Returns the signal (or ``None`` if no confluence).

    The service then publishes the signal on ZMQ and caches it in Redis.
    """

    service_id: str = "signal_engine"

    def __init__(self) -> None:
        """Initialize analyzers (sockets are wired in :meth:`run`)."""
        super().__init__(self.service_id)

        # Per-symbol stateful analyzers.
        self._micro: dict[str, MicrostructureAnalyzer] = {}
        self._tech: dict[str, TechnicalAnalyzer] = {}

        # Shared multi-timeframe aligner (all symbols share one instance).
        self._mtf = MTFAligner()

        # Confluence scorer - aggregates all signal components.
        self._scorer = SignalScorer(min_components=2, min_strength=0.20)

        # Per-symbol VPIN calculators and ADV refresh counters.
        self._vpin: dict[str, VPINCalculator] = {}
        self._adv_counter: dict[str, int] = {}

        # Pipeline encapsulates the full tick-to-signal transformation.
        self._pipeline = SignalPipeline(
            micro_store=self._micro,
            tech_store=self._tech,
            vpin_store=self._vpin,
            adv_counter=self._adv_counter,
            mtf=self._mtf,
            scorer=self._scorer,
            state=self.state,
        )

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Parse an incoming tick and run the signal-generation pipeline.

        Args:
            topic: ZMQ topic string, e.g. ``'tick.crypto.BTCUSDT'``.
            data: JSON-decoded message payload.
        """
        try:
            tick = NormalizedTick.model_validate(data)
            await self._process_tick(tick)
        except Exception as exc:
            self.logger.error(
                "Error processing tick",
                topic=topic,
                error=str(exc),
                exc_info=exc,
            )

    async def run(self) -> None:
        """Subscribe to the tick bus and dispatch to :meth:`on_message`.

        Runs until the service is stopped (CancelledError propagated
        through the ZMQ receive loop).
        """
        self.logger.info(
            "SignalEngineService starting",
            topics=_TICK_TOPICS,
        )
        try:
            await self.bus.subscribe(_TICK_TOPICS, self.on_message)
        except asyncio.CancelledError:
            self.logger.info("SignalEngineService subscribe loop cancelled")
            raise

    # ── Signal pipeline ───────────────────────────────────────────────────────

    async def _process_tick(self, tick: NormalizedTick) -> None:
        """Run the full analysis pipeline for one tick.

        Args:
            tick: Validated normalized tick.
        """
        signal = await self._pipeline.run(tick)
        if signal is not None:
            await self._publish_signal(signal)

    async def _publish_signal(self, signal: Signal) -> None:
        """Publish a signal on ZMQ and cache in Redis.

        Args:
            signal: Validated Signal object.
        """
        signal_dict = signal.model_dump()
        pub_topic = f"signal.technical.{signal.symbol}"

        await asyncio.gather(
            self.bus.publish(pub_topic, signal_dict),
            self.state.set(f"signal:{signal.symbol}", signal_dict),
        )

        self.logger.info(
            "Signal published",
            symbol=signal.symbol,
            direction=signal.direction.value,
            triggers=signal.triggers,
            confidence=signal.confidence,
            entry=str(signal.entry),
        )


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
