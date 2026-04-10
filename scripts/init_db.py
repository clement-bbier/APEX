"""Idempotent database migration runner for APEX Trading System.

Reads SQL migration files from db/migrations/ in alphabetical order,
checks schema_versions to skip already-applied migrations, and applies
new ones inside a transaction.

Usage:
    python scripts/init_db.py [--host HOST] [--port PORT] [--db DB]
                              [--user USER] [--password PASSWORD]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

import asyncpg
import structlog

logger = structlog.get_logger("init_db")


async def _ensure_schema_versions(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Create schema_versions table if it does not exist."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            version    INTEGER      PRIMARY KEY,
            filename   VARCHAR(200) NOT NULL,
            applied_at TIMESTAMPTZ  DEFAULT NOW(),
            checksum   VARCHAR(64)
        )
        """
    )


async def _get_applied(conn: asyncpg.Connection[asyncpg.Record]) -> set[str]:
    """Return the set of already-applied migration filenames."""
    rows = await conn.fetch("SELECT filename FROM schema_versions")
    return {r["filename"] for r in rows}


def _extract_version(filename: str) -> int:
    """Extract the integer version prefix from a migration filename.

    Example: '001_universal_schema.sql' -> 1
    """
    prefix = filename.split("_", maxsplit=1)[0]
    return int(prefix)


async def run_migrations(
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> None:
    """Apply all pending migrations from db/migrations/."""
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    migrations_dir = Path(__file__).resolve().parent.parent / "db" / "migrations"

    if not migrations_dir.exists():
        msg = f"Migrations directory not found: {migrations_dir}"
        raise FileNotFoundError(msg)

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        logger.info("no_migrations_found", path=str(migrations_dir))
        return

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(dsn)
    try:
        await _ensure_schema_versions(conn)
        applied = await _get_applied(conn)

        for sql_file in sql_files:
            if sql_file.name in applied:
                logger.info("migration_already_applied", filename=sql_file.name)
                continue

            sql = sql_file.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            version = _extract_version(sql_file.name)

            logger.info("applying_migration", filename=sql_file.name, version=version)

            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    """
                    INSERT INTO schema_versions (version, filename, checksum)
                    VALUES ($1, $2, $3)
                    """,
                    version,
                    sql_file.name,
                    checksum,
                )

            logger.info("migration_applied", filename=sql_file.name, version=version)

    finally:
        await conn.close()

    logger.info("all_migrations_complete")


def main() -> None:
    """CLI entry point for init_db."""
    import sys

    parser = argparse.ArgumentParser(description="APEX DB migration runner")
    parser.add_argument("--host", default="localhost", help="TimescaleDB host")
    parser.add_argument("--port", type=int, default=5432, help="TimescaleDB port")
    parser.add_argument("--db", default="apex", help="Database name")
    parser.add_argument("--user", default="apex", help="Database user")
    parser.add_argument("--password", default="apex_secret", help="Database password")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(
        run_migrations(
            host=args.host,
            port=args.port,
            db=args.db,
            user=args.user,
            password=args.password,
        )
    )


if __name__ == "__main__":
    main()
