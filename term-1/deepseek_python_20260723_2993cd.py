#!/usr/bin/env python3
"""
End-to-end verifier for the ref-verified inference service.
"""
import json
import subprocess
import time
import requests
import pytest
from pathlib import Path

BASE_URL = "http://localhost:5000"


@pytest.fixture(scope="module")
def service_ready():
    for i in range(30):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                yield
                return
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(1)
    pytest.fail("Service failed to start")


def test_service_running(service_ready):
    """Verify the Flask service is running."""
    resp = requests.get(f"{BASE_URL}/health")
    assert resp.status_code == 200


def test_ref_verification_main(service_ready):
    """Main ref should be accepted."""
    resp = requests.post(f"{BASE_URL}/infer?ref=main", json={"patient_id": "test", "visit_history": [], "device_history": [], "event_history": []})
    assert resp.status_code == 200
    assert resp.json()["ref"] == "main"


def test_ref_verification_develop(service_ready):
    """Develop ref should be accepted."""
    resp = requests.post(f"{BASE_URL}/infer?ref=develop", json={"patient_id": "test", "visit_history": [], "device_history": [], "event_history": []})
    assert resp.status_code == 200
    assert resp.json()["ref"] == "develop"


def test_invalid_ref_rejected(service_ready):
    """Invalid ref should be rejected."""
    resp = requests.post(f"{BASE_URL}/infer?ref=invalid", json={"patient_id": "test"})
    assert resp.status_code == 400


def test_perl_worker_exists(service_ready):
    """Perl worker script should exist and be executable."""
    perl_script = Path("/app/perl_worker/feature_extractor.pl")
    assert perl_script.exists()
    assert perl_script.stat().st_mode & 0o111


def test_score_in_range(service_ready):
    """Score should be between 0 and 1."""
    session_data = {
        "patient_id": "test",
        "visit_history": [{"timestamp": "2025-01-15T10:00:00", "duration": 120, "platform": "web"}],
        "device_history": [{"os": "iOS", "screen": "375x812", "battery": 0.5, "network": "wifi"}],
        "event_history": [{"type": "click", "timestamp": "2025-01-15T10:01:00"}]
    }
    resp = requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    assert resp.status_code == 200
    assert 0.0 <= resp.json()["score"] <= 1.0


def test_feature_count(service_ready):
    """Feature count should be 47."""
    resp = requests.post(f"{BASE_URL}/infer?ref=main", json={"patient_id": "test", "visit_history": [], "device_history": [], "event_history": []})
    assert resp.status_code == 200
    assert resp.json()["feature_count"] == 47