"""Test suite for perl ref-gated triage scorer gateway + worker.

Tests start the Flask app and drive it via test_client. The worker
subprocess is exercised in-process; no network port is needed.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/app/gateway")
sys.path.insert(0, "/tests")
from app import app as flask_app

client = flask_app.test_client()

from features import FEATURE_ORDER, feature_hash, compute_features, compute_score

GIT_DIR = os.environ.get("MODEL_REPO_PATH", "/srv/model-repo.git")

# ── known repository object ids ──────────────────────────────────
MAIN_C1 = "b224771e18be8178c0bd7858669502548498c3ba"     # model 1.0.0
MAIN_TIP = "da27d065c965b003cf1ece36d81925336eaf3ee4"   # model 1.1.0
LEGACY_TIP = "ce9da1320ed3c8c3b898260a6f03b678d42cb192" # model 1.3.0
RELEASE_TIP = "def6e4436e25019ddda783a6aa94dfb61a7d52b4" # model 2.0.0 (peeled of v2.0.0)
DANGLING_SHA = "e654c8748de3a32b93b44ee8d4a415e2fa1ae103" # unadvertised

EXPECTED_HASH = "aff334b4bb5b"

# ── model specs (hardcoded to match the shipped repo) ────────────
MODELS = {
    MAIN_C1: {
        "intercept": -1.2,
        "coefficients": {"n_visits": 0.15, "hr_mean": -0.03, "hr_max": 0.02,
                         "spo2_min": -0.04, "bp_sys_mean": 0.01,
                         "visit_recency_weight": 0.08, "night_visit_ratio": -0.12,
                         "n_events_weighted": 0.20, "n_fall_events": 0.35,
                         "n_distinct_devices": -0.05, "device_span_hours": 0.03,
                         "hr_slope_per_hour": -0.10},
        "model_version": "1.0.0",
    },
    MAIN_TIP: {
        "intercept": -1.5,
        "coefficients": {"n_visits": 0.18, "hr_mean": -0.04, "hr_max": 0.02,
                         "spo2_min": -0.05, "bp_sys_mean": 0.01,
                         "visit_recency_weight": 0.09, "night_visit_ratio": -0.14,
                         "n_events_weighted": 0.22, "n_fall_events": 0.38,
                         "n_distinct_devices": -0.06, "device_span_hours": 0.04,
                         "hr_slope_per_hour": -0.12},
        "model_version": "1.1.0",
    },
    LEGACY_TIP: {
        "intercept": -1.8,
        "coefficients": {"n_visits": 0.22, "hr_mean": -0.05, "hr_max": 0.03,
                         "spo2_min": -0.06, "bp_sys_mean": 0.02,
                         "visit_recency_weight": 0.10, "night_visit_ratio": -0.15,
                         "n_events_weighted": 0.25, "n_fall_events": 0.42,
                         "n_distinct_devices": -0.08, "device_span_hours": 0.05,
                         "hr_slope_per_hour": -0.15},
        "model_version": "1.3.0",
    },
    RELEASE_TIP: {
        "intercept": -2.0,
        "coefficients": {"n_visits": 0.25, "hr_mean": -0.06, "hr_max": 0.04,
                         "spo2_min": -0.07, "bp_sys_mean": 0.03,
                         "visit_recency_weight": 0.12, "night_visit_ratio": -0.18,
                         "n_events_weighted": 0.28, "n_fall_events": 0.45,
                         "n_distinct_devices": -0.10, "device_span_hours": 0.07,
                         "hr_slope_per_hour": -0.18},
        "model_version": "2.0.0",
    },
}

# ── payload fixtures ──────────────────────────────────────────────
PAYLOAD_1 = {
    "patient_id": "p-101",
    "session_start": "2024-03-01T08:00:00Z",
    "visits": [
        {"visit_id": "v1", "ts": "2024-03-01T07:00:00Z", "heart_rate": 72, "spo2": 98, "bp_sys": 120, "bp_dia": 80, "site": "clinic"},
        {"visit_id": "v2", "ts": "2024-03-01T08:00:00Z", "heart_rate": 88, "spo2": 95, "bp_sys": 135, "bp_dia": 90, "site": "home"},
        {"visit_id": "v3", "ts": "2024-03-01T06:30:00Z", "spo2": 91, "bp_sys": 110, "site": "clinic"},
        {"visit_id": "v4", "ts": "2024-03-01T09:00:00Z", "heart_rate": 100},
    ],
    "devices": [
        {"device_id": "d1", "name": "Omron M7", "first_seen": "2024-02-01T00:00:00Z", "last_seen": "2024-02-15T00:00:00Z"},
        {"device_id": "d2", "name": "omron  m7!", "first_seen": "2024-02-10T00:00:00Z", "last_seen": "2024-02-20T00:00:00Z"},
        {"device_id": "d3", "name": "Withings Scale", "first_seen": "2024-01-01T00:00:00Z"},
    ],
    "events": [
        {"event_id": "e1", "ts": "2024-02-28T22:30:00Z", "type": "fall_detected", "severity": 3},
        {"event_id": "e2", "ts": "2024-03-01T03:00:00Z", "type": "arrhythmia_alert", "severity": 5},
        {"event_id": "e3", "ts": "2024-03-01T07:00:00Z", "type": "fall_detected", "severity": 2},
    ],
}

PAYLOAD_EDGE = {
    "patient_id": "p-edge",
    "session_start": "2024-06-15T12:00:00Z",
    "visits": [{"visit_id": "v1", "ts": "2024-06-15T10:00:00Z"}],
    "devices": [],
    "events": [],
}

PAYLOAD_NIGHT = {
    "patient_id": "p-night",
    "session_start": "2024-03-01T08:00:00Z",
    "visits": [
        {"visit_id": "v1", "ts": "2024-02-29T23:00:00Z", "heart_rate": 65, "spo2": 96},
        {"visit_id": "v2", "ts": "2024-03-01T03:00:00Z", "heart_rate": 60, "spo2": 94},
        {"visit_id": "v3", "ts": "2024-03-01T07:00:00Z", "heart_rate": 72, "spo2": 98},
    ],
    "devices": [],
    "events": [],
}


def _score(payload, model_ref):
    """Post a score request and return (status_code, json_body)."""
    resp = client.post(
        "/score",
        data=json.dumps({"payload": payload, "model_ref": model_ref}),
        content_type="application/json",
    )
    return resp.status_code, (resp.get_json() or {})


# ── tests ─────────────────────────────────────────────────────────

def test_health_worker_ok():
    """Health endpoint returns worker=ok when worker ping succeeds."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["worker"] == "ok"


def test_feature_order_hash_value():
    """All success responses include the correct feature_order_hash."""
    code, body = _score(PAYLOAD_EDGE, LEGACY_TIP)
    assert code == 200
    assert body.get("feature_order_hash") == EXPECTED_HASH
    assert feature_hash() == EXPECTED_HASH


def test_score_pinned_sha_legacy_tip():
    """Pinned 40-hex SHA on legacy branch resolves and returns expected score."""
    code, body = _score(PAYLOAD_1, LEGACY_TIP)
    assert code == 200
    assert body["ok"] is True
    assert body["model_commit"] == LEGACY_TIP
    assert body["ref_kind"] == "commit"

    # all 12 features present
    assert set(body["features"].keys()) == set(FEATURE_ORDER)

    # independently compute expected score
    expected_feats = compute_features(PAYLOAD_1)
    for fname in FEATURE_ORDER:
        exp = expected_feats[fname]
        got = body["features"].get(fname)
        assert abs(float(got) - exp) < 1e-9, f"feature {fname}: got {got} expected ~{exp}"

    spec = MODELS[LEGACY_TIP]
    expected_score = compute_score(expected_feats, spec["coefficients"], spec["intercept"])
    assert abs(body["score"] - expected_score) < 5e-7
    assert body["model_version"] == spec["model_version"]


def test_score_annotated_tag_v2_0_0():
    """Annotated tag v2.0.0 peels to release tip and scores correctly."""
    code, body = _score(PAYLOAD_NIGHT, "v2.0.0")
    assert code == 200
    assert body["ref_kind"] == "tag"
    # v2.0.0 peels to RELEASE_TIP (model 2.0.0)
    assert body["model_commit"] == RELEASE_TIP
    assert body["model_version"] == "2.0.0"
    assert body["ok"] is True

    expected_feats = compute_features(PAYLOAD_NIGHT)
    for fname in FEATURE_ORDER:
        assert abs(float(body["features"].get(fname)) - expected_feats[fname]) < 1e-9, fname

    spec = MODELS[RELEASE_TIP]
    expected_score = compute_score(expected_feats, spec["coefficients"], spec["intercept"])
    assert abs(body["score"] - expected_score) < 5e-7


def test_score_main_tip_pinned_sha_with_clamp():
    """Main tip SHA on payload_1 triggers clamp (z > 40) yielding score 1.0."""
    code, body = _score(PAYLOAD_1, MAIN_TIP)
    assert code == 200
    expected_feats = compute_features(PAYLOAD_1)
    spec = MODELS[MAIN_TIP]
    expected_score = compute_score(expected_feats, spec["coefficients"], spec["intercept"])
    assert abs(body["score"] - expected_score) < 5e-7
    assert body["score"] == 1.0
    assert body["model_version"] == "1.1.0"


def test_lightweight_tag_v1_1_0_rejected():
    """Lightweight tag v1.1.0 is rejected with UNPINNED_REF (422)."""
    code, body = _score(PAYLOAD_1, "v1.1.0")
    assert code == 422
    assert body["error_code"] == "UNPINNED_REF"


def test_branch_name_rejected():
    """Branch name 'main' is unpinned and must be rejected."""
    code, body = _score(PAYLOAD_1, "main")
    assert code == 422
    assert body["error_code"] == "UNPINNED_REF"


def test_short_sha_rejected():
    """A 7-char SHA prefix is unpinned — must be rejected."""
    code, body = _score(PAYLOAD_1, MAIN_TIP[:7])
    assert code == 422
    assert body["error_code"] == "UNPINNED_REF"


def test_uppercase_sha_rejected():
    """An uppercase SHA is not a valid pinned ref — must be rejected."""
    code, body = _score(PAYLOAD_1, LEGACY_TIP.upper())
    assert code == 422
    assert body["error_code"] == "UNPINNED_REF"


def test_dangling_commit_rejected():
    """Unadvertised dangling commit is rejected with REF_MISMATCH."""
    code, body = _score(PAYLOAD_1, DANGLING_SHA)
    assert code == 422
    assert body["error_code"] == "REF_MISMATCH"


def test_score_edge_payload_sentinels():
    """Edge payload (no vitals, no devices, no events) hits all sentinel defaults."""
    code, body = _score(PAYLOAD_EDGE, LEGACY_TIP)
    assert code == 200
    expected_feats = compute_features(PAYLOAD_EDGE)
    for fname in FEATURE_ORDER:
        assert abs(float(body["features"].get(fname)) - expected_feats[fname]) < 1e-9, fname

    spec = MODELS[LEGACY_TIP]
    expected_score = compute_score(expected_feats, spec["coefficients"], spec["intercept"])
    assert abs(body["score"] - expected_score) < 5e-7


def test_night_visit_payload():
    """A payload with 2 of 3 visits at night yields correct night_visit_ratio."""
    code, body = _score(PAYLOAD_NIGHT, MAIN_TIP)
    assert code == 200
    feats = compute_features(PAYLOAD_NIGHT)
    assert abs(feats["night_visit_ratio"] - 0.6666666667) < 1e-9
    assert abs(float(body["features"]["night_visit_ratio"]) - feats["night_visit_ratio"]) < 1e-9
    spec = MODELS[MAIN_TIP]
    expected_score = compute_score(feats, spec["coefficients"], spec["intercept"])
    assert abs(body["score"] - expected_score) < 5e-7


def test_deterministic_same_request_twice():
    """Two identical requests produce byte-for-byte identical JSON bodies."""
    code1, body1 = _score(PAYLOAD_NIGHT, "v2.0.0")
    code2, body2 = _score(PAYLOAD_NIGHT, "v2.0.0")
    assert code1 == 200
    assert code2 == 200
    assert json.dumps(body1, sort_keys=True) == json.dumps(body2, sort_keys=True)


def test_invalid_payload_missing_session_start():
    """Payload with valid outer shape but missing required session_start field
    triggers worker-level INVALID_PAYLOAD (400). Requires worker implementation."""
    bad_payload = {"patient_id": "p-bad", "visits": [], "events": [], "devices": []}
    code, body = _score(bad_payload, MAIN_TIP)
    assert code == 400
    assert body.get("error_code") == "INVALID_PAYLOAD"


def test_provenance_fields_present():
    """Success responses include all provenance metadata fields."""
    code, body = _score(PAYLOAD_EDGE, LEGACY_TIP)
    assert code == 200
    assert isinstance(body.get("model_commit"), str) and len(body["model_commit"]) == 40
    assert body["ref_kind"] in ("commit", "tag")
    assert isinstance(body.get("model_version"), str) and len(body["model_version"]) > 0
    assert isinstance(body.get("feature_order_hash"), str)
    assert isinstance(body.get("features"), dict)


def test_new_ref_property_hardening():
    """Create a fresh commit with known coefficients in the bare repo
    and verify the worker resolves + scores it correctly — this
    validates real git integration and prevents hardcoding."""
    import math, random

    def git(*args):
        return subprocess.run(
            [sys.executable, "-c",
             f"import subprocess; subprocess.run(['git','--git-dir','{GIT_DIR}']+{list(args)}, check=True)"],
            capture_output=True, text=True,
        )

    # generate deterministic but varying coefficients
    rng = random.Random(424242)
    test_coeffs = {name: round(rng.uniform(-0.5, 0.5), 6) for name in FEATURE_ORDER}
    test_intercept = round(rng.uniform(-3.0, 1.0), 6)
    model_obj = {
        "model_version": "test-property",
        "intercept": test_intercept,
        "coefficients": test_coeffs,
        "trained_at": "2025-01-01T00:00:00Z",
    }
    model_json = json.dumps(model_obj)

    # write blob
    blob = subprocess.run(
        ["git", "--git-dir", GIT_DIR, "hash-object", "-w", "--stdin"],
        input=model_json, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # create tree
    tree = subprocess.run(
        ["git", "--git-dir", GIT_DIR, "mktree"],
        input=f"100644 blob {blob}\tmodel.json\n",
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # create commit on top of MAIN_C1
    commit = subprocess.run(
        ["git", "--git-dir", GIT_DIR, "commit-tree", tree, "-p", MAIN_C1, "-m", "property test"],
        input="property test\n",
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # point branch
    subprocess.run(
        ["git", "--git-dir", GIT_DIR, "update-ref", "refs/heads/test-property", commit],
        check=True,
    )

    # test with a novel payload
    test_payload = {
        "patient_id": "p-prop",
        "session_start": "2025-03-15T10:00:00Z",
        "visits": [
            {"visit_id": "v1", "ts": "2025-03-15T08:00:00Z", "heart_rate": 75, "spo2": 97, "bp_sys": 118},
            {"visit_id": "v2", "ts": "2025-03-15T09:30:00Z", "heart_rate": 82, "spo2": 95, "bp_sys": 125},
        ],
        "devices": [
            {"device_id": "d-a", "name": "Device One", "first_seen": "2025-03-01T00:00:00Z", "last_seen": "2025-03-14T00:00:00Z"},
        ],
        "events": [
            {"event_id": "e1", "ts": "2025-03-14T20:00:00Z", "type": "medication", "severity": 1},
        ],
    }

    # use the pinned commit SHA
    code, body = _score(test_payload, commit)
    assert code == 200
    assert body["model_commit"] == commit
    assert body["ref_kind"] == "commit"
    assert body["model_version"] == "test-property"

    expected_feats = compute_features(test_payload)
    for fname in FEATURE_ORDER:
        assert abs(float(body["features"].get(fname)) - expected_feats[fname]) < 1e-9, fname

    expected_score = compute_score(expected_feats, test_coeffs, test_intercept)
    assert abs(body["score"] - expected_score) < 5e-7

    # cleanup: delete the branch ref
    subprocess.run(
        ["git", "--git-dir", GIT_DIR, "update-ref", "-d", "refs/heads/test-property"],
        check=True,
    )


def test_worker_crash_or_invalid_sha():
    """A 40-hex SHA that desn't exist in the repo at all returns 422."""
    fake = "0000000000000000000000000000000000000000"
    code, body = _score(PAYLOAD_1, fake)
    assert code == 422
    assert body["error_code"] in ("REF_MISMATCH", "UNPINNED_REF")
