#!/usr/bin/env python3
"""Safely retain Vast Guardian SQLite metric data for 30 days.

The script deliberately does not prune ``events`` or ``alarm_history`` and
never runs VACUUM.  It can be run repeatedly; only rows that are still older
than the retention thresholds are candidates for deletion.
"""

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"
DEFAULT_BACKUP_DIR = Path("/var/lib/vast-guardian/backups")
RETENTION_DAYS = 30
LOCK_TIMEOUT_SECONDS = 30
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DELETE_BATCH_SIZE = 500

REQUIRED_TABLES = {
    "history": {"id", "created"},
    "hosts": {"id", "name", "last_seen"},
    "events": {"id", "host_id"},
    "alarm_history": {"id", "component", "level", "message", "event", "created"},
}

INDEXES = (
    ("idx_history_created", "history", "created"),
    ("idx_hosts_last_seen", "hosts", "last_seen"),
    ("idx_events_host_id", "events", "host_id"),
)


class RetentionError(RuntimeError):
    """Raised when the database is not safe to prune."""


def _as_utc(value):
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_local_naive(value):
    if value is None:
        return datetime.now()
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _parse_timestamp(value):
    """Return an exact Guardian timestamp, or None for unsafe input."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=LOCK_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {LOCK_TIMEOUT_SECONDS * 1000}")
    return conn


def validate_schema(conn):
    """Raise RetentionError unless all tables needed for safe pruning exist."""

    for table, expected_columns in REQUIRED_TABLES.items():
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            raise RetentionError(f"Required table is missing: {table}")

        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = sorted(expected_columns - columns)
        if missing:
            raise RetentionError(
                f"Table {table} is missing required columns: {', '.join(missing)}"
            )


def analyze_retention(conn, now_utc=None, now_local=None):
    """Return eligible IDs and conservative protection/validation statistics."""

    utc_cutoff = _as_utc(now_utc).replace(tzinfo=None) - timedelta(days=RETENTION_DAYS)
    local_cutoff = _as_local_naive(now_local) - timedelta(days=RETENTION_DAYS)

    history_ids = []
    invalid_history_dates = 0
    for row_id, created in conn.execute("SELECT id, created FROM history"):
        created_at = _parse_timestamp(created)
        if created_at is None:
            invalid_history_dates += 1
        elif created_at < utc_cutoff:
            history_ids.append(row_id)

    host_rows = conn.execute(
        """
        SELECT h.id, h.name, h.last_seen,
               EXISTS(SELECT 1 FROM events AS e WHERE e.host_id = h.id)
        FROM hosts AS h
        """
    )
    parsed_host_rows = []
    latest_by_name = {}
    for row_id, name, last_seen, has_event in host_rows:
        seen_at = _parse_timestamp(last_seen)
        parsed_host_rows.append((row_id, seen_at, has_event))
        if seen_at is not None:
            host_name = name or ""
            current_latest = latest_by_name.get(host_name)
            if current_latest is None or (seen_at, row_id) > current_latest:
                latest_by_name[host_name] = (seen_at, row_id)

    latest_host_ids = {row_id for _, row_id in latest_by_name.values()}
    host_ids = []
    invalid_host_dates = 0
    protected_latest_hosts = 0
    protected_event_hosts = 0
    for row_id, seen_at, has_event in parsed_host_rows:
        if seen_at is None:
            invalid_host_dates += 1
        elif seen_at < local_cutoff:
            if row_id in latest_host_ids:
                protected_latest_hosts += 1
            elif has_event:
                protected_event_hosts += 1
            else:
                host_ids.append(row_id)

    return {
        "history_ids": history_ids,
        "host_ids": host_ids,
        "history_candidates": len(history_ids),
        "host_candidates": len(host_ids),
        "invalid_history_dates": invalid_history_dates,
        "invalid_host_dates": invalid_host_dates,
        "protected_latest_hosts": protected_latest_hosts,
        "protected_event_hosts": protected_event_hosts,
        "history_cutoff_utc": utc_cutoff.strftime(TIMESTAMP_FORMAT),
        "hosts_cutoff_local": local_cutoff.strftime(TIMESTAMP_FORMAT),
    }


def _backup_path(db_path, backup_dir):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return backup_dir / f"{db_path.stem}-retention-{timestamp}.db"


def backup_database(db_path, backup_dir):
    """Create and integrity-check a SQLite backup before deletion."""

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_path(db_path, backup_dir)
    if backup_path.resolve() == db_path.resolve():
        raise RetentionError("Backup path must not be the source database path")

    source = _connect(db_path)
    target = _connect(backup_path)
    try:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RetentionError(f"Backup integrity check failed: {result}")
    finally:
        target.close()
        source.close()

    return backup_path


def ensure_indexes(conn):
    """Create the lookup indexes required by retention, without duplication."""

    for index_name, table, column in INDEXES:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"
        )


def _delete_ids(conn, table, ids):
    deleted = 0
    for start in range(0, len(ids), DELETE_BATCH_SIZE):
        batch = ids[start : start + DELETE_BATCH_SIZE]
        placeholders = ", ".join("?" for _ in batch)
        cursor = conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", batch)
        deleted += cursor.rowcount
    return deleted


def prune_database(db_path=DEFAULT_DB_PATH, backup_dir=DEFAULT_BACKUP_DIR, dry_run=False,
                   now_utc=None, now_local=None):
    """Analyze or prune a Guardian database according to the fixed policy."""

    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {db_path}")

    conn = _connect(db_path)
    try:
        if dry_run:
            conn.execute("BEGIN")
            validate_schema(conn)
            analysis = analyze_retention(conn, now_utc, now_local)
            conn.rollback()
            return {
                **analysis,
                "dry_run": True,
                "changed": False,
                "deleted_history": 0,
                "deleted_hosts": 0,
                "backup": None,
            }

        conn.execute("BEGIN IMMEDIATE")
        validate_schema(conn)
        analysis = analyze_retention(conn, now_utc, now_local)
        has_deletions = bool(analysis["history_ids"] or analysis["host_ids"])
        backup_path = None
        if has_deletions:
            backup_path = backup_database(db_path, backup_dir)

        ensure_indexes(conn)
        deleted_history = _delete_ids(conn, "history", analysis["history_ids"])
        deleted_hosts = _delete_ids(conn, "hosts", analysis["host_ids"])

        integrity_result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity_result != "ok":
            raise RetentionError(f"Database integrity check failed: {integrity_result}")
        conn.commit()

        return {
            **analysis,
            "dry_run": False,
            "changed": bool(deleted_history or deleted_hosts),
            "deleted_history": deleted_history,
            "deleted_hosts": deleted_hosts,
            "backup": backup_path,
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _print_result(result):
    mode = "Dry run" if result["dry_run"] else "Retention run"
    print(f"{mode}; history cutoff (UTC): {result['history_cutoff_utc']}")
    print(f"Hosts cutoff (local): {result['hosts_cutoff_local']}")
    print(f"History candidates: {result['history_candidates']}")
    print(f"Host candidates: {result['host_candidates']}")
    print(f"Invalid history dates retained: {result['invalid_history_dates']}")
    print(f"Invalid host dates retained: {result['invalid_host_dates']}")
    print(f"Hosts retained as latest: {result['protected_latest_hosts']}")
    print(f"Hosts retained by events: {result['protected_event_hosts']}")
    if result["dry_run"]:
        print("No backup was created and no data was changed.")
    else:
        print(f"Deleted history rows: {result['deleted_history']}")
        print(f"Deleted host rows: {result['deleted_hosts']}")
        print(f"Backup: {result['backup'] or 'not needed'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = prune_database(args.database, args.backup_dir, args.dry_run)
    _print_result(result)


if __name__ == "__main__":
    main()
