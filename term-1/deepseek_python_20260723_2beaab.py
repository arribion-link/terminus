#!/usr/bin/env python3
"""
Tests for the ref-verified inference service.
"""
import json
import time
import requests
import pytest

BASE_URL = "http://localhost:5000"


@pytest.fixture(scope="module")
def service_ready():
    """Wait for the Flask service to be ready."""
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


def test_service_starts(service_ready):
    """Verify the service starts and responds."""
    resp = requests.get(f"{BASE_URL}/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_inference_main_ref(service_ready):
    """Test inference with the main ref."""
    session_data = {
        "patient_id": "P001",
        "visit_history": [
            {"timestamp": "2025-01-15T10:00:00", "duration": 120, "platform": "web"},
            {"timestamp": "2025-01-16T14:30:00", "duration": 85, "platform": "mobile"}
        ],
        "device_history": [
            {"os": "iOS", "screen": "375x812", "battery": 0.85, "network": "wifi"},
            {"os": "Android", "screen": "1080x2400", "battery": 0.62, "network": "cellular"}
        ],
        "event_history": [
            {"type": "click", "timestamp": "2025-01-15T10:01:00"},
            {"type": "scroll", "timestamp": "2025-01-15T10:02:00"},
            {"type": "error", "timestamp": "2025-01-16T14:31:00"}
        ]
    }
    
    resp = requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "ref" in data
    assert "commit" in data
    assert data["ref"] == "main"
    assert 0.0 <= data["score"] <= 1.0
    assert data["feature_count"] == 47


def test_inference_develop_ref(service_ready):
    """Test inference with the develop ref."""
    session_data = {
        "patient_id": "P002",
        "visit_history": [],
        "device_history": [],
        "event_history": []
    }
    
    resp = requests.post(f"{BASE_URL}/infer?ref=develop", json=session_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ref"] == "develop"
    assert 0.0 <= data["score"] <= 1.0


def test_invalid_ref_rejected(service_ready):
    """Test that invalid refs return 400."""
    resp = requests.post(f"{BASE_URL}/infer?ref=invalid", json={"patient_id": "test"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_unpinned_ref_rejected(service_ready):
    """Test that unpinned refs are rejected."""
    resp = requests.post(f"{BASE_URL}/infer?ref=feature-branch", json={"patient_id": "test"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_empty_input_handled(service_ready):
    """Test that empty visit/device/event histories are handled."""
    session_data = {
        "patient_id": "P003",
        "visit_history": [],
        "device_history": [],
        "event_history": []
    }
    
    resp = requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["feature_count"] == 47


def test_caching_works(service_ready):
    """Test that caching reduces latency for repeated requests."""
    session_data = {
        "patient_id": "P004",
        "visit_history": [],
        "device_history": [],
        "event_history": []
    }
    
    # First request
    start = time.time()
    requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    first_time = time.time() - start
    
    time.sleep(0.5)
    
    # Second request
    start = time.time()
    requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    second_time = time.time() - start
    
    # Second request should be faster (cached)
    assert second_time < first_time * 0.8


def test_score_reproducible(service_ready):
    """Test that the same input produces the same score."""
    session_data = {
        "patient_id": "P005",
        "visit_history": [
            {"timestamp": "2025-01-15T10:00:00", "duration": 120, "platform": "web"}
        ],
        "device_history": [
            {"os": "iOS", "screen": "375x812", "battery": 0.75, "network": "wifi"}
        ],
        "event_history": [
            {"type": "click", "timestamp": "2025-01-15T10:01:00"}
        ]
    }
    
    resp1 = requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    resp2 = requests.post(f"{BASE_URL}/infer?ref=main", json=session_data)
    
    assert resp1.json()["score"] == pytest.approx(resp2.json()["score"], abs=1e-9)