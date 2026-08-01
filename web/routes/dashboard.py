from flask import Blueprint, render_template
import sqlite3

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
