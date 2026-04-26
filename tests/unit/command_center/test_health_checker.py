"""Unit tests for ``services.command_center.health_checker``.

Sprint 4 Vague 2 coverage push — prerequisite for #203.

Covers per-service heartbeat tracking, liveness windows, aggregate dead-service
detection, and percentile latency statistics over the rolling arrival buffer.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services.command_center.health_checker import HealthChecker

# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    def test_starts_with_empty_last_seen(self) -> None:
        hc = HealthChecker()
        assert hc._last_seen == {}

    def test_starts_with_empty_arrival_times_defaultdict(self) -> None:
        hc = HealthChecker()
        # defaultdict returns an empty deque for any unseen key
        assert len(hc._arrival_times["unknown"]) == 0

    def test_arrival_deque_has_maxlen_100(self) -> None:
        hc = HealthChecker()
        dq = hc._arrival_times["signal_engine"]
        assert isinstance(dq, deque)
        assert dq.maxlen == 100

    def test_service_ids_contains_all_nine_core_services(self) -> None:
        expected = {
            "data_ingestion",
            "signal_engine",
            "regime_detector",
            "fusion_engine",
            "risk_manager",
            "execution",
            "quant_analytics",
            "macro_intelligence",
            "feedback_loop",
        }
        assert set(HealthChecker.SERVICE_IDS) == expected

    def test_service_ids_is_stable_across_instances(self) -> None:
        a = HealthChecker()
        b = HealthChecker()
        assert a.SERVICE_IDS is b.SERVICE_IDS


# ---------------------------------------------------------------------------
# TestRecordHeartbeat
# ---------------------------------------------------------------------------


class TestRecordHeartbeat:
    def test_records_last_seen_using_time_time(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", timestamp_ms=123456)
        assert hc._last_seen["signal_engine"] == 1000.0

    def test_appends_to_arrival_times_deque(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=42.0):
            hc.record_heartbeat("risk_manager", timestamp_ms=0)
        assert list(hc._arrival_times["risk_manager"]) == [42.0]

    def test_multiple_heartbeats_accumulate_in_order(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[1.0, 2.0, 3.0],
        ):
            hc.record_heartbeat("execution", 0)
            hc.record_heartbeat("execution", 0)
            hc.record_heartbeat("execution", 0)
        assert list(hc._arrival_times["execution"]) == [1.0, 2.0, 3.0]
        assert hc._last_seen["execution"] == 3.0

    def test_deque_caps_at_100_entries(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[float(i) for i in range(150)],
        ):
            for _ in range(150):
                hc.record_heartbeat("data_ingestion", 0)
        dq = hc._arrival_times["data_ingestion"]
        assert len(dq) == 100
        # Oldest 50 were discarded; buffer now holds t=50..149
        assert dq[0] == 50.0
        assert dq[-1] == 149.0

    def test_accepts_unknown_service_id(self) -> None:
        """Heartbeats for services not in SERVICE_IDS are still recorded."""
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=5.0):
            hc.record_heartbeat("custom_service", 0)
        assert hc._last_seen["custom_service"] == 5.0

    def test_each_service_has_independent_deque(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[1.0, 2.0],
        ):
            hc.record_heartbeat("signal_engine", 0)
            hc.record_heartbeat("risk_manager", 0)
        assert list(hc._arrival_times["signal_engine"]) == [1.0]
        assert list(hc._arrival_times["risk_manager"]) == [2.0]

    def test_timestamp_ms_parameter_is_not_used_for_state(self) -> None:
        """Implementation uses ``time.time()``; ``timestamp_ms`` is informational."""
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=99.0):
            hc.record_heartbeat("fusion_engine", timestamp_ms=0)
            hc.record_heartbeat("fusion_engine", timestamp_ms=10**12)
        # Both entries reflect patched wall clock, not the caller-supplied value
        assert list(hc._arrival_times["fusion_engine"]) == [99.0, 99.0]


# ---------------------------------------------------------------------------
# TestIsAlive
# ---------------------------------------------------------------------------


class TestIsAlive:
    def test_unknown_service_is_not_alive(self) -> None:
        hc = HealthChecker()
        assert hc.is_alive("never_seen") is False

    def test_service_heartbeat_just_now_is_alive(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
            assert hc.is_alive("signal_engine") is True

    def test_silence_inside_default_window_is_alive(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        # 9.9s later — inside 10_000ms default window
        with patch("services.command_center.health_checker.time.time", return_value=1009.9):
            assert hc.is_alive("signal_engine") is True

    def test_silence_past_default_window_is_dead(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        # 10.1s later — outside 10_000ms default window
        with patch("services.command_center.health_checker.time.time", return_value=1010.1):
            assert hc.is_alive("signal_engine") is False

    def test_exact_boundary_is_not_alive(self) -> None:
        """Strict `<` in impl means exactly-10s-old is considered dead."""
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=1010.0):
            assert hc.is_alive("signal_engine") is False

    def test_custom_timeout_extends_window(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=1025.0):
            assert hc.is_alive("signal_engine", timeout_ms=30_000) is True
            assert hc.is_alive("signal_engine", timeout_ms=5_000) is False

    def test_zero_timeout_always_dead(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            assert hc.is_alive("signal_engine", timeout_ms=0) is False


# ---------------------------------------------------------------------------
# TestGetDeadServices
# ---------------------------------------------------------------------------


class TestGetDeadServices:
    def test_all_services_dead_on_fresh_instance(self) -> None:
        hc = HealthChecker()
        dead = hc.get_dead_services()
        assert set(dead) == set(HealthChecker.SERVICE_IDS)
        assert len(dead) == len(HealthChecker.SERVICE_IDS)

    def test_returns_empty_when_all_services_recently_seen(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=500.0):
            for sid in HealthChecker.SERVICE_IDS:
                hc.record_heartbeat(sid, 0)
            assert hc.get_dead_services() == []

    def test_reports_only_silent_services(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=100.0):
            hc.record_heartbeat("signal_engine", 0)
            hc.record_heartbeat("risk_manager", 0)
        with patch("services.command_center.health_checker.time.time", return_value=100.5):
            dead = hc.get_dead_services()
        assert "signal_engine" not in dead
        assert "risk_manager" not in dead
        # All other SERVICE_IDS are dead
        expected_dead = set(HealthChecker.SERVICE_IDS) - {
            "signal_engine",
            "risk_manager",
        }
        assert set(dead) == expected_dead

    def test_ignores_unknown_services_even_if_heartbeating(self) -> None:
        """Only SERVICE_IDS members participate in the dead-service roll-up."""
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=10.0):
            hc.record_heartbeat("rogue_service", 0)
        dead = hc.get_dead_services()
        assert "rogue_service" not in dead
        # All known services remain dead
        assert set(dead) == set(HealthChecker.SERVICE_IDS)

    def test_preserves_service_ids_order(self) -> None:
        hc = HealthChecker()
        dead = hc.get_dead_services()
        assert dead == list(HealthChecker.SERVICE_IDS)

    def test_stale_heartbeat_makes_service_dead_again(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=0.0):
            hc.record_heartbeat("execution", 0)
        # 20s of silence — past 10s default
        with patch("services.command_center.health_checker.time.time", return_value=20.0):
            assert "execution" in hc.get_dead_services()


# ---------------------------------------------------------------------------
# TestLatencyStats
# ---------------------------------------------------------------------------


class TestLatencyStats:
    def test_empty_instance_returns_none_percentiles_for_every_service(self) -> None:
        hc = HealthChecker()
        stats = hc.latency_stats()
        assert set(stats.keys()) == set(HealthChecker.SERVICE_IDS)
        for sid in HealthChecker.SERVICE_IDS:
            assert stats[sid] == {
                "p50": None,
                "p95": None,
                "p99": None,
                "alive": False,
            }

    def test_single_heartbeat_yields_none_percentiles(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=100.0):
            hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=100.5):
            stats = hc.latency_stats()
        # Need >= 2 samples to compute a delta
        assert stats["signal_engine"]["p50"] is None
        assert stats["signal_engine"]["p95"] is None
        assert stats["signal_engine"]["p99"] is None
        assert stats["signal_engine"]["alive"] is True

    def test_constant_cadence_yields_constant_percentiles(self) -> None:
        """Ten 1s-apart heartbeats → all percentiles should equal 1000ms."""
        hc = HealthChecker()
        timestamps = [float(i) for i in range(10)]
        with patch("services.command_center.health_checker.time.time", side_effect=timestamps):
            for _ in timestamps:
                hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=9.5):
            stats = hc.latency_stats()
        row = stats["signal_engine"]
        assert row["p50"] == pytest.approx(1000.0)
        assert row["p95"] == pytest.approx(1000.0)
        assert row["p99"] == pytest.approx(1000.0)
        assert row["alive"] is True

    def test_percentile_ordering_p50_le_p95_le_p99(self) -> None:
        """For any realistic cadence the percentiles are monotonic."""
        hc = HealthChecker()
        # Irregular arrivals: short then long gaps
        schedule = [0.0, 0.1, 0.3, 0.4, 1.5, 1.6, 3.0, 5.0, 5.05, 10.0]
        with patch("services.command_center.health_checker.time.time", side_effect=schedule):
            for _ in schedule:
                hc.record_heartbeat("risk_manager", 0)
        with patch("services.command_center.health_checker.time.time", return_value=10.5):
            stats = hc.latency_stats()
        row = stats["risk_manager"]
        assert row["p50"] <= row["p95"] <= row["p99"]

    def test_dead_service_reports_alive_false_in_stats(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[0.0, 1.0, 2.0],
        ):
            hc.record_heartbeat("execution", 0)
            hc.record_heartbeat("execution", 0)
            hc.record_heartbeat("execution", 0)
        with patch("services.command_center.health_checker.time.time", return_value=1_000.0):
            stats = hc.latency_stats()
        assert stats["execution"]["alive"] is False
        assert stats["execution"]["p50"] == pytest.approx(1000.0)

    def test_other_services_with_no_data_still_appear_in_output(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[0.0, 0.1, 0.2],
        ):
            hc.record_heartbeat("signal_engine", 0)
            hc.record_heartbeat("signal_engine", 0)
            hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=0.3):
            stats = hc.latency_stats()
        # Every SERVICE_ID has an entry, unpopulated ones have None percentiles
        for sid in HealthChecker.SERVICE_IDS:
            assert sid in stats
        assert stats["risk_manager"]["p50"] is None
        assert stats["signal_engine"]["p50"] is not None

    def test_percentiles_returned_as_python_floats(self) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[0.0, 0.1, 0.2, 0.3],
        ):
            for _ in range(4):
                hc.record_heartbeat("signal_engine", 0)
        with patch("services.command_center.health_checker.time.time", return_value=0.5):
            row = hc.latency_stats()["signal_engine"]
        assert isinstance(row["p50"], float)
        assert isinstance(row["p95"], float)
        assert isinstance(row["p99"], float)

    def test_large_outlier_raises_high_percentiles_more_than_median(self) -> None:
        """Inject one huge gap; p99 should jump far higher than p50."""
        hc = HealthChecker()
        # 20 arrivals: 19 evenly spaced, then a big gap
        ts = [float(i) * 0.1 for i in range(19)]
        ts.append(ts[-1] + 10.0)  # 10-second outlier gap
        with patch("services.command_center.health_checker.time.time", side_effect=ts):
            for _ in ts:
                hc.record_heartbeat("macro_intelligence", 0)
        with patch("services.command_center.health_checker.time.time", return_value=ts[-1]):
            row = hc.latency_stats()["macro_intelligence"]
        assert row["p99"] > row["p50"] * 10


# ---------------------------------------------------------------------------
# TestBoundary — explicit liveness-window edge cases
# ---------------------------------------------------------------------------


class TestBoundary:
    """Explicit boundary tests for ``is_alive`` semantics.

    Reinforces the property test by pinning down each side of the
    ``age < timeout`` boundary with a named case. Originally added after a
    Hypothesis flake at ``age_ms == timeout_ms`` caused by float-to-ms
    round-trip imprecision (e.g. ``512035 / 1000 * 1000 == 512034.99...``).
    """

    def test_age_zero_is_alive(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
            assert hc.is_alive("signal_engine", timeout_ms=10_000) is True

    def test_age_one_below_timeout_is_alive(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        # 9.999s elapsed = 9999ms = timeout − 1
        with patch("services.command_center.health_checker.time.time", return_value=1009.999):
            assert hc.is_alive("signal_engine", timeout_ms=10_000) is True

    def test_age_equals_timeout_is_dead(self) -> None:
        """Boundary case that originally triggered the Hypothesis flake."""
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=0.0):
            hc.record_heartbeat("signal_engine", 0)
        # age_ms == timeout_ms, including the FP-pathological 512035 case
        for boundary_ms in (10_000, 512_035, 1_000_000):
            with patch(
                "services.command_center.health_checker.time.time",
                return_value=boundary_ms / 1000.0,
            ):
                assert hc.is_alive("signal_engine", timeout_ms=boundary_ms) is False

    def test_age_above_timeout_is_dead(self) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1000.0):
            hc.record_heartbeat("signal_engine", 0)
        # 10.001s elapsed = 10001ms = timeout + 1
        with patch("services.command_center.health_checker.time.time", return_value=1010.001):
            assert hc.is_alive("signal_engine", timeout_ms=10_000) is False


# ---------------------------------------------------------------------------
# TestPropertyInvariants — Hypothesis
# ---------------------------------------------------------------------------


class TestPropertyInvariants:
    @given(
        arrivals=st.lists(
            st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False),
            min_size=2,
            max_size=50,
        ),
    )
    @settings(max_examples=50, deadline=None)
    def test_percentiles_are_monotonic_for_any_arrivals(self, arrivals: list[float]) -> None:
        """p50 <= p95 <= p99 is a mathematical invariant of numpy.percentile."""
        hc = HealthChecker()
        sorted_arrivals = sorted(arrivals)
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=sorted_arrivals,
        ):
            for _ in sorted_arrivals:
                hc.record_heartbeat("signal_engine", 0)
        with patch(
            "services.command_center.health_checker.time.time",
            return_value=sorted_arrivals[-1],
        ):
            row = hc.latency_stats()["signal_engine"]
        if row["p50"] is None:
            return
        assert row["p50"] <= row["p95"] <= row["p99"]

    @given(
        timeout_ms=st.integers(min_value=0, max_value=10_000_000),
        age_ms=st.integers(min_value=0, max_value=10_000_000),
    )
    @settings(max_examples=50, deadline=None)
    def test_is_alive_iff_age_strictly_less_than_timeout(
        self, timeout_ms: int, age_ms: int
    ) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=0.0):
            hc.record_heartbeat("signal_engine", 0)
        with patch(
            "services.command_center.health_checker.time.time",
            return_value=age_ms / 1000.0,
        ):
            observed = hc.is_alive("signal_engine", timeout_ms=timeout_ms)
        assert observed is (age_ms < timeout_ms)

    @given(n=st.integers(min_value=0, max_value=250))
    @settings(max_examples=30, deadline=None)
    def test_arrival_buffer_never_exceeds_maxlen(self, n: int) -> None:
        hc = HealthChecker()
        with patch(
            "services.command_center.health_checker.time.time",
            side_effect=[float(i) for i in range(n)] or [0.0],
        ):
            for _ in range(n):
                hc.record_heartbeat("signal_engine", 0)
        assert len(hc._arrival_times["signal_engine"]) == min(n, 100)

    @given(recorded=st.sets(st.sampled_from(HealthChecker.SERVICE_IDS), min_size=0))
    @settings(max_examples=30, deadline=None)
    def test_dead_services_is_complement_of_recorded_live_set(self, recorded: set[str]) -> None:
        hc = HealthChecker()
        with patch("services.command_center.health_checker.time.time", return_value=1.0):
            for sid in recorded:
                hc.record_heartbeat(sid, 0)
        with patch("services.command_center.health_checker.time.time", return_value=1.0):
            dead = set(hc.get_dead_services())
        assert dead == set(HealthChecker.SERVICE_IDS) - recorded
