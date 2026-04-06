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
import uuid
from decimal import Decimal
from typing import Any

from core.base_service import BaseService
from core.logger import get_logger
from core.models.signal import (
    Direction,
    MTFContext,
    Signal,
    SignalType,
    TechnicalFeatures,
)
from core.models.tick import NormalizedTick
from services.s02_signal_engine.microstructure import MicrostructureAnalyzer
from services.s02_signal_engine.mtf_aligner import MTFAligner
from services.s02_signal_engine.signal_scorer import SignalComponent, SignalScorer
from services.s02_signal_engine.technical import TechnicalAnalyzer
from services.s02_signal_engine.vpin import VPINCalculator

logger = get_logger("s02_signal_engine.service")

# ZMQ topic prefix for all normalized ticks.
_TICK_TOPICS: list[str] = ["tick."]

# OFI magnitude threshold for triggering an OFI signal.
_OFI_THRESHOLD: float = 0.3

# ATR multiples for stop-loss and take-profit levels.
_SL_ATR_MULT: Decimal = Decimal("1.5")
_TP1_ATR_MULT: Decimal = Decimal("2.0")
_TP2_ATR_MULT: Decimal = Decimal("3.0")

# Fallback stop-loss distance when ATR is unavailable (0.2% of entry price).
_ATR_FALLBACK_PCT: Decimal = Decimal("0.002")

# Minimum stop-loss floor when the computed stop-loss turns non-positive
# (e.g. entry near zero): expressed as a fraction of entry price.
_FALLBACK_SL_PCT: Decimal = Decimal("0.001")

# Number of triggers needed for full confidence (confidence = triggers / N).
_MAX_TRIGGERS_FOR_CONFIDENCE: float = 4.0

# How many ticks between ADV refreshes from Redis (≈5 min at 1 tick/s).
_ADV_REFRESH_EVERY: int = 300


class SignalEngineService(BaseService):
    """Generates technical trading signals from the live tick stream.

    For each incoming :class:`~core.models.tick.NormalizedTick` the service:

    1. Updates per-symbol :class:`~.microstructure.MicrostructureAnalyzer`
       and :class:`~.technical.TechnicalAnalyzer` instances.
    2. Evaluates four trigger conditions (OFI, RSI, Bollinger Band bounce,
       EMA cross) and categorises each as long or short.
    3. If a net directional consensus exists, builds a fully-populated
       :class:`~core.models.signal.Signal` with ATR-based price levels.
    4. Publishes the signal on ZMQ and caches it in Redis.
    """

    service_id: str = "s02_signal_engine"

    def __init__(self) -> None:
        """Initialize analyzers and ZMQ pub/sub sockets."""
        super().__init__(self.service_id)

        self.bus.init_publisher()
        self.bus.init_subscriber(_TICK_TOPICS)

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

        # Previous EMA values per symbol - needed for cross detection.
        self._prev_ema_8: dict[str, Decimal | None] = {}
        self._prev_ema_21: dict[str, Decimal | None] = {}

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
        symbol = tick.symbol

        # Lazy-initialize per-symbol analyzers.
        if symbol not in self._micro:
            self._micro[symbol] = MicrostructureAnalyzer(symbol)
        if symbol not in self._tech:
            self._tech[symbol] = TechnicalAnalyzer(symbol)
        if symbol not in self._vpin:
            self._vpin[symbol] = VPINCalculator(default_bucket_size=1000.0)
            self._adv_counter[symbol] = 0

        micro = self._micro[symbol]
        tech = self._tech[symbol]

        micro.update(tick)
        tech.update(tick)

        # ── VPIN: refresh ADV from S07 every N ticks, then update + gate ─────
        self._adv_counter[symbol] += 1
        if self._adv_counter[symbol] >= _ADV_REFRESH_EVERY:
            self._adv_counter[symbol] = 0
            try:
                adv_data = await self.state.get(f"analytics:adv:{symbol}")
                if isinstance(adv_data, dict):
                    adv_val = float(adv_data.get("adv_1d", 0) or 0)
                    if adv_val > 0:
                        self._vpin[symbol].update_adv(adv_val)
            except Exception as exc:
                self.logger.debug(
                    "ADV refresh failed, keeping default bucket_size",
                    symbol=symbol,
                    error=str(exc),
                )

        self._vpin[symbol].update(tick)
        vpin_metrics = self._vpin[symbol].compute()

        await self.state.set(
            f"vpin:{symbol}",
            {
                "vpin": vpin_metrics.vpin,
                "toxicity_level": vpin_metrics.toxicity_level,
                "size_multiplier": vpin_metrics.size_multiplier,
                "effective_bucket_size": vpin_metrics.effective_bucket_size,
                "adv_source": vpin_metrics.adv_source,
                "buy_volume_pct": vpin_metrics.buy_volume_pct,
            },
            ttl=60,
        )

        if vpin_metrics.toxicity_level == "extreme":
            self.logger.warning(
                "vpin_extreme_block", symbol=symbol, vpin=vpin_metrics.vpin
            )
            return  # Signal abandoned — flow too toxic

        # ── Compute indicators ────────────────────────────────────────────────
        ofi_val = micro.ofi()
        rsi_1m = tech.rsi(period=14, timeframe="1m")
        bb_upper, _bb_middle, bb_lower = tech.bollinger_bands(period=20, std=2.0, timeframe="5m")
        entry_price: Decimal = tick.price

        # EMA 5m (for cross detection state persistence)
        ema_8 = tech.ema(period=8, timeframe="5m")
        ema_21 = tech.ema(period=21, timeframe="5m")
        self._prev_ema_8[symbol] = ema_8
        self._prev_ema_21[symbol] = ema_21

        # EMA 1m and 15m (for MTF alignment scorer)
        ema_8_1m = tech.ema(period=8, timeframe="1m")
        ema_21_1m = tech.ema(period=21, timeframe="1m")
        ema_8_15m = tech.ema(period=8, timeframe="15m")
        ema_21_15m = tech.ema(period=21, timeframe="15m")
        vwap_val = tech.vwap()

        # ── Build scorer components ───────────────────────────────────────────
        # Microstructure: OFI normalised to [-1, +1]
        ofi_score = max(-1.0, min(1.0, ofi_val / max(abs(ofi_val), 1e-6))) if ofi_val != 0 else 0.0

        # Bollinger score
        if bb_upper is not None and bb_lower is not None and _bb_middle is not None:
            bb_score = tech.compute_bollinger_score(
                price=float(entry_price),
                upper=float(bb_upper),
                lower=float(bb_lower),
                middle=float(_bb_middle),
                bandwidth_pct=50.0,  # conservative default (no historical pct yet)
            )
        else:
            bb_score = 0.0

        # EMA MTF alignment score
        if (
            ema_8_1m is not None
            and ema_21_1m is not None
            and ema_8_15m is not None
            and ema_21_15m is not None
        ):
            price_above_vwap = vwap_val is not None and entry_price > vwap_val
            ema_alignment_score = self._mtf.compute_alignment_score(
                ema_fast_1m=float(ema_8_1m),
                ema_slow_1m=float(ema_21_1m),
                ema_fast_15m=float(ema_8_15m),
                ema_slow_15m=float(ema_21_15m),
                price_above_vwap=price_above_vwap,
            )
        else:
            ema_alignment_score = 0.0

        # RSI divergence score
        rsi_div = tech.rsi_divergence(timeframe="5m")
        rsi_divergence_score = (
            1.0 if rsi_div == "bullish" else (-1.0 if rsi_div == "bearish" else 0.0)
        )

        # VWAP score: (price - vwap) / vwap, normalised to [-1, +1]
        if vwap_val is not None and vwap_val > Decimal("0"):
            raw_vwap = float((entry_price - vwap_val) / vwap_val)
            # Invert: price above VWAP → short pressure; below → long pressure
            vwap_score = max(-1.0, min(1.0, -raw_vwap * 20.0))
        else:
            vwap_score = 0.0

        components = [
            SignalComponent(
                name="microstructure",
                score=ofi_score,
                weight=0.35,
                triggered=abs(ofi_val) > _OFI_THRESHOLD,
                metadata={"ofi": ofi_val, "cvd": micro.cvd()},
            ),
            SignalComponent(
                name="bollinger",
                score=bb_score,
                weight=0.25,
                triggered=abs(bb_score) > 0.15,
                metadata={"squeeze": tech.bb_squeeze(timeframe="5m")},
            ),
            SignalComponent(
                name="ema_mtf",
                score=ema_alignment_score,
                weight=0.20,
                triggered=abs(ema_alignment_score) > 0.10,
            ),
            SignalComponent(
                name="rsi_divergence",
                score=rsi_divergence_score,
                weight=0.15,
                triggered=rsi_divergence_score != 0.0,
            ),
            SignalComponent(
                name="vwap",
                score=vwap_score,
                weight=0.05,
                triggered=abs(vwap_score) > 0.002,
            ),
        ]

        final_strength, triggers = self._scorer.compute(components)

        if final_strength == 0.0:
            return  # No confluent signal

        direction = Direction.LONG if final_strength > 0 else Direction.SHORT

        # ── Price levels (ATR-based) ──────────────────────────────────────────
        atr = tech.atr(period=14, timeframe="5m")
        atr_val: Decimal = (
            atr if atr is not None and atr > Decimal("0") else entry_price * _ATR_FALLBACK_PCT
        )

        if direction == Direction.LONG:
            stop_loss = entry_price - _SL_ATR_MULT * atr_val
            take_profit = [
                entry_price + _TP1_ATR_MULT * atr_val,
                entry_price + _TP2_ATR_MULT * atr_val,
            ]
        else:
            stop_loss = entry_price + _SL_ATR_MULT * atr_val
            take_profit = [
                entry_price - _TP1_ATR_MULT * atr_val,
                entry_price - _TP2_ATR_MULT * atr_val,
            ]

        # Guard: stop_loss must be strictly positive.
        if stop_loss <= Decimal("0"):
            stop_loss = entry_price * _FALLBACK_SL_PCT

        # ── Signal strength and confidence ───────────────────────────────────
        strength = final_strength  # already signed and in [-1.0, +1.0]
        confidence = min(
            1.0, abs(final_strength) + len(triggers) / _MAX_TRIGGERS_FOR_CONFIDENCE * 0.3
        )

        # ── MTF context ───────────────────────────────────────────────────────
        self._mtf.update("5m", direction.value, abs(final_strength))
        mtf_ctx: MTFContext = self._mtf.build_context(direction.value, tick.timestamp_ms)

        # ── TechnicalFeatures snapshot ────────────────────────────────────────
        vp = tech.volume_profile()
        rsi_5m = tech.rsi(period=14, timeframe="5m")
        rsi_15m = tech.rsi(period=14, timeframe="15m")
        bb_u, bb_m, bb_l = tech.bollinger_bands(timeframe="5m")

        features = TechnicalFeatures(
            rsi_1m=rsi_1m,
            rsi_5m=rsi_5m,
            rsi_15m=rsi_15m,
            bb_upper=bb_u,
            bb_middle=bb_m,
            bb_lower=bb_l,
            bb_squeeze=tech.bb_squeeze(timeframe="5m"),
            ema_8=ema_8,
            ema_21=ema_21,
            ema_55=tech.ema(period=55, timeframe="5m"),
            vwap=tech.vwap(),
            atr_14=atr,
            poc=vp.get("poc"),
            vah=vp.get("vah"),
            val=vp.get("val"),
            ofi=ofi_val,
            cvd=micro.cvd(),
            kyle_lambda=micro.kyle_lambda(),
        )

        # ── Construct and validate Signal ─────────────────────────────────────
        try:
            signal = Signal(
                signal_id=str(uuid.uuid4()),
                symbol=symbol,
                timestamp_ms=tick.timestamp_ms,
                direction=direction,
                strength=strength,
                signal_type=SignalType.COMPOSITE,
                triggers=triggers,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                features=features,
                mtf_context=mtf_ctx,
            )
        except Exception as exc:
            self.logger.warning(
                "Signal construction failed",
                symbol=symbol,
                direction=direction.value,
                error=str(exc),
            )
            return

        # ── Publish and cache ─────────────────────────────────────────────────
        signal_dict = signal.model_dump()
        pub_topic = f"signal.technical.{symbol}"

        await asyncio.gather(
            self.bus.publish(pub_topic, signal_dict),
            self.state.set(f"signal:{symbol}", signal_dict),
        )

        self.logger.info(
            "Signal published",
            symbol=symbol,
            direction=direction.value,
            triggers=triggers,
            confidence=confidence,
            entry=str(entry_price),
        )


import sys
import os
import asyncio
from pathlib import Path

# Fix sys.path for direct module runs
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if __name__ == '__main__':
    import importlib
    
    # We expect the class name to be XxxService (e.g. DataIngestionService, SignalEngineService...)
    # But to make it generic without inspecting the AST, we can just find subclasses of BaseService
    from core.base_service import BaseService
    import inspect
    
    module_name = 'services.' + Path(__file__).parent.name + '.service'
    module = importlib.import_module(module_name)
    
    service_class = None
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseService) and obj is not BaseService:
            service_class = obj
            break
            
    if not service_class:
        print(f'Error: Could not find a BaseService subclass in {module_name}')
        sys.exit(1)
        
    async def main():
        service = service_class()
        try:
            await service.start()
            while service._running:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print('Interrupted by user...')
        finally:
            await service.stop()

    asyncio.run(main())

