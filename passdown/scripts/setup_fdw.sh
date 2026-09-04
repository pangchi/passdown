#!/usr/bin/env bash
# Provisions postgres_fdw access to the MES database and creates the
# mestoollist view, using credentials from .env. Safe to re-run.
#
# Requires: psql, envsubst (part of the gettext-base package, usually
# already present on Debian/Raspberry Pi OS — install with
# `sudo apt install gettext-base` if missing).
#
# Usage:
#   ./scripts/setup_fdw.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "No .env found. Copy .env.example to .env and fill in your credentials first." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${PASSDOWN_DB_HOST:?Set PASSDOWN_DB_HOST in .env}"
: "${PASSDOWN_DB_PORT:?Set PASSDOWN_DB_PORT in .env}"
: "${PASSDOWN_DB_NAME:?Set PASSDOWN_DB_NAME in .env}"
: "${PASSDOWN_DB_USER:?Set PASSDOWN_DB_USER in .env}"
: "${PASSDOWN_DB_PASSWORD:?Set PASSDOWN_DB_PASSWORD in .env}"

: "${MES_FDW_HOST:?Set MES_FDW_HOST in .env}"
: "${MES_FDW_PORT:?Set MES_FDW_PORT in .env}"
: "${MES_FDW_DBNAME:?Set MES_FDW_DBNAME in .env}"
: "${MES_FDW_USER:?Set MES_FDW_USER in .env}"
: "${MES_FDW_PASSWORD:?Set MES_FDW_PASSWORD in .env}"
: "${MES_FDW_REMOTE_SCHEMA:=public}"

tmp_sql="$(mktemp)"
trap 'rm -f "$tmp_sql"' EXIT

envsubst < fdw/setup_mestoollist_fdw.sql.template > "$tmp_sql"

echo "Provisioning mes_server + mestoollist against ${PASSDOWN_DB_NAME}@${PASSDOWN_DB_HOST}..."
PGPASSWORD="$PASSDOWN_DB_PASSWORD" psql \
    -h "$PASSDOWN_DB_HOST" -p "$PASSDOWN_DB_PORT" \
    -U "$PASSDOWN_DB_USER" -d "$PASSDOWN_DB_NAME" \
    -v ON_ERROR_STOP=1 \
    -f "$tmp_sql"

echo "Done. mestoollist is ready — restart the app (or just reload the page) to pick it up."
