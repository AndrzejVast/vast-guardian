#!/usr/bin/env python3

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

ENV_TOKEN = os.getenv("VAST_GUARDIAN_TELEGRAM_BOT_TOKEN", "").strip()
ENV_CHAT = os.getenv("VAST_GUARDIAN_TELEGRAM_CHAT_ID", "").strip()
STATE_PATH = "/var/lib/vast-guardian-watchdog/state.json"
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


def check():
    previous = load_state()
    current = {}

    for name, service in SERVICES.items():
        ok = active(service)
        current[name] = ok
        was_ok = previous.get(name)

        if was_ok is True and not ok:
            send(f"🔴 Vast Guardian WATCHDOG\n{name} jest NIEAKTYWNY.")
        elif was_ok is False and ok:
            send(f"🟢 Vast Guardian WATCHDOG RECOVERY\n{name} działa ponownie.")

    save_state(current)


if __name__ == "__main__":
    check()
