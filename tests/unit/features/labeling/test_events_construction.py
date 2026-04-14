"""Tests for features.labeling.events - event-time construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from features.labeling.events import build_events_from_signals


def _ts_utc(minute: int) -> datetime:
    return datetime(2024, 6, 1, tzinfo=UTC) + timedelta(minutes=minute)


def _make_signals(values: list[float | None]) -> pl.DataFrame:
    timestamps = [_ts_utc(i) for i in range(len(values))]
    return pl.DataFrame(
        {"timestamp": timestamps, "signal": values},
        schema={"timestamp": pl.Datetime("us", "UTC"), "signal": pl.Float64},
    )


class TestBuildEventsFromSignals:
    def test_threshold_triggers_events(self) -> None:
        signals = _make_signals([0.1, 0.5, 0.9, 0.2, 0.95])
        out = build_events_from_signals(signals, "signal", threshold=0.5, symbol="BTC")
        assert out["timestamp"].to_list() == [_ts_utc(2), _ts_utc(4)]

    def test_all_below_threshold_returns_empty(self) -> None:
        signals = _make_signals([0.1, 0.2, 0.3])
        out = build_events_from_signals(signals, "signal", threshold=0.9, symbol="BTC")
        assert len(out) == 0
        assert set(out.columns) == {"timestamp", "symbol", "direction"}

    def test_symbol_and_direction_populated(self) -> None:
        signals = _make_signals([0.8, 0.1, 0.7])
        out = build_events_from_signals(signals, "signal", threshold=0.5, symbol="ETH")
        assert out["symbol"].to_list() == ["ETH", "ETH"]
        assert out["direction"].to_list() == [1, 1]

    def test_tz_naive_raises(self) -> None:
        naive_ts = [datetime(2024, 6, 1) + timedelta(minutes=i) for i in range(5)]
        signals = pl.DataFrame({"timestamp": naive_ts, "signal": [0.8] * 5})
        with pytest.raises(ValueError, match="tz-naive"):
            build_events_from_signals(signals, "signal", threshold=0.5, symbol="BTC")

    def test_nan_signal_raises(self) -> None:
        signals = _make_signals([0.1, None, 0.3])
        with pytest.raises(ValueError, match="NaN/None"):
            build_events_from_signals(signals, "signal", threshold=0.2, symbol="BTC")

    def test_missing_column_raises(self) -> None:
        signals = _make_signals([0.1, 0.2])
        with pytest.raises(ValueError, match="signal_missing"):
            build_events_from_signals(signals, "signal_missing", threshold=0.5, symbol="BTC")

    def test_non_monotonic_raises(self) -> None:
        timestamps = [_ts_utc(0), _ts_utc(1), _ts_utc(1), _ts_utc(3)]
        signals = pl.DataFrame({"timestamp": timestamps, "signal": [0.1, 0.2, 0.3, 0.4]})
        with pytest.raises(ValueError, match="not strictly monotonic"):
            build_events_from_signals(signals, "signal", threshold=0.0, symbol="BTC")
