import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from database.init_db import initialize_database
from watchdog import watchdog


NOW = datetime(2026, 8, 23, 12, 0, 0)


class CollectorFreshnessWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.db_path = self.root / "guardian.db"
        self.state_path = self.root / "state.json"
        initialize_database(self.db_path)
        self.path_patches = [
            patch.object(watchdog, "DB_PATH", self.db_path),
            patch.object(watchdog, "STATE_PATH", str(self.state_path)),
        ]
        for path_patch in self.path_patches:
            path_patch.start()

    def tearDown(self):
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temporary_directory.cleanup()

    def insert_last_seen(self, value):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT INTO hosts(name, last_seen) VALUES ('host-a', ?)", (value,))
            conn.commit()
        finally:
            conn.close()

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def read_state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def run_check(self, collector_active=True, web_active=True):
        messages = []

        def active(service):
            return {
                "vast-guardian": collector_active,
                "vast-guardian-web": web_active,
            }[service]

        with patch.object(watchdog, "active", side_effect=active), \
             patch.object(watchdog, "send", side_effect=messages.append), \
             patch.object(watchdog, "datetime") as clock:
            clock.now.return_value = NOW
            clock.strptime.side_effect = datetime.strptime
            watchdog.check()
        return messages

    def test_fresh_data_is_recorded_without_notification(self):
        self.insert_last_seen((NOW - timedelta(seconds=30)).strftime(watchdog.TIMESTAMP_FORMAT))

        messages = self.run_check()

        self.assertEqual(messages, [])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "FRESH")

    def test_stale_data_sends_one_alert_without_duplicates(self):
        self.insert_last_seen((NOW - timedelta(seconds=91)).strftime(watchdog.TIMESTAMP_FORMAT))

        first_messages = self.run_check()
        second_messages = self.run_check()

        self.assertEqual(len(first_messages), 1)
        self.assertIn("STALE COLLECTOR", first_messages[0])
        self.assertEqual(second_messages, [])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "STALE")

    def test_no_hosts_record_is_stale(self):
        messages = self.run_check()

        self.assertEqual(len(messages), 1)
        self.assertIn("No collector records", messages[0])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "STALE")

    def test_stale_to_fresh_sends_one_recovery(self):
        self.write_state({
            "Guardian Collector": True,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "STALE",
        })
        self.insert_last_seen((NOW - timedelta(seconds=10)).strftime(watchdog.TIMESTAMP_FORMAT))

        first_messages = self.run_check()
        second_messages = self.run_check()

        self.assertEqual(len(first_messages), 1)
        self.assertIn("STALE COLLECTOR RECOVERY", first_messages[0])
        self.assertEqual(second_messages, [])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "FRESH")

    def test_inactive_collector_sends_only_service_alert_and_preserves_freshness(self):
        self.write_state({
            "Guardian Collector": True,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "FRESH",
        })

        messages = self.run_check(collector_active=False)

        self.assertEqual(len(messages), 1)
        self.assertIn("Guardian Collector jest NIEAKTYWNY", messages[0])
        self.assertNotIn("STALE COLLECTOR", messages[0])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "FRESH")

    def test_service_return_with_fresh_data_sends_only_service_recovery(self):
        self.write_state({
            "Guardian Collector": False,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "FRESH",
        })
        self.insert_last_seen((NOW - timedelta(seconds=10)).strftime(watchdog.TIMESTAMP_FORMAT))

        messages = self.run_check(collector_active=True)

        self.assertEqual(len(messages), 1)
        self.assertIn("Guardian Collector działa ponownie", messages[0])
        self.assertNotIn("STALE COLLECTOR", messages[0])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "FRESH")

    def test_service_return_with_stale_data_sends_service_recovery_and_stale_alert(self):
        self.write_state({
            "Guardian Collector": False,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "FRESH",
        })
        self.insert_last_seen((NOW - timedelta(seconds=91)).strftime(watchdog.TIMESTAMP_FORMAT))

        messages = self.run_check(collector_active=True)

        self.assertEqual(len(messages), 2)
        self.assertTrue(any("Guardian Collector działa ponownie" in message for message in messages))
        self.assertTrue(any("STALE COLLECTOR" in message for message in messages))
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "STALE")

    def test_sqlite_error_preserves_previous_freshness_without_notification(self):
        self.write_state({
            "Guardian Collector": True,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "STALE",
        })
        missing_db_path = self.root / "missing.db"
        with patch.object(watchdog, "DB_PATH", missing_db_path):
            messages = self.run_check()

        self.assertEqual(messages, [])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "STALE")

    def test_invalid_last_seen_preserves_previous_freshness_without_notification(self):
        self.write_state({
            "Guardian Collector": True,
            "Guardian Web": True,
            watchdog.FRESHNESS_STATE_KEY: "FRESH",
        })
        self.insert_last_seen("not-a-timestamp")

        messages = self.run_check()

        self.assertEqual(messages, [])
        self.assertEqual(self.read_state()[watchdog.FRESHNESS_STATE_KEY], "FRESH")

    def test_freshness_connection_uses_read_only_sqlite_uri(self):
        self.insert_last_seen((NOW - timedelta(seconds=10)).strftime(watchdog.TIMESTAMP_FORMAT))

        with patch.object(watchdog.sqlite3, "connect", wraps=sqlite3.connect) as connect:
            freshness, _ = watchdog.collector_freshness(NOW)

        self.assertEqual(freshness, "FRESH")
        database_uri = connect.call_args.args[0]
        self.assertIn("mode=ro", database_uri)
        self.assertTrue(connect.call_args.kwargs["uri"])


if __name__ == "__main__":
    unittest.main()
