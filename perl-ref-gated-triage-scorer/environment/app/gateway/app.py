"""
Flask gateway: /health and /score.
Delegates inference to perl worker subprocess per the IPC contract.
"""
import json
import os
import subprocess
import sys

from flask import Flask, request, jsonify

app = Flask(__name__)

WORKER_CMD = ["perl", os.environ.get("WORKER_PATH", "/app/worker/triage_worker.pl")]
WORKER_TIMEOUT = 25


def _fmt_err(code, msg):
    return jsonify({"ok": False, "error_code": code, "message": msg})


def _run_worker(input_obj):
    raw_in = json.dumps(input_obj) + "\n"
    try:
        proc = subprocess.run(
            WORKER_CMD,
            input=raw_in,
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, 502, "worker timed out"
    except OSError:
        return None, 502, "cannot start worker"

    if proc.returncode != 0 and proc.stdout.strip() == "":
        return None, 502, "worker crashed"

    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return None, 502, "worker produced invalid JSON"

    return out, None, None


@app.route("/health", methods=["GET"])
def health():
    out, status, msg = _run_worker({"op": "ping"})
    if out and out.get("ok") is True:
        return jsonify({"status": "ok", "worker": "ok"})
    return jsonify({"status": "error", "worker": "unavailable"}), 502


@app.route("/score", methods=["POST"])
def score():
    if not request.is_json:
        return jsonify({"ok": False, "error_code": "INVALID_PAYLOAD", "message": "content-type must be application/json"}), 400

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error_code": "INVALID_PAYLOAD", "message": "body must be a JSON object"}), 400

    payload = body.get("payload")
    model_ref = body.get("model_ref")

    if not isinstance(payload, dict) or not isinstance(model_ref, str):
        return jsonify({"ok": False, "error_code": "INVALID_PAYLOAD", "message": "required fields: payload (object), model_ref (string)"}), 400

    worker_in = {"op": "score", "payload": payload, "model_ref": model_ref}
    out, status, msg = _run_worker(worker_in)

    if status is not None:
        return jsonify({"ok": False, "error_code": "SERVICE_ERROR", "message": msg}), status

    if not isinstance(out, dict):
        return jsonify({"ok": False, "error_code": "SERVICE_ERROR", "message": "unexpected worker output"}), 502

    if out.get("ok") is True:
        return jsonify(out), 200

    err_code = out.get("error_code", "SERVICE_ERROR")
    err_msg = out.get("message", "unknown worker error")
    http_map = {
        "UNPINNED_REF": 422,
        "REF_MISMATCH": 422,
        "INVALID_PAYLOAD": 400,
    }
    return jsonify({"ok": False, "error_code": err_code, "message": err_msg}), http_map.get(err_code, 502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
