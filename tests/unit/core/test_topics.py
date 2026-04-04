"""Unit tests for core.topics.Topics.

Verifies format of topic strings and helper methods.
"""

from __future__ import annotations

from core.topics import Topics


def test_tick_topic_format() -> None:
    assert Topics.tick("crypto", "BTCUSDT") == "tick.crypto.BTCUSDT"


def test_tick_topic_uppercases_symbol() -> None:
    assert Topics.tick("crypto", "btcusdt") == "tick.crypto.BTCUSDT"
    assert Topics.tick("us_equity", "aapl") == "tick.us_equity.AAPL"


def test_signal_topic_format() -> None:
    assert Topics.signal("BTCUSDT") == "signal.technical.BTCUSDT"
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
