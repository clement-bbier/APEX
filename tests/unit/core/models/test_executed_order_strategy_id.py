"""Unit tests for the `strategy_id` field on the `ExecutedOrder` Pydantic model.

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

from core.models.order import ApprovedOrder, ExecutedOrder, OrderCandidate
from core.models.signal import Direction


def _make_candidate(**overrides: object) -> OrderCandidate:
    defaults: dict[str, Any] = {
        "order_id": "ord-001",
        "symbol": "BTCUSDT",
        "direction": Direction.LONG,
        "timestamp_ms": 1_700_000_000_000,
        "size": Decimal("1.0"),
        "size_scalp_exit": Decimal("0.3"),
        "size_swing_exit": Decimal("0.7"),
        "entry": Decimal("100"),
        "stop_loss": Decimal("95"),
        "target_scalp": Decimal("105"),
        "target_swing": Decimal("110"),
        "capital_at_risk": Decimal("5"),
    }
    defaults.update(overrides)
    return OrderCandidate(**defaults)


def _make_approved(**overrides: object) -> ApprovedOrder:
    defaults: dict[str, Any] = {
        "candidate": _make_candidate(),
        "approved_at_ms": 1_700_000_001_000,
        "adjusted_size": Decimal("1.0"),
    }
    defaults.update(overrides)
    return ApprovedOrder(**defaults)


def _make_executed(**overrides: object) -> ExecutedOrder:
    """Build a minimally valid ExecutedOrder, with optional overrides."""
    defaults: dict[str, Any] = {
        "approved_order": _make_approved(),
        "broker_order_id": "brk-001",
        "fill_price": Decimal("100.5"),
        "fill_size": Decimal("1.0"),
        "fill_timestamp_ms": 1_700_000_002_000,
    }
    defaults.update(overrides)
    return ExecutedOrder(**defaults)


# ── Defaults and preservation ────────────────────────────────────────────────


class TestStrategyIdDefault:
    def test_default_value_is_default(self) -> None:
        eo = _make_executed()
        assert eo.strategy_id == "default"

    def test_custom_value_preserved(self) -> None:
        eo = _make_executed(strategy_id="crypto_momentum")
        assert eo.strategy_id == "crypto_momentum"

    def test_non_default_snake_case_preserved(self) -> None:
        for sid in (
            "trend_following",
            "mean_rev_equities",
            "volatility_risk_premium",
            "macro_carry",
            "news_driven",
        ):
            assert _make_executed(strategy_id=sid).strategy_id == sid


# ── Frozen / immutability ────────────────────────────────────────────────────


class TestStrategyIdFrozen:
    def test_mutation_raises(self) -> None:
        eo = _make_executed(strategy_id="crypto_momentum")
        with pytest.raises(ValidationError):
            eo.__setattr__("strategy_id", "trend_following")


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
        _make_executed(strategy_id=bad)


def test_max_length_boundary_accepted() -> None:
    """Length 64 is the max allowed (>64 is rejected)."""
    sid = "a" * 64
    eo = _make_executed(strategy_id=sid)
    assert eo.strategy_id == sid


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
    eo = _make_executed(strategy_id=strategy_id)
    restored = ExecutedOrder.model_validate_json(eo.model_dump_json())
    assert restored.strategy_id == strategy_id
    assert restored == eo


# ── Pre-existing invariant coverage ──────────────────────────────────────────
# Keep coverage on order.py ≥ 90% by exercising ExecutedOrder properties and
# field defaults (is_paper, commission, slippage_bps).


class TestExecutedOrderInvariants:
    def test_order_id_delegates_to_approved(self) -> None:
        eo = _make_executed(
            approved_order=_make_approved(candidate=_make_candidate(order_id="ord-xyz"))
        )
        assert eo.order_id == "ord-xyz"

    def test_symbol_delegates_to_approved(self) -> None:
        eo = _make_executed(
            approved_order=_make_approved(candidate=_make_candidate(symbol="ETHUSDT"))
        )
        assert eo.symbol == "ETHUSDT"

    def test_is_paper_defaults_true(self) -> None:
        assert _make_executed().is_paper is True

    def test_fill_price_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _make_executed(fill_price=Decimal("0"))
