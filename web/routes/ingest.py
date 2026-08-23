import hmac
import os

from flask import Blueprint, jsonify, request

from database.ingest import PayloadError, persist_report


ingest = Blueprint("ingest", __name__)


def authorized(header):
    token = os.getenv("VAST_GUARDIAN_INGEST_TOKEN", "")
    prefix = "Bearer "
    return bool(token) and header.startswith(prefix) and hmac.compare_digest(header[len(prefix):], token)


@ingest.route("/api/v1/ingest", methods=["POST"])
def receive():
    if not authorized(request.headers.get("Authorization", "")):
        return jsonify({"error": "unauthorized"}), 401
    if not request.is_json:
        return jsonify({"error": "JSON required"}), 400
    try:
        return jsonify(persist_report(request.get_json()))
    except PayloadError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "storage failure"}), 500
