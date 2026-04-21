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

from core.logger import get_logger
from core.models.order import ApprovedOrder, ExecutedOrder
from core.models.tick import Market, NormalizedTick
from core.state import StateStore
from services.execution.broker_base import Broker
from services.execution.optimal_execution import MarketImpactModel

_logger = get_logger("execution.paper_trader")

_rng = secrets.SystemRandom()

# Basis points used when the tick carries no spread information.
_DEFAULT_SPREAD_BPS = Decimal("5")

# Commission rate: 0.1 % of notional.
_COMMISSION_RATE = Decimal("0.001")

# Minimum tick volume relative to order size to allow a fill.
_LIQUIDITY_MULTIPLIER = 10


_CRYPTO_SUFFIXES = ("USDT", "BUSD", "BTC", "ETH", "USDC")


class PaperTrader(Broker):
    """Simulate order execution with realistic market microstructure effects.

    Slippage is modelled using the Bouchaud et al. (2018) square-root impact law
    for large orders, and the Kyle (1985) linear model for small orders.
    Latency is sampled uniformly from ``[5 ms, 50 ms]`` to mimic network delays.

    Implements the :class:`~.broker_base.Broker` ABC so that
    :class:`~.service.ExecutionService` can route orders uniformly.
    """

    def __init__(self, state: StateStore | None = None) -> None:
        """Initialise with the market impact model.

        Args:
            state: Optional :class:`~core.state.StateStore` for fetching
                latest ticks in :meth:`place_order`. When ``None``,
                :meth:`place_order` builds a synthetic tick from the order.
        """
        self._state = state
        self._impact_model = MarketImpactModel()

    # ── Broker ABC interface ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """No-op — paper trading has no external connection."""

    async def disconnect(self) -> None:
        """No-op — paper trading has no external connection."""

    @property
    def is_connected(self) -> bool:
        """Always ``True`` for paper trading."""
        return True

    async def place_order(self, order: ApprovedOrder) -> ExecutedOrder | None:
        """Execute a paper order, returning the simulated fill immediately.

        Fetches the latest tick from Redis when *state* was provided at
        construction; otherwise synthesises a minimal tick from the order.

        Args:
            order: Risk-approved order.

        Returns:
            Simulated :class:`~core.models.order.ExecutedOrder`.
        """
        tick = await self._get_or_build_tick(order)
        return await self.execute(order, tick)

    async def cancel_order(self, order_id: str) -> bool:
        """No-op — paper fills are instantaneous.

        Returns:
            ``True`` unconditionally.
        """
        return True

    # ── Tick helper ──────────────────────────────────────────────────────────

    async def _get_or_build_tick(self, order: ApprovedOrder) -> NormalizedTick:
        """Return the latest cached tick or synthesise a minimal one.

        Args:
            order: Approved order (used to derive entry price / volume).

        Returns:
            A :class:`~core.models.tick.NormalizedTick` suitable for execution.
        """
        symbol = order.symbol
        if self._state is not None:
            raw = await self._state.get(f"tick:{symbol}")
            if raw is not None:
                try:
                    return NormalizedTick.model_validate(raw)
                except Exception as exc:
                    _logger.debug("tick_parse_failed", error=str(exc))

        is_crypto = any(symbol.endswith(s) for s in _CRYPTO_SUFFIXES)
        entry = order.candidate.entry
        size = order.adjusted_size
        return NormalizedTick(
            symbol=symbol,
            market=Market.CRYPTO if is_crypto else Market.EQUITY,
            timestamp_ms=int(time.time() * 1000),
            price=entry,
            volume=size * Decimal("100"),
            spread_bps=_DEFAULT_SPREAD_BPS,
        )

    def compute_slippage(
        self,
        spread_bps: float,
        kyle_lambda: float,
        size: Decimal,
        price: Decimal,
        adv: float = 0.0,
        daily_vol: float = 0.20,
    ) -> float:
        """Compute expected slippage in basis points.

        Uses Bouchaud et al. (2018) square-root impact law for large orders
        (participation > 1% ADV) and Kyle (1985) linear model for small orders.
        Falls back to half-spread + linear when ADV is unknown.

        Args:
            spread_bps:  Bid-ask spread in basis points.
            kyle_lambda: Price-impact coefficient (higher = more illiquid).
            size:        Order size in base currency units.
            price:       Current market price.
            adv:         Average daily volume (0 = unknown, use fallback).
            daily_vol:   Annualized daily volatility (default 20%).

        Returns:
            Slippage in basis points (>= 0).
        """
        if adv > 0:
            estimate = self._impact_model.best_impact_estimate(
                quantity=float(size),
                adv=adv,
                daily_vol=daily_vol,
                price=float(price),
                kyle_lambda=kyle_lambda,
                spread_bps=spread_bps,
            )
            return estimate.total_slippage_bps
        # Fallback to original model when ADV unknown
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
