"""FeatureStore ABC — versioned, reproducible feature persistence.

This interface defines the contract for storing and retrieving
computed features.  The concrete implementation (TimescaleDB-backed)
arrives in Phase 3.2.

Reference:
    Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
    Learning Systems". *NeurIPS*, 2503-2511.
    Fowler, M. (2002). *Patterns of Enterprise Application
    Architecture*, Ch. 10 — "Repository Pattern". Addison-Wesley.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import polars as pl


class FeatureStore(ABC):
    """Repository for versioned feature data.

    Implements the Repository Pattern (Fowler, 2002) for feature
    persistence.  Point-in-time queries via ``as_of`` prevent
    look-ahead bias (PHASE_3_SPEC Section 5.1).

    Reference:
        Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
        Learning Systems". *NeurIPS*, 2503-2511.
    """

    @abstractmethod
    async def save(
        self,
        name: str,
        version: str,
        df: pl.DataFrame,
    ) -> None:
        """Persist a versioned feature DataFrame.

        Args:
            name: Feature name (e.g. ``'har_rv'``).
            version: Semantic version string (e.g. ``'0.1.0'``).
            df: Feature data to store.
        """

    @abstractmethod
    async def load(
        self,
        name: str,
        version: str,
        as_of: datetime | None = None,
    ) -> pl.DataFrame:
        """Load a versioned feature DataFrame.

        Args:
            name: Feature name.
            version: Semantic version string.
            as_of: Point-in-time cutoff — only rows computed before
                this timestamp are returned.  Prevents look-ahead bias.

        Returns:
            Polars DataFrame of stored features.
        """

    @abstractmethod
    async def list_versions(self, name: str) -> list[str]:
        """List all stored versions for a given feature name.

        Args:
            name: Feature name.

        Returns:
            Sorted list of version strings (oldest first).
        """

    @abstractmethod
    async def latest_version(self, name: str) -> str | None:
        """Return the latest version for a given feature name.

        Args:
            name: Feature name.

        Returns:
            Latest version string, or None if no versions exist.
        """
