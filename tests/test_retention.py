import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.init_db import initialize_database
from database.retention import RETENTION_DAYS, RetentionError, prune_database


NOW_UTC = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
NOW_LOCAL = datetime(2026, 8, 20, 14, 0, 0)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.db_path = self.root / "guardian.db"
        self.backup_dir = self.root / "backups"
        initialize_database(self.db_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_retention(self, dry_run=False):
        return prune_database(
            self.db_path,
            self.backup_dir,
            dry_run=dry_run,
            now_utc=NOW_UTC,
            now_local=NOW_LOCAL,
        )

    def connect(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def timestamp(days_before, now):
        return (now - timedelta(days=days_before)).strftime("%Y-%m-%d %H:%M:%S")

    def insert_history(self, created):
        conn = self.connect()
        try:
            conn.execute("INSERT INTO history(host_name, created) VALUES ('host-a', ?)", (created,))
            conn.commit()
            return conn.execute("SELECT MAX(id) FROM history").fetchone()[0]
        finally:
            conn.close()

    def insert_host(self, name, last_seen):
        conn = self.connect()
        try:
            conn.execute("INSERT INTO hosts(name, last_seen) VALUES (?, ?)", (name, last_seen))
            conn.commit()
            return conn.execute("SELECT MAX(id) FROM hosts").fetchone()[0]
        finally:
            conn.close()

    def test_history_removes_old_but_keeps_boundary_and_fresh_rows(self):
        old_id = self.insert_history(self.timestamp(RETENTION_DAYS + 1, NOW_UTC.replace(tzinfo=None)))
        boundary_id = self.insert_history(self.timestamp(RETENTION_DAYS, NOW_UTC.replace(tzinfo=None)))
        fresh_id = self.insert_history(self.timestamp(1, NOW_UTC.replace(tzinfo=None)))

        result = self.run_retention()

        conn = self.connect()
        try:
            remaining = {row[0] for row in conn.execute("SELECT id FROM history")}
        finally:
            conn.close()
        self.assertEqual(result["deleted_history"], 1)
        self.assertNotIn(old_id, remaining)
        self.assertEqual(remaining, {boundary_id, fresh_id})

    def test_hosts_retention_preserves_boundary_fresh_and_latest_record(self):
        old_deletable = self.insert_host("host-a", self.timestamp(RETENTION_DAYS + 2, NOW_LOCAL))
        same_host_fresh = self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))
        boundary = self.insert_host("host-b", self.timestamp(RETENTION_DAYS, NOW_LOCAL))
        fresh = self.insert_host("host-c", self.timestamp(1, NOW_LOCAL))
        latest_old = self.insert_host("host-d", self.timestamp(RETENTION_DAYS + 1, NOW_LOCAL))

        result = self.run_retention()

        conn = self.connect()
        try:
            remaining = {row[0] for row in conn.execute("SELECT id FROM hosts")}
        finally:
            conn.close()
        self.assertEqual(result["deleted_hosts"], 1)
        self.assertNotIn(old_deletable, remaining)
        self.assertEqual(remaining, {same_host_fresh, boundary, fresh, latest_old})
        self.assertEqual(result["protected_latest_hosts"], 1)

    def test_latest_host_uses_last_seen_then_id_not_insert_order(self):
        latest = self.insert_host("host-a", self.timestamp(35, NOW_LOCAL))
        older_with_larger_id = self.insert_host("host-a", self.timestamp(40, NOW_LOCAL))

        result = self.run_retention()

        conn = self.connect()
        try:
            remaining = [row[0] for row in conn.execute("SELECT id FROM hosts")]
        finally:
            conn.close()
        self.assertEqual(result["deleted_hosts"], 1)
        self.assertNotIn(older_with_larger_id, remaining)
        self.assertEqual(remaining, [latest])

    def test_event_reference_protects_old_nonlatest_host(self):
        protected = self.insert_host("host-a", self.timestamp(40, NOW_LOCAL))
        latest = self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))
        conn = self.connect()
        try:
            conn.execute("INSERT INTO events(host_id, event) VALUES (?, 'legacy event')", (protected,))
            conn.commit()
        finally:
            conn.close()

        result = self.run_retention()

        conn = self.connect()
        try:
            hosts = {row[0] for row in conn.execute("SELECT id FROM hosts")}
            events = conn.execute("SELECT host_id, event FROM events").fetchall()
        finally:
            conn.close()
        self.assertEqual(hosts, {protected, latest})
        self.assertEqual(events, [(protected, "legacy event")])
        self.assertEqual(result["protected_event_hosts"], 1)

    def test_alarm_history_and_events_are_not_modified(self):
        old_host = self.insert_host("host-a", self.timestamp(50, NOW_LOCAL))
        self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))
        conn = self.connect()
        try:
            conn.execute("INSERT INTO events(host_id, event) VALUES (NULL, 'keep event')")
            conn.execute(
                "INSERT INTO alarm_history(component, level, message, event) VALUES ('GPU', 'WARNING', 'keep', 'ACTIVE')"
            )
            conn.commit()
            before_events = conn.execute("SELECT id, host_id, event FROM events").fetchall()
            before_alarms = conn.execute(
                "SELECT id, component, level, message, event FROM alarm_history"
            ).fetchall()
        finally:
            conn.close()

        self.run_retention()

        conn = self.connect()
        try:
            self.assertIsNone(conn.execute("SELECT id FROM hosts WHERE id = ?", (old_host,)).fetchone())
            self.assertEqual(conn.execute("SELECT id, host_id, event FROM events").fetchall(), before_events)
            self.assertEqual(
                conn.execute("SELECT id, component, level, message, event FROM alarm_history").fetchall(),
                before_alarms,
            )
        finally:
            conn.close()

    def test_dry_run_changes_nothing_and_creates_no_backup(self):
        self.insert_history(self.timestamp(40, NOW_UTC.replace(tzinfo=None)))
        self.insert_host("host-a", self.timestamp(40, NOW_LOCAL))
        self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))
        conn = self.connect()
        try:
            before_history = conn.execute("SELECT id FROM history").fetchall()
            before_hosts = conn.execute("SELECT id FROM hosts").fetchall()
        finally:
            conn.close()

        result = self.run_retention(dry_run=True)

        conn = self.connect()
        try:
            self.assertEqual(conn.execute("SELECT id FROM history").fetchall(), before_history)
            self.assertEqual(conn.execute("SELECT id FROM hosts").fetchall(), before_hosts)
            indexes = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        finally:
            conn.close()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["history_candidates"], 1)
        self.assertFalse(self.backup_dir.exists())
        self.assertNotIn(("idx_history_created",), indexes)

    def test_backup_contains_pre_prune_data_and_passes_integrity_check(self):
        old_history = self.insert_history(self.timestamp(40, NOW_UTC.replace(tzinfo=None)))
        self.insert_host("host-a", self.timestamp(40, NOW_LOCAL))
        self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))

        result = self.run_retention()

        self.assertTrue(result["backup"].is_file())
        backup = sqlite3.connect(result["backup"])
        try:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertIsNotNone(backup.execute("SELECT id FROM history WHERE id = ?", (old_history,)).fetchone())
        finally:
            backup.close()

    def test_error_after_history_delete_rolls_back_all_data_deletes(self):
        old_history = self.insert_history(self.timestamp(40, NOW_UTC.replace(tzinfo=None)))
        old_host = self.insert_host("host-a", self.timestamp(40, NOW_LOCAL))
        self.insert_host("host-a", self.timestamp(1, NOW_LOCAL))
        conn = self.connect()
        try:
            conn.execute(f"""
                CREATE TRIGGER abort_host_retention
                BEFORE DELETE ON hosts
                WHEN OLD.id = {old_host}
                BEGIN
                    SELECT RAISE(ABORT, 'forced retention failure');
                END
            """)
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(sqlite3.DatabaseError):
            self.run_retention()

        conn = self.connect()
        try:
            self.assertIsNotNone(conn.execute("SELECT id FROM history WHERE id = ?", (old_history,)).fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM hosts WHERE id = ?", (old_host,)).fetchone())
        finally:
            conn.close()
        self.assertEqual(len(list(self.backup_dir.glob("*.db"))), 1)

    def test_second_run_is_idempotent_and_does_not_make_another_backup(self):
        self.insert_history(self.timestamp(40, NOW_UTC.replace(tzinfo=None)))
        first = self.run_retention()
        second = self.run_retention()

        conn = self.connect()
        try:
            index_names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        finally:
            conn.close()
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertIsNone(second["backup"])
        self.assertEqual(len(list(self.backup_dir.glob("*.db"))), 1)
        self.assertTrue(
            {"idx_history_created", "idx_hosts_last_seen", "idx_events_host_id"}
            <= index_names
        )

    def test_invalid_and_blank_dates_are_reported_and_retained(self):
        invalid_history = self.insert_history("not-a-date")
        blank_history = self.insert_history("")
        invalid_host = self.insert_host("host-a", "not-a-date")
        blank_host = self.insert_host("host-b", "")

        result = self.run_retention()

        conn = self.connect()
        try:
            self.assertEqual(
                {row[0] for row in conn.execute("SELECT id FROM history")},
                {invalid_history, blank_history},
            )
            self.assertEqual(
                {row[0] for row in conn.execute("SELECT id FROM hosts")},
                {invalid_host, blank_host},
            )
        finally:
            conn.close()
        self.assertEqual(result["invalid_history_dates"], 2)
        self.assertEqual(result["invalid_host_dates"], 2)

    def test_missing_required_table_stops_without_backup_or_changes(self):
        conn = self.connect()
        try:
            conn.execute("DROP TABLE events")
            conn.execute("INSERT INTO history(host_name, created) VALUES ('host-a', '2026-07-01 00:00:00')")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(RetentionError):
            self.run_retention()

        conn = self.connect()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 1)
        finally:
            conn.close()
        self.assertFalse(self.backup_dir.exists())


if __name__ == "__main__":
    unittest.main()
