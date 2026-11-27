#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

log_step() {
    printf '\n==> %s\n' "$1"
}

log_info() {
    printf '    %s\n' "$1"
}

fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

trap 'printf "\nERROR: Command failed at line %d: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

compose() {
    docker compose --project-directory "$PROJECT_ROOT" -f "$COMPOSE_FILE" "$@"
}

read_port() {
    if [[ -n "${PORT:-}" ]]; then
        printf '%s' "$PORT"
        return
    fi
    if [[ -f "$ENV_FILE" ]]; then
        local env_port
        env_port="$(grep -E '^PORT=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | tr -d '[:space:]"'\''' || true)"
        if [[ -n "$env_port" ]]; then
            printf '%s' "$env_port"
            return
        fi
    fi
    printf '8000'
}

APP_PORT="$(read_port)"
HEALTH_URL="http://127.0.0.1:${APP_PORT}/health/db"

require_prereqs() {
    command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH."
    docker compose version >/dev/null 2>&1 || fail "docker compose plugin is not available."
    [[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"
}

wait_for_db() {
    log_step "Ensuring PostgreSQL (db) is running and healthy"
    compose up -d db

    local pg_user="${POSTGRES_USER:-postgres}"
    local pg_db="${POSTGRES_DB:-valhalla_db}"
    if [[ -f "$ENV_FILE" ]]; then
        local env_user env_db
        env_user="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | tr -d '[:space:]"'\''' || true)"
        env_db="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | tr -d '[:space:]"'\''' || true)"
        [[ -n "$env_user" ]] && pg_user="$env_user"
        [[ -n "$env_db" ]] && pg_db="$env_db"
    fi

    for _ in $(seq 1 30); do
        if compose exec -T db pg_isready -U "$pg_user" -d "$pg_db" >/dev/null 2>&1; then
            log_info "PostgreSQL is ready."
            return 0
        fi
        sleep 2
    done

    fail "PostgreSQL did not become ready within 60 seconds."
}

wait_for_health() {
    log_step "Verifying application health ($HEALTH_URL)"
    for _ in $(seq 1 30); do
        if command -v curl >/dev/null 2>&1; then
            if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
                log_info "Application is healthy."
                return 0
            fi
        elif compose exec -T web curl -fsS "http://localhost:8000/health/db" >/dev/null 2>&1; then
            log_info "Application is healthy."
            return 0
        fi
        sleep 2
    done

    printf '\nRecent web logs:\n' >&2
    compose logs --tail=30 web >&2 || true
    fail "Health check failed at $HEALTH_URL after 60 seconds."
}

cmd_update() {
    local skip_backup=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-backup)
                skip_backup=1
                shift
                ;;
            -h|--help)
                cat <<'EOF'
Usage: manage.sh update [--skip-backup]

Safely update the deployment:
  1. Check for uncommitted local Git changes
  2. Create a local pre-update backup via scripts/backup.sh --no-telegram
  3. Pull latest code (git pull --ff-only)
  4. Rebuild web image
  5. Ensure db is running and run alembic upgrade head
  6. Restart web and verify /health/db
EOF
                return 0
                ;;
            *)
                fail "Unknown option for update: $1"
                ;;
        esac
    done

    require_prereqs
    command -v git >/dev/null 2>&1 || fail "git is not installed or not in PATH."

    log_step "Checking Git working tree"
    if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain)" ]]; then
        git -C "$PROJECT_ROOT" status --short >&2
        fail "Uncommitted local changes detected. Commit or stash them before updating."
    fi
    log_info "Working tree is clean."

    if [[ "$skip_backup" -eq 0 ]]; then
        log_step "Creating pre-update local backup"
        [[ -f "$SCRIPT_DIR/backup.sh" ]] || fail "Backup script not found: $SCRIPT_DIR/backup.sh"
        bash "$SCRIPT_DIR/backup.sh" --no-telegram
    else
        log_step "Skipping pre-update backup (--skip-backup)"
    fi

    log_step "Pulling latest code (git pull --ff-only)"
    git -C "$PROJECT_ROOT" pull --ff-only

    log_step "Rebuilding web Docker image"
    compose build web

    wait_for_db

    log_step "Running database migrations (alembic upgrade head)"
    compose run --rm --no-deps web alembic upgrade head

    log_step "Starting updated web container"
    compose up -d --no-deps web

    wait_for_health
    log_step "Update complete"
}

cmd_start() {
    require_prereqs
    log_step "Starting Docker Compose stack"
    compose up -d
    wait_for_health
}

cmd_stop() {
    require_prereqs
    log_step "Stopping Docker Compose containers (preserving volumes and data)"
    compose stop
    log_info "Containers stopped."
}

cmd_restart() {
    require_prereqs
    log_step "Restarting application"
    compose up -d
    compose restart web
    wait_for_health
}

cmd_status() {
    require_prereqs

    log_step "Container status"
    compose ps

    log_step "Git commit"
    if command -v git >/dev/null 2>&1 && git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        local branch commit dirty_state
        branch="$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
        commit="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || printf 'unknown')"
        if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain)" ]]; then
            dirty_state="dirty"
        else
            dirty_state="clean"
        fi
        log_info "$branch @ $commit ($dirty_state)"
    else
        log_info "Git metadata unavailable"
    fi

    log_step "Alembic revision"
    if compose ps --status running --services 2>/dev/null | grep -qx "web"; then
        compose exec -T web alembic current || log_info "Could not read Alembic revision."
    else
        log_info "web container is not running."
    fi

    log_step "Health endpoint ($HEALTH_URL)"
    if command -v curl >/dev/null 2>&1; then
        local resp
        if resp="$(curl -fsS "$HEALTH_URL" 2>/dev/null)"; then
            log_info "HEALTHY: $resp"
        else
            log_info "UNHEALTHY or unreachable"
            return 1
        fi
    else
        if compose exec -T web curl -fsS "http://localhost:8000/health/db" >/dev/null 2>&1; then
            log_info "HEALTHY"
        else
            log_info "UNHEALTHY or unreachable"
            return 1
        fi
    fi
}

cmd_logs() {
    require_prereqs
    log_step "Streaming web logs (Ctrl+C to exit)"
    compose logs -f --tail=100 web "$@"
}

usage() {
    cat <<'EOF'
Usage: scripts/manage.sh <command> [options]

Manage the Valhalla Tutor Docker Compose stack on a single VPS.

Commands:
  update [--skip-backup]  Check clean Git tree, run local backup, pull, rebuild, migrate, restart, and verify health
  start                   Start the Docker Compose stack and verify /health/db
  stop                    Gracefully stop running containers without deleting volumes or data
  restart                 Restart the application and verify /health/db
  status                  Show container status, Git commit, Alembic revision, and /health/db status
  logs                    Stream recent web container logs
  help                    Show this help message
EOF
}

main() {
    if [[ $# -eq 0 ]]; then
        usage
        exit 1
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        update)
            cmd_update "$@"
            ;;
        start)
            cmd_start "$@"
            ;;
        stop)
            cmd_stop "$@"
            ;;
        restart)
            cmd_restart "$@"
            ;;
        status)
            cmd_status "$@"
            ;;
        logs)
            cmd_logs "$@"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            printf 'Error: Unknown command "%s"\n\n' "$cmd" >&2
            usage >&2
            exit 1
            ;;
    esac
}

main "$@"
