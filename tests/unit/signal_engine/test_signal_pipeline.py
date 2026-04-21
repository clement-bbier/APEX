"""Unit tests for SignalPipeline — each step testable in isolation.

Tests verify that the pipeline decomposes _process_tick correctly:
each step reads/writes the expected PipelineState fields without
requiring the full service to be stood up.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.tick import Market, NormalizedTick, TradeSide
from services.signal_engine.microstructure import MicrostructureAnalyzer
from services.signal_engine.mtf_aligner import MTFAligner
from services.signal_engine.pipeline import PipelineState, SignalPipeline
from services.signal_engine.signal_scorer import SignalScorer
from services.signal_engine.technical import TechnicalAnalyzer
from services.signal_engine.vpin import VPINCalculator


def _make_tick(
    symbol: str = "BTCUSDT",
    price: str = "50000",
    volume: str = "10",
    timestamp_ms: int = 1_000_000,
) -> NormalizedTick:
    return NormalizedTick(
        symbol=symbol,
        market=Market.CRYPTO,
        timestamp_ms=timestamp_ms,
        price=Decimal(price),
        volume=Decimal(volume),
        side=TradeSide.BUY,
        bid=Decimal(price) * Decimal("0.9999"),
        ask=Decimal(price) * Decimal("1.0001"),
        spread_bps=Decimal("5"),
    )


def _make_pipeline() -> SignalPipeline:
    """Create a pipeline with empty stores and a mock state."""
    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()
    return SignalPipeline(
        micro_store={},
        tech_store={},
        vpin_store={},
        adv_counter={},
        mtf=MTFAligner(),
        scorer=SignalScorer(min_components=2, min_strength=0.20),
        state=state,
    )


class TestPipelineState:
    def test_symbol_set_from_tick(self) -> None:
        tick = _make_tick(symbol="ETHUSDT")
        ps = PipelineState(tick=tick)
        assert ps.symbol == "ETHUSDT"

    def test_default_values(self) -> None:
        ps = PipelineState(tick=_make_tick())
        assert ps.vpin_blocked is False
        assert ps.signal is None
        assert ps.direction is None
        assert ps.components == []


class TestEnsureInitialized:
    def test_creates_analyzers_on_first_tick(self) -> None:
        pipeline = _make_pipeline()
        ps = PipelineState(tick=_make_tick())
        pipeline.ensure_initialized(ps)
        assert ps.micro is not None
        assert ps.tech is not None
        assert isinstance(ps.micro, MicrostructureAnalyzer)
        assert isinstance(ps.tech, TechnicalAnalyzer)

    def test_reuses_analyzers_on_second_tick(self) -> None:
        pipeline = _make_pipeline()
        ps1 = PipelineState(tick=_make_tick())
        pipeline.ensure_initialized(ps1)
        micro_ref = ps1.micro

        ps2 = PipelineState(tick=_make_tick(timestamp_ms=2_000_000))
        pipeline.ensure_initialized(ps2)
        assert ps2.micro is micro_ref  # same instance

    def test_creates_vpin_calculator(self) -> None:
        pipeline = _make_pipeline()
        ps = PipelineState(tick=_make_tick())
        pipeline.ensure_initialized(ps)
        assert "BTCUSDT" in pipeline._vpin_store
        assert isinstance(pipeline._vpin_store["BTCUSDT"], VPINCalculator)


class TestRefreshVpin:
    @pytest.mark.asyncio
    async def test_normal_toxicity_does_not_block(self) -> None:
        pipeline = _make_pipeline()
        ps = PipelineState(tick=_make_tick())
        pipeline.ensure_initialized(ps)
        await pipeline.refresh_vpin(ps)
        assert ps.vpin_blocked is False

    @pytest.mark.asyncio
    async def test_state_set_called_with_vpin_data(self) -> None:
        pipeline = _make_pipeline()
        ps = PipelineState(tick=_make_tick())
        pipeline.ensure_initialized(ps)
        await pipeline.refresh_vpin(ps)
        pipeline._state.set.assert_called_once()  # type: ignore[union-attr]
        call_args = pipeline._state.set.call_args  # type: ignore[union-attr]
        assert call_args[0][0] == "vpin:BTCUSDT"


class TestComputeIndicators:
    def test_sets_ofi_and_ema_values(self) -> None:
        pipeline = _make_pipeline()
        # Feed enough ticks for analyzers to produce values.
        ticks = [_make_tick(timestamp_ms=1_000_000 + i * 1000) for i in range(5)]
        for tick in ticks:
            ps = PipelineState(tick=tick)
            pipeline.ensure_initialized(ps)
        # Compute indicators on the last state
        pipeline.compute_indicators(ps)
        # OFI should be a float (may be 0.0 for identical ticks)
        assert isinstance(ps.ofi_val, float)


class TestBuildComponents:
    def test_builds_five_components(self) -> None:
        pipeline = _make_pipeline()
        ticks = [_make_tick(timestamp_ms=1_000_000 + i * 1000) for i in range(5)]
        for tick in ticks:
            ps = PipelineState(tick=tick)
            pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        pipeline.build_components(ps)
        assert len(ps.components) == 5
        names = {c.name for c in ps.components}
        assert names == {"microstructure", "bollinger", "ema_mtf", "rsi_divergence", "vwap"}


class TestComputePriceLevels:
    def test_long_stop_below_entry(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick(price="50000")
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        # Force direction for testing
        from core.models.signal import Direction

        ps.direction = Direction.LONG
        pipeline.compute_price_levels(ps)
        assert ps.stop_loss < tick.price
        assert all(tp > tick.price for tp in ps.take_profit)

    def test_short_stop_above_entry(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick(price="50000")
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        from core.models.signal import Direction

        ps.direction = Direction.SHORT
        pipeline.compute_price_levels(ps)
        assert ps.stop_loss > tick.price
        assert all(tp < tick.price for tp in ps.take_profit)

    def test_stop_loss_never_non_positive(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick(price="0.001")
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        from core.models.signal import Direction

        ps.direction = Direction.SHORT
        pipeline.compute_price_levels(ps)
        assert ps.stop_loss > Decimal("0")


class TestBuildMtfContext:
    def test_builds_features_and_context(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick()
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        from core.models.signal import Direction

        ps.direction = Direction.LONG
        ps.final_strength = 0.5
        ps.triggers = ["microstructure", "bollinger"]
        pipeline.build_mtf_context(ps)
        assert ps.mtf_ctx is not None
        assert ps.features is not None
        assert ps.confidence > 0.0


class TestConstructSignal:
    def test_constructs_valid_signal(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick()
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        from core.models.signal import Direction

        ps.direction = Direction.LONG
        ps.final_strength = 0.5
        ps.triggers = ["microstructure", "bollinger"]
        pipeline.compute_price_levels(ps)
        pipeline.build_mtf_context(ps)
        pipeline.construct_signal(ps)
        assert ps.signal is not None
        assert ps.signal.symbol == "BTCUSDT"
        assert ps.signal.direction == Direction.LONG

    def test_invalid_signal_sets_none(self) -> None:
        pipeline = _make_pipeline()
        tick = _make_tick()
        ps = PipelineState(tick=tick)
        pipeline.ensure_initialized(ps)
        pipeline.compute_indicators(ps)
        from core.models.signal import Direction

        ps.direction = Direction.LONG
        ps.strength = 999.0  # invalid: out of [-1, 1]
        ps.confidence = 999.0  # invalid
        ps.stop_loss = Decimal("0")  # invalid
        pipeline.construct_signal(ps)
        # Signal construction failed, signal stays None
        assert ps.signal is None


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_run_returns_none_for_single_tick(self) -> None:
        """A single tick cannot produce enough triggers for a signal."""
        pipeline = _make_pipeline()
        tick = _make_tick()
        result = await pipeline.run(tick)
        assert result is None  # Not enough data for confluence
