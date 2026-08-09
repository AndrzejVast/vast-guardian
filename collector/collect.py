#!/usr/bin/env python3

import os
import sys
import sqlite3
import subprocess
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def cmd(command):
    return subprocess.check_output(command, shell=True, text=True).strip()


def collect():
    gpu = cmd("nvidia-smi --query-gpu=name --format=csv,noheader")
    gpu_temp = cmd("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits")
    gpu_util = cmd("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits")
    vram = cmd("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits")

    docker = cmd("systemctl is-active docker")
    cpu = cmd("top -bn1 | grep 'Cpu(s)' | awk '{print int($2+$4)}'")
    ram = cmd("free | awk '/Mem:/ {print int($3/$2*100)}'")
    disk = cmd("df / | awk 'NR==2 {print int($5)}' | tr -d '%'")
    status = cmd("systemctl is-active vastai")
    ip = cmd("hostname -I | awk '{print $1}'")

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
        "vastserver2",
        ip,
        status,
        gpu,
        gpu_temp,
        gpu_util,
        vram,
        cpu,
        ram,
        disk,
        docker,
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
        "vastserver2",
        int(gpu_temp),
        int(gpu_util),
        int(vram),
        int(cpu),
        int(ram),
        int(disk)
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
