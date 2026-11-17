#!/bin/sh
set -e

# Ensure uploads directories exist
mkdir -p /app/uploads/practice_booklets /app/uploads/report_cards

# Wait for PostgreSQL to become reachable and ready
if [ -n "$POSTGRES_SERVER" ]; then
    echo "Verifying database connectivity at $POSTGRES_SERVER:${POSTGRES_PORT:-5432}..."
    MAX_RETRIES=${DB_WAIT_RETRIES:-30}
    COUNT=0
    until python -c "
import sys, psycopg2, os
try:
    conn = psycopg2.connect(
        host=os.environ.get('POSTGRES_SERVER', 'db'),
        port=int(os.environ.get('POSTGRES_PORT', 5432)),
        user=os.environ.get('POSTGRES_USER', 'postgres'),
        password=os.environ.get('POSTGRES_PASSWORD', ''),
        dbname=os.environ.get('POSTGRES_DB', 'valhalla_db'),
        connect_timeout=3
    )
    conn.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
        COUNT=$((COUNT + 1))
        if [ "$COUNT" -ge "$MAX_RETRIES" ]; then
            echo "Error: Timed out waiting for database at $POSTGRES_SERVER:${POSTGRES_PORT:-5432}." >&2
            exit 1
        fi
        echo "Database is not ready yet (attempt $COUNT/$MAX_RETRIES). Waiting 1s..."
        sleep 1
    done
    echo "Database connection established successfully."
fi

# Run database migrations if AUTO_MIGRATE is not explicitly disabled
if [ "${AUTO_MIGRATE:-true}" = "true" ]; then
    echo "Executing database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "Database migrations completed."
else
    echo "AUTO_MIGRATE is disabled. Skipping automatic database migrations."
fi

# Set default web worker concurrency if unset
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"

# Hand over to the primary command (e.g. uvicorn)
exec "$@"
