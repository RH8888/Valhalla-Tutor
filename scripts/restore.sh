#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"
PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-}"
AUTO_YES=0
DRY_RUN=0
RESTORE_DB=1
RESTORE_UPLOADS=1
SKIP_HEALTH=0
BACKUP_FILE=""

usage() {
    cat <<'EOF'
Usage: restore.sh [OPTIONS] <backup_file>

Verify and safely restore a Valhalla Tutor backup (.tar.gz or .tar.gz.enc).

Options:
  --yes, -y               Skip interactive confirmation prompt (for automation)
  --dry-run               Verify backup integrity, checksums, and dump contents without modifying live data
  --passphrase-file FILE  Read decryption passphrase from FILE (or set BACKUP_ENCRYPTION_KEY)
  --db-only               Restore only the PostgreSQL database
  --uploads-only          Restore only the uploaded files volume
  --skip-health-check     Skip post-restore /health/db verification
  --compose-file FILE     Path to docker-compose.yml (default: ./docker-compose.yml)
  -h, --help              Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)
            AUTO_YES=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --passphrase-file)
            PASSPHRASE_FILE="$2"
            shift 2
            ;;
        --db-only)
            RESTORE_DB=1
            RESTORE_UPLOADS=0
            shift
            ;;
        --uploads-only)
            RESTORE_DB=0
            RESTORE_UPLOADS=1
            shift
            ;;
        --skip-health-check)
            SKIP_HEALTH=1
            shift
            ;;
        --compose-file)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Error: Unknown option '$1'" >&2
            usage >&2
            exit 1
            ;;
        *)
            [[ -z "$BACKUP_FILE" ]] || { echo "Error: Multiple backup files specified" >&2; exit 1; }
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"
}

die() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2
    exit 1
}

[[ -n "$BACKUP_FILE" ]] || { usage >&2; exit 1; }
[[ -r "$BACKUP_FILE" ]] || die "Backup file not found or not readable: $BACKUP_FILE"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-valhalla_db}"

command -v docker >/dev/null 2>&1 || die "docker is required"
command -v tar >/dev/null 2>&1 || die "tar is required"
command -v gzip >/dev/null 2>&1 || die "gzip is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
docker compose version >/dev/null 2>&1 || die "docker compose plugin is required"

dc() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

WORK_DIR="$(mktemp -d)"
cleanup() {
    if [[ -d "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT ERR INT TERM

BUNDLE_PATH="$WORK_DIR/bundle.tar.gz"

if [[ "$BACKUP_FILE" == *.enc ]]; then
    command -v openssl >/dev/null 2>&1 || die "openssl is required to decrypt .enc backups"
    log "Decrypting backup archive..."
    if [[ -n "$PASSPHRASE_FILE" ]]; then
        [[ -r "$PASSPHRASE_FILE" ]] || die "Passphrase file not readable: $PASSPHRASE_FILE"
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
            -in "$BACKUP_FILE" -out "$BUNDLE_PATH" -pass "file:$PASSPHRASE_FILE" \
            || die "Decryption failed (check passphrase)"
    elif [[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
            -in "$BACKUP_FILE" -out "$BUNDLE_PATH" -pass env:BACKUP_ENCRYPTION_KEY \
            || die "Decryption failed (check BACKUP_ENCRYPTION_KEY)"
    else
        die "Encrypted backup requires BACKUP_ENCRYPTION_KEY or --passphrase-file"
    fi
else
    cp "$BACKUP_FILE" "$BUNDLE_PATH"
fi

log "Verifying bundle archive integrity..."
gzip -t "$BUNDLE_PATH" || die "Backup bundle failed gzip integrity check"
mkdir -p "$WORK_DIR/extracted"
tar -xzf "$BUNDLE_PATH" -C "$WORK_DIR/extracted" || die "Failed to extract backup bundle"

EXTRACTED_DIR="$WORK_DIR/extracted"
[[ -f "$EXTRACTED_DIR/SHA256SUMS" ]] || die "Missing SHA256SUMS in backup bundle"
[[ -f "$EXTRACTED_DIR/db.dump" ]] || die "Missing db.dump in backup bundle"
[[ -f "$EXTRACTED_DIR/uploads.tar.gz" ]] || die "Missing uploads.tar.gz in backup bundle"

log "Verifying SHA-256 checksums..."
(
    cd "$EXTRACTED_DIR"
    sha256sum -c SHA256SUMS >/dev/null
) || die "SHA-256 checksum verification failed; aborting without touching live data"

log "Verifying PostgreSQL dump readability..."
dc exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 \
    || die "PostgreSQL container 'db' is not ready"
dc exec -T db pg_restore --list < "$EXTRACTED_DIR/db.dump" >/dev/null \
    || die "db.dump failed pg_restore --list verification"

log "Verifying uploads archive integrity..."
gzip -t "$EXTRACTED_DIR/uploads.tar.gz" || die "uploads.tar.gz failed gzip integrity check"
tar -tzf "$EXTRACTED_DIR/uploads.tar.gz" >/dev/null || die "uploads.tar.gz failed tar listing check"

if [[ -f "$EXTRACTED_DIR/metadata.txt" ]]; then
    log "Backup metadata:"
    sed 's/^/  /' "$EXTRACTED_DIR/metadata.txt"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    log "Dry-run verification PASSED. No live data was modified."
    exit 0
fi

if [[ "$AUTO_YES" -ne 1 ]]; then
    echo ""
    echo "WARNING: This will overwrite live data in database '$POSTGRES_DB' and/or '/app/uploads'."
    read -r -p "Type 'RESTORE' to continue: " CONFIRM
    if [[ "$CONFIRM" != "RESTORE" ]]; then
        die "Restore cancelled by operator"
    fi
fi

log "Stopping 'web' container to prevent concurrent writes during restore..."
dc stop web

if [[ "$RESTORE_DB" -eq 1 ]]; then
    log "Terminating active connections to '$POSTGRES_DB'..."
    dc exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();" \
        >/dev/null

    log "Restoring PostgreSQL database '$POSTGRES_DB' (single transaction)..."
    dc exec -T db pg_restore \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --single-transaction \
        --exit-on-error \
        < "$EXTRACTED_DIR/db.dump"
    log "Database restore completed."
fi

if [[ "$RESTORE_UPLOADS" -eq 1 ]]; then
    log "Restoring uploaded files into uploads_data volume..."
    dc run --rm -T --no-deps --entrypoint "" web sh -c '
        set -eu
        STAGE="/app/uploads/.restore_tmp"
        rm -rf "$STAGE"
        mkdir -p "$STAGE"
        tar -xzf - -C "$STAGE"
        test -d "$STAGE/uploads"
        find /app/uploads -mindepth 1 -maxdepth 1 ! -name ".restore_tmp" -exec rm -rf {} +
        mkdir -p /app/uploads/practice_booklets /app/uploads/report_cards
        cp -a "$STAGE/uploads/." /app/uploads/
        rm -rf "$STAGE"
    ' < "$EXTRACTED_DIR/uploads.tar.gz"
    log "Uploaded files restore completed."
fi

log "Starting 'web' container..."
dc up -d web

if [[ "$SKIP_HEALTH" -eq 0 ]]; then
    log "Waiting for application health check (/health/db)..."
    HEALTHY=0
    for _ in $(seq 1 30); do
        if dc exec -T web curl -fsS http://localhost:8000/health/db >/dev/null 2>&1; then
            HEALTHY=1
            break
        fi
        sleep 2
    done
    [[ "$HEALTHY" -eq 1 ]] || die "Application failed /health/db check after restore"
    log "Application is healthy (/health/db returned 200 OK)."
fi

log "Restore workflow completed successfully."
