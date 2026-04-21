"""Tests for exposure_monitor.py (Phase 6).

All functions are pure -- no Redis, no async, no I/O.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.order import OrderCandidate
from core.models.signal import Direction
from services.risk_manager.exposure_monitor import (
    check_correlation,
    check_max_positions,
    check_per_class_exposure,
    check_total_exposure,
)
from services.risk_manager.models import BlockReason, Position

_CAPITAL = Decimal("100_000")


def _pos(symbol: str, size: str, price: str) -> Position:
    return Position(symbol=symbol, size=Decimal(size), entry_price=Decimal(price))


def _order(symbol: str = "BTCUSDT", size: str = "0.01", entry: str = "50000") -> OrderCandidate:
    sz = Decimal(size)
    return OrderCandidate(
        order_id="o1",
        symbol=symbol,
        direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000,
        size=sz,
        size_scalp_exit=sz * Decimal("0.35"),
        size_swing_exit=sz * Decimal("0.65"),
        entry=Decimal(entry),
        stop_loss=Decimal("49500"),
        target_scalp=Decimal("50750"),
        target_swing=Decimal("51500"),
        capital_at_risk=Decimal("5"),
    )


class TestMaxPositions:
    def test_at_limit_adds_one_fails(self) -> None:
        positions = [_pos(f"SYM{i}", "1", "100") for i in range(6)]
        r = check_max_positions(positions)
        assert not r.passed
        assert r.block_reason == BlockReason.MAX_POSITIONS_EXCEEDED

    def test_below_limit_passes(self) -> None:
        positions = [_pos(f"SYM{i}", "1", "100") for i in range(5)]
        r = check_max_positions(positions)
        assert r.passed

    def test_zero_positions_passes_all(self) -> None:
        r = check_max_positions([])
        assert r.passed


class TestTotalExposure:
    def test_exact_boundary_pass(self) -> None:
        # 19.9% existing: 19900 notional, new order adds 0, so 19900/100000 = 19.9%
        positions = [_pos("AAPL", "199", "100")]  # 199 * 100 = 19900
        r = check_total_exposure(
            _order(symbol="MSFT", size="0.001", entry="10"), positions, _CAPITAL
        )
        assert r.passed  # total = 19910/100000 = 19.91%

    def test_exact_boundary_fail(self) -> None:
        # 20.1%: new order takes total over
        positions = [_pos("AAPL", "199", "100")]  # 19900
        big_order = _order(symbol="MSFT", size="10", entry="30")  # adds 300
        r = check_total_exposure(big_order, positions, _CAPITAL)
        assert not r.passed  # 20200/100000 = 20.2%
        assert r.block_reason == BlockReason.MAX_TOTAL_EXPOSURE

    def test_new_order_counted_in_exposure(self) -> None:
        # Empty positions, large order
        big_order = _order(symbol="AAPL", size="21", entry="1000")  # 21000/100000 = 21%
        r = check_total_exposure(big_order, [], _CAPITAL)
        assert not r.passed


class TestPerClassExposure:
    def test_crypto_ceiling_pass(self) -> None:
        positions = [_pos("ETHUSDT", "0.001", "1000")]  # 1 USDT
        order = _order(symbol="BTCUSDT", size="0.001", entry="50000")  # 50 USDT
        r = check_per_class_exposure(order, positions, _CAPITAL)
        assert r.passed  # 51/100000 = 0.051%

    def test_crypto_ceiling_fail(self) -> None:
        positions = [_pos("ETHUSDT", "0.12", "100000")]  # 12000
        order = _order(symbol="BTCUSDT", size="0.001", entry="50000")  # adds 50
        r = check_per_class_exposure(order, positions, _CAPITAL)
        assert not r.passed  # 12050/100000 = 12.05% > 12%
        assert r.block_reason == BlockReason.MAX_CLASS_EXPOSURE

    def test_equity_separate_from_crypto(self) -> None:
        # 12% crypto does NOT block equity
        positions = [_pos("BTCUSDT", "0.12", "100000")]  # 12000 crypto
        equity_order = _order(symbol="AAPL", size="10", entry="100")  # 1000 equity
        r = check_per_class_exposure(equity_order, positions, _CAPITAL)
        assert r.passed


class TestCorrelation:
    def test_correlation_blocks_high_rho(self) -> None:
        positions = [_pos("AAPL", "10", "150")]
        corr = {("MSFT", "AAPL"): 0.76}
        r = check_correlation(_order(symbol="MSFT"), positions, corr)
        assert not r.passed
        assert r.block_reason == BlockReason.HIGH_CORRELATION

    def test_correlation_allows_low_rho(self) -> None:
        positions = [_pos("AAPL", "10", "150")]
        corr = {("MSFT", "AAPL"): 0.74}
        r = check_correlation(_order(symbol="MSFT"), positions, corr)
        assert r.passed

    def test_correlation_missing_pair_passes(self) -> None:
        positions = [_pos("AAPL", "10", "150")]
        r = check_correlation(_order(symbol="TSLA"), positions, {})
        assert r.passed

    def test_zero_positions_passes_all(self) -> None:
        r = check_correlation(_order(symbol="MSFT"), [], {})
        assert r.passed
