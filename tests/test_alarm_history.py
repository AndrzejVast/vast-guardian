import sqlite3
import tempfile
import unittest
from pathlib import Path

from monitor import alarms


class AlarmHistoryTests(unittest.TestCase):
    def test_alarm_history_returns_the_newest_fifty_rows(self):
        original_db_path = alarms.DB_PATH

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                db_path = Path(temporary_directory) / "guardian.db"
                alarms.DB_PATH = str(db_path)

                conn = sqlite3.connect(db_path)
                try:
                    conn.execute("""
                        CREATE TABLE alarm_history(
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            component TEXT NOT NULL,
                            level TEXT NOT NULL,
                            message TEXT NOT NULL,
                            event TEXT NOT NULL,
                            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    for number in range(51):
                        conn.execute("""
                            INSERT INTO alarm_history(component, level, message, event)
                            VALUES (?, 'WARNING', 'message', 'ACTIVE')
                        """, (f"component-{number}",))
                    conn.commit()
                finally:
                    conn.close()

                rows = alarms.alarm_history()

            self.assertEqual(len(rows), 50)
            self.assertEqual(rows[0]["component"], "component-50")
            self.assertEqual(rows[-1]["component"], "component-1")
        finally:
            alarms.DB_PATH = original_db_path
