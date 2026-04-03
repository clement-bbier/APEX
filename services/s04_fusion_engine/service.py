"""S04 Fusion Engine service for APEX Trading System.

Subscribes to technical signals, fuses them with the current regime, sizes
positions using the Kelly criterion, and publishes :class:`OrderCandidate`
objects for validation by the Risk Manager.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal
from typing import Any

from core.base_service import BaseService
from core.config import get_settings
from core.models.order import OrderCandidate
from core.models.regime import Regime
from core.models.signal import Signal, TechnicalFeatures
from services.s04_fusion_engine.fusion import FusionEngine
from services.s04_fusion_engine.hedge_trigger import HedgeTrigger
from services.s04_fusion_engine.kelly_sizer import KellySizer
from services.s04_fusion_engine.strategy import StrategySelector

_SIGNAL_TOPICS: list[str] = ["signal.technical."]
_ORDER_CANDIDATE_TOPIC = "order.candidate"
_REGIME_KEY = "regime:current"

# Default capital used when the value cannot be read from settings.
_DEFAULT_CAPITAL = Decimal("10000.0")


class FusionEngineService(BaseService):
    """Transforms validated signals into sized order candidates.

    For each incoming ``signal.technical.{SYMBOL}`` message the service:

    1. Reads ``regime:current`` from Redis and parses it as a
       :class:`~core.models.regime.Regime`.
    2. Computes a fusion score via :class:`~.fusion.FusionEngine`.
    3. Validates strategy compatibility via :class:`~.strategy.StrategySelector`.
    4. Computes the Kelly position size via :class:`~.kelly_sizer.KellySizer`.
    5. Splits the size into scalp (35 %) / swing (65 %) exit fractions.
    6. Evaluates hedge triggers and, if warranted, adds hedge metadata.
    7. Publishes the :class:`~core.models.order.OrderCandidate` on ZMQ.
    """

    service_id = "s04_fusion_engine"

    def __init__(self) -> None:
        """Initialize fusion components and ZMQ pub/sub."""
        super().__init__(self.service_id)
        self._fusion = FusionEngine()
        self._strategy = StrategySelector()
        self._kelly = KellySizer()
        self._hedge = HedgeTrigger()
        self.bus.init_publisher()

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """Parse an incoming signal and run the fusion pipeline.

        Args:
            topic: ZMQ topic string, e.g. ``'signal.technical.BTCUSDT'``.
            data:  JSON-decoded message payload.
        """
        try:
            signal = Signal.model_validate(data)
            await self._process_signal(signal)
        except Exception as exc:
            self.logger.error(
                "Error processing signal",
                topic=topic,
                error=str(exc),
                exc_info=exc,
            )

    async def run(self) -> None:
        """Subscribe to technical-signal topics and dispatch to :meth:`on_message`."""
        self.logger.info(
            "FusionEngineService starting",
            topics=_SIGNAL_TOPICS,
        )
        try:
            await self.bus.subscribe(_SIGNAL_TOPICS, self.on_message)
        except asyncio.CancelledError:
            self.logger.info("FusionEngineService subscribe loop cancelled")
            raise

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def _process_signal(self, signal: Signal) -> None:
        """Run the full fusion pipeline for one signal.

        Args:
            signal: Validated incoming signal.
        """
        regime = await self._load_regime()
        if regime is None:
            self.logger.warning(
                "No regime available, dropping signal",
                symbol=signal.symbol,
            )
            return

        # ── Strategy gating ───────────────────────────────────────────────────
        strategy = self._fusion.select_strategy(regime)
        if strategy == "blocked":
            self.logger.info(
                "Strategy blocked by regime",
                symbol=signal.symbol,
                risk_mode=regime.risk_mode.value,
            )
            return

        if not self._strategy.is_active(strategy, regime):
            self.logger.info(
                "Strategy inactive for current regime",
                symbol=signal.symbol,
                strategy=strategy,
            )
            return

        # ── Fusion score ──────────────────────────────────────────────────────
        fusion_score = self._fusion.compute_final_score(signal, regime)
        strategy_mult = self._strategy.get_size_multiplier(strategy, regime)

        # ── Kelly sizing ──────────────────────────────────────────────────────
        settings = get_settings()
        capital: Decimal = settings.initial_capital

        win_rate, avg_rr = await self._kelly.get_stats(self.state, signal.symbol)
        kelly_f = self._kelly.kelly_fraction(win_rate, avg_rr)

        kyle_lambda = (
            signal.features.kyle_lambda
            if signal.features is not None and signal.features.kyle_lambda is not None
            else 0.0
        )
        is_crypto = "USD" in signal.symbol or "BTC" in signal.symbol or "ETH" in signal.symbol

        raw_size = self._kelly.position_size(
            capital=capital,
            kelly_f=kelly_f,
            regime_mult=regime.macro_mult * strategy_mult,
            session_mult=regime.session_mult,
            kyle_lambda=kyle_lambda,
            is_crypto=is_crypto,
        )

        # Apply fusion score as an additional scaling factor (capped at 1.0).
        size = raw_size * Decimal(str(min(fusion_score, 1.0)))
        if size <= Decimal("0"):
            self.logger.info(
                "Computed size is zero, dropping signal",
                symbol=signal.symbol,
                fusion_score=fusion_score,
            )
            return

        # ── Exit split: 35 % scalp / 65 % swing ──────────────────────────────
        size_scalp = (size * Decimal("0.35")).quantize(Decimal("0.00000001"))
        size_swing = (size - size_scalp).quantize(Decimal("0.00000001"))
        # Ensure sizes sum to size exactly by assigning remainder to swing.
        if size_scalp + size_swing != size:
            size_swing = size - size_scalp

        # ── Capital at risk ────────────────────────────────────────────────────
        risk_per_unit = abs(signal.entry - signal.stop_loss)
        capital_at_risk = size * risk_per_unit / signal.entry
        if capital_at_risk <= Decimal("0"):
            capital_at_risk = size * Decimal("0.01")

        # ── Hedge evaluation ──────────────────────────────────────────────────
        features: TechnicalFeatures = (
            signal.features if signal.features is not None else TechnicalFeatures()
        )
        hedge_bool, hedge_dir, hedge_sz = self._hedge.should_hedge(signal, features, regime, size)

        # ── Build OrderCandidate ───────────────────────────────────────────────
        candidate = OrderCandidate(
            order_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            direction=signal.direction,
            timestamp_ms=int(time.time() * 1000),
            size=size,
            size_scalp_exit=size_scalp,
            size_swing_exit=size_swing,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            target_scalp=signal.take_profit[0],
            target_swing=signal.take_profit[1],
            capital_at_risk=capital_at_risk,
            hedge_direction=hedge_dir,
            hedge_size=hedge_sz,
            fusion_score=fusion_score,
            kelly_fraction=kelly_f,
            source_signal=signal,
        )

        candidate_dict = candidate.model_dump(mode="json")
        await self.bus.publish(_ORDER_CANDIDATE_TOPIC, candidate_dict)

        self.logger.info(
            "OrderCandidate published",
            symbol=signal.symbol,
            direction=signal.direction.value,
            size=str(size),
            fusion_score=fusion_score,
            strategy=strategy,
            hedge=hedge_bool,
        )

    async def _load_regime(self) -> Regime | None:
        """Read the current regime from Redis.

        Returns:
            Parsed :class:`~core.models.regime.Regime` or ``None`` if absent.
        """
        raw = await self.state.get(_REGIME_KEY)
        if raw is None:
            return None
        try:
            return Regime.model_validate(raw)
        except Exception as exc:
            self.logger.error(
                "Failed to parse regime",
                error=str(exc),
                exc_info=exc,
            )
            return None
