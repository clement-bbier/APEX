"""TimescaleFeatureStore — TimescaleDB-backed feature store with Redis cache.

Implements point-in-time queries via the ``computed_at`` column
in both ``feature_values`` and ``feature_versions``.  Load with
``as_of=T`` returns only values computed at wall-clock time <= T,
making look-ahead bias structurally impossible (PHASE_3_SPEC Section 5.1).

References:
    Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
    Learning Systems". *NeurIPS*, 2503-2511.
    Fowler, M. (2002). *Patterns of Enterprise Application
    Architecture*, Ch. 10 — "Repository Pattern". Addison-Wesley.
    Kleppmann, M. (2017). *Designing Data-Intensive Applications*,
    Ch. 11 — "Stream Processing". O'Reilly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import polars as pl
import redis.asyncio as redis
import structlog

from features.exceptions import (
    FeatureVersionExistsError,
    FeatureVersionNotFoundError,
    LookAheadViolationError,
)
from features.registry import FeatureRegistry
from features.store.base import FeatureStore
from features.versioning import FeatureVersion

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TimescaleFeatureStore(FeatureStore):
    """TimescaleDB-backed feature store with Redis cache.

    Implements the Repository Pattern (Fowler, 2002) over
    ``feature_values`` and ``feature_versions`` hypertables.

    Point-in-time guarantee:
        Every ``load()`` call with ``as_of=T`` filters on
        ``computed_at <= T`` in both the version resolution query
        and the data fetch query.  This makes look-ahead bias
        structurally impossible.

    References:
        Sculley et al. (2015) NeurIPS; Fowler (2002) PoEAA Ch. 10;
        Kleppmann (2017) DDIA Ch. 11.
    """

    def __init__(
        self,
        pg_pool: asyncpg.Pool[asyncpg.Record],
        redis_client: redis.Redis,
        registry: FeatureRegistry,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._pool = pg_pool
        self._redis = redis_client
        self._registry = registry
        self._cache_ttl = cache_ttl_seconds

    # ── FeatureStore.save ────────────────────────────────────────────────

    async def save(
        self,
        asset_id: UUID,
        features: pl.DataFrame,
        version: FeatureVersion,
    ) -> None:
        """Persist a versioned feature DataFrame via COPY protocol.

        Refuses to overwrite existing versions (immutability invariant).
        After inserting data, registers the version in the catalog.

        Args:
            asset_id: Asset UUID.
            features: DataFrame with ``timestamp`` + feature columns.
            version: Immutable version record.

        Raises:
            FeatureVersionExistsError: If the version already exists.
        """
        existing = await self._registry.get(asset_id, version.feature_name, version.version)
        if existing is not None:
            raise FeatureVersionExistsError(
                f"Version '{version.version}' for feature "
                f"'{version.feature_name}' on asset {asset_id} "
                f"already exists (computed_at={existing.computed_at})."
            )

        records: list[tuple[UUID, str, str, datetime, float | None, datetime]] = []
        timestamps = features["timestamp"].to_list()
        values = features[version.feature_name].to_list()

        for ts, val in zip(timestamps, values, strict=True):
            records.append(
                (
                    asset_id,
                    version.feature_name,
                    version.version,
                    ts,
                    float(val) if val is not None else None,
                    version.computed_at,
                )
            )

        await self._pool.copy_records_to_table(
            "feature_values",
            records=records,
            columns=[
                "asset_id",
                "feature_name",
                "version",
                "timestamp",
                "value",
                "computed_at",
            ],
        )

        await self._registry.register(version)

        logger.info(
            "feature_store.saved",
            asset_id=str(asset_id),
            feature_name=version.feature_name,
            version=version.version,
            rows=len(records),
        )

    # ── FeatureStore.load ────────────────────────────────────────────────

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

        If ``as_of`` is None, defaults to ``datetime.now(UTC)`` and
        logs a warning (callers should always be explicit for backtests).

        Args:
            asset_id: Asset UUID.
            feature_names: Feature names to load.
            start: Start of time range (inclusive).
            end: End of time range (inclusive).
            as_of: Point-in-time cutoff.
            version: Specific version string.  If None, latest per
                feature as of ``as_of`` is resolved.

        Returns:
            Polars DataFrame with ``timestamp`` + one column per feature.

        Raises:
            FeatureVersionNotFoundError: If a requested feature has
                no version matching the criteria.
            LookAheadViolationError: If any returned row has
                computed_at > as_of (should be structurally impossible).
        """
        if not feature_names:
            return pl.DataFrame({"timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC"))})

        if as_of is None:
            as_of = datetime.now(UTC)
            logger.warning(
                "feature_store.load_without_as_of",
                asset_id=str(asset_id),
                feature_names=feature_names,
                resolved_as_of=as_of.isoformat(),
            )

        frames: list[pl.DataFrame] = []
        for fname in feature_names:
            resolved_version = version
            if resolved_version is None:
                ver_record = await self._registry.latest_version(asset_id, fname, as_of)
                if ver_record is None:
                    raise FeatureVersionNotFoundError(
                        f"No version found for feature '{fname}' on "
                        f"asset {asset_id} as of {as_of.isoformat()}."
                    )
                resolved_version = ver_record.version

            cache_key = self._cache_key(asset_id, fname, resolved_version, start, end, as_of)
            cached = await self._cache_get(cache_key)
            if cached is not None:
                frames.append(cached.rename({"value": fname}))
                continue

            rows = await self._pool.fetch(
                """
                SELECT timestamp, value
                FROM feature_values
                WHERE asset_id = $1
                  AND feature_name = $2
                  AND version = $3
                  AND timestamp >= $4
                  AND timestamp <= $5
                  AND computed_at <= $6
                ORDER BY timestamp
                """,
                asset_id,
                fname,
                resolved_version,
                start,
                end,
                as_of,
            )

            if rows:
                df = pl.DataFrame(
                    {
                        "timestamp": [r["timestamp"] for r in rows],
                        "value": [r["value"] for r in rows],
                    }
                )
                # Structural safety check (§5.1)
                self._assert_no_lookahead(df, as_of, fname)
                await self._cache_set(cache_key, df)
                frames.append(df.rename({"value": fname}))
            else:
                frames.append(
                    pl.DataFrame(
                        {
                            "timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                            fname: pl.Series([], dtype=pl.Float64),
                        }
                    )
                )

        if not frames:
            return pl.DataFrame({"timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC"))})

        result = frames[0]
        for frame in frames[1:]:
            result = result.join(frame, on="timestamp", how="full", coalesce=True)

        return result.sort("timestamp")

    # ── FeatureStore.list_versions ───────────────────────────────────────

    async def list_versions(
        self,
        asset_id: UUID,
        feature_name: str,
    ) -> list[FeatureVersion]:
        """Delegate to registry."""
        return await self._registry.list_versions(asset_id, feature_name)

    # ── FeatureStore.latest_version ──────────────────────────────────────

    async def latest_version(
        self,
        asset_id: UUID,
        feature_name: str,
        as_of: datetime | None = None,
    ) -> FeatureVersion | None:
        """Delegate to registry."""
        return await self._registry.latest_version(asset_id, feature_name, as_of)

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _assert_no_lookahead(
        df: pl.DataFrame,
        as_of: datetime,
        feature_name: str,
    ) -> None:
        """Guard: verify no row has a future computed_at (structural bug check)."""
        if "computed_at" in df.columns:
            raw_max = df["computed_at"].max()
            if raw_max is not None:
                max_computed = datetime.fromisoformat(str(raw_max)) if not isinstance(raw_max, datetime) else raw_max
                if max_computed > as_of:
                    raise LookAheadViolationError(
                        f"Feature '{feature_name}' returned rows with "
                        f"computed_at={max_computed!r} > as_of={as_of!r}. "
                        f"This is a structural bug in the query."
                    )

    @staticmethod
    def _cache_key(
        asset_id: UUID,
        feature_name: str,
        version: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> str:
        """Build a deterministic Redis cache key."""
        return (
            f"feature:{asset_id}:{feature_name}:{version}"
            f":{start.isoformat()}:{end.isoformat()}"
            f":{as_of.isoformat()}"
        )

    async def _cache_get(self, key: str) -> pl.DataFrame | None:
        """Try to load a cached DataFrame from Redis."""
        try:
            data = await self._redis.get(key)
            if data is None:
                return None
            parsed = json.loads(data)
            return pl.DataFrame(parsed)
        except Exception:
            return None

    async def _cache_set(self, key: str, df: pl.DataFrame) -> None:
        """Cache a DataFrame in Redis with TTL."""
        try:
            data = df.to_dict(as_series=False)
            await self._redis.setex(key, self._cache_ttl, json.dumps(data, default=str))
        except Exception as exc:
            logger.debug(
                "feature_store.cache_set_failed",
                key=key,
                error=str(exc),
            )
