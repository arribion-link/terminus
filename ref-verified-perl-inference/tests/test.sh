#!/bin/bash
set -uo pipefail

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    mkdir -p /logs/verifier
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

mkdir -p /logs/verifier

# Start the gateway if it isn't already up (agents may have started it
# themselves while working; either way we make sure it's running before
# grading).
if ! curl -s -o /dev/null http://127.0.0.1:8080/healthz; then
    nohup python3 /app/gateway/app.py > /tmp/gateway.log 2>&1 &
    for _ in $(seq 1 30); do
        if curl -s -o /dev/null http://127.0.0.1:8080/healthz; then
            break
        fi
        sleep 0.5
    done
fi

# pytest, pytest-json-ctrf, and requests are pre-installed in the image.
python -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
rc=$?

if [ "$rc" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
