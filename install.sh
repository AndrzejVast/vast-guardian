#!/usr/bin/env bash
# Safe, idempotent installer for Vast Guardian.
set -euo pipefail

readonly REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly OS_RELEASE_FILE="${VAST_GUARDIAN_OS_RELEASE:-/etc/os-release}"
readonly ETC_DIR="${VAST_GUARDIAN_ETC_DIR:-/etc/vast-guardian}"
readonly SYSTEMD_DIR="${VAST_GUARDIAN_SYSTEMD_DIR:-/etc/systemd/system}"
readonly DATA_DIR="${VAST_GUARDIAN_DATA_DIR:-/var/lib/vast-guardian}"
readonly ENV_FILE="${ETC_DIR}/guardian.env"
readonly LEGACY_TELEGRAM_ENV="${ETC_DIR}/telegram.env"
readonly DB_PATH="${REPO_DIR}/database/vast_guardian.db"
readonly PYTHON_BIN="${VAST_GUARDIAN_PYTHON:-python3}"
readonly SYSTEMCTL_BIN="${VAST_GUARDIAN_SYSTEMCTL:-systemctl}"
readonly TEST_MODE="${VAST_GUARDIAN_TEST_MODE:-0}"

ROLE=""
HOST_KEY="${VAST_GUARDIAN_HOST_KEY:-}"
CENTRAL_URL="${VAST_GUARDIAN_CENTRAL_URL:-}"
INGEST_TOKEN="${VAST_GUARDIAN_INGEST_TOKEN:-}"
DRY_RUN=0
ROLLBACK_NEEDED=0
INSTALL_USER="${SUDO_USER:-$(id -un)}"
declare -a CREATED_UNITS=()
declare -a BACKED_UP_UNITS=()
declare -a STARTED_UNITS=()
declare -a ENABLED_UNITS=()
ROLLBACK_DIR=""

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [--role central|agent] [options]

Options:
  --role ROLE          Install the central or agent role.
  --host-key KEY       Stable host identifier (default: local hostname).
  --central-url URL    Required configuration for an agent.
  --ingest-token TOKEN Required configuration for an agent; never printed.
  --dry-run            Show the plan without modifying files or services.
  -h, --help           Show this help.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

note() {
    echo "==> $*"
}

run() {
    if (( DRY_RUN )); then
        printf 'DRY-RUN: '
        printf '%q ' "$@"
        printf '\n'
    else
        "$@"
    fi
}

require_file() {
    [[ -f "$1" ]] || die "Required repository file is missing: $1"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command is missing: $1"
}

parse_args() {
    while (($#)); do
        case "$1" in
            --role)
                (($# >= 2)) || die "--role requires central or agent"
                ROLE="$2"
                shift 2
                ;;
            --host-key)
                (($# >= 2)) || die "--host-key requires a value"
                HOST_KEY="$2"
                shift 2
                ;;
            --central-url)
                (($# >= 2)) || die "--central-url requires a value"
                CENTRAL_URL="$2"
                shift 2
                ;;
            --ingest-token)
                (($# >= 2)) || die "--ingest-token requires a value"
                INGEST_TOKEN="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "Unknown option: $1"
                ;;
        esac
    done
}

select_role() {
    if [[ -z "$ROLE" ]]; then
        [[ -t 0 ]] || die "--role is required when stdin is not interactive"
        read -r -p "Vast Guardian role (central/agent): " ROLE
    fi
    [[ "$ROLE" == "central" || "$ROLE" == "agent" ]] || die "Role must be central or agent"
}

detect_host_key() {
    if [[ -z "$HOST_KEY" ]]; then
        HOST_KEY="$(hostname)"
    fi
    [[ "$HOST_KEY" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "Host key contains unsupported characters"
}

collect_agent_configuration() {
    if [[ "$ROLE" != "agent" ]]; then
        return 0
    fi
    if [[ -z "$CENTRAL_URL" && -t 0 && ! $DRY_RUN -eq 1 ]]; then
        read -r -p "Central ingest URL: " CENTRAL_URL
    fi
    if [[ -z "$INGEST_TOKEN" && -t 0 && ! $DRY_RUN -eq 1 ]]; then
        read -r -s -p "Central ingest token: " INGEST_TOKEN
        printf '\n'
    fi
    [[ -n "$CENTRAL_URL" ]] || die "Agent role requires --central-url or VAST_GUARDIAN_CENTRAL_URL"
    [[ "$CENTRAL_URL" == https://* ]] || die "Agent central URL must use https://"
    [[ -n "$INGEST_TOKEN" ]] || die "Agent role requires --ingest-token or VAST_GUARDIAN_INGEST_TOKEN"
}

preflight() {
    require_file "$OS_RELEASE_FILE"
    # shellcheck disable=SC1090
    source "$OS_RELEASE_FILE"
    [[ "${ID:-}" == "ubuntu" ]] || die "Only Ubuntu 22.04 and 24.04 are supported"
    [[ "${VERSION_ID:-}" == "22.04" || "${VERSION_ID:-}" == "24.04" ]] || die "Only Ubuntu 22.04 and 24.04 are supported"
    require_command "$PYTHON_BIN"
    "$PYTHON_BIN" -c 'import sqlite3' || die "Python sqlite3 module is required"
    require_command "$SYSTEMCTL_BIN"
    if [[ "$TEST_MODE" != "1" ]]; then
        id -u "$INSTALL_USER" >/dev/null 2>&1 || die "Service user does not exist: ${INSTALL_USER}"
    fi
    require_file "${REPO_DIR}/database/init_db.py"
    require_file "${REPO_DIR}/database/migrate_db.py"
    require_file "${REPO_DIR}/config/guardian.env.example"
    if [[ "$ROLE" == "central" ]]; then
        local unit
        for unit in vast-guardian.service.in vast-guardian-web.service.in \
            vast-guardian-watchdog.service.in vast-guardian-watchdog.timer \
            vast-guardian-heartbeat.service.in vast-guardian-heartbeat.timer; do
            require_file "${REPO_DIR}/systemd/${unit}"
        done
    else
        require_file "${REPO_DIR}/systemd/vast-guardian-agent.service.in"
    fi
}

show_plan() {
    echo "Vast Guardian installation plan"
    echo "  role: ${ROLE}"
    echo "  host key: ${HOST_KEY}"
    echo "  repository: ${REPO_DIR}"
    echo "  service user: ${INSTALL_USER}"
    echo "  environment file: ${ENV_FILE} (mode 0600)"
    echo "  unsupported actions: no NVIDIA driver, Docker, Vast.ai, network, system upgrade, or tenant workload changes"
    if [[ "$ROLE" == "central" ]]; then
        echo "  database: initialize a new database or safely migrate the existing local database"
        echo "  systemd units: vast-guardian.service, vast-guardian-web.service"
        echo "                 vast-guardian-watchdog.service/timer"
        echo "                 vast-guardian-heartbeat.service/timer"
        echo "  service behaviour: daemon-reload; only start Guardian units that are currently inactive"
    else
        echo "  central URL: configured (value hidden)"
        echo "  ingest token: configured (value hidden)"
        echo "  systemd units: vast-guardian-agent.service only"
    fi
    if (( DRY_RUN )); then
        echo "  mode: DRY-RUN — no files, database, or services will change"
    fi
}

write_environment_file() {
    if [[ -e "$ENV_FILE" ]]; then
        note "Keeping existing environment file unchanged: ${ENV_FILE}"
        return
    fi
    if (( DRY_RUN )); then
        note "Would create ${ENV_FILE} with mode 0600; no secrets are printed"
        return
    fi

    install -d -m 700 "$ETC_DIR"
    local temporary_file
    temporary_file="${ENV_FILE}.tmp.$$"
    {
        printf '# Managed by Vast Guardian installer. Keep this file outside Git.\n'
        printf 'VAST_GUARDIAN_ROLE=%q\n' "$ROLE"
        printf 'VAST_GUARDIAN_HOST_KEY=%q\n' "$HOST_KEY"
        printf 'VAST_GUARDIAN_CENTRAL_URL=%q\n' "$CENTRAL_URL"
        printf 'VAST_GUARDIAN_INGEST_TOKEN=%q\n' "$INGEST_TOKEN"
        printf 'VAST_GUARDIAN_TELEGRAM_BOT_TOKEN=\n'
        printf 'VAST_GUARDIAN_TELEGRAM_CHAT_ID=\n'
    } > "$temporary_file"
    chmod 600 "$temporary_file"
    mv "$temporary_file" "$ENV_FILE"
}

render_unit() {
    local source="$1"
    local destination="$2"
    local rendered="${ROLLBACK_DIR}/$(basename "$destination").new"
    sed \
        -e "s|@GUARDIAN_USER@|${INSTALL_USER}|g" \
        -e "s|@REPO_PATH@|${REPO_DIR}|g" \
        -e "s|@ENV_FILE@|${ENV_FILE}|g" \
        "$source" > "$rendered"

    if [[ -e "$destination" ]]; then
        cp -p "$destination" "${ROLLBACK_DIR}/$(basename "$destination").old"
        BACKED_UP_UNITS+=("$destination")
    else
        CREATED_UNITS+=("$destination")
    fi
    install -m 644 "$rendered" "$destination"
}

install_central_units() {
    local -a source_units=(
        "vast-guardian.service.in:vast-guardian.service"
        "vast-guardian-web.service.in:vast-guardian-web.service"
        "vast-guardian-watchdog.service.in:vast-guardian-watchdog.service"
        "vast-guardian-watchdog.timer:vast-guardian-watchdog.timer"
        "vast-guardian-heartbeat.service.in:vast-guardian-heartbeat.service"
        "vast-guardian-heartbeat.timer:vast-guardian-heartbeat.timer"
    )
    if (( DRY_RUN )); then
        note "Would render and install central Guardian systemd units in ${SYSTEMD_DIR}"
        return
    fi

    ROLLBACK_DIR="$(mktemp -d)"
    ROLLBACK_NEEDED=1
    local pair source destination
    for pair in "${source_units[@]}"; do
        source="${pair%%:*}"
        destination="${pair##*:}"
        render_unit "${REPO_DIR}/systemd/${source}" "${SYSTEMD_DIR}/${destination}"
    done
    "$SYSTEMCTL_BIN" daemon-reload

    local unit
    for unit in vast-guardian.service vast-guardian-web.service \
        vast-guardian-watchdog.timer vast-guardian-heartbeat.timer; do
        if ! "$SYSTEMCTL_BIN" is-enabled --quiet "$unit"; then
            "$SYSTEMCTL_BIN" enable "$unit"
            ENABLED_UNITS+=("$unit")
        fi
        if ! "$SYSTEMCTL_BIN" is-active --quiet "$unit"; then
            "$SYSTEMCTL_BIN" start "$unit"
            STARTED_UNITS+=("$unit")
        fi
    done
    ROLLBACK_NEEDED=0
    rm -rf "$ROLLBACK_DIR"
    ROLLBACK_DIR=""
}

install_agent_unit() {
    if (( DRY_RUN )); then
        note "Would render and install vast-guardian-agent.service in ${SYSTEMD_DIR}"
        return
    fi
    ROLLBACK_DIR="$(mktemp -d)"
    ROLLBACK_NEEDED=1
    render_unit "${REPO_DIR}/systemd/vast-guardian-agent.service.in" "${SYSTEMD_DIR}/vast-guardian-agent.service"
    "$SYSTEMCTL_BIN" daemon-reload
    if ! "$SYSTEMCTL_BIN" is-enabled --quiet vast-guardian-agent.service; then
        "$SYSTEMCTL_BIN" enable vast-guardian-agent.service
        ENABLED_UNITS+=("vast-guardian-agent.service")
    fi
    if ! "$SYSTEMCTL_BIN" is-active --quiet vast-guardian-agent.service; then
        "$SYSTEMCTL_BIN" start vast-guardian-agent.service
        STARTED_UNITS+=("vast-guardian-agent.service")
    fi
    ROLLBACK_NEEDED=0
    rm -rf "$ROLLBACK_DIR"
    ROLLBACK_DIR=""
}

rollback_units() {
    local status="$?"
    if (( ROLLBACK_NEEDED )); then
        echo "Installation failed; rolling back units started or created by this run." >&2
        local unit destination backup
        for unit in "${STARTED_UNITS[@]}"; do
            "$SYSTEMCTL_BIN" stop "$unit" || true
        done
        for unit in "${ENABLED_UNITS[@]}"; do
            "$SYSTEMCTL_BIN" disable "$unit" || true
        done
        for destination in "${CREATED_UNITS[@]}"; do
            rm -f "$destination"
        done
        for destination in "${BACKED_UP_UNITS[@]}"; do
            backup="${ROLLBACK_DIR}/$(basename "$destination").old"
            [[ -f "$backup" ]] && cp -p "$backup" "$destination"
        done
        "$SYSTEMCTL_BIN" daemon-reload || true
    fi
    [[ -n "$ROLLBACK_DIR" ]] && rm -rf "$ROLLBACK_DIR"
    exit "$status"
}

setup_central_database() {
    if (( DRY_RUN )); then
        if [[ -f "$DB_PATH" ]]; then
            note "Would run the safe database migration with a Backup API backup before schema changes"
        else
            note "Would initialize a new local SQLite database"
        fi
        return
    fi

    install -d -m 700 "$DATA_DIR/backups"
    if [[ -f "$DB_PATH" ]]; then
        "$PYTHON_BIN" "${REPO_DIR}/database/migrate_db.py" \
            --database "$DB_PATH" --backup-dir "$DATA_DIR/backups"
    else
        "$PYTHON_BIN" "${REPO_DIR}/database/init_db.py"
        "$PYTHON_BIN" "${REPO_DIR}/database/migrate_db.py" \
            --database "$DB_PATH" --backup-dir "$DATA_DIR/backups"
    fi
    ensure_database_ownership
}

ensure_database_ownership() {
    [[ -f "$DB_PATH" ]] || die "Database was not created: ${DB_PATH}"
    local database_file
    for database_file in "$DB_PATH" "${DB_PATH}-wal" "${DB_PATH}-shm" "${DB_PATH}-journal"; do
        [[ -e "$database_file" ]] || continue
        chown "$INSTALL_USER" "$database_file"
        chmod u+rw "$database_file"
    done
}

main() {
    parse_args "$@"
    select_role
    detect_host_key
    collect_agent_configuration
    preflight
    show_plan

    if (( DRY_RUN )); then
        return
    fi
    if [[ "${EUID}" -ne 0 ]]; then
        [[ "$TEST_MODE" == "1" ]] || die "Run the installer with sudo (or use --dry-run)"
        [[ "$ETC_DIR" != "/etc/vast-guardian" && "$SYSTEMD_DIR" != "/etc/systemd/system" && "$DATA_DIR" != "/var/lib/vast-guardian" ]] || die "Test mode requires temporary installation directories"
    fi

    trap rollback_units EXIT
    write_environment_file
    if [[ "$ROLE" == "central" ]]; then
        setup_central_database
        install_central_units
    else
        install_agent_unit
    fi
    trap - EXIT
    echo "Installation completed for role: ${ROLE}"
}

main "$@"
