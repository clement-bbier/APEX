"""Unit tests for PaperTrader.execute().

Tests slippage application, fill price direction, commission,
and liquidity rejection. Uses real Pydantic model instances
(no mocks) to ensure correctness against actual validation rules.
No real broker, no network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.models.order import ApprovedOrder, OrderCandidate, OrderType
from core.models.signal import Direction, Signal, SignalType
from core.models.tick import Market, NormalizedTick, TradeSide
from services.s06_execution.paper_trader import PaperTrader


def _make_signal(direction: Direction = Direction.LONG, entry: str = "50000") -> Signal:
    entry_d = Decimal(entry)
    if direction == Direction.LONG:
        stop = entry_d - Decimal("500")
        tp1 = entry_d + Decimal("750")  # R:R = 1.5
        tp2 = entry_d + Decimal("1500")
    else:
        stop = entry_d + Decimal("500")
        tp1 = entry_d - Decimal("750")
        tp2 = entry_d - Decimal("1500")

    return Signal(
        signal_id="test-signal-001",
        symbol="BTCUSDT",
        timestamp_ms=1_000_000,
        direction=direction,
        strength=0.6,
        signal_type=SignalType.COMPOSITE,
        triggers=["RSI_oversold", "OFI"],
        entry=entry_d,
        stop_loss=stop,
        take_profit=[tp1, tp2],
        confidence=0.6,
    )


def _make_approved_order(
    direction: Direction = Direction.LONG,
    entry: str = "50000",
    size: str = "0.1",
) -> ApprovedOrder:
    signal = _make_signal(direction, entry)
    entry_d = Decimal(entry)
    size_d = Decimal(size)
    size_scalp = (size_d * Decimal("35") / Decimal("100")).quantize(Decimal("0.000001"))
    size_swing = size_d - size_scalp

    if direction == Direction.LONG:
        stop = entry_d - Decimal("500")
        tp1 = entry_d + Decimal("750")
        tp2 = entry_d + Decimal("1500")
    else:
        stop = entry_d + Decimal("500")
        tp1 = entry_d - Decimal("750")
        tp2 = entry_d - Decimal("1500")

    candidate = OrderCandidate(
        order_id="order-001",
        symbol="BTCUSDT",
        direction=direction,
        timestamp_ms=1_000_000,
        size=size_d,
        size_scalp_exit=size_scalp,
        size_swing_exit=size_swing,
        entry=entry_d,
        stop_loss=stop,
        target_scalp=tp1,
        target_swing=tp2,
        capital_at_risk=Decimal("50"),
        source_signal=signal,
    )
    return ApprovedOrder(
        candidate=candidate,
        approved_at_ms=1_000_001,
        regime_mult=1.0,
        adjusted_size=size_d,
        order_type=OrderType.LIMIT,
    )


def _make_tick(
    price: str = "50000",
    volume: str = "100",
    spread_bps: str = "5",
) -> NormalizedTick:
    p = Decimal(price)
    return NormalizedTick(
        symbol="BTCUSDT",
        market=Market.CRYPTO,
        timestamp_ms=1_000_000,
        price=p,
        volume=Decimal(volume),
        side=TradeSide.UNKNOWN,
        bid=p * Decimal("0.9999"),
        ask=p * Decimal("1.0001"),
        spread_bps=Decimal(spread_bps),
    )


class TestExecuteSlippage:
    """Slippage = spread/2 + kyle_lambda × fill_size, applied to fill price."""

    @pytest.mark.asyncio
    async def test_long_fill_price_above_entry(self) -> None:
        """LONG fill: slippage worsens entry → fill_price > entry."""
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick, kyle_lambda=0.0)
        assert executed.fill_price > order.candidate.entry

    @pytest.mark.asyncio
    async def test_short_fill_price_below_entry(self) -> None:
        """SHORT fill: slippage worsens entry → fill_price < entry."""
        trader = PaperTrader()
        order = _make_approved_order(Direction.SHORT, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick, kyle_lambda=0.0)
        assert executed.fill_price < order.candidate.entry

    @pytest.mark.asyncio
    async def test_fill_price_equals_entry_for_zero_spread(self) -> None:
        """Zero spread + zero lambda → fill_price equals entry exactly."""
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="0")
        # Provide spread_bps=0 via the tick
        executed = await trader.execute(order, tick, kyle_lambda=0.0)
        # fill_price = entry * (1 + 0/10000) = entry
        assert executed.fill_price == order.candidate.entry

    @pytest.mark.asyncio
    async def test_wider_spread_increases_slippage(self) -> None:
        """Wider spread → fill_price further from entry."""
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")

        tick_tight = _make_tick(price="50000", volume="100", spread_bps="2")
        tick_wide = _make_tick(price="50000", volume="100", spread_bps="20")

        exec_tight = await trader.execute(order, tick_tight, kyle_lambda=0.0)
        exec_wide = await trader.execute(order, tick_wide, kyle_lambda=0.0)

        assert exec_wide.fill_price > exec_tight.fill_price


class TestExecuteLiquidityCheck:
    """Raises ValueError when tick volume < fill_size × 10."""

    @pytest.mark.asyncio
    async def test_raises_on_insufficient_liquidity(self) -> None:
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        # volume=0.5 < 0.1 × 10 = 1.0 → insufficient
        tick = _make_tick(price="50000", volume="0.5")
        with pytest.raises(ValueError, match="Insufficient liquidity"):
            await trader.execute(order, tick)

    @pytest.mark.asyncio
    async def test_passes_with_sufficient_liquidity(self) -> None:
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        # volume=10 >= 0.1 × 10 = 1.0 → OK
        tick = _make_tick(price="50000", volume="10", spread_bps="5")
        executed = await trader.execute(order, tick)
        assert executed is not None


class TestExecuteReturnType:
    @pytest.mark.asyncio
    async def test_returns_executed_order(self) -> None:
        from core.models.order import ExecutedOrder

        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick)
        assert isinstance(executed, ExecutedOrder)

    @pytest.mark.asyncio
    async def test_is_paper_flag_set(self) -> None:
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick)
        assert executed.is_paper is True

    @pytest.mark.asyncio
    async def test_commission_is_positive(self) -> None:
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick)
        assert executed.commission > Decimal("0")

    @pytest.mark.asyncio
    async def test_fill_size_matches_order_size(self) -> None:
        trader = PaperTrader()
        order = _make_approved_order(Direction.LONG, entry="50000", size="0.1")
        tick = _make_tick(price="50000", volume="100", spread_bps="5")
        executed = await trader.execute(order, tick)
        assert executed.fill_size == order.adjusted_size


class TestComputeSlippage:
    """Unit tests for PaperTrader.compute_slippage."""

    def test_fallback_without_adv(self) -> None:
        trader = PaperTrader()
        result = trader.compute_slippage(
            spread_bps=10.0,
            kyle_lambda=0.0,
            size=Decimal("1"),
            price=Decimal("50000"),
            adv=0.0,
        )
        assert result == pytest.approx(5.0)  # spread/2 = 10/2

    def test_adv_path_uses_impact_model(self) -> None:
        trader = PaperTrader()
        result = trader.compute_slippage(
            spread_bps=5.0,
            kyle_lambda=1e-5,
            size=Decimal("100"),
            price=Decimal("50000"),
            adv=1_000_000.0,
            daily_vol=0.20,
        )
        assert result > 0.0

    def test_adv_path_larger_order_more_slippage(self) -> None:
        trader = PaperTrader()
        small = trader.compute_slippage(
            spread_bps=5.0,
            kyle_lambda=1e-5,
            size=Decimal("10"),
            price=Decimal("50000"),
            adv=1_000_000.0,
        )
        large = trader.compute_slippage(
            spread_bps=5.0,
            kyle_lambda=1e-5,
            size=Decimal("10000"),
            price=Decimal("50000"),
            adv=1_000_000.0,
        )
        assert large > small

    def test_fallback_never_negative(self) -> None:
        trader = PaperTrader()
        result = trader.compute_slippage(
            spread_bps=0.0,
            kyle_lambda=0.0,
            size=Decimal("0"),
            price=Decimal("100"),
        )
        assert result >= 0.0


class TestExecuteExit:
    @pytest.mark.asyncio
    async def test_exit_returns_dict_with_required_keys(self) -> None:
        trader = PaperTrader()
        position = {"symbol": "BTCUSDT", "entry": "50000"}
        result = await trader.execute_exit(
            position=position,
            exit_price=Decimal("51000"),
            size=Decimal("0.1"),
        )
        for key in ("symbol", "entry", "exit_price", "size", "commission", "is_paper"):
            assert key in result

    @pytest.mark.asyncio
    async def test_exit_is_paper_true(self) -> None:
        trader = PaperTrader()
        result = await trader.execute_exit(
            position={"symbol": "BTCUSDT", "entry": "50000"},
            exit_price=Decimal("51000"),
            size=Decimal("0.05"),
        )
        assert result["is_paper"] is True

    @pytest.mark.asyncio
    async def test_exit_price_below_quoted_due_to_slippage(self) -> None:
        """Exit simulated price should be lower than the quoted exit_price."""
        trader = PaperTrader()
        exit_p = Decimal("51000")
        result = await trader.execute_exit(
            position={"symbol": "BTCUSDT", "entry": "50000"},
            exit_price=exit_p,
            size=Decimal("0.1"),
        )
        assert Decimal(result["exit_price"]) < exit_p
