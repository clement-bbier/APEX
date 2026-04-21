"""Tests for gap detector (pure function + Hypothesis property tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from services.data_ingestion.orchestrator.gap_detector import Gap, detect_gaps

_INTERVAL = timedelta(minutes=1)
_BASE = datetime(2025, 1, 1, tzinfo=UTC)


class TestDetectGaps:
    """Tests for detect_gaps."""

    def test_no_gaps_in_contiguous_data(self) -> None:
        timestamps = [_BASE + _INTERVAL * i for i in range(10)]
        gaps = detect_gaps(timestamps, _INTERVAL, _BASE, timestamps[-1] + _INTERVAL)
        assert gaps == []

    def test_single_gap_detected(self) -> None:
        timestamps = [
            _BASE,
            _BASE + timedelta(minutes=1),
            _BASE + timedelta(minutes=2),
            # gap: 3 and 4 missing
            _BASE + timedelta(minutes=5),
        ]
        gaps = detect_gaps(
            timestamps,
            _INTERVAL,
            _BASE,
            _BASE + timedelta(minutes=6),
        )
        assert len(gaps) == 1
        assert gaps[0].start == _BASE + timedelta(minutes=2)
        assert gaps[0].end == _BASE + timedelta(minutes=5)

    def test_multiple_gaps_detected(self) -> None:
        timestamps = [
            _BASE,
            # gap
            _BASE + timedelta(minutes=5),
            _BASE + timedelta(minutes=6),
            # gap
            _BASE + timedelta(minutes=10),
        ]
        gaps = detect_gaps(
            timestamps,
            _INTERVAL,
            _BASE,
            _BASE + timedelta(minutes=11),
        )
        assert len(gaps) == 2

    def test_empty_timestamps_returns_gap(self) -> None:
        start = _BASE
        end = _BASE + timedelta(hours=1)
        gaps = detect_gaps([], _INTERVAL, start, end)
        assert len(gaps) == 1
        assert gaps[0].start == start
        assert gaps[0].end == end

    def test_empty_timestamps_no_gap_if_short_window(self) -> None:
        start = _BASE
        end = _BASE + timedelta(seconds=30)
        gaps = detect_gaps([], _INTERVAL, start, end)
        assert gaps == []

    def test_gap_at_beginning(self) -> None:
        timestamps = [_BASE + timedelta(minutes=5)]
        gaps = detect_gaps(timestamps, _INTERVAL, _BASE, _BASE + timedelta(minutes=6))
        assert len(gaps) >= 1
        assert gaps[0].start == _BASE
        assert gaps[0].end == _BASE + timedelta(minutes=5)

    def test_gap_at_end(self) -> None:
        timestamps = [_BASE]
        end = _BASE + timedelta(minutes=10)
        gaps = detect_gaps(timestamps, _INTERVAL, _BASE, end)
        assert len(gaps) >= 1
        assert gaps[-1].start == _BASE
        assert gaps[-1].end == end


class TestGapModel:
    """Tests for the Gap model."""

    def test_duration_property(self) -> None:
        gap = Gap(
            start=_BASE,
            end=_BASE + timedelta(hours=2),
            expected_interval=_INTERVAL,
        )
        assert gap.duration == timedelta(hours=2)


class TestGapDetectorHypothesis:
    """Property-based tests for detect_gaps."""

    @given(
        n=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_contiguous_data_has_no_interior_gaps(self, n: int) -> None:
        """Perfectly spaced timestamps should never produce interior gaps."""
        interval = timedelta(minutes=5)
        timestamps = [_BASE + interval * i for i in range(n)]
        if not timestamps:
            return
        start = timestamps[0]
        end = timestamps[-1] + interval
        gaps = detect_gaps(timestamps, interval, start, end)
        # No gaps between consecutive points (may have boundary gaps)
        interior_gaps = [g for g in gaps if g.start != start and g.end != end]
        assert interior_gaps == []
