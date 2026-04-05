"""Tests for KellySizer.get_rolling_stats_from_redis."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.s04_fusion_engine.kelly_sizer import KellySizer


class TestKellyRollingStats:
    def sizer(self) -> KellySizer:
        return KellySizer()

    @pytest.mark.asyncio
    async def test_defaults_when_no_data(self) -> None:
        state = AsyncMock()
        state.get.return_value = None
        win_rate, avg_rr = await self.sizer().get_rolling_stats_from_redis(state)
        assert win_rate == 0.50
        assert avg_rr == 1.50

    @pytest.mark.asyncio
    async def test_defaults_when_n_trades_below_20(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.60, "avg_rr": 2.0, "n_trades": 10}
        win_rate, avg_rr = await self.sizer().get_rolling_stats_from_redis(state)
        assert win_rate == 0.50
        assert avg_rr == 1.50

    @pytest.mark.asyncio
    async def test_reads_live_stats(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.58, "avg_rr": 1.8, "n_trades": 50}
        win_rate, avg_rr = await self.sizer().get_rolling_stats_from_redis(state)
        assert win_rate == pytest.approx(0.58)
        assert avg_rr == pytest.approx(1.8)

    @pytest.mark.asyncio
    async def test_win_rate_clamped_high(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.99, "avg_rr": 2.0, "n_trades": 100}
        win_rate, _ = await self.sizer().get_rolling_stats_from_redis(state)
        assert win_rate <= 0.70

    @pytest.mark.asyncio
    async def test_win_rate_clamped_low(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.05, "avg_rr": 2.0, "n_trades": 100}
        win_rate, _ = await self.sizer().get_rolling_stats_from_redis(state)
        assert win_rate >= 0.40

    @pytest.mark.asyncio
    async def test_avg_rr_clamped(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.55, "avg_rr": 100.0, "n_trades": 100}
        _, avg_rr = await self.sizer().get_rolling_stats_from_redis(state)
        assert avg_rr <= 4.0

    @pytest.mark.asyncio
    async def test_strategy_key_used_in_redis_lookup(self) -> None:
        state = AsyncMock()
        state.get.return_value = None
        await self.sizer().get_rolling_stats_from_redis(state, strategy_key="btc")
        state.get.assert_called_with("feedback:kelly_stats:btc")


class TestKellyGetStats:
    def sizer(self) -> KellySizer:
        return KellySizer()

    @pytest.mark.asyncio
    async def test_defaults_when_no_key(self) -> None:
        state = AsyncMock()
        state.get.return_value = None
        win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == 0.5
        assert avg_rr == 1.5

    @pytest.mark.asyncio
    async def test_reads_live_data(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.62, "avg_rr": 2.1}
        win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == pytest.approx(0.62)
        assert avg_rr == pytest.approx(2.1)

    @pytest.mark.asyncio
    async def test_win_rate_clamped_to_zero_one(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 1.5, "avg_rr": 2.0}
        win_rate, _ = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate <= 1.0

    @pytest.mark.asyncio
    async def test_avg_rr_clamped_above_zero(self) -> None:
        state = AsyncMock()
        state.get.return_value = {"win_rate": 0.5, "avg_rr": -5.0}
        _, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert avg_rr >= 0.01

    @pytest.mark.asyncio
    async def test_uses_defaults_when_keys_missing(self) -> None:
        state = AsyncMock()
        state.get.return_value = {}  # dict but empty
        win_rate, avg_rr = await self.sizer().get_stats(state, "ETHUSDT")
        assert win_rate == pytest.approx(0.5)
        assert avg_rr == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_redis_key_contains_symbol(self) -> None:
        state = AsyncMock()
        state.get.return_value = None
        await self.sizer().get_stats(state, "AAPL")
        state.get.assert_called_with("kelly:AAPL")
