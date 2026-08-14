#!/usr/bin/env python3

import os
import subprocess
import urllib.parse
import urllib.request

TOKEN = os.getenv("VAST_GUARDIAN_TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("VAST_GUARDIAN_TELEGRAM_CHAT_ID", "").strip()

def cmd(command):
    try:
        return subprocess.check_output(
            command,
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"

def active(service):
    return subprocess.run(
        ["systemctl", "is-active", service],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ).returncode == 0

def send(text):
    if not TOKEN or not CHAT_ID:
        return False

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text
    }).encode()

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False

def main():
    guardian = "active" if active("vast-guardian") else "inactive"
    web = "active" if active("vast-guardian-web") else "inactive"
    docker = cmd("systemctl is-active docker")
    vastai = cmd("systemctl is-active vastai")
    uptime = cmd("uptime -p")
    gpu = cmd("nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu --format=csv,noheader")
    disk = cmd("df / | awk 'NR==2 {print $5}'")

    text = (
        "🟢 Vast Guardian — HEARTBEAT\n\n"
        f"Guardian: {guardian}\n"
        f"Dashboard: {web}\n"
        f"Docker: {docker}\n"
        f"Vast.ai: {vastai}\n"
        f"GPU: {gpu}\n"
        f"Disk: {disk}\n"
        f"Uptime: {uptime}"
    )

    if send(text):
        print("Heartbeat sent.")
    else:
        print("Heartbeat send failed.")

if __name__ == "__main__":
    main()
