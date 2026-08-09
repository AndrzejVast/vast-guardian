#!/usr/bin/env python3

import json
import os
import urllib.error
import urllib.parse
import urllib.request


TELEGRAM_BOT_TOKEN = os.getenv("VAST_GUARDIAN_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("VAST_GUARDIAN_TELEGRAM_CHAT_ID", "").strip()


def configured():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(text):
    """Send one Telegram message. Returns True on success, False otherwise."""
    if not configured():
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.loads(response.read().decode("utf-8"))
            return bool(result.get("ok"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def format_alarm(alarm):
    icon = "🔴" if alarm["level"] == "CRITICAL" else "🟠"
    return (
        f"{icon} Vast Guardian {alarm['level']}\n"
        f"Komponent: {alarm['component']}\n"
        f"{alarm['message']}"
    )


def format_recovery(component):
    return f"🟢 Vast Guardian RECOVERY\nKomponent: {component}\nProblem ustąpił."
