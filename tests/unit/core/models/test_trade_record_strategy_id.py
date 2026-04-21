"""Unit tests for the `strategy_id` field on the `TradeRecord` Pydantic model.

Mirrors ``tests/unit/core/models/test_order_candidate_strategy_id.py`` for
cross-model consistency per Phase A §2.2.1 / Charter §5.5 / ADR-0007 §D6.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from core.models.order import TradeRecord
from core.models.signal import Direction


def _make_trade(**overrides: object) -> TradeRecord:
    """Build a minimally valid TradeRecord, with optional overrides."""
    defaults: dict[str, Any] = {
        "trade_id": "trd-001",
        "symbol": "BTCUSDT",
        "direction": Direction.LONG,
        "entry_timestamp_ms": 1_700_000_000_000,
        "exit_timestamp_ms": 1_700_000_060_000,
        "entry_price": Decimal("100"),
        "exit_price": Decimal("105"),
        "size": Decimal("1.0"),
        "gross_pnl": Decimal("5"),
        "net_pnl": Decimal("4.9"),
        "commission": Decimal("0.05"),
        "slippage_cost": Decimal("0.05"),
    }
    defaults.update(overrides)
    return TradeRecord(**defaults)


# ── Defaults and preservation ────────────────────────────────────────────────


class TestStrategyIdDefault:
    def test_default_value_is_default(self) -> None:
        tr = _make_trade()
        assert tr.strategy_id == "default"

    def test_custom_value_preserved(self) -> None:
        tr = _make_trade(strategy_id="crypto_momentum")
        assert tr.strategy_id == "crypto_momentum"

    def test_non_default_snake_case_preserved(self) -> None:
        for sid in (
            "trend_following",
            "mean_rev_equities",
            "volatility_risk_premium",
            "macro_carry",
            "news_driven",
        ):
            assert _make_trade(strategy_id=sid).strategy_id == sid


# ── Frozen / immutability ────────────────────────────────────────────────────


class TestStrategyIdFrozen:
    def test_mutation_raises(self) -> None:
        tr = _make_trade(strategy_id="crypto_momentum")
        with pytest.raises(ValidationError):
            tr.__setattr__("strategy_id", "trend_following")


# ── Validator rejection cases ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " leading",
        "trailing ",
        "has space",
        "has\ttab",
        "has\nnewline",
        "has\u00a0nbsp",
        "has\u2003emspace",
        "has/slash",
        "has\\backslash",
        "has'quote",
        'has"dq',
        "a" * 65,
    ],
)
def test_invalid_strategy_id_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _make_trade(strategy_id=bad)


def test_max_length_boundary_accepted() -> None:
    """Length 64 is the max allowed (>64 is rejected)."""
    sid = "a" * 64
    tr = _make_trade(strategy_id=sid)
    assert tr.strategy_id == sid


# ── Hypothesis round-trip property ───────────────────────────────────────────


_ALLOWED_ALPHABET = st.characters(
    whitelist_categories=(),
    whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789_",
)

_valid_strategy_ids = st.text(
    alphabet=_ALLOWED_ALPHABET,
    min_size=1,
    max_size=64,
)


@given(strategy_id=_valid_strategy_ids)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_json_roundtrip_preserves_strategy_id(strategy_id: str) -> None:
    """For any valid ASCII snake_case id, JSON round-trip is lossless."""
    tr = _make_trade(strategy_id=strategy_id)
    restored = TradeRecord.model_validate_json(tr.model_dump_json())
    assert restored.strategy_id == strategy_id
    assert restored == tr


# ── Pre-existing invariant coverage ──────────────────────────────────────────
# Keep coverage on order.py ≥ 90% by exercising TradeRecord properties
# (is_winner, r_multiple) that otherwise have no dedicated test file.


class TestTradeRecordInvariants:
    def test_is_winner_true_for_positive_net_pnl(self) -> None:
        assert _make_trade(net_pnl=Decimal("1")).is_winner is True

    def test_is_winner_false_for_zero_net_pnl(self) -> None:
        assert _make_trade(net_pnl=Decimal("0")).is_winner is False

    def test_is_winner_false_for_negative_net_pnl(self) -> None:
        assert _make_trade(net_pnl=Decimal("-1")).is_winner is False

    def test_r_multiple_long_winner(self) -> None:
        tr = _make_trade(
            entry_price=Decimal("100"),
            exit_price=Decimal("105"),
            size=Decimal("1"),
            net_pnl=Decimal("5"),
        )
        assert tr.r_multiple == Decimal("1")

    def test_r_multiple_returns_none_when_no_move(self) -> None:
        tr = _make_trade(
            entry_price=Decimal("100"),
            exit_price=Decimal("100"),
            size=Decimal("1"),
            net_pnl=Decimal("0"),
        )
        assert tr.r_multiple is None
