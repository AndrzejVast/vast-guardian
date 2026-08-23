"""Validation and transactional persistence for agent metric reports."""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "vast_guardian.db"
HOST_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_TEXT = 255
METRIC_TEXT = ("ip", "gpu", "docker")
METRIC_NUMBERS = ("gpu_temp", "gpu_util", "vram", "cpu", "ram", "disk")


class PayloadError(ValueError):
    pass


def _iso8601(value):
    if not isinstance(value, str) or len(value) > 64:
        raise PayloadError("observed_at must be an ISO8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PayloadError("observed_at must be valid ISO8601") from exc
    if parsed.tzinfo is None:
        raise PayloadError("observed_at must include a timezone")


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise PayloadError("schema_version must be 1")
    report_id = payload.get("report_id")
    if not isinstance(report_id, str) or not report_id.strip() or len(report_id) > 128:
        raise PayloadError("report_id is invalid")
    host_key = payload.get("host_key")
    if not isinstance(host_key, str) or not HOST_KEY_RE.fullmatch(host_key):
        raise PayloadError("host_key is invalid")
    _iso8601(payload.get("observed_at"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise PayloadError("metrics is required")
    for key in METRIC_TEXT:
        value = metrics.get(key)
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise PayloadError(f"metrics.{key} is invalid")
    for key in METRIC_NUMBERS:
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadError(f"metrics.{key} must be numeric")
    return host_key, report_id, metrics


def persist_report(payload, db_path=DB_PATH, received_at=None):
    host_key, report_id, metrics = validate_payload(payload)
    received_at = received_at or datetime.now(timezone.utc)
    timestamp = received_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO ingest_reports(report_id, host_key) VALUES (?, ?)", (report_id, host_key))
        except sqlite3.IntegrityError:
            conn.rollback()
            return {"status": "duplicate", "host_key": host_key}
        conn.execute("""INSERT INTO hosts(name, ip, status, gpu, last_seen, gpu_temp, gpu_util, vram, cpu, ram, disk, docker)
            VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (host_key, metrics["ip"], metrics["gpu"], timestamp, metrics["gpu_temp"], metrics["gpu_util"], metrics["vram"], metrics["cpu"], metrics["ram"], metrics["disk"], metrics["docker"]))
        conn.execute("""INSERT INTO history(host_name, gpu_temp, gpu_util, vram, cpu, ram, disk, created)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (host_key, metrics["gpu_temp"], metrics["gpu_util"], metrics["vram"], metrics["cpu"], metrics["ram"], metrics["disk"], timestamp))
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "accepted", "host_key": host_key}
