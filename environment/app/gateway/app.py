#!/usr/bin/env python3
"""Ref-gated triage scorer gateway.

Thin Flask front door. All feature flattening, ref-pinning verification,
and inference logic live in the Perl worker at /app/worker/infer.pl -- this
process only validates the transport-level request shape and shells out.
"""
import json
import subprocess

from flask import Flask, jsonify, request

app = Flask(__name__)

WORKER_PATH = "/app/worker/infer.pl"

# error -> HTTP status mapping, keyed on the worker's "error" field
_ERROR_STATUS = {
    "bad_request": 400,
    "unpinned_ref": 422,
    "ref_mismatch": 422,
    "incomplete_coefficients": 422,
    "internal_error": 500,
    "not_implemented": 501,
}


@app.route("/v1/score", methods=["POST"])
def score():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "bad_request", "detail": "request body must be a JSON object"}), 400
    if "model_ref" not in body or "session" not in body:
        return jsonify({"error": "bad_request", "detail": 'request must include "model_ref" and "session"'}), 400

    proc = subprocess.run(
        ["perl", WORKER_PATH],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        timeout=30,
    )

    stdout = proc.stdout.strip()
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return jsonify({
            "error": "internal_error",
            "detail": "worker produced non-JSON output",
        }), 500

    if "error" in payload:
        status = _ERROR_STATUS.get(payload["error"], 500)
        return jsonify(payload), status

    return jsonify(payload), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
