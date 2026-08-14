#!/usr/bin/env python3

"""Create the SQLite schema used by Vast Guardian."""

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"


def initialize_database(db_path=DEFAULT_DB_PATH):
    """Create all tables required by a fresh Vast Guardian installation."""

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS hosts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        ip TEXT,
        status TEXT,
        gpu TEXT,
        last_seen TEXT,
        gpu_temp INTEGER,
        gpu_util INTEGER,
        vram INTEGER,
        cpu INTEGER,
        ram INTEGER,
        disk INTEGER,
        docker TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        event TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_name TEXT,
        gpu_temp INTEGER,
        gpu_util INTEGER,
        vram INTEGER,
        cpu INTEGER,
        ram INTEGER,
        disk INTEGER,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alarm_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        event TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_database()
    print("Database initialized.")
