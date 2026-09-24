#!/bin/sh
# Substitute environment variables into the SQL module config
# then wait for Postgres to be ready before starting FreeRADIUS.
set -e

SQL_CONF="/etc/freeradius/3.0/mods-available/sql"
TEMP_CONF="${SQL_CONF}.tmp"

# Replace shell-style ${VAR} placeholders in the sql module config
sed \
    -e "s/\${RADIUS_DB_HOST}/${RADIUS_DB_HOST:-db}/g" \
    -e "s/\${RADIUS_DB_PORT}/${RADIUS_DB_PORT:-5432}/g" \
    -e "s/\${RADIUS_DB_NAME}/${RADIUS_DB_NAME:-radius}/g" \
    -e "s/\${RADIUS_DB_USER}/${RADIUS_DB_USER:-radius}/g" \
    -e "s/\${RADIUS_DB_PASSWORD}/${RADIUS_DB_PASSWORD:-devpassword}/g" \
    "$SQL_CONF" > "$TEMP_CONF"

mv "$TEMP_CONF" "$SQL_CONF"

# Wait for Postgres to be ready
echo "Waiting for Postgres at ${RADIUS_DB_HOST:-db}:${RADIUS_DB_PORT:-5432}..."
until pg_isready -h "${RADIUS_DB_HOST:-db}" -p "${RADIUS_DB_PORT:-5432}" -U "${RADIUS_DB_USER:-radius}" -d "${RADIUS_DB_NAME:-radius}" -q; do
    sleep 2
done
echo "Postgres ready. Starting FreeRADIUS..."

exec "$@"
