"""Unit tests for core.topics.Topics.

Verifies format of topic strings and helper methods, including the
per-strategy ``signal_for`` factory introduced in Phase A §2.2.2.
"""

from __future__ import annotations

import re
import warnings

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.topics import Topics


def test_tick_topic_format() -> None:
    assert Topics.tick("crypto", "BTCUSDT") == "tick.crypto.BTCUSDT"


def test_tick_topic_uppercases_symbol() -> None:
    assert Topics.tick("crypto", "btcusdt") == "tick.crypto.BTCUSDT"
    assert Topics.tick("us_equity", "aapl") == "tick.us_equity.AAPL"


def test_signal_topic_format() -> None:
    with pytest.warns(DeprecationWarning, match="signal_for"):
        assert Topics.signal("BTCUSDT") == "signal.technical.BTCUSDT"
    with pytest.warns(DeprecationWarning, match="signal_for"):
        assert Topics.signal("ethusdt") == "signal.technical.ETHUSDT"


def test_health_topic_format() -> None:
    assert Topics.health("s01_data_ingestion") == "service.health.s01_data_ingestion"
    assert Topics.health("s05_risk_manager") == "service.health.s05_risk_manager"


def test_catalyst_topic_format() -> None:
    assert Topics.catalyst("FOMC") == "macro.catalyst.FOMC"
    assert Topics.catalyst("cpi") == "macro.catalyst.CPI"


def test_class_constants_are_strings() -> None:
    """All class-level attributes (non-callable, non-private) must be str."""
    for attr in dir(Topics):
        if attr.startswith("_"):
            continue
        value = getattr(Topics, attr)
        if callable(value):
            continue
        assert isinstance(value, str), f"Topics.{attr} should be str, got {type(value)}"


def test_no_hardcoded_topic_duplicates() -> None:
    """All class-level string constants must be unique."""
    values = [
        getattr(Topics, attr)
        for attr in dir(Topics)
        if not attr.startswith("_") and not callable(getattr(Topics, attr))
    ]
    assert len(values) == len(set(values)), "Duplicate topic string constants found"


# ── signal_for factory (Phase A §2.2.2, Charter §5.5, ADR-0007 §D7) ─────────


def test_signal_for_format_named_strategy() -> None:
    assert (
        Topics.signal_for("crypto_momentum", "BTCUSDT")
        == "signal.technical.crypto_momentum.BTCUSDT"
    )


def test_signal_for_format_default_strategy() -> None:
    assert Topics.signal_for("default", "BTCUSDT") == "signal.technical.default.BTCUSDT"


def test_signal_for_uppercases_symbol() -> None:
    assert (
        Topics.signal_for("crypto_momentum", "btcusdt")
        == "signal.technical.crypto_momentum.BTCUSDT"
    )


def test_signal_for_is_static_method() -> None:
    assert isinstance(Topics.__dict__["signal_for"], staticmethod)


@pytest.mark.parametrize(
    "bad_strategy_id",
    ["", " ", "   ", "a b", "a/b", "a\\b", "a'b", 'a"b', "a" * 65],
)
def test_signal_for_rejects_invalid_strategy_id(bad_strategy_id: str) -> None:
    with pytest.raises(ValueError, match="strategy_id"):
        Topics.signal_for(bad_strategy_id, "BTCUSDT")


@pytest.mark.parametrize("bad_symbol", ["", " ", "   ", "sym with space"])
def test_signal_for_rejects_invalid_symbol(bad_symbol: str) -> None:
    with pytest.raises(ValueError, match="symbol"):
        Topics.signal_for("default", bad_symbol)


def test_signal_for_accepts_max_length_strategy_id() -> None:
    """Boundary: exactly 64 chars is allowed; 65 is rejected (covered above)."""
    sid = "a" * 64
    assert Topics.signal_for(sid, "BTCUSDT") == f"signal.technical.{sid}.BTCUSDT"


_VALID_ID_CHARS = st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"),
    whitelist_characters="_-",
)
_VALID_SYM_CHARS = st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"),
)


@given(
    strategy_id=st.text(alphabet=_VALID_ID_CHARS, min_size=1, max_size=64),
    symbol=st.text(alphabet=_VALID_SYM_CHARS, min_size=1, max_size=16),
)
@settings(max_examples=100)
def test_signal_for_property_prefix_and_dot_count(strategy_id: str, symbol: str) -> None:
    """Any valid (strategy_id, symbol) yields ``signal.technical.<sid>.<sym>``.

    The result must start with the canonical prefix and have exactly two
    additional dots (one between prefix and strategy_id, one between
    strategy_id and symbol). strategy_id and symbol themselves are
    constrained by hypothesis to alphanumerics + ``_``/``-``, so no
    extra dots can leak in.
    """
    topic = Topics.signal_for(strategy_id, symbol)
    assert topic.startswith("signal.technical.")
    suffix = topic[len("signal.technical.") :]
    assert suffix.count(".") == 1
    assert re.fullmatch(r"signal\.technical\.[^.]+\.[^.]+", topic) is not None


def test_signal_for_emits_no_deprecation_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        Topics.signal_for("crypto_momentum", "BTCUSDT")


def test_legacy_signal_emits_deprecation_warning() -> None:
    with pytest.warns(DeprecationWarning, match="signal_for"):
        result = Topics.signal("BTCUSDT")
    assert result == "signal.technical.BTCUSDT"
