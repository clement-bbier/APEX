"""Order lifecycle manager for APEX Trading System - S06 Execution.

Tracks order state in Redis, generates broker order IDs, and identifies
stale unconfirmed orders.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

from core.models.order import ApprovedOrder
from core.state import StateStore

# Seconds after submission before an order is considered timed-out.
_SUBMIT_TIMEOUT_S: float = 30.0


class OrderManager:
    """Manage order lifecycle state in Redis.

    Each order is stored under ``order:{order_id}`` as a JSON dict with
    fields: ``broker_order_id``, ``status``, ``submitted_at``,
    ``fill_price``, ``fill_size``, and ``cancel_reason``.
    """

    def __init__(self, state: StateStore) -> None:
        """Initialize the order manager.

        Args:
            state: Connected :class:`~core.state.StateStore` instance.
        """
        self._state = state

    # ── Order operations ──────────────────────────────────────────────────────

    async def submit(self, approved: ApprovedOrder) -> str:
        """Record an order as submitted and return the generated broker order ID.

        Args:
            approved: The approved order to submit.

        Returns:
            A unique broker order ID string.
        """
        broker_order_id = f"brk-{uuid.uuid4()}"
        record = {
            "order_id": approved.order_id,
            "broker_order_id": broker_order_id,
            "symbol": approved.symbol,
            "status": "submitted",
            "submitted_at": time.time(),
            "fill_price": None,
            "fill_size": None,
            "cancel_reason": None,
        }
        await self._state.set(f"order:{approved.order_id}", record)
        return broker_order_id

    async def confirm(
        self,
        order_id: str,
        fill_price: Decimal,
        fill_size: Decimal,
    ) -> None:
        """Update the order status to ``filled`` with execution details.

        Args:
            order_id:   The order ID to confirm.
            fill_price: Actual execution price.
            fill_size:  Actual filled quantity.
        """
        record = await self._state.get(f"order:{order_id}") or {}
        record.update(
            {
                "status": "filled",
                "fill_price": str(fill_price),
                "fill_size": str(fill_size),
                "filled_at": time.time(),
            }
        )
        await self._state.set(f"order:{order_id}", record)

    async def cancel(self, order_id: str, reason: str) -> None:
        """Update the order status to ``cancelled``.

        Args:
            order_id: The order ID to cancel.
            reason:   Human-readable cancellation reason.
        """
        record = await self._state.get(f"order:{order_id}") or {}
        record.update(
            {
                "status": "cancelled",
                "cancel_reason": reason,
                "cancelled_at": time.time(),
            }
        )
        await self._state.set(f"order:{order_id}", record)

    async def timeout_check(self) -> list[str]:
        """Return IDs of orders submitted longer than :data:`_SUBMIT_TIMEOUT_S` ago.

        Scans all ``order:*`` keys in Redis and returns those still in
        ``submitted`` status past the timeout threshold.

        Returns:
            List of timed-out order ID strings.
        """
        r = self._state._ensure_connected()
        keys = await r.keys("order:*")
        timed_out: list[str] = []
        now = time.time()
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            record = await self._state.get(key_str)
            if not isinstance(record, dict):
                continue
            if record.get("status") != "submitted":
                continue
            submitted_at = record.get("submitted_at", now)
            if now - float(submitted_at) > _SUBMIT_TIMEOUT_S:
                timed_out.append(record.get("order_id", key_str.split(":", 1)[-1]))
        return timed_out
