"""
Demo REST API for ASAP (AS400 Status Alert Platform).

Simulates a company system-status API so ASAP can be developed/tested
locally without touching real internal endpoints.

Endpoints:
    GET    /demo/api/SystemStatus            -> list all systems
    GET    /demo/api/SystemStatus/<system>    -> get one system
    PUT    /demo/api/SystemStatus/<system>    -> create or update a system
    DELETE /demo/api/SystemStatus/<system>    -> remove a system

Data model (per system):
    {
        "system": "AS400-PROD",
        "online": true,
        "dateTimeUtc": "2026-07-16T12:00:00Z",
        "reason": "all good"
    }

Run:
    pip install -r requirements.txt
    python demo_api.py

Then point ASAP's .env at it:
    API_URL=http://127.0.0.1:5000/demo/api/SystemStatus
"""

from datetime import datetime, timezone
from flask import Flask, jsonify, request, abort

app = Flask(__name__)

# In-memory "database" — resets every time the server restarts.
systems = {
    "AS400-PROD": {
        "system": "AS400-PROD",
        "online": True,
        "dateTimeUtc": datetime.now(timezone.utc).isoformat(),
        "reason": "all good",
    },
    "WEB-APP": {
        "system": "WEB-APP",
        "online": True,
        "dateTimeUtc": datetime.now(timezone.utc).isoformat(),
        "reason": "all good",
    },
}


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


@app.route("/demo/api/SystemStatus", methods=["GET"])
def list_systems():
    """Return the status of all systems as a list."""
    return jsonify(list(systems.values())), 200


@app.route("/demo/api/SystemStatus/<system>", methods=["GET"])
def get_system(system):
    """Return the status of a single system."""
    record = systems.get(system)
    if record is None:
        abort(404, description=f"System '{system}' not found")
    return jsonify(record), 200


@app.route("/demo/api/SystemStatus/<system>", methods=["PUT"])
def upsert_system(system):
    """
    Create or update a system's status.

    Expected JSON body:
        {
            "online": true,
            "reason": "optional text"
        }
    """
    body = request.get_json(silent=True) or {}

    if "online" not in body or not isinstance(body["online"], bool):
        abort(400, description="'online' (boolean) is required")

    record = {
        "system": system,
        "online": body["online"],
        "dateTimeUtc": now_utc_iso(),
        "reason": body.get("reason", "" if body["online"] else "no reason given"),
    }
    systems[system] = record
    return jsonify(record), 200


@app.route("/demo/api/SystemStatus/<system>", methods=["DELETE"])
def delete_system(system):
    """Remove a system from the demo data set."""
    if system not in systems:
        abort(404, description=f"System '{system}' not found")
    del systems[system]
    return "", 204


@app.errorhandler(404)
@app.errorhandler(400)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)