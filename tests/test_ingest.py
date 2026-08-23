import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database.ingest import PayloadError, persist_report, validate_payload
from database.init_db import initialize_database


def payload(report_id="report-1"):
    return {"schema_version": 1, "report_id": report_id, "host_key": "vast-server", "observed_at": "2026-08-23T12:00:00Z", "metrics": {"ip": "10.0.0.2", "gpu": "GPU", "gpu_temp": 60, "gpu_util": 20, "vram": 100, "cpu": 10, "ram": 30, "disk": 40, "docker": "active"}}


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "guardian.db"
        initialize_database(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_and_duplicate_report_are_idempotent(self):
        now = datetime(2026, 8, 23, 12, 1, tzinfo=timezone.utc)
        self.assertEqual(persist_report(payload(), self.db, now)["status"], "accepted")
        self.assertEqual(persist_report(payload(), self.db, now)["status"], "duplicate")
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM hosts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ingest_reports").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT last_seen FROM hosts").fetchone()[0], "2026-08-23 12:01:00")
        finally:
            conn.close()

    def test_invalid_payloads_are_rejected(self):
        for mutate in (
            lambda p: p.pop("metrics"),
            lambda p: p.update(host_key="bad host"),
            lambda p: p.update(observed_at="not-a-date"),
            lambda p: p["metrics"].update(cpu="high"),
        ):
            value = payload()
            mutate(value)
            with self.assertRaises(PayloadError):
                validate_payload(value)

    def test_database_error_rolls_back_all_rows(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("CREATE TRIGGER fail_history BEFORE INSERT ON history BEGIN SELECT RAISE(ABORT, 'fail'); END")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(sqlite3.Error):
            persist_report(payload(), self.db)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ingest_reports").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM hosts").fetchone()[0], 0)
        finally:
            conn.close()
