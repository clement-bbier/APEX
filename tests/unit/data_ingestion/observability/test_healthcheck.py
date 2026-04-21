"""Unit tests for S01 observability health checks.

Verifies liveness, readiness, dependency check strategies,
and the HealthChecker orchestrator.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.data_ingestion.observability.healthcheck import (
    DatabaseCheck,
    HealthChecker,
    HealthCheckResult,
    HealthReport,
    HealthStatus,
    RedisCheck,
)


class TestHealthCheckResult:
    """Tests for the HealthCheckResult dataclass."""

    def test_healthy_result(self) -> None:
        result = HealthCheckResult(name="test", status=HealthStatus.HEALTHY, message="ok")
        assert result.name == "test"
        assert result.status == HealthStatus.HEALTHY

    def test_frozen_immutable(self) -> None:
        result = HealthCheckResult(name="test", status=HealthStatus.HEALTHY, message="ok")
        with pytest.raises(AttributeError):
            result.name = "modified"  # type: ignore[misc]


class TestHealthReport:
    """Tests for the HealthReport dataclass."""

    def test_to_dict_serialization(self) -> None:
        checks = [
            HealthCheckResult(name="db", status=HealthStatus.HEALTHY, message="ok"),
        ]
        report = HealthReport(status=HealthStatus.HEALTHY, checks=checks)
        d = report.to_dict()
        assert d["status"] == "healthy"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "db"

    def test_to_dict_excludes_empty_details(self) -> None:
        checks = [
            HealthCheckResult(name="db", status=HealthStatus.HEALTHY, message="ok"),
        ]
        report = HealthReport(status=HealthStatus.HEALTHY, checks=checks)
        d = report.to_dict()
        assert "details" not in d["checks"][0]


class TestDatabaseCheck:
    """Tests for the DatabaseCheck strategy."""

    async def test_healthy_when_repo_ok(self) -> None:
        repo = AsyncMock()
        repo.health_check.return_value = True
        check = DatabaseCheck(repo)
        result = await check.check()
        assert result.status == HealthStatus.HEALTHY
        assert check.name == "database"

    async def test_unhealthy_when_repo_fails(self) -> None:
        repo = AsyncMock()
        repo.health_check.return_value = False
        check = DatabaseCheck(repo)
        result = await check.check()
        assert result.status == HealthStatus.UNHEALTHY

    async def test_unhealthy_on_exception(self) -> None:
        repo = AsyncMock()
        repo.health_check.side_effect = ConnectionError("db down")
        check = DatabaseCheck(repo)
        result = await check.check()
        assert result.status == HealthStatus.UNHEALTHY
        assert "db down" in result.message


class TestRedisCheck:
    """Tests for the RedisCheck strategy."""

    async def test_healthy_when_ping_ok(self) -> None:
        redis = AsyncMock()
        redis.ping.return_value = True
        check = RedisCheck(redis)
        result = await check.check()
        assert result.status == HealthStatus.HEALTHY
        assert check.name == "redis"

    async def test_unhealthy_when_ping_fails(self) -> None:
        redis = AsyncMock()
        redis.ping.return_value = False
        check = RedisCheck(redis)
        result = await check.check()
        assert result.status == HealthStatus.UNHEALTHY

    async def test_unhealthy_on_exception(self) -> None:
        redis = AsyncMock()
        redis.ping.side_effect = ConnectionError("redis down")
        check = RedisCheck(redis)
        result = await check.check()
        assert result.status == HealthStatus.UNHEALTHY


class TestHealthChecker:
    """Tests for the HealthChecker orchestrator."""

    def test_liveness_always_healthy(self) -> None:
        checker = HealthChecker()
        result = checker.liveness()
        assert result.status == HealthStatus.HEALTHY
        assert result.name == "liveness"

    async def test_readiness_all_healthy(self) -> None:
        repo = AsyncMock()
        repo.health_check.return_value = True
        checker = HealthChecker(dependency_checks=[DatabaseCheck(repo)])
        report = await checker.readiness()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.checks) == 1

    async def test_readiness_degraded_on_unhealthy_dep(self) -> None:
        repo = AsyncMock()
        repo.health_check.return_value = False
        checker = HealthChecker(dependency_checks=[DatabaseCheck(repo)])
        report = await checker.readiness()
        assert report.status == HealthStatus.UNHEALTHY

    async def test_readiness_empty_deps_is_healthy(self) -> None:
        checker = HealthChecker(dependency_checks=[])
        report = await checker.readiness()
        assert report.status == HealthStatus.HEALTHY

    async def test_readiness_multiple_deps(self) -> None:
        repo = AsyncMock()
        repo.health_check.return_value = True
        redis = AsyncMock()
        redis.ping.return_value = True
        checker = HealthChecker(dependency_checks=[DatabaseCheck(repo), RedisCheck(redis)])
        report = await checker.readiness()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.checks) == 2
