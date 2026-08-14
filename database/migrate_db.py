#!/usr/bin/env python3

"""Safely add missing Vast Guardian columns to an existing SQLite database."""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"
DEFAULT_BACKUP_DIR = Path("/var/lib/vast-guardian/backups")
HOSTS_COLUMNS = (
    ("gpu_temp", "INTEGER"),
    ("gpu_util", "INTEGER"),
    ("vram", "INTEGER"),
    ("cpu", "INTEGER"),
    ("ram", "INTEGER"),
    ("disk", "INTEGER"),
    ("docker", "TEXT"),
)


def table_columns(conn, table_name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]


def backup_database(db_path, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    backup_path = backup_dir / f"{db_path.stem}-{timestamp}.db"

    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    return backup_path


def migrate_database(db_path=DEFAULT_DB_PATH, backup_dir=None, dry_run=False):
    """Add missing hosts metric columns without deleting existing data."""

    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {db_path}")

    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    backup_dir = Path(backup_dir)

    conn = sqlite3.connect(str(db_path))
    try:
        existing_columns = table_columns(conn, "hosts")
        if not existing_columns:
            raise RuntimeError("Table hosts does not exist; initialize the database first.")

        missing_columns = [
            (name, column_type)
            for name, column_type in HOSTS_COLUMNS
            if name not in existing_columns
        ]

        if dry_run or not missing_columns:
            return {
                "backup": None,
                "missing_columns": [name for name, _ in missing_columns],
                "changed": False,
            }

        try:
            conn.execute("BEGIN IMMEDIATE")
            backup_path = backup_database(db_path, backup_dir)
            for name, column_type in missing_columns:
                conn.execute(f"ALTER TABLE hosts ADD COLUMN {name} {column_type}")
            final_columns = table_columns(conn, "hosts")
            still_missing = [name for name, _ in HOSTS_COLUMNS if name not in final_columns]
            if still_missing:
                raise RuntimeError(
                    f"Migration incomplete; missing columns: {', '.join(still_missing)}"
                )

            integrity_result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity_result != "ok":
                raise RuntimeError(f"Integrity check failed: {integrity_result}")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {
            "backup": backup_path,
            "missing_columns": [name for name, _ in missing_columns],
            "changed": True,
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = migrate_database(args.database, args.backup_dir, args.dry_run)
    if result["changed"]:
        print(f"Backup created: {result['backup']}")
        print("Added columns: " + ", ".join(result["missing_columns"]))
    elif result["missing_columns"]:
        print("Dry run; columns to add: " + ", ".join(result["missing_columns"]))
    else:
        print("Database schema is already up to date.")


if __name__ == "__main__":
    main()
