"""Unit tests for the `strategy_id` field on the `OrderCandidate` Pydantic model.

Mirrors ``tests/unit/core/models/test_signal_strategy_id.py`` for cross-model
consistency per Phase A §2.2.1 / Charter §5.5 / ADR-0007 §D6:

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

from core.models.order import OrderCandidate
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


# ── Defaults and preservation ────────────────────────────────────────────────


class TestStrategyIdDefault:
    def test_default_value_is_default(self) -> None:
        cand = _make_candidate()
        assert cand.strategy_id == "default"

    def test_custom_value_preserved(self) -> None:
        cand = _make_candidate(strategy_id="crypto_momentum")
        assert cand.strategy_id == "crypto_momentum"

    def test_non_default_snake_case_preserved(self) -> None:
        for sid in (
            "trend_following",
            "mean_rev_equities",
            "volatility_risk_premium",
            "macro_carry",
            "news_driven",
        ):
            assert _make_candidate(strategy_id=sid).strategy_id == sid


# ── Frozen / immutability ────────────────────────────────────────────────────


class TestStrategyIdFrozen:
    def test_mutation_raises(self) -> None:
        cand = _make_candidate(strategy_id="crypto_momentum")
        with pytest.raises(ValidationError):
            cand.__setattr__("strategy_id", "trend_following")


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
        _make_candidate(strategy_id=bad)


def test_max_length_boundary_accepted() -> None:
    """Length 64 is the max allowed (>64 is rejected)."""
    sid = "a" * 64
    cand = _make_candidate(strategy_id=sid)
    assert cand.strategy_id == sid


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
    cand = _make_candidate(strategy_id=strategy_id)
    restored = OrderCandidate.model_validate_json(cand.model_dump_json())
    assert restored.strategy_id == strategy_id
    assert restored == cand


# ── Pre-existing invariant coverage ──────────────────────────────────────────
# Exercise the OrderCandidate.validate_exit_sizes model_validator so that
# adding the strategy_id field does not regress overall coverage on order.py
# below the 90% gate required by Roadmap §2.2.1 acceptance.


class TestExitSizeValidator:
    def test_exit_sizes_sum_to_total(self) -> None:
        cand = _make_candidate(
            size=Decimal("1.0"),
            size_scalp_exit=Decimal("0.4"),
            size_swing_exit=Decimal("0.6"),
        )
        assert cand.size_scalp_exit + cand.size_swing_exit == cand.size

    def test_exit_sizes_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_candidate(
                size=Decimal("1.0"),
                size_scalp_exit=Decimal("0.3"),
                size_swing_exit=Decimal("0.5"),
            )

    def test_exit_sizes_within_tolerance_accepted(self) -> None:
        """Rounding errors below 1e-4 should not raise."""
        cand = _make_candidate(
            size=Decimal("1.0"),
            size_scalp_exit=Decimal("0.30005"),
            size_swing_exit=Decimal("0.69995"),
        )
        assert cand.size == Decimal("1.0")
