"""FeatureStore ABC — versioned, reproducible feature persistence.

This interface defines the contract for storing and retrieving
computed features.  The concrete implementation (TimescaleDB-backed)
arrives in Phase 3.2.

Phase 3.2 revision: added ``asset_id`` parameter to all methods
to support multi-asset feature storage (D017).

Reference:
    Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
    Learning Systems". *NeurIPS*, 2503-2511.
    Fowler, M. (2002). *Patterns of Enterprise Application
    Architecture*, Ch. 10 — "Repository Pattern". Addison-Wesley.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

import polars as pl

from features.versioning import FeatureVersion


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
        asset_id: UUID,
        features: pl.DataFrame,
        version: FeatureVersion,
    ) -> None:
        """Persist a versioned feature DataFrame.

        Args:
            asset_id: Asset UUID.
            features: Feature data to store.
            version: Immutable version record.

        Raises:
            FeatureVersionExistsError: If the version already exists.
        """

    @abstractmethod
    async def load(
        self,
        asset_id: UUID,
        feature_names: list[str],
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
        version: str | None = None,
    ) -> pl.DataFrame:
        """Load feature data with point-in-time semantics.

        Args:
            asset_id: Asset UUID.
            feature_names: Feature names to load.
            start: Start of time range (inclusive).
            end: End of time range (inclusive).
            as_of: Point-in-time cutoff — only data computed before
                this timestamp is returned.  Prevents look-ahead bias.
            version: Specific version to load.  If None, the latest
                version as of ``as_of`` is resolved automatically.

        Returns:
            Polars DataFrame with timestamp + one column per feature.
        """

    @abstractmethod
    async def list_versions(
        self,
        asset_id: UUID,
        feature_name: str,
    ) -> list[FeatureVersion]:
        """List all stored versions for a given asset + feature.

        Args:
            asset_id: Asset UUID.
            feature_name: Feature name.

        Returns:
            List of FeatureVersion records, oldest first.
        """

    @abstractmethod
    async def latest_version(
        self,
        asset_id: UUID,
        feature_name: str,
        as_of: datetime | None = None,
    ) -> FeatureVersion | None:
        """Return the latest version for a given asset + feature.

        Args:
            asset_id: Asset UUID.
            feature_name: Feature name.
            as_of: If provided, only versions computed before this
                timestamp are considered.

        Returns:
            Latest FeatureVersion, or None if no versions exist.
        """
