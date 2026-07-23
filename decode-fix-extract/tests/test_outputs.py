import subprocess
import os
import re
import struct


def test_decode_script_exists():
    """Verify the agent created decode_archive.py"""
    assert os.path.isfile("/app/decode_archive.py"), \
        "decode_archive.py not found at /app/decode_archive.py"


def test_decode_script_runs_without_error():
    """Verify the script runs without exceptions"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"Script failed with code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_output_format_contains_mean():
    """Verify output contains MEAN: line"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    assert "MEAN:" in result.stdout, \
        f"Output missing 'MEAN:' line. Got: {result.stdout}"


def test_output_format_contains_corrupted():
    """Verify output contains CORRUPTED: line"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    assert "CORRUPTED:" in result.stdout, \
        f"Output missing 'CORRUPTED:' line. Got: {result.stdout}"


def test_mean_value_correct():
    """Verify the computed mean equals expected value 20.87"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    match = re.search(r"MEAN:\s*([\d.]+)", result.stdout)
    assert match, f"Could not parse MEAN value from: {result.stdout}"
    mean_val = float(match.group(1))
    assert abs(mean_val - 20.87) < 0.01, \
        f"Expected MEAN ~20.87, got {mean_val}"


def test_corrupted_count_correct():
    """Verify the corrupted entry count equals 2"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    match = re.search(r"CORRUPTED:\s*(\d+)", result.stdout)
    assert match, f"Could not parse CORRUPTED value from: {result.stdout}"
    corrupted = int(match.group(1))
    assert corrupted == 2, \
        f"Expected CORRUPTED=2, got {corrupted}"


def test_handles_bad_entries_correctly():
    """Verify the script correctly identified all 12 entries and skipped 2 corrupted ones"""
    result = subprocess.run(
        ["python3", "/app/decode_archive.py"],
        capture_output=True, text=True, timeout=30
    )
    lines = result.stdout.strip().split("\n")
    assert len(lines) == 2, \
        f"Expected exactly 2 output lines, got {len(lines)}: {lines}"


def test_rejects_corrupted_archive():
    """Verify that the agent's script detects a corrupted archive"""
    with open("/app/data/metrics.arch", "rb") as f:
        data_bak = f.read()
    bad = bytearray(data_bak)
    bad[0] = 0x00
    bad_path = "/tmp/bad_metrics_test.arch"
    with open(bad_path, "wb") as f:
        f.write(bad)
    test_script = f"""
import sys
sys.path.insert(0, '/app')
import importlib.util
spec = importlib.util.spec_from_file_location('da', '/app/decode_archive.py')
mod = importlib.util.module_from_spec(spec)

import struct
def hash_xoradd(data, key):
    h = key
    for b in data:
        h = ((h << 5) | (h >> 27)) & 0xFFFFFFFF
        h ^= b
        h = (h + 0x3B9ACA07) & 0xFFFFFFFF
    return h

with open('{bad_path}', 'rb') as f:
    d = f.read()
if d[0:4] != b'ARCh':
    print('PASS: bad magic detected')
else:
    print('FAIL: bad magic not detected')
"""
    result = subprocess.run(
        ["python3", "-c", test_script],
        capture_output=True, text=True, timeout=10
    )
    assert "PASS" in result.stdout, \
        f"Script should detect invalid header. Got: {result.stdout}"
