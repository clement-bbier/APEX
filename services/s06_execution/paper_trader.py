"""Paper-trading execution simulator for APEX Trading System - S06.

Simulates order fills with realistic slippage, latency, commission, and
basic liquidity checks.  All fills are flagged ``is_paper=True``.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from decimal import Decimal
from typing import Any

from core.models.order import ApprovedOrder, ExecutedOrder
from core.models.tick import NormalizedTick

_rng = secrets.SystemRandom()

# Basis points used when the tick carries no spread information.
_DEFAULT_SPREAD_BPS = Decimal("5")

# Commission rate: 0.1 % of notional.
_COMMISSION_RATE = Decimal("0.001")

# Minimum tick volume relative to order size to allow a fill.
_LIQUIDITY_MULTIPLIER = 10


class PaperTrader:
    """Simulate order execution with realistic market microstructure effects.

    Slippage is modelled as half-spread plus a Kyle-lambda market-impact term.
    Latency is sampled uniformly from ``[5 ms, 50 ms]`` to mimic network delays.
    """

    def compute_slippage(
        self,
        spread_bps: float,
        kyle_lambda: float,
        size: Decimal,
        price: Decimal,
    ) -> float:
        """Compute expected slippage in basis points.

        Formula: half_spread_bps + kyle_lambda * size

        Args:
            spread_bps:  Bid-ask spread in basis points.
            kyle_lambda: Price-impact coefficient (higher = more illiquid).
            size:        Order size in base currency units.
            price:       Current market price (reserved for future scaling).

        Returns:
            Slippage in basis points (>= 0).
        """
        _ = price  # reserved for future price-impact scaling
        return max(0.0, spread_bps / 2.0 + kyle_lambda * float(size))

    async def execute(
        self,
        approved: ApprovedOrder,
        current_tick: NormalizedTick,
        kyle_lambda: float = 0.0,
    ) -> ExecutedOrder:
        """Simulate the fill of an approved order.

        Args:
            approved:    The risk-approved order to execute.
            current_tick: Latest market tick for the symbol.
            kyle_lambda: Price-impact coefficient.  Higher values mean more
                         slippage for larger orders.

        Returns:
            A fully-populated :class:`~core.models.order.ExecutedOrder`.

        Raises:
            ValueError: If tick volume is insufficient relative to order size.
        """
        candidate = approved.candidate
        fill_size = approved.adjusted_size

        # ── Liquidity check ────────────────────────────────────────────────────
        if current_tick.volume < fill_size * _LIQUIDITY_MULTIPLIER:
            raise ValueError(
                f"Insufficient liquidity: tick volume {current_tick.volume} < "
                f"required {fill_size * _LIQUIDITY_MULTIPLIER}"
            )

        # ── Slippage ───────────────────────────────────────────────────────────
        spread_bps = (
            current_tick.spread_bps if current_tick.spread_bps is not None else _DEFAULT_SPREAD_BPS
        )
        slippage_bps = Decimal(str(float(spread_bps) / 2.0 + kyle_lambda * float(fill_size)))

        # ── Simulated network latency ──────────────────────────────────────────
        await asyncio.sleep(_rng.uniform(0.005, 0.050))

        # ── Fill price ─────────────────────────────────────────────────────────
        from core.models.signal import Direction  # local import avoids circularity

        entry = candidate.entry
        slippage_factor = slippage_bps / Decimal("10000")
        if candidate.direction == Direction.LONG:
            fill_price = entry * (Decimal("1") + slippage_factor)
        else:
            fill_price = entry * (Decimal("1") - slippage_factor)

        # ── Commission ─────────────────────────────────────────────────────────
        commission = fill_price * fill_size * _COMMISSION_RATE

        return ExecutedOrder(
            approved_order=approved,
            broker_order_id=f"paper-{candidate.order_id}",
            fill_price=fill_price,
            fill_size=fill_size,
            fill_timestamp_ms=int(time.time() * 1000),
            slippage_bps=slippage_bps,
            commission=commission,
            is_paper=True,
        )

    async def execute_exit(
        self,
        position: dict[str, Any],
        exit_price: Decimal,
        size: Decimal,
    ) -> dict[str, Any]:
        """Simulate an exit (close) trade for an open position.

        Args:
            position:   Position metadata dict (must contain at least
                        ``"symbol"`` and ``"entry"``).
            exit_price: Target exit price.
            size:       Size to close in base units.

        Returns:
            Dict summarising the simulated exit fill.
        """
        await asyncio.sleep(_rng.uniform(0.005, 0.050))

        slippage_factor = Decimal("0.0005")  # 5 bps default on exits
        # Exits are closes, so we fill slightly worse than quoted.
        simulated_exit = exit_price * (Decimal("1") - slippage_factor)
        commission = simulated_exit * size * _COMMISSION_RATE

        return {
            "symbol": position.get("symbol", ""),
            "entry": str(position.get("entry", "0")),
            "exit_price": str(simulated_exit),
            "size": str(size),
            "commission": str(commission),
            "fill_timestamp_ms": int(time.time() * 1000),
            "is_paper": True,
        }
