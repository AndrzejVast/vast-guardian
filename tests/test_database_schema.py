import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.init_db import initialize_database
from database.migrate_db import DEFAULT_BACKUP_DIR, migrate_database


EXPECTED_HOSTS_COLUMNS = [
    "id", "name", "ip", "status", "gpu", "last_seen",
    "gpu_temp", "gpu_util", "vram", "cpu", "ram", "disk", "docker",
]


class DatabaseSchemaTests(unittest.TestCase):
    def test_default_backup_directory_is_outside_the_repository(self):
        self.assertEqual(DEFAULT_BACKUP_DIR, Path("/var/lib/vast-guardian/backups"))

    def test_fresh_database_has_collector_hosts_columns(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "guardian.db"
            initialize_database(db_path)

            conn = sqlite3.connect(db_path)
            try:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(hosts)")]
            finally:
                conn.close()

            self.assertEqual(columns, EXPECTED_HOSTS_COLUMNS)

    def test_migration_adds_missing_columns_and_preserves_rows(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "guardian.db"
            backup_dir = Path(temporary_directory) / "backups"

            conn = sqlite3.connect(db_path)
            try:
                conn.execute("""
                    CREATE TABLE hosts(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        ip TEXT,
                        status TEXT,
                        gpu TEXT,
                        last_seen TEXT
                    )
                """)
                conn.execute("INSERT INTO hosts(name) VALUES ('existing-host')")
                conn.commit()
            finally:
                conn.close()

            result = migrate_database(db_path, backup_dir)
            second_result = migrate_database(db_path, backup_dir)

            conn = sqlite3.connect(db_path)
            try:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(hosts)")]
                row_count = conn.execute("SELECT COUNT(*) FROM hosts").fetchone()[0]
            finally:
                conn.close()

            self.assertTrue(result["changed"])
            self.assertTrue(result["backup"].is_file())
            self.assertEqual(columns, EXPECTED_HOSTS_COLUMNS)
            self.assertEqual(row_count, 1)
            self.assertFalse(second_result["changed"])
            self.assertEqual(second_result["missing_columns"], [])
            self.assertIsNone(second_result["backup"])
