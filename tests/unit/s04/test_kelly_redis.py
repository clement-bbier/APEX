"""Tests for KellySizer.get_rolling_stats_from_redis and dual-read get_stats.

Storage contract:
- ``get_rolling_stats_from_redis`` reads ``feedback:kelly_stats:{key}`` which
  is a JSON-serialized STRING value written by S09 slow analysis — tests mock
  ``state.get``.
- ``get_stats`` reads ``kelly:{strategy_id}:{symbol}`` / ``kelly:{symbol}``
  which are Redis HASHES written by S09 ``_fast_analysis`` via
  :meth:`StateStore.hset` — tests mock ``state.hgetall``. (Using ``state.get``
  here would raise ``WRONGTYPE`` at runtime against a hash.)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, call, patch

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
    """Single-key behavior of ``get_stats`` against the Redis HASH backend."""

    def sizer(self) -> KellySizer:
        return KellySizer()

    @pytest.mark.asyncio
    async def test_defaults_when_no_key(self) -> None:
        """Both hashes empty → defaults."""
        state = AsyncMock()
        state.hgetall.return_value = {}
        win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == 0.5
        assert avg_rr == 1.5

    @pytest.mark.asyncio
    async def test_reads_live_data(self) -> None:
        """Non-empty primary hash → values read directly, no fallback."""
        state = AsyncMock()
        state.hgetall.return_value = {"win_rate": 0.62, "avg_rr": 2.1}
        win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == pytest.approx(0.62)
        assert avg_rr == pytest.approx(2.1)

    @pytest.mark.asyncio
    async def test_win_rate_clamped_to_zero_one(self) -> None:
        state = AsyncMock()
        state.hgetall.return_value = {"win_rate": 1.5, "avg_rr": 2.0}
        win_rate, _ = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate <= 1.0

    @pytest.mark.asyncio
    async def test_avg_rr_clamped_above_zero(self) -> None:
        state = AsyncMock()
        state.hgetall.return_value = {"win_rate": 0.5, "avg_rr": -5.0}
        _, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert avg_rr >= 0.01

    @pytest.mark.asyncio
    async def test_redis_key_contains_symbol(self) -> None:
        """Primary key is attempted first; legacy key is the fallback on miss.

        Ensures future refactors cannot silently break the per-strategy
        primary lookup (addresses #209 Copilot thread 3).
        """
        state = AsyncMock()
        state.hgetall.return_value = {}
        await self.sizer().get_stats(state, "AAPL")
        assert state.hgetall.await_args_list == [
            call("kelly:default:AAPL"),
            call("kelly:AAPL"),
        ]


class TestKellyDualRead:
    """Dual-read migration (Roadmap v3.0 section 2.2.5, ADR-0007 section D9).

    ``get_stats`` issues ``hgetall`` against ``kelly:{strategy_id}:{symbol}``
    first, falls back to the legacy ``kelly:{symbol}`` hash on empty-miss, and
    emits a structlog WARNING whenever the legacy path is hit so residual
    dependency is observable.
    """

    def sizer(self) -> KellySizer:
        return KellySizer()

    @staticmethod
    def _keyed_state(store: dict[str, dict[str, Any]]) -> AsyncMock:
        """Build an AsyncMock StateStore backed by an in-memory hash-dict.

        Mirrors ``StateStore.hgetall`` semantics: missing keys resolve to
        an empty dict (never ``None``).
        """
        state = AsyncMock()

        async def _hgetall(key: str) -> dict[str, Any]:
            return store.get(key, {})

        state.hgetall.side_effect = _hgetall
        return state

    @pytest.mark.asyncio
    async def test_new_key_hit_no_fallback(self) -> None:
        store = {"kelly:default:BTCUSDT": {"win_rate": 0.60, "avg_rr": 2.0}}
        state = self._keyed_state(store)
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == pytest.approx(0.60)
        assert avg_rr == pytest.approx(2.0)
        state.hgetall.assert_awaited_once_with("kelly:default:BTCUSDT")
        mock_log.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_key_fallback_warns(self) -> None:
        store = {"kelly:BTCUSDT": {"win_rate": 0.55, "avg_rr": 1.8}}
        state = self._keyed_state(store)
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == pytest.approx(0.55)
        assert avg_rr == pytest.approx(1.8)
        # Primary tried first, then legacy — ordered assertion.
        assert state.hgetall.await_args_list == [
            call("kelly:default:BTCUSDT"),
            call("kelly:BTCUSDT"),
        ]
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args
        assert call_args.args[0] == "kelly_sizer.legacy_key_fallback"
        assert call_args.kwargs["strategy_id"] == "default"
        assert call_args.kwargs["symbol"] == "BTCUSDT"
        assert call_args.kwargs["legacy_key"] == "kelly:BTCUSDT"
        assert call_args.kwargs["new_key"] == "kelly:default:BTCUSDT"

    @pytest.mark.asyncio
    async def test_new_key_wins_when_both_present(self) -> None:
        store = {
            "kelly:default:BTCUSDT": {"win_rate": 0.65, "avg_rr": 2.5},
            "kelly:BTCUSDT": {"win_rate": 0.40, "avg_rr": 1.2},
        }
        state = self._keyed_state(store)
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == pytest.approx(0.65)
        assert avg_rr == pytest.approx(2.5)
        state.hgetall.assert_awaited_once_with("kelly:default:BTCUSDT")
        mock_log.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_missing_returns_defaults(self) -> None:
        state = self._keyed_state({})
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            win_rate, avg_rr = await self.sizer().get_stats(state, "BTCUSDT")
        assert win_rate == 0.5
        assert avg_rr == 1.5
        assert state.hgetall.await_args_list == [
            call("kelly:default:BTCUSDT"),
            call("kelly:BTCUSDT"),
        ]
        mock_log.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_default_strategy_id_fallback(self) -> None:
        store = {"kelly:BTCUSDT": {"win_rate": 0.58, "avg_rr": 1.9}}
        state = self._keyed_state(store)
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            win_rate, avg_rr = await self.sizer().get_stats(
                state, "BTCUSDT", strategy_id="crypto_momentum"
            )
        assert win_rate == pytest.approx(0.58)
        assert avg_rr == pytest.approx(1.9)
        assert state.hgetall.await_args_list == [
            call("kelly:crypto_momentum:BTCUSDT"),
            call("kelly:BTCUSDT"),
        ]
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["strategy_id"] == "crypto_momentum"
        assert mock_log.warning.call_args.kwargs["new_key"] == "kelly:crypto_momentum:BTCUSDT"

    @pytest.mark.asyncio
    async def test_malformed_primary_value_raises(self) -> None:
        """Non-numeric value in a populated primary hash → fail-loud (ValueError).

        The legacy fallback is gated strictly on the primary hash being
        *empty* (cache miss). A populated primary hash with a corrupted
        ``win_rate`` value does not silently fall back to the legacy key;
        it surfaces as a ``ValueError`` via ``float(...)`` — matching the
        fail-loud contract used by :mod:`portfolio_tracker` (addresses
        #209 Copilot thread 2).
        """
        store = {
            "kelly:default:BTCUSDT": {"win_rate": "not_a_number", "avg_rr": 1.8},
            "kelly:BTCUSDT": {"win_rate": 0.99, "avg_rr": 3.0},
        }
        state = self._keyed_state(store)
        with patch("services.s04_fusion_engine.kelly_sizer._logger") as mock_log:
            with pytest.raises(ValueError, match="could not convert"):
                await self.sizer().get_stats(state, "BTCUSDT")
        # Crucially: fallback was NOT triggered — only the primary key was read.
        state.hgetall.assert_awaited_once_with("kelly:default:BTCUSDT")
        mock_log.warning.assert_not_called()
