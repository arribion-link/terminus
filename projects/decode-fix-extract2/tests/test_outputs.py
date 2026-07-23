import os
import hashlib
import subprocess


def test_result_file_exists():
    """Verify the agent created /app/result.txt"""
    assert os.path.isfile("/app/result.txt"), \
        "result.txt not found at /app/result.txt"


def test_result_file_not_empty():
    """Verify result.txt has content"""
    size = os.path.getsize("/app/result.txt")
    assert size > 0, \
        f"result.txt is empty (0 bytes)"


def test_output_matches_expected():
    """Verify the output matches the expected sha256 prefix"""
    msg_path = "/app/data/message.txt"
    assert os.path.isfile(msg_path), "message.txt not found"
    with open(msg_path, "rb") as f:
        msg_content = f.read()
    full_hash = hashlib.sha256(msg_content).hexdigest()
    expected = full_hash[:16]
    with open("/app/result.txt") as f:
        actual = f.read().strip()
    assert actual == expected, \
        f"Expected output '{expected}', got '{actual}'"


def test_traversed_full_chain():
    """Verify the agent traversed all 5 chain links (not just the last)"""
    data_dir = "/app/data"
    manifest_path = os.path.join(data_dir, "manifest.txt")
    assert os.path.isfile(manifest_path), "manifest.txt not found"

    with open(manifest_path) as f:
        start_hash = f.readline().strip().split("START: ")[1]

    visited = 0
    current_hash = start_hash
    while True:
        path = os.path.join(data_dir, current_hash)
        if not os.path.isfile(path):
            break
        with open(path) as f:
            content = f.read()
        visited += 1
        if "EXEC:" in content:
            break
        elif "NEXT:" in content:
            current_hash = content.split("NEXT: ")[1].strip().split("\n")[0]
        else:
            break

    assert visited == 5, \
        f"Expected to traverse 5 chain files, but traversal visited {visited} files"


def test_did_not_use_decoy():
    """Verify the agent found exactly 13 data files (5 chain + 1 manifest + 1 message + 6 decoys)"""
    data_dir = "/app/data"
    all_files = [f for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, f))]
    total_files = len(all_files)
    assert total_files == 13, \
        f"Expected exactly 13 files in data dir, found {total_files}"
