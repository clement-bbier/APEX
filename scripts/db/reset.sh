#!/usr/bin/env bash
# scripts/db/reset.sh — DESTRUCTIVE: wipe the TimescaleDB volume.
#
# ╔══════════════════════════════════════════════════════════════════╗
# ║                         DEV ONLY                                 ║
# ║                                                                  ║
# ║  This script destroys the TimescaleDB Docker volume. Every row   ║
# ║  of every table — ticks, bars, signals, trades, PnL snapshots —  ║
# ║  is GONE after this runs. There is no undo.                      ║
# ║                                                                  ║
# ║  Refuses to run unless APEX_ENV=dev is set explicitly, and asks  ║
# ║  for a typed confirmation on top of that.                        ║
# ╚══════════════════════════════════════════════════════════════════╝
#
# Usage:
#   APEX_ENV=dev scripts/db/reset.sh

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ "${APEX_ENV:-}" != "dev" ]; then
    cat <<'EOF' >&2
[reset] REFUSING to run: APEX_ENV is not set to "dev".

This script is destructive (wipes the TimescaleDB volume). It is
intentionally gated behind the APEX_ENV=dev guard so that nobody can
run it against a staging or production compose stack by muscle memory.

To proceed on your local dev box:
    APEX_ENV=dev scripts/db/reset.sh
EOF
    exit 1
fi

cat <<'EOF'
╔══════════════════════════════════════════════════════════════════╗
║  APEX TimescaleDB RESET                                         ║
║                                                                  ║
║  About to:                                                       ║
║    1. docker compose stop  timescaledb                           ║
║    2. docker compose rm -f timescaledb                           ║
║    3. docker volume rm apex-trading_timescale_data               ║
║                                                                  ║
║  Every tick, bar, signal, order, trade, PnL snapshot will be     ║
║  permanently destroyed.                                          ║
╚══════════════════════════════════════════════════════════════════╝
EOF

read -r -p 'Type "WIPE" (uppercase) to proceed: ' confirmation
if [ "$confirmation" != "WIPE" ]; then
    echo "[reset] confirmation did not match — aborting."
    exit 1
fi

echo "[reset] stopping timescaledb ..."
docker compose -f "$COMPOSE_FILE" stop timescaledb || true

echo "[reset] removing timescaledb container ..."
docker compose -f "$COMPOSE_FILE" rm -f timescaledb || true

VOLUME_NAME="$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)timescale_data$' | head -n 1 || true)"
if [ -n "$VOLUME_NAME" ]; then
    echo "[reset] removing volume $VOLUME_NAME ..."
    docker volume rm "$VOLUME_NAME"
else
    echo "[reset] (no timescale_data volume found — already gone)"
fi

echo "[reset] done. Run scripts/db/init.sh to rebuild."
