"""Tests Command Center API endpoints."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.s10_monitor.command_api import (
    ActionResult,
    AlertEntry,
    CBEventInfo,
    PerformanceStats,
    PnLSummary,
    PositionSummary,
    RegimeSummary,
    ServiceHealth,
    SignalSummary,
    SystemStatus,
    _require_confirmation,
)


class TestRequireConfirmation:
    def test_none_raises(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _require_confirmation(None)
        assert exc.value.status_code == 403

    def test_wrong_value_raises(self) -> None:
        with pytest.raises(HTTPException):
            _require_confirmation("no")

    def test_yes_passes(self) -> None:
        _require_confirmation("YES")  # no exception


class TestResponseModels:
    def test_service_health_fields(self) -> None:
        s = ServiceHealth(service_id="s01", status="healthy", last_seen_seconds=3.0, is_alive=True)
        assert s.service_id == "s01"
        assert s.is_alive is True

    def test_system_status_fields(self) -> None:
        ss = SystemStatus(
            all_healthy=True,
            services=[],
            circuit_breaker="CLOSED",
            trading_mode="PAPER",
            uptime_seconds=100.0,
        )
        assert ss.all_healthy is True

    def test_pnl_summary_fields(self) -> None:
        p = PnLSummary(
            realized_today="$100.00",
            unrealized_total="$50.00",
            daily_pnl_pct=1.5,
            max_drawdown_pct=0.5,
            win_rate_rolling=0.6,
            trade_count_today=5,
            sharpe_rolling=1.2,
        )
        assert p.daily_pnl_pct == 1.5

    def test_regime_summary_fields(self) -> None:
        r = RegimeSummary(
            vol_regime="normal",
            trend_regime="ranging",
            risk_mode="normal",
            macro_mult=1.0,
            session="us_prime",
            session_mult=1.2,
            event_active=False,
            next_cb_event=None,
        )
        assert r.macro_mult == 1.0

    def test_signal_summary_fields(self) -> None:
        s = SignalSummary(
            symbol="BTCUSDT",
            direction="long",
            strength=0.8,
            triggers=["OFI", "BB"],
            confidence=0.9,
            age_seconds=5.0,
        )
        assert "OFI" in s.triggers

    def test_cb_event_info_fields(self) -> None:
        e = CBEventInfo(
            institution="FOMC",
            event_type="rate_decision",
            scheduled_at="2025-01-29T19:00",
            minutes_until=45.0,
            block_active=False,
            monitor_active=False,
        )
        assert e.institution == "FOMC"

    def test_action_result_success(self) -> None:
        r = ActionResult(success=True, message="Done", timestamp="123")
        assert r.success is True

    def test_action_result_failure(self) -> None:
        r = ActionResult(success=False, message="Error: redis timeout", timestamp="456")
        assert r.success is False
        assert "Error" in r.message

    def test_alert_entry_levels(self) -> None:
        for level in ["INFO", "WARNING", "CRITICAL"]:
            a = AlertEntry(timestamp="2024-01-01T00:00:00", level=level, message=f"{level} test")
            assert a.level == level

    def test_performance_stats_fields(self) -> None:
        p = PerformanceStats(
            sharpe_daily=1.5,
            sortino_daily=2.0,
            calmar=3.0,
            max_drawdown_pct=4.0,
            win_rate=0.6,
            profit_factor=1.8,
            avg_win_usd=150.0,
            avg_loss_usd=80.0,
            total_trades=50,
            best_session="us_prime",
            best_signal_type="OFI",
        )
        assert p.sharpe_daily == 1.5

    def test_position_summary_pnl_sign(self) -> None:
        pos = PositionSummary(
            symbol="BTCUSDT",
            direction="long",
            entry_price="50000",
            size="0.1",
            unrealized_pnl_pct=2.5,
            session="us_prime",
        )
        assert pos.unrealized_pnl_pct > 0


class TestGetSystemStatusMocked:
    @pytest.mark.asyncio
    async def test_dead_services_mark_unhealthy(self) -> None:
        from services.s10_monitor.command_api import get_system_status

        state = AsyncMock()
        state.get.return_value = None  # all services return None = dead
        result = await get_system_status(state)
        assert result.all_healthy is False
        assert len(result.services) > 0
        assert all(not s.is_alive for s in result.services)

    @pytest.mark.asyncio
    async def test_healthy_service_detected(self) -> None:
        from services.s10_monitor.command_api import get_system_status

        now_ms = int(time.time() * 1000)
        state = AsyncMock()
        state.get.return_value = {"timestamp_ms": now_ms, "status": "healthy"}
        result = await get_system_status(state)
        assert any(s.is_alive for s in result.services)

    @pytest.mark.asyncio
    async def test_cb_state_read_from_redis(self) -> None:
        from services.s10_monitor.command_api import get_system_status

        state = AsyncMock()
        state.get.side_effect = lambda key: {"circuit_breaker:state": "open"}.get(key)
        result = await get_system_status(state)
        assert isinstance(result.circuit_breaker, str)


class TestGetPnLMocked:
    @pytest.mark.asyncio
    async def test_empty_trades_returns_zeros(self) -> None:
        from services.s10_monitor.command_api import get_pnl

        state = AsyncMock()
        state.lrange.return_value = []
        state.get.return_value = None
        result = await get_pnl(state)
        assert result.trade_count_today == 0
        assert result.win_rate_rolling == 0.0

    @pytest.mark.asyncio
    async def test_winning_trades_positive_win_rate(self) -> None:
        from services.s10_monitor.command_api import get_pnl

        state = AsyncMock()
        state.get.return_value = None
        state.lrange.return_value = [
            {"net_pnl": 100, "exit_timestamp_ms": int(time.time() * 1000)} for _ in range(10)
        ]
        result = await get_pnl(state)
        assert result.win_rate_rolling > 0.5


class TestGetRegimeMocked:
    @pytest.mark.asyncio
    async def test_empty_regime_returns_defaults(self) -> None:
        from services.s10_monitor.command_api import get_regime

        state = AsyncMock()
        state.get.return_value = {}
        result = await get_regime(state)
        assert isinstance(result.macro_mult, float)
        assert isinstance(result.event_active, bool)


class TestResetCBMocked:
    @pytest.mark.asyncio
    async def test_reset_requires_confirmation(self) -> None:
        from services.s10_monitor.command_api import reset_circuit_breaker

        state = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await reset_circuit_breaker(state, x_confirm=None)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reset_with_confirmation_succeeds(self) -> None:
        from services.s10_monitor.command_api import reset_circuit_breaker

        state = AsyncMock()
        state.set.return_value = None
        result = await reset_circuit_breaker(state, x_confirm="YES")
        assert result.success is True
        state.set.assert_called_once()


class TestGetConfigMocked:
    @pytest.mark.asyncio
    async def test_config_never_exposes_secrets(self) -> None:
        from services.s10_monitor.command_api import get_config

        result = await get_config()
        assert "api_key" not in str(result).lower()
        assert "secret" not in str(result).lower()
        assert "password" not in str(result).lower()
        assert "trading_mode" in result
        assert "initial_capital" in result
