#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"

echo "Starting PostgreSQL service for full test suite..."
docker compose -f "$COMPOSE_FILE" up -d db

echo "Waiting for PostgreSQL to become healthy..."
for _ in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-valhalla_db}" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "Building web image and running full pytest suite (including TestClient & PostgreSQL integration)..."
docker compose -f "$COMPOSE_FILE" build web
docker compose -f "$COMPOSE_FILE" run --rm -T --no-deps \
    -v "$PROJECT_ROOT/tests:/app/tests:ro" \
    -e ENVIRONMENT=test \
    -e POSTGRES_SERVER=db \
    -e POSTGRES_PORT=5432 \
    web pytest -q
