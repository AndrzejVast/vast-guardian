import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database.init_db import initialize_database
from monitor import alarms


class AlarmStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / "guardian.db"
        initialize_database(self.db_path)
        self.original_db_path = alarms.DB_PATH
        alarms.DB_PATH = str(self.db_path)

    def tearDown(self):
        alarms.DB_PATH = self.original_db_path
        self.temporary_directory.cleanup()

    @staticmethod
    def result(status="HEALTHY", active_alarms=None):
        active_alarms = active_alarms or []
        return {
            "status": status,
            "critical": sum(a["level"] == "CRITICAL" for a in active_alarms),
            "warnings": sum(a["level"] == "WARNING" for a in active_alarms),
            "count": len(active_alarms),
            "alarms": active_alarms,
        }

    def test_missing_state_returns_unknown(self):
        self.assertEqual(alarms.current_alarm_state(), alarms.UNKNOWN_ALARM_STATE)

    def test_first_healthy_cycle_persists_current_state_without_history(self):
        alarms.record_alarm_state(self.result())

        state = alarms.current_alarm_state()
        conn = sqlite3.connect(self.db_path)
        try:
            history_count = conn.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(state["status"], "HEALTHY")
        self.assertEqual(state["alarms"], [])
        self.assertIsNotNone(state["checked_at"])
        self.assertEqual(history_count, 0)

    def test_warning_persists_json_and_counts(self):
        warning = {"component": "GPU", "level": "WARNING", "message": "GPU temperature is 80°C"}
        alarms.record_alarm_state(self.result("WARNING", [warning]))

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT status, critical, warnings, count, alarms_json FROM alarm_state WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[:4], ("WARNING", 0, 1, 1))
        self.assertEqual(json.loads(row[4]), [warning])
        self.assertEqual(alarms.current_alarm_state()["alarms"], [warning])

    def test_critical_persists_current_state(self):
        critical = {"component": "Disk", "level": "CRITICAL", "message": "Disk usage is 95%"}
        alarms.record_alarm_state(self.result("CRITICAL", [critical]))

        state = alarms.current_alarm_state()
        self.assertEqual(state["status"], "CRITICAL")
        self.assertEqual(state["critical"], 1)
        self.assertEqual(state["warnings"], 0)
        self.assertEqual(state["count"], 1)

    def test_recovery_updates_current_state_to_healthy_and_history_to_recovery(self):
        warning = {"component": "GPU", "level": "WARNING", "message": "GPU temperature is 80°C"}
        alarms.record_alarm_state(self.result("WARNING", [warning]))
        alarms.record_alarm_state(self.result())

        conn = sqlite3.connect(self.db_path)
        try:
            events = conn.execute(
                "SELECT event FROM alarm_history WHERE component = 'GPU' ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(events, [("ACTIVE",), ("RECOVERY",)])
        self.assertEqual(alarms.current_alarm_state()["status"], "HEALTHY")

    def test_history_only_records_changes_while_state_updates_each_cycle(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("CREATE TABLE state_updates(count INTEGER NOT NULL)")
            conn.execute("INSERT INTO state_updates VALUES (0)")
            conn.execute("""
                CREATE TRIGGER count_alarm_state_updates
                AFTER UPDATE ON alarm_state
                BEGIN
                    UPDATE state_updates SET count = count + 1;
                END
            """)
            conn.commit()
        finally:
            conn.close()

        alarms.record_alarm_state(self.result())
        alarms.record_alarm_state(self.result())

        conn = sqlite3.connect(self.db_path)
        try:
            history_count = conn.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
            update_count = conn.execute("SELECT count FROM state_updates").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(history_count, 0)
        self.assertEqual(update_count, 1)

    def test_corrupt_json_returns_unknown_without_writing_or_notifying(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO alarm_state(id, status, critical, warnings, count, alarms_json, checked_at)
                VALUES(1, 'WARNING', 0, 1, 1, '{bad json', '2026-08-20 12:00:00')
            """)
            conn.commit()
        finally:
            conn.close()

        with patch.object(alarms, "send_message") as send_message:
            state = alarms.current_alarm_state()

        conn = sqlite3.connect(self.db_path)
        try:
            stored_json = conn.execute("SELECT alarms_json FROM alarm_state WHERE id = 1").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(state["status"], "UNKNOWN")
        self.assertEqual(state["checked_at"], "2026-08-20 12:00:00")
        self.assertEqual(stored_json, "{bad json")
        send_message.assert_not_called()

    def test_database_error_rolls_back_history_and_state_before_telegram(self):
        warning = {"component": "GPU", "level": "WARNING", "message": "GPU temperature is 80°C"}
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TRIGGER fail_alarm_state_insert
                BEFORE INSERT ON alarm_state
                BEGIN
                    SELECT RAISE(ABORT, 'forced alarm_state failure');
                END
            """)
            conn.commit()
        finally:
            conn.close()

        with patch.object(alarms, "send_message") as send_message:
            with self.assertRaises(sqlite3.DatabaseError):
                alarms.record_alarm_state(self.result("WARNING", [warning]))

        conn = sqlite3.connect(self.db_path)
        try:
            history_count = conn.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
            state_count = conn.execute("SELECT COUNT(*) FROM alarm_state").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(history_count, 0)
        self.assertEqual(state_count, 0)
        send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
