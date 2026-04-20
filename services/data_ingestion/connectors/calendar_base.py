"""Abstract base class for APEX calendar event connectors.

Defines the CalendarConnector interface — separate from DataConnector and
MacroConnector because calendar events use ``EconomicEvent`` (dates of
CB meetings, economic data releases) rather than time series data.

Uses the Strategy pattern (Gamma et al. 1994) for interchangeable
calendar sources (Fed FOMC scraper, ECB calendar, BoJ MPM, FRED releases).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from core.models.data import EconomicEvent


class CalendarConnector(ABC):
    """Abstract interface for calendar event connectors.

    Every concrete connector must implement:
    - ``fetch_events``: download calendar events in a date range
    - ``connector_name``: human-readable identifier
    """

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Return a human-readable identifier for this connector."""
        ...

    @abstractmethod
    def fetch_events(
        self,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[EconomicEvent]]:
        """Yield batches of economic events in the given date range.

        Args:
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`EconomicEvent` instances.
        """
        ...
