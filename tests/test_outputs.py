"""Behavioral tests for the ref-gated triage scorer.

These tests drive the system exclusively through the HTTP gateway
(POST /v1/score) and independently recompute expected model scores from the
feature contract and the model repository, rather than trusting whatever the
worker under test reports. This ensures the tests catch a worker that
returns a plausible-looking but incorrect score.
"""
import json
import math
import subprocess

import pytest
import requests

BASE_URL = "http://127.0.0.1:8080"
CONTRACT_PATH = "/app/contract/feature_contract.json"
LOCKFILE_PATH = "/app/config/model.lock.json"
REPO_PATH = "/app/model.git"


# --------------------------------------------------------------------------
# Independent reference implementation of the feature contract (CONTRACT.md).
# This intentionally does not import or call any worker code.
# --------------------------------------------------------------------------
def _flatten(session: dict) -> dict:
    patient = session.get("patient") or {}
    visits = session.get("visits") or []
    devices = session.get("devices") or []
    events = session.get("events") or []

    spo2_values = [
        r["value"]
        for d in devices
        for r in (d.get("readings") or [])
        if r.get("metric") == "spo2" and "value" in r
    ]
    acuities = [v["acuity"] for v in visits if "acuity" in v]
    severities = [e["severity"] for e in events if "severity" in e]

    return {
        "patient_age": float(patient.get("age", 0.0)),
        "patient_sex_f": 1.0 if patient.get("sex") == "F" else 0.0,
        "visit_count": float(len(visits)),
        "visit_ed_count": float(sum(1 for v in visits if v.get("type") == "ed")),
        "visit_acuity_max": float(max(acuities)) if acuities else 0.0,
        "visit_duration_total": float(sum(v.get("duration_min", 0) for v in visits)),
        "device_spo2_min": float(min(spo2_values)) if spo2_values else 100.0,
        "event_count": float(len(events)),
        "event_severity_max": float(max(severities)) if severities else 0.0,
        "event_triage_escalation_present": 1.0
        if any(e.get("code") == "triage_escalation" for e in events)
        else 0.0,
    }


def _load_contract() -> dict:
    with open(CONTRACT_PATH) as fh:
        return json.load(fh)


def _load_lockfile() -> dict:
    with open(LOCKFILE_PATH) as fh:
        return json.load(fh)


def _coefficients_at(ref_or_sha: str) -> dict:
    out = subprocess.run(
        ["git", "-C", REPO_PATH, "show", f"{ref_or_sha}:coefficients.json"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _current_tip(ref: str) -> str:
    out = subprocess.run(
        ["git", "-C", REPO_PATH, "rev-parse", ref],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _expected_score(session: dict, coeffs: dict, contract: dict) -> float:
    features = _flatten(session)
    z = coeffs["bias"]
    for f in contract["features"]:
        name = f["name"]
        val = features.get(name, f["default"])
        z += coeffs["weights"][name] * val
    return 1.0 / (1.0 + math.exp(-z))


SAMPLE_SESSION = {
    "session_id": "sess-001",
    "patient": {"age": 54, "sex": "F"},
    "visits": [
        {"visit_id": "v1", "type": "ed", "acuity": 3, "duration_min": 42},
        {"visit_id": "v2", "type": "clinic", "acuity": 1, "duration_min": 15},
    ],
    "devices": [
        {
            "device_id": "d1",
            "kind": "pulse_ox",
            "readings": [
                {"metric": "spo2", "value": 94.2},
                {"metric": "spo2", "value": 91.0},
            ],
        }
    ],
    "events": [
        {"event_id": "e1", "code": "triage_escalation", "severity": 2},
        {"event_id": "e2", "code": "med_admin", "severity": 1},
    ],
}

EMPTY_SESSION = {
    "session_id": "sess-002",
    "patient": {"age": 22, "sex": "M"},
    "visits": [],
    "devices": [],
    "events": [],
}


def _score(model_ref, session):
    return requests.post(
        f"{BASE_URL}/v1/score",
        json={"model_ref": model_ref, "session": session},
        timeout=10,
    )


def test_healthz_ok():
    """The gateway's health endpoint is reachable and reports ok."""
    resp = requests.get(f"{BASE_URL}/healthz", timeout=10)
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_trusted_ref_returns_correct_score():
    """A ref that matches its lockfile pin scores correctly against the
    independently-recomputed expected value, and the response shape matches
    the contract (score, label, provenance with commit + contract version)."""
    contract = _load_contract()
    lock = _load_lockfile()
    coeffs = _coefficients_at(lock["stable"])
    expected = _expected_score(SAMPLE_SESSION, coeffs, contract)

    resp = _score("stable", SAMPLE_SESSION)
    assert resp.status_code == 200
    body = resp.json()

    assert body["score"] == pytest.approx(expected, abs=1e-4)
    assert body["label"] in (0, 1)
    assert body["label"] == (1 if expected >= 0.5 else 0)

    prov = body["provenance"]
    assert prov["model_ref"] == "stable"
    assert prov["model_commit"] == lock["stable"]
    assert prov["contract_version"] == contract["contract_version"]


def test_empty_session_uses_contract_defaults():
    """A session with no visits/devices/events must fall back to each
    feature's contract-defined default (e.g. device_spo2_min defaults to
    100.0), not to zero or a crash."""
    contract = _load_contract()
    lock = _load_lockfile()
    coeffs = _coefficients_at(lock["stable"])
    expected = _expected_score(EMPTY_SESSION, coeffs, contract)

    resp = _score("stable", EMPTY_SESSION)
    assert resp.status_code == 200
    assert resp.json()["score"] == pytest.approx(expected, abs=1e-4)


def test_result_is_deterministic():
    """Scoring identical input twice must yield an identical score and
    resolved commit -- no hidden randomness or time-dependence."""
    first = _score("stable", SAMPLE_SESSION).json()
    second = _score("stable", SAMPLE_SESSION).json()
    assert first["score"] == second["score"]
    assert first["provenance"]["model_commit"] == second["provenance"]["model_commit"]


def test_unpinned_ref_is_rejected():
    """A ref name that never appears in the lockfile must be refused, not
    silently scored against whatever the branch currently contains."""
    resp = _score("canary", SAMPLE_SESSION)
    assert resp.status_code == 422
    assert resp.json()["error"] == "unpinned_ref"


def test_mismatched_ref_is_rejected():
    """'release' is pinned in the lockfile to an older commit than what the
    branch currently points to (simulating a post-pin model swap). The
    worker must detect the mismatch and refuse to score, rather than trusting
    the branch's current tip."""
    lock = _load_lockfile()
    pinned_sha = lock["release"]
    actual_tip = _current_tip("release")
    assert actual_tip != pinned_sha, "fixture invariant broken: release tip should differ from its pin"

    resp = _score("release", SAMPLE_SESSION)
    assert resp.status_code == 422
    assert resp.json()["error"] == "ref_mismatch"


def test_incomplete_coefficients_are_rejected():
    """'beta' is pinned correctly (ref resolves to the pinned commit) but the
    coefficients at that commit are missing a contract feature and include
    an unknown one. The worker must catch this schema mismatch rather than
    scoring with partial/garbage weights."""
    resp = _score("beta", SAMPLE_SESSION)
    assert resp.status_code == 422
    assert resp.json()["error"] == "incomplete_coefficients"


def test_missing_model_ref_is_bad_request():
    """A request missing the required model_ref field is rejected as a
    client error, not passed through to the worker."""
    resp = requests.post(f"{BASE_URL}/v1/score", json={"session": SAMPLE_SESSION}, timeout=10)
    assert resp.status_code == 400


def test_missing_session_is_bad_request():
    """A request missing the required session field is rejected as a client
    error."""
    resp = requests.post(f"{BASE_URL}/v1/score", json={"model_ref": "stable"}, timeout=10)
    assert resp.status_code == 400


def test_spo2_min_taken_across_all_devices():
    """device_spo2_min must be the minimum spo2 reading across *all* devices
    in the session, not just the first device or a single reading."""
    session = {
        "session_id": "sess-multi-device",
        "patient": {"age": 40, "sex": "M"},
        "visits": [],
        "devices": [
            {"device_id": "d1", "kind": "pulse_ox", "readings": [{"metric": "spo2", "value": 97.0}]},
            {"device_id": "d2", "kind": "pulse_ox", "readings": [{"metric": "spo2", "value": 88.5}]},
        ],
        "events": [],
    }
    contract = _load_contract()
    lock = _load_lockfile()
    coeffs = _coefficients_at(lock["stable"])
    expected = _expected_score(session, coeffs, contract)

    resp = _score("stable", session)
    assert resp.status_code == 200
    assert resp.json()["score"] == pytest.approx(expected, abs=1e-4)


def test_visit_ed_count_only_counts_ed_type():
    """visit_ed_count must only count visits whose type is exactly 'ed',
    ignoring other visit types like 'clinic'."""
    session = {
        "session_id": "sess-visit-types",
        "patient": {"age": 30, "sex": "F"},
        "visits": [
            {"visit_id": "v1", "type": "clinic", "acuity": 2, "duration_min": 10},
            {"visit_id": "v2", "type": "clinic", "acuity": 2, "duration_min": 10},
        ],
        "devices": [],
        "events": [],
    }
    contract = _load_contract()
    lock = _load_lockfile()
    coeffs = _coefficients_at(lock["stable"])
    expected = _expected_score(session, coeffs, contract)

    resp = _score("stable", session)
    assert resp.status_code == 200
    assert resp.json()["score"] == pytest.approx(expected, abs=1e-4)
