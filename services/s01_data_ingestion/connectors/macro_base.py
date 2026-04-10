"""Abstract base class for APEX macro-economic data connectors.

Defines the MacroConnector interface — separate from DataConnector because
macro series use ``series_id`` (e.g. ``FEDFUNDS``) instead of
``symbol + bar_size``.

Uses the Strategy pattern (Gamma et al. 1994) for interchangeable
macro data sources (FRED, ECB, BoJ, …).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from core.models.data import MacroPoint, MacroSeriesMeta


class MacroConnector(ABC):
    """Abstract interface for macro-economic data connectors.

    Every concrete connector must implement:
    - ``fetch_series``: download historical macro data points
    - ``fetch_metadata``: retrieve series metadata
    - ``connector_name``: human-readable identifier
    """

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Return a human-readable identifier for this connector."""
        ...

    @abstractmethod
    def fetch_series(
        self,
        series_id: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[MacroPoint]]:
        """Yield batches of macro data points for *series_id* in the given range.

        Args:
            series_id: Provider-native series identifier (e.g. ``FEDFUNDS``).
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`MacroPoint` instances, up to 1000 per batch.
        """
        ...

    @abstractmethod
    async def fetch_metadata(self, series_id: str) -> MacroSeriesMeta:
        """Retrieve metadata for a macro series.

        Args:
            series_id: Provider-native series identifier.

        Returns:
            A :class:`MacroSeriesMeta` with source, name, frequency, unit, etc.
        """
        ...
