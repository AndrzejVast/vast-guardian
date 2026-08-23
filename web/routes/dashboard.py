from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, render_template, jsonify, abort
import sqlite3

from system.info import health_summary
from system.info import health
from monitor.alarms import current_alarm_state, alarm_history

dashboard = Blueprint("dashboard", __name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"
HOST_ONLINE_SECONDS = 90


def _connect():
    """Open the central SQLite database for dashboard reads."""
    conn = sqlite3.connect(f"{Path(DB_PATH).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _last_seen_is_fresh(value):
    """Return whether a collector timestamp is recent enough to be online."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() <= HOST_ONLINE_SECONDS


def _host_response(row):
    payload = dict(row)
    payload["online"] = _last_seen_is_fresh(payload.get("last_seen"))
    payload["freshness"] = "ONLINE" if payload["online"] else "STALE"
    return payload


@dashboard.route("/")
def index():
    return render_template("dashboard.html")


@dashboard.route("/api/history")
def history():
    conn = _connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            created,
            gpu_temp,
            gpu_util,
            cpu,
            ram,
            disk,
            vram
        FROM history
        ORDER BY id DESC
        LIMIT 100
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    rows.reverse()

    return jsonify(rows)


@dashboard.route("/api/status")
def status():
    conn = _connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM hosts
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    if row:
        return jsonify(dict(row))

    return jsonify({})


@dashboard.route("/api/v1/hosts")
def hosts():
    """Return one latest status record for every reporting host."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT h.name, h.last_seen
            FROM hosts AS h
            INNER JOIN (
                SELECT name, MAX(id) AS latest_id
                FROM hosts
                WHERE TRIM(COALESCE(name, '')) <> ''
                GROUP BY name
            ) AS latest ON latest.latest_id = h.id
            ORDER BY h.name COLLATE NOCASE
        """).fetchall()
    finally:
        conn.close()
    return jsonify([
        {
            "host_key": row["name"],
            "last_seen": row["last_seen"],
            "online": _last_seen_is_fresh(row["last_seen"]),
        }
        for row in rows
    ])


@dashboard.route("/api/v1/hosts/<host_key>/status")
def host_status(host_key):
    """Return the latest stored status for one host, never another host."""
    conn = _connect()
    try:
        row = conn.execute("""
            SELECT *
            FROM hosts
            WHERE name = ?
            ORDER BY id DESC
            LIMIT 1
        """, (host_key,)).fetchone()
    finally:
        conn.close()
    if row is None:
        abort(404)
    return jsonify(_host_response(row))


@dashboard.route("/api/v1/hosts/<host_key>/history")
def host_history(host_key):
    """Return chart samples belonging only to the requested host."""
    conn = _connect()
    try:
        exists = conn.execute("SELECT 1 FROM hosts WHERE name = ? LIMIT 1", (host_key,)).fetchone()
        if exists is None:
            abort(404)
        rows = conn.execute("""
            SELECT created, gpu_temp, gpu_util, cpu, ram, disk, vram
            FROM history
            WHERE host_name = ?
            ORDER BY id DESC
            LIMIT 100
        """, (host_key,)).fetchall()
    finally:
        conn.close()
    payload = [dict(row) for row in rows]
    payload.reverse()
    return jsonify(payload)


@dashboard.route("/api/health")
def api_health():
    return jsonify(
        health_summary()
    )


@dashboard.route("/api/system")
def api_system():
    return jsonify(
        health()
    )


@dashboard.route("/api/alarms")
def alarms():
    return jsonify(current_alarm_state())


@dashboard.route("/api/alarm-history")
def api_alarm_history():
    return jsonify(alarm_history())
