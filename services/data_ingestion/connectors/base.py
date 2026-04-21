"""Abstract base class for all APEX data connectors.

Defines the DataConnector interface that all exchange-specific connectors
must implement. Uses the Strategy pattern (Gamma et al. 1994) for
interchangeable data sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from core.models.data import Bar, BarSize, DbTick


class DataConnector(ABC):
    """Abstract interface for exchange data connectors.

    Every concrete connector must implement:
    - ``fetch_bars``: download historical OHLCV bars
    - ``fetch_ticks``: download historical tick/trade data
    - ``connector_name``: human-readable identifier
    """

    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        bar_size: BarSize,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[Bar]]:
        """Yield batches of historical bars for *symbol* in the given range.

        Args:
            symbol: Exchange-native trading pair (e.g. ``BTCUSDT``).
            bar_size: Bar time-frame resolution.
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`Bar` instances, up to 1000 per batch.
        """
        ...

    @abstractmethod
    def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[DbTick]]:
        """Yield batches of historical ticks for *symbol* in the given range.

        Args:
            symbol: Exchange-native trading pair (e.g. ``BTCUSDT``).
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`DbTick` instances, up to 1000 per batch.
        """
        ...

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Return a human-readable identifier for this connector."""
        ...
