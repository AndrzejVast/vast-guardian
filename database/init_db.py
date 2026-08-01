#!/usr/bin/env python3

import sqlite3

conn = sqlite3.connect("database/vast_guardian.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS hosts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    ip TEXT,
    status TEXT,
    gpu TEXT,
    last_seen TEXT
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
conn.commit()
conn.close()

print("Database initialized.")
