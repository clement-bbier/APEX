"""Tests for TradeAnalyzer attribution and Kelly stats update.

Regression suite for #258: ``analyze`` previously mixed Decimal
``TradeRecord`` fields with float defaults via a defensive
``getattr(trade, "...", 0.0) or 0.0`` pattern, raising
``TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and
'float'`` when the analyzer was fed real (Pydantic) ``TradeRecord``
objects. These tests use real ``TradeRecord`` instances — never Mock or
synthetic float-based dicts — so the regression bites if the bug is
ever reintroduced.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models.order import TradeRecord
from core.models.signal import Direction
from services.feedback_loop.trade_analyzer import TradeAnalyzer


def _make_trade(
    *,
    trade_id: str = "T1",
    symbol: str = "AAPL",
    entry_price: Decimal = Decimal("100"),
    exit_price: Decimal = Decimal("110"),
    net_pnl: Decimal = Decimal("100"),
    gross_pnl: Decimal = Decimal("110"),
    size: Decimal = Decimal("10"),
    signal_type: str = "COMPOSITE",
    regime_at_entry: str = "normal",
    session_at_entry: str = "us_prime",
    mtf_alignment_score: float = 0.8,
    strategy_id: str = "default",
) -> TradeRecord:
    """Build a real ``TradeRecord`` with safe defaults.

    Returns a fully-constructed Pydantic model — not a Mock — so that
    ``analyze`` operates on the same object shape it sees in production.
    """
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        direction=Direction.LONG,
        entry_timestamp_ms=1_700_000_000_000,
        exit_timestamp_ms=1_700_000_060_000,
        entry_price=entry_price,
        exit_price=exit_price,
        size=size,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        commission=Decimal("1"),
        slippage_cost=Decimal("0.5"),
        signal_type=signal_type,
        regime_at_entry=regime_at_entry,
        session_at_entry=session_at_entry,
        mtf_alignment_score=mtf_alignment_score,
        strategy_id=strategy_id,
    )


class TestTradeAnalyzer:
    def test_analyze_returns_required_keys(self) -> None:
        analyzer = TradeAnalyzer()
        trade = _make_trade()
        result = analyzer.analyze(trade)
        assert "signal_type" in result
        assert "regime_at_entry" in result
        assert "session" in result
        assert "r_multiple" in result
        assert "mtf_score" in result
        assert "expected_slippage_bps" in result
        assert "actual_outcome" in result

    def test_batch_analyze_length(self) -> None:
        analyzer = TradeAnalyzer()
        trades = [_make_trade(trade_id=f"T{i}") for i in range(5)]
        results = analyzer.batch_analyze(trades)
        assert len(results) == 5

    def test_actual_outcome_matches_net_pnl(self) -> None:
        analyzer = TradeAnalyzer()
        trade = _make_trade(net_pnl=Decimal("50"))
        result = analyzer.analyze(trade)
        assert result["actual_outcome"] == pytest.approx(50.0)

    def test_attribution_context_passes_through(self) -> None:
        """Signal/regime/session/mtf metadata is copied verbatim into the dict."""
        analyzer = TradeAnalyzer()
        trade = _make_trade(
            signal_type="HAR_RV",
            regime_at_entry="trending",
            session_at_entry="asia",
            mtf_alignment_score=0.42,
        )
        result = analyzer.analyze(trade)
        assert result["signal_type"] == "HAR_RV"
        assert result["regime_at_entry"] == "trending"
        assert result["session"] == "asia"
        assert result["mtf_score"] == pytest.approx(0.42)

    def test_empty_attribution_strings_default_to_unknown(self) -> None:
        """Pydantic default for signal_type/regime/session is ``""``; analyze
        coerces empty strings to ``"unknown"`` to preserve the legacy
        contract for downstream JSON consumers."""
        analyzer = TradeAnalyzer()
        trade = _make_trade(signal_type="", regime_at_entry="", session_at_entry="")
        result = analyzer.analyze(trade)
        assert result["signal_type"] == "unknown"
        assert result["regime_at_entry"] == "unknown"
        assert result["session"] == "unknown"

    @pytest.mark.asyncio
    async def test_update_kelly_stats_skips_below_5_trades(self) -> None:
        state = AsyncMock()
        analyzer = TradeAnalyzer(state=state)
        await analyzer._update_kelly_stats([_make_trade() for _ in range(3)])
        state.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_kelly_stats_no_state_is_noop(self) -> None:
        analyzer = TradeAnalyzer(state=None)
        # Should not raise even without state
        await analyzer._update_kelly_stats([_make_trade() for _ in range(10)])


class TestTradeAnalyzerWithRealTradeRecord:
    """Regression tests for #258.

    Bug: ``getattr(trade, "...", 0.0) or 0.0`` silently coerced Decimal
    ``TradeRecord`` fields to float, then raised ``TypeError`` on
    ``Decimal / float`` mixed arithmetic. These tests exercise the real
    Pydantic ``TradeRecord`` path so any future regression of the bug
    bites immediately.
    """

    def test_analyze_real_trade_record_no_typeerror(self) -> None:
        """Regression: real TradeRecord no longer raises TypeError."""
        trade = _make_trade()
        result = TradeAnalyzer().analyze(trade)
        assert isinstance(result, dict)
        # risk = |100 - 110| = 10, pnl = 100 → r_multiple = 10.0
        assert result["r_multiple"] == pytest.approx(10.0)
        assert result["actual_outcome"] == pytest.approx(100.0)

    def test_batch_analyze_real_trade_record_no_typeerror(self) -> None:
        """Regression: batch_analyze on real TradeRecord list."""
        trades = [_make_trade(trade_id=f"T{i}") for i in range(3)]
        result = TradeAnalyzer().batch_analyze(trades)
        assert len(result) == 3
        for entry in result:
            assert isinstance(entry, dict)
            assert "r_multiple" in entry

    def test_analyze_zero_risk_falls_back_to_unit_risk(self) -> None:
        """When entry == exit (zero price move), risk falls back to Decimal('1').

        Without this guard, ``pnl / risk`` would divide by zero.
        ``Decimal('1')`` lets the analyzer report ``r_multiple == net_pnl``
        rather than raising ZeroDivisionError.
        """
        trade = _make_trade(
            entry_price=Decimal("100"),
            exit_price=Decimal("100"),
            net_pnl=Decimal("50"),
        )
        result = TradeAnalyzer().analyze(trade)
        assert result["r_multiple"] == pytest.approx(50.0)

    def test_analyze_zero_pnl_returns_zero_r_multiple(self) -> None:
        """Zero PnL trade has r_multiple = 0."""
        trade = _make_trade(
            net_pnl=Decimal("0"),
            gross_pnl=Decimal("0"),
        )
        result = TradeAnalyzer().analyze(trade)
        assert result["r_multiple"] == pytest.approx(0.0)
        assert result["actual_outcome"] == pytest.approx(0.0)

    def test_analyze_negative_pnl_yields_negative_r_multiple(self) -> None:
        """Losing trade reports a negative r_multiple."""
        trade = _make_trade(
            entry_price=Decimal("100"),
            exit_price=Decimal("95"),
            net_pnl=Decimal("-50"),
        )
        result = TradeAnalyzer().analyze(trade)
        # risk = |100-95| = 5, pnl = -50 → r_multiple = -10.0
        assert result["r_multiple"] == pytest.approx(-10.0)

    def test_analyze_decimal_arithmetic_preserves_precision(self) -> None:
        """Sub-cent Decimal inputs survive without precision loss in the
        intermediate Decimal arithmetic (final cast to float for JSON is OK)."""
        trade = _make_trade(
            entry_price=Decimal("100.123456"),
            exit_price=Decimal("100.654321"),
            net_pnl=Decimal("5.302865"),
        )
        # risk = 0.530865, pnl = 5.302865 → r_multiple ≈ 9.989
        result = TradeAnalyzer().analyze(trade)
        assert result["r_multiple"] == pytest.approx(
            float(Decimal("5.302865") / Decimal("0.530865")), rel=1e-9
        )

    @given(
        entry_cents=st.integers(min_value=1, max_value=100_000),
        exit_cents=st.integers(min_value=1, max_value=100_000),
        pnl_cents=st.integers(min_value=-100_000, max_value=100_000),
    )
    @settings(max_examples=200, deadline=None)
    def test_property_no_typeerror_for_any_decimal_inputs(
        self,
        entry_cents: int,
        exit_cents: int,
        pnl_cents: int,
    ) -> None:
        """Property: arbitrary valid Decimal inputs never raise TypeError.

        Combined with the explicit r_multiple math tests above, this
        covers the failure surface that #258 originally exposed.
        """
        trade = _make_trade(
            entry_price=Decimal(entry_cents) / 100,
            exit_price=Decimal(exit_cents) / 100,
            net_pnl=Decimal(pnl_cents) / 100,
        )
        result = TradeAnalyzer().analyze(trade)
        assert isinstance(result, dict)
        assert "r_multiple" in result
        assert isinstance(result["r_multiple"], float)
