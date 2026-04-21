#!/usr/bin/env bash
# scripts/db/init.sh — bring up TimescaleDB and apply migrations.
#
# Idempotent: safe to run repeatedly. Every SQL file in db/migrations/
# is guarded with CREATE ... IF NOT EXISTS and equivalent TimescaleDB
# clauses, so re-application is a no-op.
#
# Usage:
#   scripts/db/init.sh                 # default apex DB
#   DB_NAME=apex_test scripts/db/init.sh
#
# Environment:
#   DB_HOST       (default: localhost)
#   DB_PORT       (default: 5432)
#   DB_USER       (default: apex)
#   DB_NAME       (default: apex)
#   DB_PASSWORD   (default: apex_secret — override in .env for real use)
#   COMPOSE_FILE  (default: docker/docker-compose.yml)
#
# Exit codes:
#   0 success
#   1 TimescaleDB failed to become healthy in time
#   2 a migration file failed to apply

set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-apex}"
DB_NAME="${DB_NAME:-apex}"
DB_PASSWORD="${DB_PASSWORD:-apex_secret}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "[init] TimescaleDB bring-up ..."
docker compose -f "$COMPOSE_FILE" up -d timescaledb

echo "[init] waiting for TimescaleDB to be healthy ..."
TIMEOUT=60
ELAPSED=0
until docker compose -f "$COMPOSE_FILE" exec -T timescaledb \
        pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
        echo "[init] ERROR: TimescaleDB did not become ready in ${TIMEOUT}s"
        docker compose -f "$COMPOSE_FILE" logs --tail=40 timescaledb
        exit 1
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo "[init] TimescaleDB is healthy."

echo "[init] applying migrations from db/migrations/ ..."
shopt -s nullglob
MIGRATIONS=(db/migrations/*.sql)
if [ ${#MIGRATIONS[@]} -eq 0 ]; then
    echo "[init] WARN: no *.sql files found in db/migrations/"
    exit 0
fi

for migration in "${MIGRATIONS[@]}"; do
    name="$(basename "$migration")"
    echo "[init]   → $name"
    if ! docker compose -f "$COMPOSE_FILE" exec -T \
            -e PGPASSWORD="$DB_PASSWORD" timescaledb \
            psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q < "$migration"; then
        echo "[init] ERROR: migration $name failed"
        exit 2
    fi
done

echo "[init] schema versions:"
docker compose -f "$COMPOSE_FILE" exec -T \
    -e PGPASSWORD="$DB_PASSWORD" timescaledb \
    psql -U "$DB_USER" -d "$DB_NAME" -c \
    "SELECT version, filename, applied_at FROM schema_versions_v2 ORDER BY version;" \
    || echo "[init] (schema_versions_v2 not present — schema v2 not yet applied)"

echo "[init] done."
