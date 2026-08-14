#!/usr/bin/env python3

import sqlite3

from system.info import health
from monitor.telegram import format_alarm, format_recovery, send_message


GPU_WARNING = 80
GPU_CRITICAL = 90
DISK_WARNING = 80
DISK_CRITICAL = 90
DB_PATH = "database/vast_guardian.db"


def check_alarms():

    h = health()
    alarms = []

    # Guardian
    if h["guardian"] != "active":
        alarms.append({
            "component": "Guardian",
            "level": "CRITICAL",
            "message": "Vast Guardian Web is not active"
        })

    # Docker
    if h["docker"] != "active":
        alarms.append({
            "component": "Docker",
            "level": "CRITICAL",
            "message": "Docker service is not active"
        })

    # Vast.ai
    if h["vastai"] != "active":
        alarms.append({
            "component": "VastAI",
            "level": "CRITICAL",
            "message": "Vast.ai service is not active"
        })

    # Internet
    if h["internet"] != "online":
        alarms.append({
            "component": "Internet",
            "level": "CRITICAL",
            "message": "Internet connection is offline"
        })

    # GPU temperature
    try:
        gpu_temp = int(h["gpu_temp"])

        if gpu_temp >= GPU_CRITICAL:
            alarms.append({
                "component": "GPU",
                "level": "CRITICAL",
                "message": f"GPU temperature is {gpu_temp}°C"
            })
        elif gpu_temp >= GPU_WARNING:
            alarms.append({
                "component": "GPU",
                "level": "WARNING",
                "message": f"GPU temperature is {gpu_temp}°C"
            })

    except (ValueError, TypeError):
        pass

    # Disk usage
    try:
        disk = int(h["disk"])

        if disk >= DISK_CRITICAL:
            alarms.append({
                "component": "Disk",
                "level": "CRITICAL",
                "message": f"Disk usage is {disk}%"
            })
        elif disk >= DISK_WARNING:
            alarms.append({
                "component": "Disk",
                "level": "WARNING",
                "message": f"Disk usage is {disk}%"
            })

    except (ValueError, TypeError):
        pass

    critical = sum(
        1 for alarm in alarms
        if alarm["level"] == "CRITICAL"
    )

    warnings = sum(
        1 for alarm in alarms
        if alarm["level"] == "WARNING"
    )

    if critical > 0:
        status = "CRITICAL"
    elif warnings > 0:
        status = "WARNING"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "critical": critical,
        "warnings": warnings,
        "count": len(alarms),
        "alarms": alarms
    }


def record_alarm_state(result):
    """Store only alarm state changes and notify Telegram once per change."""

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    current = {
        alarm["component"]: alarm
        for alarm in result["alarms"]
    }

    cur.execute("""
        SELECT component, level, message, event
        FROM alarm_history
        WHERE id IN (
            SELECT MAX(id)
            FROM alarm_history
            WHERE event IN ('ACTIVE', 'RECOVERY')
            GROUP BY component
        )
    """)

    previous = {
        row[0]: {
            "level": row[1],
            "message": row[2],
            "event": row[3]
        }
        for row in cur.fetchall()
    }

    notifications = []

    # New or changed alarms.
    for component, alarm in current.items():
        old = previous.get(component)
        if (
            old is None
            or old["event"] == "RECOVERY"
            or old["level"] != alarm["level"]
            or old["message"] != alarm["message"]
        ):
            cur.execute("""
                INSERT INTO alarm_history(component, level, message, event)
                VALUES (?, ?, ?, 'ACTIVE')
            """, (
                component,
                alarm["level"],
                alarm["message"]
            ))
            notifications.append(("alarm", alarm))

    # Alarms that disappeared are recovery events.
    for component, old in previous.items():
        if component not in current and old["event"] == "ACTIVE":
            cur.execute("""
                INSERT INTO alarm_history(component, level, message, event)
                VALUES (?, ?, ?, 'RECOVERY')
            """, (
                component,
                old["level"],
                f"{component} returned to HEALTHY"
            ))
            notifications.append(("recovery", component))

    conn.commit()
    conn.close()

    # Notifications are best-effort and must never stop the collector.
    for kind, value in notifications:
        try:
            if kind == "alarm":
                send_message(format_alarm(value))
            else:
                send_message(format_recovery(value))
        except Exception as exc:
            print(f"Telegram notification skipped: {exc}")


def alarm_history(limit=50):
    """Return the most recent persisted alarm state changes."""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, component, level, message, event, created
        FROM alarm_history
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
