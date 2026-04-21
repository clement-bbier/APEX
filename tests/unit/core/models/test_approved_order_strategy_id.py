"""Unit tests for the `strategy_id` field on the `ApprovedOrder` Pydantic model.

Mirrors ``tests/unit/core/models/test_order_candidate_strategy_id.py`` for
cross-model consistency per Phase A §2.2.1 / Charter §5.5 / ADR-0007 §D6:

- default value is ``"default"`` (backward compatibility with the legacy
  single-strategy codebase);
- custom values are preserved verbatim;
- the model stays ``frozen=True`` so mutation is rejected;
- structurally unsafe identifiers (whitespace, slashes, quotes, empty,
  length > 64) are rejected for ZMQ/Redis/filesystem compatibility;
- JSON round-trip preserves any valid ASCII snake_case identifier.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from core.models.order import ApprovedOrder, OrderCandidate, OrderType
from core.models.signal import Direction


def _make_candidate(**overrides: object) -> OrderCandidate:
    """Build a minimally valid long-direction OrderCandidate, with optional overrides."""
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
    """Build a minimally valid ApprovedOrder, with optional overrides."""
    defaults: dict[str, Any] = {
        "candidate": _make_candidate(),
        "approved_at_ms": 1_700_000_001_000,
        "adjusted_size": Decimal("1.0"),
    }
    defaults.update(overrides)
    return ApprovedOrder(**defaults)


# ── Defaults and preservation ────────────────────────────────────────────────


class TestStrategyIdDefault:
    def test_default_value_is_default(self) -> None:
        ao = _make_approved()
        assert ao.strategy_id == "default"

    def test_custom_value_preserved(self) -> None:
        ao = _make_approved(strategy_id="crypto_momentum")
        assert ao.strategy_id == "crypto_momentum"

    def test_non_default_snake_case_preserved(self) -> None:
        for sid in (
            "trend_following",
            "mean_rev_equities",
            "volatility_risk_premium",
            "macro_carry",
            "news_driven",
        ):
            assert _make_approved(strategy_id=sid).strategy_id == sid


# ── Frozen / immutability ────────────────────────────────────────────────────


class TestStrategyIdFrozen:
    def test_mutation_raises(self) -> None:
        ao = _make_approved(strategy_id="crypto_momentum")
        with pytest.raises(ValidationError):
            ao.__setattr__("strategy_id", "trend_following")


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
        _make_approved(strategy_id=bad)


def test_max_length_boundary_accepted() -> None:
    """Length 64 is the max allowed (>64 is rejected)."""
    sid = "a" * 64
    ao = _make_approved(strategy_id=sid)
    assert ao.strategy_id == sid


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
    ao = _make_approved(strategy_id=strategy_id)
    restored = ApprovedOrder.model_validate_json(ao.model_dump_json())
    assert restored.strategy_id == strategy_id
    assert restored == ao


# ── Pre-existing invariant coverage ──────────────────────────────────────────
# Keep coverage on order.py ≥ 90% by exercising ApprovedOrder properties and
# defaults around regime_mult / order_type / notes.


class TestApprovedOrderInvariants:
    def test_order_id_delegates_to_candidate(self) -> None:
        ao = _make_approved(candidate=_make_candidate(order_id="ord-xyz"))
        assert ao.order_id == "ord-xyz"

    def test_symbol_delegates_to_candidate(self) -> None:
        ao = _make_approved(candidate=_make_candidate(symbol="ETHUSDT"))
        assert ao.symbol == "ETHUSDT"

    def test_default_order_type_is_limit(self) -> None:
        assert _make_approved().order_type == OrderType.LIMIT

    def test_regime_mult_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_approved(regime_mult=1.5)
