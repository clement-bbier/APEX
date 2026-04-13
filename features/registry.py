"""FeatureRegistry — metadata catalog for computed features.

Backed by the ``feature_versions`` table in TimescaleDB. Provides
lookup and listing of feature versions with point-in-time semantics.

Reference:
    Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
    Learning Systems". *NeurIPS*, 2503-2511 — Section 2.2
    "Hidden Feedback Loops": a registry makes feature dependencies
    explicit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import structlog

from features.versioning import FeatureVersion

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class FeatureRegistry:
    """Metadata catalog of available features.

    All operations go through asyncpg against the ``feature_versions``
    table created by ``db/migrations/002_feature_store.sql``.

    Reference:
        Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
        Learning Systems". *NeurIPS*, 2503-2511.
    """

    def __init__(self, pool: asyncpg.Pool[asyncpg.Record]) -> None:
        self._pool = pool

    async def register(self, version: FeatureVersion) -> None:
        """Register a new feature version in the catalog.

        Args:
            version: Immutable version record to register.

        Raises:
            asyncpg.UniqueViolationError: If (asset_id, feature_name,
                version) already exists — versions are immutable.
        """
        await self._pool.execute(
            """
            INSERT INTO feature_versions (
                asset_id, feature_name, version, computed_at,
                content_hash, calculator_name, calculator_params,
                row_count, start_ts, end_ts
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            version.asset_id,
            version.feature_name,
            version.version,
            version.computed_at,
            version.content_hash,
            version.calculator_name,
            json.dumps(dict(version.calculator_params)),
            version.row_count,
            version.start_ts,
            version.end_ts,
        )
        logger.info(
            "feature_version.registered",
            asset_id=str(version.asset_id),
            feature_name=version.feature_name,
            version=version.version,
            row_count=version.row_count,
        )

    async def list_features(self, asset_id: UUID) -> list[str]:
        """List distinct feature names available for an asset.

        Args:
            asset_id: Asset UUID.

        Returns:
            Sorted list of feature names.
        """
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT feature_name
            FROM feature_versions
            WHERE asset_id = $1
            ORDER BY feature_name
            """,
            asset_id,
        )
        return [r["feature_name"] for r in rows]

    async def list_versions(
        self,
        asset_id: UUID,
        feature_name: str,
    ) -> list[FeatureVersion]:
        """List all versions for a given asset + feature, oldest first.

        Args:
            asset_id: Asset UUID.
            feature_name: Feature name.

        Returns:
            List of FeatureVersion records ordered by computed_at ASC.
        """
        rows = await self._pool.fetch(
            """
            SELECT * FROM feature_versions
            WHERE asset_id = $1 AND feature_name = $2
            ORDER BY computed_at ASC
            """,
            asset_id,
            feature_name,
        )
        return [self._row_to_version(r) for r in rows]

    async def latest_version(
        self,
        asset_id: UUID,
        feature_name: str,
        as_of: datetime | None = None,
    ) -> FeatureVersion | None:
        """Return the latest version for a feature, optionally as of a point in time.

        Args:
            asset_id: Asset UUID.
            feature_name: Feature name.
            as_of: If provided, only versions with computed_at <= as_of
                are considered (point-in-time semantics).

        Returns:
            Latest FeatureVersion, or None if no versions match.
        """
        if as_of is None:
            as_of = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """
            SELECT * FROM feature_versions
            WHERE asset_id = $1 AND feature_name = $2
              AND computed_at <= $3
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            asset_id,
            feature_name,
            as_of,
        )
        if row is None:
            return None
        return self._row_to_version(row)

    async def get(
        self,
        asset_id: UUID,
        feature_name: str,
        version: str,
    ) -> FeatureVersion | None:
        """Get a specific version record.

        Args:
            asset_id: Asset UUID.
            feature_name: Feature name.
            version: Version string.

        Returns:
            FeatureVersion if found, else None.
        """
        row = await self._pool.fetchrow(
            """
            SELECT * FROM feature_versions
            WHERE asset_id = $1 AND feature_name = $2 AND version = $3
            """,
            asset_id,
            feature_name,
            version,
        )
        if row is None:
            return None
        return self._row_to_version(row)

    @staticmethod
    def _row_to_version(row: asyncpg.Record) -> FeatureVersion:
        """Convert an asyncpg Record to a FeatureVersion."""
        params = row["calculator_params"]
        if isinstance(params, str):
            params = json.loads(params)
        return FeatureVersion(
            asset_id=row["asset_id"],
            feature_name=row["feature_name"],
            version=row["version"],
            computed_at=row["computed_at"],
            content_hash=row["content_hash"],
            calculator_name=row["calculator_name"],
            calculator_params=params if params else {},
            row_count=row["row_count"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
        )
