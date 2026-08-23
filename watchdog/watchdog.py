#!/usr/bin/env python3

import json
import os
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ENV_TOKEN = os.getenv("VAST_GUARDIAN_TELEGRAM_BOT_TOKEN", "").strip()
ENV_CHAT = os.getenv("VAST_GUARDIAN_TELEGRAM_CHAT_ID", "").strip()
STATE_PATH = "/var/lib/vast-guardian-watchdog/state.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"
STALE_AFTER_SECONDS = 90
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
FRESHNESS_STATE_KEY = "Collector Freshness"
NOTIFIED_STATES_KEY = "Notified States"
SERVICES = {
    "Guardian Collector": "vast-guardian",
    "Guardian Web": "vast-guardian-web",
}


def active(service):
    result = subprocess.run(
        ["systemctl", "is-active", service],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def send(text):
    if not ENV_TOKEN or not ENV_CHAT:
        return False
    data = urllib.parse.urlencode({"chat_id": ENV_CHAT, "text": text}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{ENV_TOKEN}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, STATE_PATH)


def collector_freshness(now=None):
    """Return (FRESH|STALE, reason) from the latest collector database write."""

    if now is None:
        now = datetime.now()

    try:
        database_uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(database_uri, uri=True)
        try:
            row = conn.execute("""
                SELECT last_seen
                FROM hosts
                ORDER BY id DESC
                LIMIT 1
            """).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return None, f"SQLite read failed: {exc}"

    if row is None:
        return "STALE", "No collector records in hosts"

    try:
        last_seen = datetime.strptime(row[0], TIMESTAMP_FORMAT)
    except (TypeError, ValueError):
        return None, f"Invalid last_seen value: {row[0]!r}"

    age_seconds = (now - last_seen).total_seconds()
    if age_seconds > STALE_AFTER_SECONDS:
        return "STALE", f"Last collector data is {int(age_seconds)} seconds old"
    return "FRESH", None


def check():
    previous = load_state()
    current = {}
    previous_notified = previous.get(NOTIFIED_STATES_KEY, {})
    notified = dict(previous_notified) if isinstance(previous_notified, dict) else {}

    for name, service in SERVICES.items():
        ok = active(service)
        current[name] = ok
        was_ok = previous.get(name)
        notification_key = f"service:{name}"
        notified_ok = notified.get(notification_key, was_ok)

        if was_ok is None:
            # Preserve the existing watchdog behavior: no alert on its first run.
            notified.setdefault(notification_key, ok)
        elif not ok and notified_ok is not False:
            if send(f"🔴 Vast Guardian WATCHDOG\n{name} jest NIEAKTYWNY."):
                notified[notification_key] = False
        elif ok and notified_ok is False:
            if send(f"🟢 Vast Guardian WATCHDOG RECOVERY\n{name} działa ponownie."):
                notified[notification_key] = True

    collector_active = current["Guardian Collector"]
    previous_freshness = previous.get(FRESHNESS_STATE_KEY)
    if collector_active:
        freshness, reason = collector_freshness()
        if freshness is None:
            print(f"Collector freshness check skipped: {reason}")
            if previous_freshness is not None:
                current[FRESHNESS_STATE_KEY] = previous_freshness
        else:
            current[FRESHNESS_STATE_KEY] = freshness
            notified_freshness = notified.get(FRESHNESS_STATE_KEY, previous_freshness)
            if freshness == "STALE" and notified_freshness != "STALE":
                if send(
                    "🔴 Vast Guardian STALE COLLECTOR\n"
                    f"{reason}."
                ):
                    notified[FRESHNESS_STATE_KEY] = "STALE"
            elif freshness == "FRESH" and notified_freshness == "STALE":
                if send(
                    "🟢 Vast Guardian STALE COLLECTOR RECOVERY\n"
                    "Collector zapisuje ponownie świeże dane."
                ):
                    notified[FRESHNESS_STATE_KEY] = "FRESH"
            elif notified_freshness is None:
                notified[FRESHNESS_STATE_KEY] = "FRESH"
    elif previous_freshness is not None:
        # A stopped service must not create a stale alert or erase freshness state.
        current[FRESHNESS_STATE_KEY] = previous_freshness

    current[NOTIFIED_STATES_KEY] = notified
    save_state(current)


if __name__ == "__main__":
    check()
