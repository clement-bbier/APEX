"""Tests for S10's ``risk.system.state_change`` handler (ADR-0006 observability).

Closes the Phase 5.1 dashboard-observability gap identified by
STRATEGIC_AUDIT_2026-04-17: S10 now subscribes to
:attr:`core.topics.Topics.RISK_SYSTEM_STATE_CHANGE`, persists the latest
transition to Redis, emits a structured log, and raises a CRITICAL alert
on any non-HEALTHY state.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.topics import Topics
from services.command_center.service import MonitorService


@pytest.fixture
def monitor_service() -> MonitorService:
    """Return an S10 MonitorService instance with mocked collaborators.

    We bypass ``BaseService.__init__`` (which wires ZMQ + Redis) because we
    only exercise the in-process handler.
    """
    svc = MonitorService.__new__(MonitorService)
    svc._signal_count = 0
    svc._order_count = 0
    svc._last_risk_system_state = None
    svc.state = MagicMock()
    svc.state.set = AsyncMock()
    svc._alert = MagicMock()
    svc._alert.alert = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_handler_persists_latest_event(monitor_service: MonitorService) -> None:
    event = {
        "previous_state": "healthy",
        "new_state": "degraded",
        "redis_reachable": True,
        "heartbeat_age_seconds": 7.0,
        "cause": "heartbeat_stale",
        "timestamp_utc": "2026-04-17T12:00:00+00:00",
    }
    await monitor_service._handle_risk_system_state_change(event)

    monitor_service.state.set.assert_awaited_once()
    args, kwargs = monitor_service.state.set.await_args
    assert args[0] == "risk:system:state_change:latest"
    assert args[1] == event
    assert kwargs.get("ttl") == 300
    assert monitor_service._last_risk_system_state == event


@pytest.mark.asyncio
async def test_handler_alerts_on_non_healthy_state(monitor_service: MonitorService) -> None:
    event = {
        "previous_state": "healthy",
        "new_state": "unavailable",
        "cause": "redis_connection_error",
    }
    await monitor_service._handle_risk_system_state_change(event)

    monitor_service._alert.alert.assert_called_once()
    level, message = monitor_service._alert.alert.call_args.args
    assert level == "CRITICAL"
    assert "unavailable" in message.lower()
    assert "redis_connection_error" in message


@pytest.mark.asyncio
async def test_handler_no_alert_when_returning_to_healthy(monitor_service: MonitorService) -> None:
    event = {
        "previous_state": "degraded",
        "new_state": "healthy",
        "cause": "recovery",
    }
    await monitor_service._handle_risk_system_state_change(event)
    monitor_service._alert.alert.assert_not_called()


@pytest.mark.asyncio
async def test_handler_tolerates_redis_set_failure(monitor_service: MonitorService) -> None:
    monitor_service.state.set = AsyncMock(side_effect=RuntimeError("boom"))
    event = {
        "previous_state": "healthy",
        "new_state": "degraded",
        "cause": "heartbeat_stale",
    }
    # Must not propagate — dashboard observability is best-effort.
    await monitor_service._handle_risk_system_state_change(event)
    # Alert path still fires despite persistence failure.
    monitor_service._alert.alert.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_routes_risk_system_state_change(monitor_service: MonitorService) -> None:
    event = {
        "previous_state": "healthy",
        "new_state": "degraded",
        "cause": "heartbeat_stale",
    }
    await monitor_service.on_message(Topics.RISK_SYSTEM_STATE_CHANGE, event)
    # Routed through the handler — state.set called with the canonical key.
    monitor_service.state.set.assert_awaited_once()
    args, _ = monitor_service.state.set.await_args
    assert args[0] == "risk:system:state_change:latest"
