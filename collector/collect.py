#!/usr/bin/env python3

import os
import sys
import sqlite3
import subprocess
from datetime import datetime, timezone
import uuid

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def cmd(command):
    return subprocess.check_output(command, shell=True, text=True).strip()


def collect_metrics():
    """Read local metrics without writing a database or sending notifications."""
    return {
        "ip": cmd("hostname -I | awk '{print $1}'"),
        "gpu": cmd("nvidia-smi --query-gpu=name --format=csv,noheader"),
        "gpu_temp": int(cmd("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits")),
        "gpu_util": int(cmd("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits")),
        "vram": int(cmd("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits")),
        "cpu": int(cmd("top -bn1 | grep 'Cpu(s)' | awk '{print int($2+$4)}'")),
        "ram": int(cmd("free | awk '/Mem:/ {print int($3/$2*100)}'")),
        "disk": int(cmd("df / | awk 'NR==2 {print int($5)}' | tr -d '%'")),
        "docker": cmd("systemctl is-active docker"),
        "status": cmd("systemctl is-active vastai"),
    }


def agent_payload(host_key=None):
    metrics = collect_metrics()
    metrics.pop("status")
    return {
        "schema_version": 1,
        "report_id": str(uuid.uuid4()),
        "host_key": host_key or os.getenv("VAST_GUARDIAN_HOST_KEY") or cmd("hostname"),
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metrics": metrics,
    }


def collect():
    metrics = collect_metrics()

    conn = sqlite3.connect("database/vast_guardian.db")
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO hosts(
        name, ip, status, gpu,
        gpu_temp, gpu_util, vram,
        cpu, ram, disk, docker,
        last_seen
    )
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        os.getenv("VAST_GUARDIAN_HOST_KEY", "vastserver2"), metrics["ip"], metrics["status"], metrics["gpu"], metrics["gpu_temp"], metrics["gpu_util"], metrics["vram"], metrics["cpu"], metrics["ram"], metrics["disk"], metrics["docker"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    cur.execute("""
    INSERT INTO history(
        host_name,
        gpu_temp,
        gpu_util,
        vram,
        cpu,
        ram,
        disk
    )
    VALUES(?,?,?,?,?,?,?)
    """, (
        os.getenv("VAST_GUARDIAN_HOST_KEY", "vastserver2"), metrics["gpu_temp"], metrics["gpu_util"], metrics["vram"], metrics["cpu"], metrics["ram"], metrics["disk"]
    ))

    conn.commit()
    conn.close()

    # Alarm checking must never stop metric collection.
    try:
        from monitor.alarms import check_alarms, record_alarm_state
        result = check_alarms()
        record_alarm_state(result)
    except Exception as exc:
        print(f"Alarm check skipped: {exc}")

    print("Host zapisany.")


if __name__ == "__main__":
    collect()
