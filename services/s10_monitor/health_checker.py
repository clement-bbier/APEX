"""Health Checker for APEX Trading System Monitor."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Optional

from core.logger import get_logger

logger = get_logger("s10_monitor.health_checker")


class HealthChecker:
    """Per-service heartbeat tracking with latency statistics."""

    SERVICE_IDS = [
        "s01_data_ingestion",
        "s02_signal_engine",
        "s03_regime_detector",
        "s04_fusion_engine",
        "s05_risk_manager",
        "s06_execution",
        "s07_quant_analytics",
        "s08_macro_intelligence",
        "s09_feedback_loop",
    ]

    def __init__(self) -> None:
        """Initialize health checker."""
        self._last_seen: dict[str, float] = {}
        self._arrival_times: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=100)
        )

    def record_heartbeat(self, service_id: str, timestamp_ms: int) -> None:
        """Record a heartbeat from a service.

        Args:
            service_id: Service identifier.
            timestamp_ms: Heartbeat timestamp in UTC milliseconds.
        """
        now = time.time()
        self._last_seen[service_id] = now
        self._arrival_times[service_id].append(now)

    def is_alive(self, service_id: str, timeout_ms: int = 10000) -> bool:
        """Check if a service is alive within the timeout window.

        Args:
            service_id: Service to check.
            timeout_ms: Maximum acceptable silence in milliseconds.

        Returns:
            True if last heartbeat was within timeout.
        """
        last = self._last_seen.get(service_id)
        if last is None:
            return False
        return (time.time() - last) * 1000 < timeout_ms

    def get_dead_services(self) -> list[str]:
        """Return list of service IDs that have not sent a heartbeat within 10s.

        Returns:
            List of unresponsive service IDs.
        """
        return [sid for sid in self.SERVICE_IDS if not self.is_alive(sid)]

    def latency_stats(self) -> dict[str, dict]:
        """Compute p50/p95/p99 inter-arrival latency per service.

        Returns:
            Dict of service_id -> {"p50": float, "p95": float, "p99": float}.
        """
        import numpy as np

        stats: dict[str, dict] = {}
        for sid in self.SERVICE_IDS:
            arrivals = list(self._arrival_times[sid])
            if len(arrivals) < 2:
                stats[sid] = {"p50": None, "p95": None, "p99": None, "alive": self.is_alive(sid)}
                continue
            deltas_ms = [
                (arrivals[i + 1] - arrivals[i]) * 1000
                for i in range(len(arrivals) - 1)
            ]
            stats[sid] = {
                "p50": float(np.percentile(deltas_ms, 50)),
                "p95": float(np.percentile(deltas_ms, 95)),
                "p99": float(np.percentile(deltas_ms, 99)),
                "alive": self.is_alive(sid),
            }
        return stats
