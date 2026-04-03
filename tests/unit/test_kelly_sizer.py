"""Unit tests for KellySizer: Kelly criterion position sizing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.s04_fusion_engine.kelly_sizer import KellySizer


class TestKellySizer:
    """Tests for the KellySizer position sizing logic."""

    def setup_method(self) -> None:
        self.sizer = KellySizer()

    def test_kelly_fraction_positive_edge(self) -> None:
        """Positive edge (win_rate=0.6, rr=2.0) should give positive fraction."""
        f = self.sizer.kelly_fraction(win_rate=0.6, avg_rr=2.0)
        assert f > 0.0
        assert f <= 0.25  # quarter-Kelly cap

    def test_kelly_fraction_zero_edge(self) -> None:
        """Zero edge (break-even) should give zero fraction."""
        # f* = (p*b - q) / b; with p=0.5, b=1.0 → f* = 0
        f = self.sizer.kelly_fraction(win_rate=0.5, avg_rr=1.0)
        assert f == pytest.approx(0.0, abs=1e-9)

    def test_kelly_fraction_negative_edge_clamped(self) -> None:
        """Negative edge should be clamped to 0."""
        # p=0.3, b=1.0 → f* = (0.3 - 0.7) / 1.0 = -0.4 → clamped to 0
        f = self.sizer.kelly_fraction(win_rate=0.3, avg_rr=1.0)
        assert f == 0.0

    def test_kelly_fraction_high_win_rate_capped_at_quarter(self) -> None:
        """Very high win rate should be capped at 0.25."""
        f = self.sizer.kelly_fraction(win_rate=0.95, avg_rr=5.0)
        assert f <= 0.25

    def test_position_size_capped_at_ten_percent(self) -> None:
        """Position size should never exceed 10% of capital."""
        capital = Decimal("100000")
        size = self.sizer.position_size(
            capital=capital,
            kelly_f=0.5,  # artificially large to test cap
            regime_mult=1.0,
            session_mult=1.0,
            kyle_lambda=0.0,
            is_crypto=False,
        )
        assert size <= capital * Decimal("0.10") + Decimal("0.01")  # tolerance

    def test_crypto_size_multiplier_applied(self) -> None:
        """Crypto positions should be 70% of the equivalent equity size."""
        capital = Decimal("100000")
        equity_size = self.sizer.position_size(
            capital=capital,
            kelly_f=0.05,
            regime_mult=1.0,
            session_mult=1.0,
            kyle_lambda=0.0,
            is_crypto=False,
        )
        crypto_size = self.sizer.position_size(
            capital=capital,
            kelly_f=0.05,
            regime_mult=1.0,
            session_mult=1.0,
            kyle_lambda=0.0,
            is_crypto=True,
        )
        assert crypto_size == pytest.approx(float(equity_size) * 0.70, rel=1e-6)

    def test_illiquid_market_reduces_size(self) -> None:
        """High Kyle lambda (illiquid) should reduce position size."""
        capital = Decimal("100000")
        liquid = self.sizer.position_size(
            capital=capital, kelly_f=0.05, regime_mult=1.0,
            session_mult=1.0, kyle_lambda=0.0, is_crypto=False,
        )
        illiquid = self.sizer.position_size(
            capital=capital, kelly_f=0.05, regime_mult=1.0,
            session_mult=1.0, kyle_lambda=0.009, is_crypto=False,
        )
        assert illiquid < liquid

    def test_regime_mult_zero_gives_zero_size(self) -> None:
        """Regime multiplier of 0 (crisis) should result in zero size."""
        capital = Decimal("100000")
        size = self.sizer.position_size(
            capital=capital, kelly_f=0.05, regime_mult=0.0,
            session_mult=1.0, kyle_lambda=0.0, is_crypto=False,
        )
        assert size == Decimal("0")
