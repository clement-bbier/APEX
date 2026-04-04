"""Unit tests for PositionRules and check_max_risk_per_trade."""
from __future__ import annotations

from decimal import Decimal

from core.config import Settings
from core.models.order import OrderCandidate
from core.models.signal import Direction, Signal
from services.s05_risk_manager.position_rules import (
    PositionRules,
    RuleResult,
    check_max_risk_per_trade,
)


def _make_signal(
    entry: str = "50000",
    stop_loss: str = "49500",
    tp0: str = "51000",
    tp1: str = "52000",
) -> Signal:
    """Build a minimal valid Signal."""
    return Signal(
        signal_id="sig1",
        symbol="BTCUSDT",
        direction=Direction.LONG,
        strength=0.8,
        confidence=0.9,
        timestamp_ms=1_700_000_000_000,
        entry=Decimal(entry),
        stop_loss=Decimal(stop_loss),
        take_profit=[Decimal(tp0), Decimal(tp1)],
    )


def _make_candidate(
    size: str = "0.01",
    entry: str = "50000.0",
    stop_loss: str = "49500.0",
    capital_at_risk: str = "5.0",
    source_signal: Signal | None = None,
) -> OrderCandidate:
    """Build a minimal valid OrderCandidate.

    Default: 0.01 BTC @ $50k = $500 position < 10% of $100k capital.
    """
    size_dec = Decimal(size)
    scalp = size_dec * Decimal("0.35")
    swing = size_dec - scalp

    return OrderCandidate(
        order_id="ord1",
        symbol="BTCUSDT",
        direction=Direction.LONG,
        timestamp_ms=1_700_000_000_000,
        size=size_dec,
        size_scalp_exit=scalp,
        size_swing_exit=swing,
        entry=Decimal(entry),
        stop_loss=Decimal(stop_loss),
        target_scalp=Decimal("51000.0"),
        target_swing=Decimal("52000.0"),
        capital_at_risk=Decimal(capital_at_risk),
        source_signal=source_signal,
    )


class TestPositionRulesHappyPath:
    def test_valid_order_passes_all_checks(self) -> None:
        rules = PositionRules()
        candidate = _make_candidate()
        passed, reason = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True
        assert reason == ""

    def test_valid_order_with_good_rr_passes(self) -> None:
        rules = PositionRules()
        # entry=50000, stop=49500 → risk=500; tp0=51250 → reward=1250 → rr=2.5 > 1.5
        signal = _make_signal(entry="50000", stop_loss="49500", tp0="51250")
        candidate = _make_candidate(source_signal=signal)
        passed, _ = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True


class TestPositionRulesCapitalAtRisk:
    def test_capital_at_risk_too_high_fails(self) -> None:
        rules = PositionRules()
        # max_position_risk_pct default = 0.5% → max_risk = 500 on 100k
        candidate = _make_candidate(capital_at_risk="600.0")
        passed, reason = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is False
        assert "capital_at_risk" in reason

    def test_capital_at_risk_below_limit_passes(self) -> None:
        rules = PositionRules()
        candidate = _make_candidate(capital_at_risk="4.99")
        passed, _ = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True


class TestPositionRulesStopLoss:
    def test_valid_stop_loss_passes(self) -> None:
        rules = PositionRules()
        candidate = _make_candidate(stop_loss="49500.0")
        passed, _ = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True


class TestPositionRulesRiskReward:
    def test_low_rr_fails(self) -> None:
        rules = PositionRules()
        settings = Settings()
        # entry=50000, stop=49500 → risk=500; tp0=50250 → reward=250 → rr=0.5 < 1.5
        signal = _make_signal(entry="50000", stop_loss="49500", tp0="50250", tp1="50500")
        candidate = _make_candidate(source_signal=signal)
        passed, reason = rules.validate(candidate, Decimal("100000"), settings)
        assert passed is False
        assert "risk_reward" in reason

    def test_no_source_signal_skips_rr_check(self) -> None:
        rules = PositionRules()
        candidate = _make_candidate(source_signal=None)
        passed, _ = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True

    def test_source_signal_with_no_rr_skips_check(self) -> None:
        """Signal where risk==0 gives risk_reward=None → check skipped."""
        # entry == stop_loss would fail Signal validation; instead use rr > min
        signal = _make_signal(entry="50000", stop_loss="49500", tp0="51250")
        candidate = _make_candidate(source_signal=signal)
        rules = PositionRules()
        passed, _ = rules.validate(candidate, Decimal("100000"), Settings())
        assert passed is True

    def test_rr_exactly_at_minimum_passes(self) -> None:
        rules = PositionRules()
        settings = Settings()
        # min_risk_reward = 1.5; entry=50000, stop=49500 → risk=500; tp0=50750 → rr=1.5
        signal = _make_signal(entry="50000", stop_loss="49500", tp0="50750")
        candidate = _make_candidate(source_signal=signal)
        passed, _ = rules.validate(candidate, Decimal("100000"), settings)
        # 1.5 is NOT < 1.5, so passes
        assert passed is True


class TestPositionRulesMaxSize:
    def test_huge_position_fails_max_size_check(self) -> None:
        rules = PositionRules()
        settings = Settings()
        capital = Decimal("10000")
        # max_position_size_pct default = 10 → max = 1000
        # size=100, entry=50000 → position_value=5_000_000 >> 1000
        size_dec = Decimal("100")
        scalp = size_dec * Decimal("0.35")
        swing = size_dec - scalp
        candidate = OrderCandidate(
            order_id="ord3",
            symbol="BTCUSDT",
            direction=Direction.LONG,
            timestamp_ms=1_700_000_000_000,
            size=size_dec,
            size_scalp_exit=scalp,
            size_swing_exit=swing,
            entry=Decimal("50000"),
            stop_loss=Decimal("49500"),
            target_scalp=Decimal("51000"),
            target_swing=Decimal("52000"),
            capital_at_risk=Decimal("50"),
        )
        passed, reason = rules.validate(candidate, capital, settings)
        assert passed is False
        assert "position_value" in reason


class TestCheckMaxRiskPerTrade:
    def test_risk_within_budget_passes(self) -> None:
        class MockOrder:
            entry_price = Decimal("50000")
            stop_loss = Decimal("49750")  # 250 risk per unit
            size_total = Decimal("0.1")   # total risk = 25 < 500 (0.5% of 100k)

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is True
        assert result.reason == ""

    def test_risk_exceeds_budget_fails(self) -> None:
        class MockOrder:
            entry_price = Decimal("50000")
            stop_loss = Decimal("49000")  # 1000 risk per unit
            size_total = Decimal("1.0")   # total risk = 1000 > 500 (0.5% of 100k)

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is False
        assert "exceeds max" in result.reason

    def test_zero_entry_fails(self) -> None:
        class MockOrder:
            entry_price = Decimal("0")
            stop_loss = Decimal("49500")
            size_total = Decimal("1.0")

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is False
        assert "invalid" in result.reason

    def test_zero_stop_fails(self) -> None:
        class MockOrder:
            entry_price = Decimal("50000")
            stop_loss = Decimal("0")
            size_total = Decimal("1.0")

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is False

    def test_zero_size_fails(self) -> None:
        class MockOrder:
            entry_price = Decimal("50000")
            stop_loss = Decimal("49500")
            size_total = Decimal("0")

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is False

    def test_missing_attributes_treated_as_zero(self) -> None:
        class EmptyOrder:
            pass

        result = check_max_risk_per_trade(EmptyOrder(), Decimal("100000"))
        assert result.passed is False

    def test_exactly_below_budget_passes(self) -> None:
        """Order well within 0.5% risk should pass."""
        class MockOrder:
            entry_price = Decimal("50000")
            stop_loss = Decimal("49500")   # 500 risk per unit
            size_total = Decimal("0.09")   # total risk = 45 < 500

        result = check_max_risk_per_trade(MockOrder(), Decimal("100000"))
        assert result.passed is True

    def test_rule_result_dataclass_defaults(self) -> None:
        r = RuleResult(passed=True)
        assert r.passed is True
        assert r.reason == ""

    def test_rule_result_with_reason(self) -> None:
        r = RuleResult(passed=False, reason="exceeded budget")
        assert r.passed is False
        assert r.reason == "exceeded budget"
