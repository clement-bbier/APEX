"""Broker abstract base class — common interface for all execution backends.

All execution backends (Alpaca, Binance, PaperTrader, future IBKR, …) must
implement this interface so that :class:`ExecutionService` depends on the
abstraction rather than on concrete broker classes (DIP).

The :meth:`place_order` contract returns ``ExecutedOrder`` when the fill is
synchronous (e.g. paper trading) and ``None`` when the fill will be confirmed
asynchronously (e.g. live venue).

References:
    Robert C. Martin (2017) Clean Architecture Ch. 11 — DIP
    Gang of Four (1994) — Strategy Pattern
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models.order import ApprovedOrder, ExecutedOrder


class Broker(ABC):
    """Abstract broker interface for APEX execution backends."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to broker (auth, websocket, etc.). Idempotent."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection cleanly. Idempotent."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Current connection state."""
        ...

    @abstractmethod
    async def place_order(self, order: ApprovedOrder) -> ExecutedOrder | None:
        """Place an order for execution.

        Args:
            order: Risk-approved order ready for execution.

        Returns:
            ``ExecutedOrder`` when the fill is synchronous (paper),
            ``None`` when the fill will be confirmed asynchronously (live).

        Raises:
            BrokerConnectionError: If the broker is not connected.
            BrokerRejectedError: If the broker rejects the order.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an outstanding order by ID.

        Returns:
            ``True`` if cancel succeeded, ``False`` if already filled/cancelled.
        """
        ...


class BrokerConnectionError(RuntimeError):
    """Raised when a broker operation fails due to connection issues."""


class BrokerRejectedError(RuntimeError):
    """Raised when the broker rejects an order (insufficient funds, etc.)."""
