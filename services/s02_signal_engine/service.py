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
from services.s02_signal_engine.technical import TechnicalAnalyzer

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

        micro = self._micro[symbol]
        tech = self._tech[symbol]

        micro.update(tick)
        tech.update(tick)

        # ── Evaluate triggers ─────────────────────────────────────────────────
        long_triggers: list[str] = []
        short_triggers: list[str] = []

        # OFI signal
        ofi_val = micro.ofi()
        if ofi_val > _OFI_THRESHOLD:
            long_triggers.append("OFI_positive")
        elif ofi_val < -_OFI_THRESHOLD:
            short_triggers.append("OFI_negative")

        # RSI oversold / overbought (1-minute bars)
        rsi_1m = tech.rsi(period=14, timeframe="1m")
        if rsi_1m is not None:
            if rsi_1m < 30.0:
                long_triggers.append("RSI_oversold")
            elif rsi_1m > 70.0:
                short_triggers.append("RSI_overbought")

        # Bollinger Band bounce (5-minute bars)
        bb_upper, _bb_middle, bb_lower = tech.bollinger_bands(period=20, std=2.0, timeframe="5m")
        entry_price: Decimal = tick.price
        if bb_upper is not None and bb_lower is not None:
            bb_range = bb_upper - bb_lower
            if bb_range > Decimal("0"):
                proximity = bb_range * Decimal("0.05")
                if entry_price >= bb_upper - proximity:
                    short_triggers.append("BB_upper_bounce")
                elif entry_price <= bb_lower + proximity:
                    long_triggers.append("BB_lower_bounce")

        # EMA 8 / 21 cross (5-minute bars)
        ema_8 = tech.ema(period=8, timeframe="5m")
        ema_21 = tech.ema(period=21, timeframe="5m")
        prev_8 = self._prev_ema_8.get(symbol)
        prev_21 = self._prev_ema_21.get(symbol)

        if ema_8 is not None and ema_21 is not None and prev_8 is not None and prev_21 is not None:
            if prev_8 < prev_21 and ema_8 > ema_21:
                long_triggers.append("EMA_cross_bullish")
            elif prev_8 > prev_21 and ema_8 < ema_21:
                short_triggers.append("EMA_cross_bearish")

        # Persist EMA values for next tick's cross detection.
        self._prev_ema_8[symbol] = ema_8
        self._prev_ema_21[symbol] = ema_21

        # ── Determine consensus direction ─────────────────────────────────────
        n_long = len(long_triggers)
        n_short = len(short_triggers)

        if n_long == 0 and n_short == 0:
            return  # No triggers - no signal.
        if n_long == n_short:
            return  # Tied - ambiguous direction.

        direction = Direction.LONG if n_long > n_short else Direction.SHORT
        triggers = long_triggers if direction == Direction.LONG else short_triggers

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
        raw_strength = min(1.0, len(triggers) / _MAX_TRIGGERS_FOR_CONFIDENCE)
        strength = -raw_strength if direction == Direction.SHORT else raw_strength
        confidence = raw_strength  # mirrors magnitude of strength

        # ── MTF context ───────────────────────────────────────────────────────
        self._mtf.update("5m", direction.value, raw_strength)
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
