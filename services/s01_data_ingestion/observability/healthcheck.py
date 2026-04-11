"""Structured health checks for S01 Data Ingestion.

Implements liveness, readiness, and dependency checks following
the Kubernetes health probe conventions. Uses the Strategy pattern
for pluggable dependency checkers.

References:
    Beyer et al. (2016) SRE Book Ch. 6 — monitoring distributed systems
    Kubernetes probe docs — https://kubernetes.io/docs/tasks/configure-pod-container/
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HasHealthCheck(Protocol):
    """Protocol for objects that support health_check()."""

    async def health_check(self) -> bool: ...


@runtime_checkable
class HasPing(Protocol):
    """Protocol for objects that support ping()."""

    async def ping(self) -> bool: ...


class HealthStatus(StrEnum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class HealthCheckResult:
    """Result of a single health check.

    Attributes:
        name: Check identifier (e.g. ``database``, ``redis``).
        status: Health status.
        message: Human-readable detail.
        timestamp: When the check was performed (UTC).
        details: Optional extra info for debugging.
    """

    name: str
    status: HealthStatus
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


class DependencyCheck(ABC):
    """Abstract interface for a single dependency health check (Strategy)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the dependency name."""
        ...

    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """Execute the health check and return the result."""
        ...


class DatabaseCheck(DependencyCheck):
    """Health check for the TimescaleDB connection pool."""

    def __init__(self, repo: HasHealthCheck) -> None:
        self._repo = repo

    @property
    def name(self) -> str:
        return "database"

    async def check(self) -> HealthCheckResult:
        """Verify database connectivity via ``repo.health_check()``."""
        try:
            is_healthy: bool = await self._repo.health_check()
            if is_healthy:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="Database connection pool responsive",
                )
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message="Database health check returned False",
            )
        except Exception as exc:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {exc}",
            )


class RedisCheck(DependencyCheck):
    """Health check for the Redis connection."""

    def __init__(self, redis_client: HasPing) -> None:
        self._redis = redis_client

    @property
    def name(self) -> str:
        return "redis"

    async def check(self) -> HealthCheckResult:
        """Verify Redis connectivity via PING."""
        try:
            result: bool = await self._redis.ping()
            if result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="Redis PING successful",
                )
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message="Redis PING returned False",
            )
        except Exception as exc:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Redis check failed: {exc}",
            )


@dataclass(frozen=True)
class HealthReport:
    """Aggregate health report from all checks.

    Attributes:
        status: Overall status (worst of all dependency statuses).
        checks: Individual check results.
        timestamp: When the report was generated (UTC).
    """

    status: HealthStatus
    checks: list[HealthCheckResult]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict for API responses."""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "timestamp": c.timestamp.isoformat(),
                    **({} if not c.details else {"details": c.details}),
                }
                for c in self.checks
            ],
        }


class HealthChecker:
    """Orchestrates liveness, readiness, and dependency health checks.

    Args:
        dependency_checks: List of dependency check strategies.
    """

    def __init__(self, dependency_checks: list[DependencyCheck] | None = None) -> None:
        self._checks = dependency_checks or []

    def liveness(self) -> HealthCheckResult:
        """Liveness probe — always healthy if the process is running."""
        return HealthCheckResult(
            name="liveness",
            status=HealthStatus.HEALTHY,
            message="Process is alive",
        )

    async def readiness(self) -> HealthReport:
        """Readiness probe — checks all dependencies.

        Returns:
            ``HealthReport`` with overall status derived from the
            worst individual check status.
        """
        results: list[HealthCheckResult] = []
        for dep in self._checks:
            result = await dep.check()
            results.append(result)

        overall = self._compute_overall_status(results)
        return HealthReport(status=overall, checks=results)

    @staticmethod
    def _compute_overall_status(
        results: list[HealthCheckResult],
    ) -> HealthStatus:
        """Derive overall status from individual results.

        Uses worst-status semantics: if any check is UNHEALTHY,
        overall is UNHEALTHY; if any is DEGRADED, overall is DEGRADED.
        """
        if not results:
            return HealthStatus.HEALTHY

        statuses = {r.status for r in results}
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY
