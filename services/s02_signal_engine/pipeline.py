"""Signal pipeline — decomposes _process_tick into testable steps.

Each step operates on a shared :class:`PipelineState` dataclass, making it
possible to unit-test every stage in isolation without standing up the full
service.

Reference:
    Robert C. Martin (2008) Clean Code Ch. 3 — "Functions should do one
    thing. They should do it well. They should do it only."
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from core.logger import get_logger
from core.models.signal import (
    Direction,
    MTFContext,
    Signal,
    SignalType,
    TechnicalFeatures,
)
from core.models.tick import NormalizedTick
from core.state import StateStore
from services.s02_signal_engine.microstructure import MicrostructureAnalyzer
from services.s02_signal_engine.mtf_aligner import MTFAligner
from services.s02_signal_engine.signal_scorer import SignalComponent, SignalScorer
from services.s02_signal_engine.technical import TechnicalAnalyzer
from services.s02_signal_engine.vpin import VPINCalculator

logger = get_logger("s02_signal_engine.pipeline")

# OFI magnitude threshold for triggering an OFI signal.
_OFI_THRESHOLD: float = 0.3

# ATR multiples for stop-loss and take-profit levels.
_SL_ATR_MULT: Decimal = Decimal("1.5")
_TP1_ATR_MULT: Decimal = Decimal("2.0")
_TP2_ATR_MULT: Decimal = Decimal("3.0")

# Fallback stop-loss distance when ATR is unavailable (0.2% of entry price).
_ATR_FALLBACK_PCT: Decimal = Decimal("0.002")

# Minimum stop-loss floor when the computed stop-loss turns non-positive.
_FALLBACK_SL_PCT: Decimal = Decimal("0.001")

# Number of triggers needed for full confidence.
_MAX_TRIGGERS_FOR_CONFIDENCE: float = 4.0

# How many ticks between ADV refreshes from Redis (≈5 min at 1 tick/s).
_ADV_REFRESH_EVERY: int = 300


@dataclass
class PipelineState:
    """Mutable state passed between pipeline steps."""

    tick: NormalizedTick
    symbol: str = ""

    # Step 1: analyzers (set during ensure_initialized)
    micro: MicrostructureAnalyzer | None = None
    tech: TechnicalAnalyzer | None = None

    # Step 2: VPIN
    vpin_blocked: bool = False

    # Step 3: indicators
    ofi_val: float = 0.0
    rsi_1m: float | None = None
    bb_upper: Decimal | None = None
    bb_middle: Decimal | None = None
    bb_lower: Decimal | None = None
    ema_8: Decimal | None = None
    ema_21: Decimal | None = None
    ema_8_1m: Decimal | None = None
    ema_21_1m: Decimal | None = None
    ema_8_15m: Decimal | None = None
    ema_21_15m: Decimal | None = None
    vwap_val: Decimal | None = None

    # Step 4: scorer
    components: list[SignalComponent] = field(default_factory=list)
    final_strength: float = 0.0
    triggers: list[str] = field(default_factory=list)
    direction: Direction | None = None

    # Step 5: price levels
    stop_loss: Decimal = Decimal("0")
    take_profit: list[Decimal] = field(default_factory=list)
    atr_val: Decimal = Decimal("0")

    # Step 6: MTF context
    strength: float = 0.0
    confidence: float = 0.0
    mtf_ctx: MTFContext | None = None
    features: TechnicalFeatures | None = None

    # Step 7: signal
    signal: Signal | None = None

    def __post_init__(self) -> None:
        self.symbol = self.tick.symbol


class SignalPipeline:
    """Encapsulates the tick-to-signal transformation in discrete steps.

    Each step reads and writes fields on a shared :class:`PipelineState`.
    The full pipeline is executed via :meth:`run`.
    """

    def __init__(
        self,
        *,
        micro_store: dict[str, MicrostructureAnalyzer],
        tech_store: dict[str, TechnicalAnalyzer],
        vpin_store: dict[str, VPINCalculator],
        adv_counter: dict[str, int],
        mtf: MTFAligner,
        scorer: SignalScorer,
        state: StateStore,
    ) -> None:
        self._micro_store = micro_store
        self._tech_store = tech_store
        self._vpin_store = vpin_store
        self._adv_counter = adv_counter
        self._mtf = mtf
        self._scorer = scorer
        self._state = state

    # ── Step 1: Lazy-init ────────────────────────────────────────────────────

    def ensure_initialized(self, ps: PipelineState) -> None:
        """Lazy-initialize per-symbol analyzers on first tick.

        Args:
            ps: Current pipeline state.
        """
        symbol = ps.symbol
        if symbol not in self._micro_store:
            self._micro_store[symbol] = MicrostructureAnalyzer(symbol)
        if symbol not in self._tech_store:
            self._tech_store[symbol] = TechnicalAnalyzer(symbol)
        if symbol not in self._vpin_store:
            self._vpin_store[symbol] = VPINCalculator(default_bucket_size=1000.0)
            self._adv_counter[symbol] = 0

        ps.micro = self._micro_store[symbol]
        ps.tech = self._tech_store[symbol]

        ps.micro.update(ps.tick)
        ps.tech.update(ps.tick)

    # ── Step 2: VPIN refresh ─────────────────────────────────────────────────

    async def refresh_vpin(self, ps: PipelineState) -> None:
        """Update VPIN estimate and gate on extreme toxicity.

        Sets ``ps.vpin_blocked = True`` if toxicity is extreme, aborting
        the pipeline.

        Args:
            ps: Current pipeline state.
        """
        symbol = ps.symbol
        self._adv_counter[symbol] = self._adv_counter.get(symbol, 0) + 1
        if self._adv_counter[symbol] >= _ADV_REFRESH_EVERY:
            self._adv_counter[symbol] = 0
            try:
                adv_data = await self._state.get(f"analytics:adv:{symbol}")
                if isinstance(adv_data, dict):
                    adv_val = float(adv_data.get("adv_1d", 0) or 0)
                    if adv_val > 0:
                        self._vpin_store[symbol].update_adv(adv_val)
            except Exception as exc:
                logger.debug(
                    "ADV refresh failed, keeping default bucket_size",
                    symbol=symbol,
                    error=str(exc),
                )

        self._vpin_store[symbol].update(ps.tick)
        vpin_metrics = self._vpin_store[symbol].compute()

        await self._state.set(
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
            logger.warning("vpin_extreme_block", symbol=symbol, vpin=vpin_metrics.vpin)
            ps.vpin_blocked = True

    # ── Step 3: Compute indicators ───────────────────────────────────────────

    def compute_indicators(self, ps: PipelineState) -> None:
        """Compute all indicator families from analyzer state.

        Args:
            ps: Current pipeline state.
        """
        assert ps.micro is not None
        assert ps.tech is not None
        tech = ps.tech
        micro = ps.micro

        ps.ofi_val = micro.ofi()
        ps.rsi_1m = tech.rsi(period=14, timeframe="1m")
        ps.bb_upper, ps.bb_middle, ps.bb_lower = tech.bollinger_bands(
            period=20, std=2.0, timeframe="5m"
        )

        ps.ema_8 = tech.ema(period=8, timeframe="5m")
        ps.ema_21 = tech.ema(period=21, timeframe="5m")

        # EMA 1m and 15m (for MTF alignment scorer)
        ps.ema_8_1m = tech.ema(period=8, timeframe="1m")
        ps.ema_21_1m = tech.ema(period=21, timeframe="1m")
        ps.ema_8_15m = tech.ema(period=8, timeframe="15m")
        ps.ema_21_15m = tech.ema(period=21, timeframe="15m")
        ps.vwap_val = tech.vwap()

    # ── Step 4: Build scorer components ──────────────────────────────────────

    def build_components(self, ps: PipelineState) -> None:
        """Assemble scorer input components from computed indicators.

        Args:
            ps: Current pipeline state.
        """
        assert ps.tech is not None
        assert ps.micro is not None
        tech = ps.tech
        entry_price = ps.tick.price

        # Microstructure: OFI normalised to [-1, +1]
        ofi_val = ps.ofi_val
        ofi_score = max(-1.0, min(1.0, ofi_val / max(abs(ofi_val), 1e-6))) if ofi_val != 0 else 0.0

        # Bollinger score
        if ps.bb_upper is not None and ps.bb_lower is not None and ps.bb_middle is not None:
            bb_score = tech.compute_bollinger_score(
                price=float(entry_price),
                upper=float(ps.bb_upper),
                lower=float(ps.bb_lower),
                middle=float(ps.bb_middle),
                bandwidth_pct=50.0,
            )
        else:
            bb_score = 0.0

        # EMA MTF alignment score
        if (
            ps.ema_8_1m is not None
            and ps.ema_21_1m is not None
            and ps.ema_8_15m is not None
            and ps.ema_21_15m is not None
        ):
            price_above_vwap = ps.vwap_val is not None and entry_price > ps.vwap_val
            ema_alignment_score = self._mtf.compute_alignment_score(
                ema_fast_1m=float(ps.ema_8_1m),
                ema_slow_1m=float(ps.ema_21_1m),
                ema_fast_15m=float(ps.ema_8_15m),
                ema_slow_15m=float(ps.ema_21_15m),
                price_above_vwap=price_above_vwap,
            )
        else:
            ema_alignment_score = 0.0

        # RSI divergence score
        rsi_div = tech.rsi_divergence(timeframe="5m")
        rsi_divergence_score = (
            1.0 if rsi_div == "bullish" else (-1.0 if rsi_div == "bearish" else 0.0)
        )

        # VWAP score
        if ps.vwap_val is not None and ps.vwap_val > Decimal("0"):
            raw_vwap = float((entry_price - ps.vwap_val) / ps.vwap_val)
            vwap_score = max(-1.0, min(1.0, -raw_vwap * 20.0))
        else:
            vwap_score = 0.0

        ps.components = [
            SignalComponent(
                name="microstructure",
                score=ofi_score,
                weight=0.35,
                triggered=abs(ofi_val) > _OFI_THRESHOLD,
                metadata={"ofi": ofi_val, "cvd": ps.micro.cvd()},
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

        ps.final_strength, ps.triggers = self._scorer.compute(ps.components)

        if ps.final_strength != 0.0:
            ps.direction = Direction.LONG if ps.final_strength > 0 else Direction.SHORT

    # ── Step 5: Compute price levels ─────────────────────────────────────────

    def compute_price_levels(self, ps: PipelineState) -> None:
        """Compute ATR-based stop-loss and take-profit levels.

        Args:
            ps: Current pipeline state.
        """
        assert ps.tech is not None
        assert ps.direction is not None
        entry_price = ps.tick.price

        atr = ps.tech.atr(period=14, timeframe="5m")
        ps.atr_val = (
            atr if atr is not None and atr > Decimal("0") else entry_price * _ATR_FALLBACK_PCT
        )

        if ps.direction == Direction.LONG:
            ps.stop_loss = entry_price - _SL_ATR_MULT * ps.atr_val
            ps.take_profit = [
                entry_price + _TP1_ATR_MULT * ps.atr_val,
                entry_price + _TP2_ATR_MULT * ps.atr_val,
            ]
        else:
            ps.stop_loss = entry_price + _SL_ATR_MULT * ps.atr_val
            ps.take_profit = [
                entry_price - _TP1_ATR_MULT * ps.atr_val,
                entry_price - _TP2_ATR_MULT * ps.atr_val,
            ]

        if ps.stop_loss <= Decimal("0"):
            ps.stop_loss = entry_price * _FALLBACK_SL_PCT

    # ── Step 6: Build MTF context + features ─────────────────────────────────

    def build_mtf_context(self, ps: PipelineState) -> None:
        """Assemble multi-timeframe context and technical features.

        Args:
            ps: Current pipeline state.
        """
        assert ps.direction is not None
        assert ps.tech is not None
        assert ps.micro is not None
        tech = ps.tech

        ps.strength = ps.final_strength
        ps.confidence = min(
            1.0, abs(ps.final_strength) + len(ps.triggers) / _MAX_TRIGGERS_FOR_CONFIDENCE * 0.3
        )

        self._mtf.update("5m", ps.direction.value, abs(ps.final_strength))
        ps.mtf_ctx = self._mtf.build_context(ps.direction.value, ps.tick.timestamp_ms)

        # TechnicalFeatures snapshot
        vp = tech.volume_profile()
        rsi_5m = tech.rsi(period=14, timeframe="5m")
        rsi_15m = tech.rsi(period=14, timeframe="15m")
        bb_u, bb_m, bb_l = tech.bollinger_bands(timeframe="5m")

        ps.features = TechnicalFeatures(
            rsi_1m=ps.rsi_1m,
            rsi_5m=rsi_5m,
            rsi_15m=rsi_15m,
            bb_upper=bb_u,
            bb_middle=bb_m,
            bb_lower=bb_l,
            bb_squeeze=tech.bb_squeeze(timeframe="5m"),
            ema_8=ps.ema_8,
            ema_21=ps.ema_21,
            ema_55=tech.ema(period=55, timeframe="5m"),
            vwap=tech.vwap(),
            atr_14=tech.atr(period=14, timeframe="5m"),
            poc=vp.get("poc"),
            vah=vp.get("vah"),
            val=vp.get("val"),
            ofi=ps.ofi_val,
            cvd=ps.micro.cvd(),
            kyle_lambda=ps.micro.kyle_lambda(),
        )

    # ── Step 7: Construct signal ─────────────────────────────────────────────

    def construct_signal(self, ps: PipelineState) -> None:
        """Construct, validate, and set the final Signal on state.

        Args:
            ps: Current pipeline state.
        """
        assert ps.direction is not None
        try:
            ps.signal = Signal(
                signal_id=str(uuid.uuid4()),
                symbol=ps.symbol,
                timestamp_ms=ps.tick.timestamp_ms,
                direction=ps.direction,
                strength=ps.strength,
                signal_type=SignalType.COMPOSITE,
                triggers=ps.triggers,
                entry=ps.tick.price,
                stop_loss=ps.stop_loss,
                take_profit=ps.take_profit,
                confidence=ps.confidence,
                features=ps.features,
                mtf_context=ps.mtf_ctx,
            )
        except Exception as exc:
            logger.warning(
                "Signal construction failed",
                symbol=ps.symbol,
                direction=ps.direction.value,
                error=str(exc),
            )

    # ── Full pipeline ────────────────────────────────────────────────────────

    async def run(self, tick: NormalizedTick) -> Signal | None:
        """Execute the full tick-to-signal pipeline.

        Args:
            tick: Validated normalized tick.

        Returns:
            A :class:`Signal` if confluence conditions are met, else ``None``.
        """
        ps = PipelineState(tick=tick)

        # Step 1: lazy-init
        self.ensure_initialized(ps)

        # Step 2: VPIN
        await self.refresh_vpin(ps)
        if ps.vpin_blocked:
            return None

        # Step 3: indicators
        self.compute_indicators(ps)

        # Step 4: scorer components
        self.build_components(ps)
        if ps.final_strength == 0.0:
            return None  # No confluent signal

        # Step 5: price levels
        self.compute_price_levels(ps)

        # Step 6: MTF context + features
        self.build_mtf_context(ps)

        # Step 7: construct signal
        self.construct_signal(ps)

        return ps.signal
