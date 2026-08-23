import importlib
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from database.init_db import initialize_database
from monitor import alarms


class FakeBlueprint:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        def decorator(function):
            return function

        return decorator


class FakeFlask:
    def __init__(self, *args, **kwargs):
        pass

    def register_blueprint(self, *args, **kwargs):
        pass


def load_dashboard_module():
    fake_flask = types.ModuleType("flask")
    fake_flask.Blueprint = FakeBlueprint
    fake_flask.Flask = FakeFlask
    fake_flask.jsonify = lambda value: value
    fake_flask.render_template = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    fake_flask.request = types.SimpleNamespace(headers={}, is_json=False)

    for module_name in ("web.routes.dashboard", "web.routes", "web"):
        sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, {"flask": fake_flask}):
        return importlib.import_module("web.routes.dashboard")


class DashboardAlarmRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard_module = load_dashboard_module()

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / "guardian.db"
        initialize_database(self.db_path)
        self.original_db_path = alarms.DB_PATH
        alarms.DB_PATH = str(self.db_path)

    def tearDown(self):
        alarms.DB_PATH = self.original_db_path
        self.temporary_directory.cleanup()

    def test_api_alarms_only_reads_current_state_and_preserves_contract(self):
        expected = {
            "status": "UNKNOWN",
            "critical": 0,
            "warnings": 0,
            "count": 0,
            "alarms": [],
            "checked_at": None,
        }
        self.assertFalse(hasattr(self.dashboard_module, "check_alarms"))
        self.assertFalse(hasattr(self.dashboard_module, "record_alarm_state"))

        with patch.object(self.dashboard_module, "current_alarm_state", return_value=expected) as current:
            response = self.dashboard_module.alarms()

        self.assertEqual(response, expected)
        current.assert_called_once_with()
        self.assertEqual(
            set(response),
            {"status", "critical", "warnings", "count", "alarms", "checked_at"},
        )

    def test_api_alarms_does_not_change_sqlite_rows(self):
        before = self._table_counts()

        response = self.dashboard_module.alarms()

        self.assertEqual(response["status"], "UNKNOWN")
        self.assertEqual(self._table_counts(), before)

    def test_alarm_history_endpoint_is_read_only(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO alarm_history(component, level, message, event)
                VALUES ('GPU', 'WARNING', 'GPU temperature is 80°C', 'ACTIVE')
            """)
            conn.commit()
        finally:
            conn.close()
        before = self._table_counts()

        response = self.dashboard_module.api_alarm_history()

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["component"], "GPU")
        self.assertEqual(self._table_counts(), before)

    def test_frontend_has_explicit_unknown_handling(self):
        template = (Path(__file__).resolve().parent.parent / "web" / "templates" / "dashboard.html")
        contents = template.read_text(encoding="utf-8")

        self.assertIn('data.status==="UNKNOWN"', contents)
        self.assertIn("Brak wyniku sprawdzenia alarmów", contents)

    def test_alarm_history_panel_is_compact_scrollable_and_expandable(self):
        template = (Path(__file__).resolve().parent.parent / "web" / "templates" / "dashboard.html")
        contents = template.read_text(encoding="utf-8")

        self.assertIn("alarm-history-list{max-height:240px;overflow-y:auto", contents)
        self.assertIn(".history-panel.expanded .alarm-history-list{max-height:520px}", contents)
        self.assertIn("@media(max-width:600px)", contents)
        self.assertIn('id="alarmHistoryToggle"', contents)
        self.assertIn("Rozwiń", contents)
        self.assertIn("Zwiń", contents)
        self.assertIn("toggleAlarmHistory", contents)
        self.assertIn("list.scrollTop=list.scrollHeight", contents)

    def test_frontend_uses_professional_responsive_chart_layout(self):
        template = (Path(__file__).resolve().parent.parent / "web" / "templates" / "dashboard.html")
        contents = template.read_text(encoding="utf-8")

        self.assertIn(".charts-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))", contents)
        self.assertIn(".dashboard-shell{max-width:1680px}", contents)
        self.assertIn(".chart-box{height:320px}", contents)
        self.assertIn(".dashboard-section,.alarms-panel,.history-panel{padding:18px;margin-bottom:16px}", contents)
        self.assertIn(".section-heading{margin-bottom:14px}", contents)
        self.assertIn(".card{padding:17px}", contents)
        self.assertIn(".health-card{padding:14px}", contents)
        self.assertIn("maxTicksLimit:6", contents)
        self.assertIn("tooltip:{backgroundColor", contents)
        self.assertIn("pointRadius:showPoints?2:0", contents)
        self.assertIn("@media(max-width:900px)", contents)

    def test_alarm_history_renders_recovery_independently_of_previous_level(self):
        template = (Path(__file__).resolve().parent.parent / "web" / "templates" / "dashboard.html")
        contents = template.read_text(encoding="utf-8")

        self.assertIn('isRecovery=event.event==="RECOVERY"', contents)
        self.assertIn('cls=isRecovery?"recovery":event.level.toLowerCase()', contents)
        self.assertIn('eventName=isRecovery?"RECOVERY":event.level', contents)
        self.assertIn(".alarm-history-item.recovery{border-left-color:var(--green)}", contents)
        self.assertIn(".history-event.recovery{color:var(--green)}", contents)

    def _table_counts(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("alarm_history", "alarm_state", "events", "history", "hosts")
            }
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
