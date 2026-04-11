"""Async repository for all TimescaleDB operations.

Uses asyncpg connection pool with COPY protocol for bulk inserts.
Implements the Repository pattern (Fowler 2002, Ch. 18).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timezone

import asyncpg

from services.s01_data_ingestion.observability.metrics import (
    record_db_insert,
    record_db_query,
)
from services.s01_data_ingestion.observability.tracing import trace_async

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
)

_MACRO_META_FIELDS = ("series_id", "source", "name", "frequency", "unit", "description")


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
        """Create the connection pool with JSON/JSONB codec registration."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
            init=self._init_connection,
        )

    @staticmethod
    async def _init_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
        """Register JSON/JSONB codecs so asyncpg auto-serializes dicts."""
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "json",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
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
        return uuid.UUID(str(row["asset_id"]))

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
        row = await pool.fetchrow("SELECT * FROM assets WHERE asset_id = $1", asset_id)
        if row is None:
            return None
        return self._row_to_asset(row)

    async def search_assets(self, query: str, asset_class: AssetClass | None = None) -> list[Asset]:
        """Search assets by symbol prefix, optionally filtered by asset_class."""
        pool = self._get_pool()
        if asset_class is not None:
            rows = await pool.fetch(
                "SELECT * FROM assets WHERE symbol ILIKE $1 AND asset_class = $2 ORDER BY symbol",
                f"{query}%",
                asset_class.value,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM assets WHERE symbol ILIKE $1 ORDER BY symbol",
                f"{query}%",
            )
        return [self._row_to_asset(r) for r in rows]

    async def list_assets(self, asset_class: AssetClass | None = None) -> list[Asset]:
        """List all assets, optionally filtered by asset_class."""
        pool = self._get_pool()
        if asset_class is not None:
            rows = await pool.fetch(
                "SELECT * FROM assets WHERE asset_class = $1 ORDER BY symbol",
                asset_class.value,
            )
        else:
            rows = await pool.fetch("SELECT * FROM assets ORDER BY symbol")
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

    @trace_async("timescale.insert_bars")
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
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "bars",
            records=records,
            columns=[
                "asset_id",
                "bar_type",
                "bar_size",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
                "adj_close",
            ],
        )
        record_db_insert("bars", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_bars(
        self,
        asset_id: uuid.UUID,
        bar_type: str,
        bar_size: str,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[Bar]:
        """Fetch bars for an asset within a time range."""
        pool = self._get_pool()
        sql = """
            SELECT * FROM bars
            WHERE asset_id = $1 AND bar_type = $2 AND bar_size = $3
              AND timestamp >= $4 AND timestamp < $5
            ORDER BY timestamp
        """
        params: list[object] = [asset_id, bar_type, bar_size, start, end]
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await pool.fetch(sql, *params)
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

    @trace_async("timescale.insert_ticks")
    async def insert_ticks(self, ticks: list[DbTick]) -> int:
        """Bulk-insert ticks using COPY protocol. Returns count inserted."""
        if not ticks:
            return 0
        pool = self._get_pool()
        records = [
            (t.asset_id, t.timestamp, t.trade_id, t.price, t.quantity, t.side) for t in ticks
        ]
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "ticks",
            records=records,
            columns=["asset_id", "timestamp", "trade_id", "price", "quantity", "side"],
        )
        record_db_insert("ticks", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_ticks(
        self,
        asset_id: uuid.UUID,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[DbTick]:
        """Fetch ticks for an asset within a time range."""
        pool = self._get_pool()
        sql = """
            SELECT * FROM ticks
            WHERE asset_id = $1 AND timestamp >= $2 AND timestamp < $3
            ORDER BY timestamp
        """
        params: list[object] = [asset_id, start, end]
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await pool.fetch(sql, *params)
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

    @trace_async("timescale.insert_macro_points")
    async def insert_macro_points(self, points: list[MacroPoint]) -> int:
        """Bulk-insert macro series points. Returns count inserted."""
        if not points:
            return 0
        pool = self._get_pool()
        records = [(p.series_id, p.timestamp, p.value) for p in points]
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "macro_series",
            records=records,
            columns=["series_id", "timestamp", "value"],
        )
        record_db_insert("macro_series", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_macro_series(
        self,
        series_id: str,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[MacroPoint]:
        """Fetch macro series data within a time range."""
        pool = self._get_pool()
        sql = """
            SELECT * FROM macro_series
            WHERE series_id = $1 AND timestamp >= $2 AND timestamp < $3
            ORDER BY timestamp
        """
        params: list[object] = [series_id, start, end]
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await pool.fetch(sql, *params)
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
            meta.series_id,
            meta.source,
            meta.name,
            meta.frequency,
            meta.unit,
            meta.description,
        )

    async def get_macro_metadata(self, series_id: str) -> MacroSeriesMeta | None:
        """Fetch metadata for a macro series by series_id."""
        pool = self._get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM macro_series_metadata WHERE series_id = $1",
            series_id,
        )
        if row is None:
            return None
        return MacroSeriesMeta(**{f: row[f] for f in _MACRO_META_FIELDS})

    # ── Fundamentals ──────────────────────────────────────────────────────────

    @trace_async("timescale.insert_fundamentals")
    async def insert_fundamentals(self, points: list[FundamentalPoint]) -> int:
        """Bulk-insert fundamental data points. Returns count inserted."""
        if not points:
            return 0
        pool = self._get_pool()
        records = [
            (p.asset_id, p.report_date, p.period_type, p.metric_name, p.value, p.currency)
            for p in points
        ]
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "fundamentals",
            records=records,
            columns=["asset_id", "report_date", "period_type", "metric_name", "value", "currency"],
        )
        record_db_insert("fundamentals", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_fundamentals(
        self,
        asset_id: uuid.UUID,
        start: date,
        end: date,
        period_type: str | None = None,
        limit: int | None = None,
    ) -> list[FundamentalPoint]:
        """Fetch fundamental data points for an asset within a date range."""
        pool = self._get_pool()
        if period_type is not None:
            sql = """
                SELECT * FROM fundamentals
                WHERE asset_id = $1 AND report_date >= $2 AND report_date < $3
                  AND period_type = $4
                ORDER BY report_date, metric_name
            """
            params: list[object] = [asset_id, start, end, period_type]
        else:
            sql = """
                SELECT * FROM fundamentals
                WHERE asset_id = $1 AND report_date >= $2 AND report_date < $3
                ORDER BY report_date, metric_name
            """
            params = [asset_id, start, end]
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await pool.fetch(sql, *params)
        return [
            FundamentalPoint(
                asset_id=r["asset_id"],
                report_date=r["report_date"],
                period_type=r["period_type"],
                metric_name=r["metric_name"],
                value=r["value"],
                currency=r["currency"],
            )
            for r in rows
        ]

    # ── Events ────────────────────────────────────────────────────────────────

    @trace_async("timescale.insert_economic_events")
    async def insert_economic_events(self, events: list[EconomicEvent]) -> int:
        """Bulk-insert economic events. Returns count inserted."""
        if not events:
            return 0
        pool = self._get_pool()
        records = [
            (
                e.event_id,
                e.event_type,
                e.scheduled_time,
                e.actual,
                e.consensus,
                e.prior,
                e.impact_score,
                e.related_asset_id,
                e.source,
            )
            for e in events
        ]
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "economic_events",
            records=records,
            columns=[
                "event_id",
                "event_type",
                "scheduled_time",
                "actual",
                "consensus",
                "prior",
                "impact_score",
                "related_asset_id",
                "source",
            ],
        )
        record_db_insert("economic_events", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    @trace_async("timescale.insert_corporate_events")
    async def insert_corporate_events(self, events: list[CorporateEvent]) -> int:
        """Bulk-insert corporate events. Returns count inserted."""
        if not events:
            return 0
        pool = self._get_pool()
        records = [
            (e.event_id, e.asset_id, e.event_date, e.event_type, e.details_json) for e in events
        ]
        start = time.monotonic()
        result = await pool.copy_records_to_table(
            "corporate_events",
            records=records,
            columns=["event_id", "asset_id", "event_date", "event_type", "details_json"],
        )
        record_db_insert("corporate_events", time.monotonic() - start)
        return int(result.split()[-1]) if isinstance(result, str) else len(records)

    async def get_economic_events(
        self,
        start: datetime,
        end: datetime,
        event_type: str | None = None,
        min_impact: int = 1,
        limit: int | None = None,
    ) -> list[EconomicEvent]:
        """Fetch economic events within a time range, with optional filters.

        Also used by the /upcoming endpoint (which is just a time-window alias).
        """
        pool = self._get_pool()
        if event_type is not None:
            sql = """
                SELECT * FROM economic_events
                WHERE scheduled_time >= $1 AND scheduled_time < $2
                  AND event_type = $3 AND impact_score >= $4
                ORDER BY scheduled_time
            """
            params: list[object] = [start, end, event_type, min_impact]
        else:
            sql = """
                SELECT * FROM economic_events
                WHERE scheduled_time >= $1 AND scheduled_time < $2
                  AND impact_score >= $3
                ORDER BY scheduled_time
            """
            params = [start, end, min_impact]
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await pool.fetch(sql, *params)
        return [self._row_to_economic_event(r) for r in rows]

    @staticmethod
    def _row_to_economic_event(row: asyncpg.Record) -> EconomicEvent:
        """Convert an asyncpg Record to an EconomicEvent model."""
        return EconomicEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            scheduled_time=row["scheduled_time"],
            actual=row["actual"],
            consensus=row["consensus"],
            prior=row["prior"],
            impact_score=row["impact_score"],
            related_asset_id=row["related_asset_id"],
            source=row.get("source"),
        )

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
            run_id,
            connector,
            asset_id,
            datetime.now(timezone.utc),
        )
        return run_id

    async def finish_ingestion_run(
        self,
        run_id: uuid.UUID,
        status: IngestionStatus,
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
            datetime.now(timezone.utc),
            status.value,
            rows,
            error,
            run_id,
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
