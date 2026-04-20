"""Unit tests for the `strategy_id` field on the `Signal` Pydantic model.

Covers Phase A §2.2.1 / Charter §5.5 / ADR-0007 §D6:

- default value is `"default"` (backward compatibility with the legacy
  single-strategy codebase);
- custom values are preserved verbatim;
- the model stays `frozen=True` so mutation is rejected;
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

from core.models.signal import Direction, Signal


def _make_signal(**overrides: object) -> Signal:
    """Build a minimally valid long-direction Signal, with optional overrides."""
    defaults: dict[str, Any] = {
        "signal_id": "sig-001",
        "symbol": "BTCUSDT",
        "timestamp_ms": 1_700_000_000_000,
        "direction": Direction.LONG,
        "strength": 0.5,
        "entry": Decimal("100"),
        "stop_loss": Decimal("95"),
        "take_profit": [Decimal("105"), Decimal("110")],
    }
    defaults.update(overrides)
    return Signal(**defaults)


# ── Defaults and preservation ────────────────────────────────────────────────


class TestStrategyIdDefault:
    def test_default_value_is_default(self) -> None:
        sig = _make_signal()
        assert sig.strategy_id == "default"

    def test_custom_value_preserved(self) -> None:
        sig = _make_signal(strategy_id="crypto_momentum")
        assert sig.strategy_id == "crypto_momentum"

    def test_non_default_snake_case_preserved(self) -> None:
        for sid in (
            "trend_following",
            "mean_rev_equities",
            "volatility_risk_premium",
            "macro_carry",
            "news_driven",
        ):
            assert _make_signal(strategy_id=sid).strategy_id == sid


# ── Frozen / immutability ────────────────────────────────────────────────────


class TestStrategyIdFrozen:
    def test_mutation_raises(self) -> None:
        sig = _make_signal(strategy_id="crypto_momentum")
        with pytest.raises(ValidationError):
            sig.__setattr__("strategy_id", "trend_following")


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
        "has/slash",
        "has\\backslash",
        "has'quote",
        'has"dq',
        "a" * 65,
    ],
)
def test_invalid_strategy_id_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _make_signal(strategy_id=bad)


def test_max_length_boundary_accepted() -> None:
    """Length 64 is the max allowed (>64 is rejected)."""
    sid = "a" * 64
    sig = _make_signal(strategy_id=sid)
    assert sig.strategy_id == sid


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
    sig = _make_signal(strategy_id=strategy_id)
    restored = Signal.model_validate_json(sig.model_dump_json())
    assert restored.strategy_id == strategy_id
    assert restored == sig


# ── Pre-existing invariant coverage ──────────────────────────────────────────
# Exercise the Signal model_validator and risk_reward property so that adding
# the strategy_id field does not regress overall coverage on signal.py below
# the 90% gate required by Roadmap §2.2.1 acceptance.


class TestPriceLevelValidator:
    def test_long_stop_above_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_signal(
                direction=Direction.LONG,
                entry=Decimal("100"),
                stop_loss=Decimal("105"),
                take_profit=[Decimal("110"), Decimal("120")],
            )

    def test_long_tp_below_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_signal(
                direction=Direction.LONG,
                entry=Decimal("100"),
                stop_loss=Decimal("95"),
                take_profit=[Decimal("99"), Decimal("98")],
            )

    def test_short_happy_path(self) -> None:
        sig = _make_signal(
            direction=Direction.SHORT,
            strength=-0.5,
            entry=Decimal("100"),
            stop_loss=Decimal("105"),
            take_profit=[Decimal("95"), Decimal("90")],
        )
        assert sig.direction == Direction.SHORT

    def test_short_stop_below_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_signal(
                direction=Direction.SHORT,
                strength=-0.5,
                entry=Decimal("100"),
                stop_loss=Decimal("95"),
                take_profit=[Decimal("90"), Decimal("85")],
            )

    def test_short_tp_above_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_signal(
                direction=Direction.SHORT,
                strength=-0.5,
                entry=Decimal("100"),
                stop_loss=Decimal("105"),
                take_profit=[Decimal("101"), Decimal("102")],
            )


class TestRiskReward:
    def test_risk_reward_long(self) -> None:
        sig = _make_signal(
            entry=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=[Decimal("110"), Decimal("120")],
        )
        assert sig.risk_reward == Decimal("2")

    def test_risk_reward_zero_risk_returns_none(self) -> None:
        # Direction.FLAT bypasses the price-level validator, allowing entry==stop.
        sig = _make_signal(
            direction=Direction.FLAT,
            strength=0.0,
            entry=Decimal("100"),
            stop_loss=Decimal("100"),
            take_profit=[Decimal("110"), Decimal("120")],
        )
        assert sig.risk_reward is None
