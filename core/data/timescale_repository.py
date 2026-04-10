"""Async repository for all TimescaleDB operations.

Uses asyncpg connection pool with COPY protocol for bulk inserts.
Implements the Repository pattern (Fowler 2002, Ch. 18).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from core.models.data import (
    Asset,
    AssetClass,
    Bar,
    BarSize,
    BarType,
    CorporateEvent,
    DataQualityEntry,
    DbTick,
    EconomicEvent,
    FundamentalPoint,
    IngestionStatus,
    MacroPoint,
    MacroSeriesMeta,
    Severity,
)


class TimescaleRepository:
    """Async repository for all TimescaleDB operations.

    Uses asyncpg connection pool with COPY protocol for bulk inserts.
    """

    def __init__(self, dsn: str, pool_min: int = 2, pool_max: int = 10) -> None:
        self._dsn = dsn
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None

    async def connect(self) -> None:
        """Create the connection pool."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _get_pool(self) -> asyncpg.Pool[asyncpg.Record]:
        """Return the pool, raising if not connected."""
        if self._pool is None:
            msg = "Repository not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._pool

    # ── Assets ────────────────────────────────────────────────────────────────

    async def upsert_asset(self, asset: Asset) -> uuid.UUID:
        """Insert or update an asset, returning its asset_id."""
        pool = self._get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO assets (
                asset_id, symbol, exchange, asset_class, currency,
                timezone, tick_size, lot_size, is_active,
                listing_date, delisting_date, metadata_json,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (symbol, exchange) DO UPDATE SET
                asset_class   = EXCLUDED.asset_class,
                currency      = EXCLUDED.currency,
                timezone      = EXCLUDED.timezone,
                tick_size     = EXCLUDED.tick_size,
                lot_size      = EXCLUDED.lot_size,
                is_active     = EXCLUDED.is_active,
                listing_date  = EXCLUDED.listing_date,
                delisting_date = EXCLUDED.delisting_date,
                metadata_json = EXCLUDED.metadata_json,
                updated_at    = NOW()
            RETURNING asset_id
            """,
            asset.asset_id,
            asset.symbol,
            asset.exchange,
            asset.asset_class.value,
            asset.currency,
            asset.timezone,
            asset.tick_size,
            asset.lot_size,
            asset.is_active,
            asset.listing_date,
            asset.delisting_date,
            asset.metadata_json,
            asset.created_at or datetime.now(timezone.utc),
            asset.updated_at or datetime.now(timezone.utc),
        )
        return uuid.UUID(str(row["asset_id"]))  # type: ignore[index]

    async def get_asset(self, symbol: str, exchange: str) -> Asset | None:
        """Look up an asset by symbol and exchange."""
        pool = self._get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM assets WHERE symbol = $1 AND exchange = $2",
            symbol.upper(),
            exchange.upper(),
        )
        if row is None:
            return None
        return self._row_to_asset(row)

    async def get_asset_by_id(self, asset_id: uuid.UUID) -> Asset | None:
        """Look up an asset by its UUID."""
        pool = self._get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM assets WHERE asset_id = $1", asset_id
        )
        if row is None:
            return None
        return self._row_to_asset(row)

    async def search_assets(
        self, query: str, asset_class: str | None = None
    ) -> list[Asset]:
        """Search assets by symbol prefix, optionally filtered by asset_class."""
        pool = self._get_pool()
        if asset_class is not None:
            rows = await pool.fetch(
                "SELECT * FROM assets WHERE symbol ILIKE $1 AND asset_class = $2 ORDER BY symbol",
                f"{query}%",
                asset_class,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM assets WHERE symbol ILIKE $1 ORDER BY symbol",
                f"{query}%",
            )
        return [self._row_to_asset(r) for r in rows]

    @staticmethod
    def _row_to_asset(row: asyncpg.Record) -> Asset:
        """Convert an asyncpg Record to an Asset model."""
        return Asset(
            asset_id=row["asset_id"],
            symbol=row["symbol"],
            exchange=row["exchange"],
            asset_class=AssetClass(row["asset_class"]),
            currency=row["currency"],
            timezone=row["timezone"],
            tick_size=row["tick_size"],
            lot_size=row["lot_size"],
            is_active=row["is_active"],
            listing_date=row["listing_date"],
            delisting_date=row["delisting_date"],
            metadata_json=dict(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ── Bars ──────────────────────────────────────────────────────────────────

    async def insert_bars(self, bars: list[Bar]) -> int:
        """Bulk-insert bars using COPY protocol. Returns count inserted."""
        if not bars:
            return 0
        pool = self._get_pool()
        records = [
            (
                b.asset_id,
                b.bar_type.value,
                b.bar_size.value,
                b.timestamp,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.trade_count,
                b.vwap,
                b.adj_close,
            )
            for b in bars
        ]
        result = await pool.copy_records_to_table(
            "bars",
            records=records,
            columns=[
                "asset_id", "bar_type", "bar_size", "timestamp",
                "open", "high", "low", "close", "volume",
                "trade_count", "vwap", "adj_close",
            ],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_bars(
        self,
        asset_id: uuid.UUID,
        bar_type: str,
        bar_size: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Fetch bars for an asset within a time range."""
        pool = self._get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM bars
            WHERE asset_id = $1 AND bar_type = $2 AND bar_size = $3
              AND timestamp >= $4 AND timestamp < $5
            ORDER BY timestamp
            """,
            asset_id, bar_type, bar_size, start, end,
        )
        return [
            Bar(
                asset_id=r["asset_id"],
                bar_type=BarType(r["bar_type"]),
                bar_size=BarSize(r["bar_size"]),
                timestamp=r["timestamp"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                trade_count=r["trade_count"],
                vwap=r["vwap"],
                adj_close=r["adj_close"],
            )
            for r in rows
        ]

    # ── Ticks ─────────────────────────────────────────────────────────────────

    async def insert_ticks(self, ticks: list[DbTick]) -> int:
        """Bulk-insert ticks using COPY protocol. Returns count inserted."""
        if not ticks:
            return 0
        pool = self._get_pool()
        records = [
            (t.asset_id, t.timestamp, t.trade_id, t.price, t.quantity, t.side)
            for t in ticks
        ]
        result = await pool.copy_records_to_table(
            "ticks",
            records=records,
            columns=["asset_id", "timestamp", "trade_id", "price", "quantity", "side"],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_ticks(
        self, asset_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[DbTick]:
        """Fetch ticks for an asset within a time range."""
        pool = self._get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM ticks
            WHERE asset_id = $1 AND timestamp >= $2 AND timestamp < $3
            ORDER BY timestamp
            """,
            asset_id, start, end,
        )
        return [
            DbTick(
                asset_id=r["asset_id"],
                timestamp=r["timestamp"],
                trade_id=r["trade_id"],
                price=r["price"],
                quantity=r["quantity"],
                side=r["side"],
            )
            for r in rows
        ]

    # ── Macro ─────────────────────────────────────────────────────────────────

    async def insert_macro_points(
        self, series_id: str, points: list[MacroPoint]
    ) -> int:
        """Bulk-insert macro series points. Returns count inserted."""
        if not points:
            return 0
        pool = self._get_pool()
        records = [(series_id, p.timestamp, p.value) for p in points]
        result = await pool.copy_records_to_table(
            "macro_series",
            records=records,
            columns=["series_id", "timestamp", "value"],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_macro_series(
        self, series_id: str, start: datetime, end: datetime
    ) -> list[MacroPoint]:
        """Fetch macro series data within a time range."""
        pool = self._get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM macro_series
            WHERE series_id = $1 AND timestamp >= $2 AND timestamp < $3
            ORDER BY timestamp
            """,
            series_id, start, end,
        )
        return [
            MacroPoint(
                series_id=r["series_id"],
                timestamp=r["timestamp"],
                value=r["value"],
            )
            for r in rows
        ]

    async def upsert_macro_metadata(self, meta: MacroSeriesMeta) -> None:
        """Insert or update macro series metadata."""
        pool = self._get_pool()
        await pool.execute(
            """
            INSERT INTO macro_series_metadata (series_id, source, name, frequency, unit, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (series_id) DO UPDATE SET
                source = EXCLUDED.source,
                name   = EXCLUDED.name,
                frequency = EXCLUDED.frequency,
                unit = EXCLUDED.unit,
                description = EXCLUDED.description
            """,
            meta.series_id, meta.source, meta.name,
            meta.frequency, meta.unit, meta.description,
        )

    # ── Fundamentals ──────────────────────────────────────────────────────────

    async def insert_fundamentals(self, points: list[FundamentalPoint]) -> int:
        """Bulk-insert fundamental data points. Returns count inserted."""
        if not points:
            return 0
        pool = self._get_pool()
        records = [
            (p.asset_id, p.report_date, p.period_type, p.metric_name, p.value, p.currency)
            for p in points
        ]
        result = await pool.copy_records_to_table(
            "fundamentals",
            records=records,
            columns=["asset_id", "report_date", "period_type", "metric_name", "value", "currency"],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    # ── Events ────────────────────────────────────────────────────────────────

    async def insert_economic_events(self, events: list[EconomicEvent]) -> int:
        """Bulk-insert economic events. Returns count inserted."""
        if not events:
            return 0
        pool = self._get_pool()
        records = [
            (
                e.event_id, e.event_type, e.scheduled_time,
                e.actual, e.consensus, e.prior,
                e.impact_score, e.related_asset_id, e.source,
            )
            for e in events
        ]
        result = await pool.copy_records_to_table(
            "economic_events",
            records=records,
            columns=[
                "event_id", "event_type", "scheduled_time",
                "actual", "consensus", "prior",
                "impact_score", "related_asset_id", "source",
            ],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def insert_corporate_events(self, events: list[CorporateEvent]) -> int:
        """Bulk-insert corporate events. Returns count inserted."""
        if not events:
            return 0
        pool = self._get_pool()
        records = [
            (e.event_id, e.asset_id, e.event_date, e.event_type, e.details_json)
            for e in events
        ]
        result = await pool.copy_records_to_table(
            "corporate_events",
            records=records,
            columns=["event_id", "asset_id", "event_date", "event_type", "details_json"],
        )
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    # ── Ingestion tracking ────────────────────────────────────────────────────

    async def start_ingestion_run(
        self, connector: str, asset_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        """Create a new ingestion run and return its run_id."""
        pool = self._get_pool()
        run_id = uuid.uuid4()
        await pool.execute(
            """
            INSERT INTO ingestion_runs (run_id, connector, asset_id, started_at, status)
            VALUES ($1, $2, $3, $4, 'running')
            """,
            run_id, connector, asset_id, datetime.now(timezone.utc),
        )
        return run_id

    async def finish_ingestion_run(
        self,
        run_id: uuid.UUID,
        status: str,
        rows: int,
        error: str | None = None,
    ) -> None:
        """Mark an ingestion run as finished."""
        pool = self._get_pool()
        await pool.execute(
            """
            UPDATE ingestion_runs
            SET finished_at = $1, status = $2, rows_inserted = $3, error_message = $4
            WHERE run_id = $5
            """,
            datetime.now(timezone.utc), status, rows, error, run_id,
        )

    # ── Data quality ──────────────────────────────────────────────────────────

    async def log_quality_check(self, entry: DataQualityEntry) -> None:
        """Insert a data quality log entry."""
        pool = self._get_pool()
        await pool.execute(
            """
            INSERT INTO data_quality_log
                (check_id, timestamp, check_type, asset_id, severity, details_json, resolved)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            entry.check_id,
            entry.timestamp or datetime.now(timezone.utc),
            entry.check_type,
            entry.asset_id,
            entry.severity.value,
            entry.details_json,
            entry.resolved,
        )

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the pool is connected and responsive."""
        try:
            pool = self._get_pool()
            row = await pool.fetchrow("SELECT 1 AS ok")
            return row is not None and row["ok"] == 1
        except Exception:
            return False
