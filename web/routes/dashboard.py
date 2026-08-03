from flask import Blueprint, render_template, jsonify
import sqlite3

from system.info import health_summary
from system.info import health

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/")
def index():

    conn = sqlite3.connect("database/vast_guardian.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM hosts
        ORDER BY id DESC
        LIMIT 1
    """)

    hosts = cur.fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        hosts=hosts
    )


@dashboard.route("/api/history")
def history():

    conn = sqlite3.connect("database/vast_guardian.db")
    conn.row_factory = sqlite3.Row
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

    conn = sqlite3.connect("database/vast_guardian.db")
    conn.row_factory = sqlite3.Row
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
