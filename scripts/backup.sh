#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
KEEP_DAYS="${BACKUP_RETENTION_DAYS:-14}"
KEEP_COUNT="${BACKUP_RETENTION_COUNT:-7}"
ENCRYPT_MODE="auto"
PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-}"
SKIP_TELEGRAM=0

usage() {
    cat <<'EOF'
Usage: backup.sh [OPTIONS]

Create a verified, atomic backup of Valhalla Tutor's PostgreSQL database and uploads volume.

Options:
  --backup-dir DIR        Target directory for backups (default: ./backups)
  --keep-days N           Delete backups older than N days (default: 14, 0 disables age pruning)
  --keep-count N          Always retain at least N newest backups (default: 7)
  --encrypt               Require AES-256-CBC encryption (fails if no key/passphrase is provided)
  --no-encrypt            Disable encryption even if BACKUP_ENCRYPTION_KEY is set
  --passphrase-file FILE  Read encryption passphrase from FILE (or set BACKUP_ENCRYPTION_KEY)
  --no-telegram           Skip off-site Telegram delivery step
  --compose-file FILE     Path to docker-compose.yml (default: ./docker-compose.yml)
  -h, --help              Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup-dir)
            BACKUP_DIR="$2"
            shift 2
            ;;
        --keep-days)
            KEEP_DAYS="$2"
            shift 2
            ;;
        --keep-count)
            KEEP_COUNT="$2"
            shift 2
            ;;
        --encrypt)
            ENCRYPT_MODE="yes"
            shift
            ;;
        --no-encrypt)
            ENCRYPT_MODE="no"
            shift
            ;;
        --passphrase-file)
            PASSPHRASE_FILE="$2"
            ENCRYPT_MODE="yes"
            shift 2
            ;;
        --no-telegram)
            SKIP_TELEGRAM=1
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
        *)
            echo "Error: Unknown option '$1'" >&2
            usage >&2
            exit 1
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

if [[ "$ENCRYPT_MODE" == "auto" ]]; then
    if [[ -n "${BACKUP_ENCRYPTION_KEY:-}" || -n "$PASSPHRASE_FILE" ]]; then
        ENCRYPT_MODE="yes"
    else
        ENCRYPT_MODE="no"
    fi
fi

if [[ "$ENCRYPT_MODE" == "yes" ]]; then
    command -v openssl >/dev/null 2>&1 || die "openssl is required for encryption"
    if [[ -n "$PASSPHRASE_FILE" ]]; then
        [[ -r "$PASSPHRASE_FILE" ]] || die "Passphrase file not readable: $PASSPHRASE_FILE"
    elif [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
        die "Encryption requested but neither BACKUP_ENCRYPTION_KEY nor --passphrase-file is set"
    fi
fi

mkdir -p "$BACKUP_DIR"

LOCK_DIR="$BACKUP_DIR/.backup.lock"
STAGING_DIR=""
FINAL_TMP=""
LOCK_ACQUIRED=0

cleanup() {
    local exit_code=$?
    if [[ -n "$FINAL_TMP" && -f "$FINAL_TMP" ]]; then
        rm -f "$FINAL_TMP"
    fi
    if [[ -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
        rm -rf "$STAGING_DIR"
    fi
    if [[ "$LOCK_ACQUIRED" -eq 1 && -d "$LOCK_DIR" ]]; then
        rm -rf "$LOCK_DIR"
    fi
    if [[ "$exit_code" -ne 0 ]]; then
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Backup failed (exit $exit_code). No partial backup was kept." >&2
    fi
    exit "$exit_code"
}
trap cleanup EXIT ERR INT TERM

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    die "Another backup process is already running (lock: $LOCK_DIR)"
fi
LOCK_ACQUIRED=1
echo "$$" > "$LOCK_DIR/pid"

dc() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

log "Checking database container readiness..."
dc exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 \
    || die "PostgreSQL container 'db' is not ready"

STAGING_DIR="$(mktemp -d "$BACKUP_DIR/.staging.XXXXXX")"
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"

log "Capturing consistent PostgreSQL snapshot ($POSTGRES_DB)..."
dc exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -b --no-owner --no-privileges \
    > "$STAGING_DIR/db.dump"

[[ -s "$STAGING_DIR/db.dump" ]] || die "Database dump is empty"

log "Verifying PostgreSQL dump archive..."
dc exec -T db pg_restore --list < "$STAGING_DIR/db.dump" >/dev/null \
    || die "Database dump failed pg_restore --list verification"

log "Capturing uploaded files archive..."
if dc ps --status running --services 2>/dev/null | grep -qx "web"; then
    dc exec -T web tar -czf - -C /app uploads > "$STAGING_DIR/uploads.tar.gz"
else
    dc run --rm -T --no-deps --entrypoint "" web tar -czf - -C /app uploads > "$STAGING_DIR/uploads.tar.gz"
fi

log "Verifying uploaded files archive..."
gzip -t "$STAGING_DIR/uploads.tar.gz" || die "uploads.tar.gz failed gzip integrity check"
tar -tzf "$STAGING_DIR/uploads.tar.gz" >/dev/null || die "uploads.tar.gz failed tar listing check"

ALEMBIC_REV="$(dc exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null || echo "unknown")"
GIT_SHA="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
UPLOAD_COUNT="$(tar -tzf "$STAGING_DIR/uploads.tar.gz" | grep -v '/$' | wc -l | tr -d ' ')"

cat > "$STAGING_DIR/metadata.txt" <<EOF
timestamp_utc=$TIMESTAMP
postgres_db=$POSTGRES_DB
alembic_version=${ALEMBIC_REV:-unknown}
git_commit=$GIT_SHA
upload_file_count=$UPLOAD_COUNT
db_dump_bytes=$(wc -c < "$STAGING_DIR/db.dump" | tr -d ' ')
uploads_tar_bytes=$(wc -c < "$STAGING_DIR/uploads.tar.gz" | tr -d ' ')
EOF

log "Generating and verifying SHA-256 manifest..."
(
    cd "$STAGING_DIR"
    sha256sum db.dump uploads.tar.gz metadata.txt > SHA256SUMS
    sha256sum -c SHA256SUMS >/dev/null
) || die "SHA-256 manifest verification failed"

log "Packaging backup bundle..."
tar -czf "$STAGING_DIR/bundle.tar.gz" -C "$STAGING_DIR" db.dump uploads.tar.gz metadata.txt SHA256SUMS
gzip -t "$STAGING_DIR/bundle.tar.gz" || die "bundle.tar.gz failed gzip check"
tar -tzf "$STAGING_DIR/bundle.tar.gz" >/dev/null || die "bundle.tar.gz failed tar check"

if [[ "$ENCRYPT_MODE" == "yes" ]]; then
    FINAL_NAME="valhalla_backup_${TIMESTAMP}.tar.gz.enc"
    FINAL_TMP="$BACKUP_DIR/.tmp.${FINAL_NAME}.$$"
    log "Encrypting backup bundle with AES-256-CBC (PBKDF2)..."
    if [[ -n "$PASSPHRASE_FILE" ]]; then
        openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
            -in "$STAGING_DIR/bundle.tar.gz" -out "$FINAL_TMP" \
            -pass "file:$PASSPHRASE_FILE"
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
            -in "$FINAL_TMP" -pass "file:$PASSPHRASE_FILE" | tar -tzf - >/dev/null \
            || die "Encrypted backup failed decryption verification"
    else
        openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
            -in "$STAGING_DIR/bundle.tar.gz" -out "$FINAL_TMP" \
            -pass env:BACKUP_ENCRYPTION_KEY
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
            -in "$FINAL_TMP" -pass env:BACKUP_ENCRYPTION_KEY | tar -tzf - >/dev/null \
            || die "Encrypted backup failed decryption verification"
    fi
else
    FINAL_NAME="valhalla_backup_${TIMESTAMP}.tar.gz"
    FINAL_TMP="$BACKUP_DIR/.tmp.${FINAL_NAME}.$$"
    mv "$STAGING_DIR/bundle.tar.gz" "$FINAL_TMP"
fi

mv "$FINAL_TMP" "$BACKUP_DIR/$FINAL_NAME"
FINAL_TMP=""
log "Backup created and verified: $BACKUP_DIR/$FINAL_NAME"

# Optional off-site Telegram delivery (never fails local backup)
if [[ "$SKIP_TELEGRAM" -eq 0 ]]; then
    log "Attempting off-site Telegram delivery (if enabled in DB settings)..."
    if dc ps --status running --services 2>/dev/null | grep -qx "web"; then
        dc exec -T web python -m app.services.telegram_backup_service \
            --stdin --filename "$FINAL_NAME" < "$BACKUP_DIR/$FINAL_NAME" \
            || log "Warning: Telegram delivery step failed; local backup remains intact."
    else
        dc run --rm -T --no-deps --entrypoint "" web python -m app.services.telegram_backup_service \
            --stdin --filename "$FINAL_NAME" < "$BACKUP_DIR/$FINAL_NAME" \
            || log "Warning: Telegram delivery step failed; local backup remains intact."
    fi
fi

# Retention cleanup (only after new backup succeeds)
if [[ "$KEEP_DAYS" -gt 0 ]] 2>/dev/null; then
    mapfile -t ALL_BACKUPS < <(
        find "$BACKUP_DIR" -maxdepth 1 -type f \
            \( -name 'valhalla_backup_*.tar.gz' -o -name 'valhalla_backup_*.tar.gz.enc' \) \
            -printf '%T@ %p\n' | sort -rn | awk '{print $2}'
    )
    TOTAL_BACKUPS="${#ALL_BACKUPS[@]}"
    if [[ "$TOTAL_BACKUPS" -gt "$KEEP_COUNT" ]]; then
        CUTOFF_EPOCH=$(( $(date +%s) - (KEEP_DAYS * 86400) ))
        for (( i=KEEP_COUNT; i<TOTAL_BACKUPS; i++ )); do
            OLD_FILE="${ALL_BACKUPS[$i]}"
            FILE_MTIME="$(stat -c %Y "$OLD_FILE" 2>/dev/null || echo 0)"
            if [[ "$FILE_MTIME" -lt "$CUTOFF_EPOCH" ]]; then
                rm -f "$OLD_FILE"
                log "Pruned expired backup: $OLD_FILE"
            fi
        done
    fi
fi

log "Backup workflow completed successfully."
