"""PnL Tracker for APEX Trading System Monitor."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.pnl_tracker")


class PnLTracker:
    """Tracks realized, unrealized, daily PnL and equity curve."""

    async def get_realized_pnl(self, state: StateStore) -> Decimal:
        """Sum all net_pnl from trade records in Redis.

        Args:
            state: Active StateStore.

        Returns:
            Total realized net PnL.
        """
        trades = await state.lrange("trades:all", 0, -1)
        total = Decimal("0")
        for trade in trades:
            if isinstance(trade, dict):
                total += Decimal(str(trade.get("net_pnl", 0)))
        return total

    async def get_unrealized_pnl(
        self,
        state: StateStore,
        current_prices: dict[str, Decimal],
    ) -> Decimal:
        """Compute unrealized PnL from open positions vs current prices.

        Args:
            state: Active StateStore.
            current_prices: Mapping of symbol → current price.

        Returns:
            Total unrealized PnL.
        """
        total = Decimal("0")
        for symbol, price in current_prices.items():
            pos = await state.get(f"positions:{symbol}")
            if not pos or not isinstance(pos, dict):
                continue
            entry = Decimal(str(pos.get("entry_price", 0)))
            size = Decimal(str(pos.get("size", 0)))
            direction = pos.get("direction", "long")
            if entry > 0 and size > 0:
                pnl = (price - entry) * size
                if direction == "short":
                    pnl = -pnl
                total += pnl
        return total

    async def get_daily_pnl(self, state: StateStore) -> Decimal:
        """Sum PnL from trades closed today.

        Args:
            state: Active StateStore.

        Returns:
            Today's realized PnL.
        """
        today_start_ms = int(time.time() // 86400 * 86400 * 1000)
        trades = await state.lrange("trades:all", 0, -1)
        total = Decimal("0")
        for trade in trades:
            if isinstance(trade, dict):
                exit_ms = trade.get("exit_timestamp_ms", 0)
                if exit_ms >= today_start_ms:
                    total += Decimal(str(trade.get("net_pnl", 0)))
        return total

    async def get_max_drawdown(self, state: StateStore) -> float:
        """Compute max drawdown from equity curve stored in Redis.

        Args:
            state: Active StateStore.

        Returns:
            Max drawdown as a fraction (e.g. 0.05 = 5%).
        """
        curve = await state.lrange("equity_curve", 0, -1)
        if len(curve) < 2:
            return 0.0
        equity_values = [float(e.get("equity", 0)) if isinstance(e, dict) else float(e) for e in curve]
        peak = equity_values[0]
        max_dd = 0.0
        for val in equity_values:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    async def update_equity_curve(self, state: StateStore, equity: Decimal) -> None:
        """Append equity snapshot to Redis list.

        Args:
            state: Active StateStore.
            equity: Current portfolio equity value.
        """
        entry = {
            "equity": str(equity),
            "timestamp_ms": int(time.time() * 1000),
        }
        await state.lpush("equity_curve", entry)
        await state.ltrim("equity_curve", 0, 9999)  # Keep last 10k points
