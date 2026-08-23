"""Agent-only reporting loop; it never writes SQLite or sends Telegram."""
import json
import os
import time
import urllib.error
import urllib.request

from collector.collect import agent_payload


TIMEOUT_SECONDS = 5
MAX_RETRIES = 3


def send_report(payload):
    url = os.environ.get("VAST_GUARDIAN_CENTRAL_URL", "")
    token = os.environ.get("VAST_GUARDIAN_INGEST_TOKEN", "")
    if not url or not token:
        raise RuntimeError("Agent central URL or ingest token is missing")
    if not url.startswith("https://") and not (url.startswith("http://") and os.environ.get("VAST_GUARDIAN_ALLOW_INSECURE_HTTP") == "1"):
        raise RuntimeError("Agent central URL must use https://")
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Ingest returned HTTP {response.status}")
        return json.loads(response.read().decode() or "{}")


def run_once(pending=None, attempts=0):
    if pending is None:
        try:
            payload = agent_payload()
        except Exception as exc:
            print(f"Agent metric collection failed: {exc}")
            return None, 0
    else:
        payload = pending
    try:
        send_report(payload)
        return None, 0
    except (RuntimeError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"Agent report failed: {exc}")
        return (payload, attempts + 1) if attempts + 1 < MAX_RETRIES else (None, 0)


def main():
    pending, attempts = None, 0
    while True:
        pending, attempts = run_once(pending, attempts)
        time.sleep(5)


if __name__ == "__main__":
    main()
