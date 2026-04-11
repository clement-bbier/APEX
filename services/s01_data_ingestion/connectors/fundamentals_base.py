"""Abstract base class for APEX fundamentals data connectors.

Defines the FundamentalsConnector interface — separate from DataConnector
and MacroConnector because fundamentals use ``FundamentalPoint`` (per-asset
financial metrics) and ``CorporateEvent`` (splits, dividends, etc.).

Uses the Strategy pattern (Gamma et al. 1994) for interchangeable
fundamentals sources (SEC EDGAR, SimFin, ...).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from core.models.data import CorporateEvent, FundamentalPoint


class FundamentalsConnector(ABC):
    """Abstract interface for fundamentals data connectors.

    Every concrete connector must implement:
    - ``fetch_fundamentals``: download financial metrics for a ticker
    - ``fetch_corporate_events``: download corporate events for a ticker
    - ``connector_name``: human-readable identifier
    """

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Return a human-readable identifier for this connector."""
        ...

    @abstractmethod
    def fetch_fundamentals(
        self,
        ticker: str,
        filing_types: list[str],
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[FundamentalPoint]]:
        """Yield batches of fundamental data points for *ticker*.

        Args:
            ticker: Equity ticker symbol (e.g. ``AAPL``).
            filing_types: Filing types to include (e.g. ``["10-K", "10-Q"]``).
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`FundamentalPoint` instances.
        """
        ...

    @abstractmethod
    def fetch_corporate_events(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[list[CorporateEvent]]:
        """Yield batches of corporate events for *ticker*.

        Args:
            ticker: Equity ticker symbol (e.g. ``AAPL``).
            start: Inclusive start of the date range (UTC).
            end: Exclusive end of the date range (UTC).

        Yields:
            Lists of :class:`CorporateEvent` instances.
        """
        ...
